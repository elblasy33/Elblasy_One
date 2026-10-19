import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from elblasy_api import audit
from elblasy_api.config import Settings, get_settings
from elblasy_api.db import get_session
from elblasy_api.deps import api_error, current_user, get_vault, require
from elblasy_api.models import OdooConnection, User
from elblasy_api.odoo.client import BridgeClient, OdooCredentials, OdooError
from elblasy_api.odoo.compat import assess
from elblasy_api.readiness.engine import (
    RULESET_VERSION,
    classify_environment,
    evaluate,
    summarize,
)
from elblasy_api.security.rbac import P_CONFIG, P_CONNECTIONS
from elblasy_api.security.ssrf import UnsafeUrlError, validate_odoo_url
from elblasy_api.security.vault import SecretVault

router = APIRouter(prefix="/connections", tags=["connections"])


class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(max_length=500)
    db_name: str = Field(min_length=1, max_length=120)
    login: str = Field(min_length=1, max_length=200)
    secret: str = Field(min_length=1, max_length=500, repr=False)  # Odoo API key


class RotateIn(BaseModel):
    secret: str = Field(min_length=1, max_length=500, repr=False)


class ConnectionOut(BaseModel):
    id: str
    name: str
    base_url: str
    db_name: str
    status: str
    odoo_series: str | None
    odoo_edition: str | None
    compatibility_status: str
    capabilities: dict[str, bool] | None
    allowed_companies: list[dict[str, Any]] | None
    manifest_fetched_at: datetime | None
    last_health_ok_at: datetime | None


def _out(c: OdooConnection) -> ConnectionOut:
    m = c.capability_manifest or {}
    return ConnectionOut(
        id=str(c.id), name=c.name, base_url=c.base_url, db_name=c.db_name, status=c.status,
        odoo_series=c.odoo_series, odoo_edition=c.odoo_edition,
        compatibility_status=c.compatibility_status, capabilities=m.get("capabilities"),
        allowed_companies=m.get("allowed_companies"),
        manifest_fetched_at=c.manifest_fetched_at, last_health_ok_at=c.last_health_ok_at,
    )  # fmt: skip


def _client(url: str, db_name: str, login: str, secret: str, s: Settings) -> BridgeClient:
    try:
        target = validate_odoo_url(
            url, production=s.is_production, allow_private=s.allow_private_odoo_hosts,
            allow_insecure_http=s.allow_insecure_odoo_http,
        )  # fmt: skip
    except UnsafeUrlError as exc:
        raise api_error(422, "unsafe_url", str(exc)) from exc
    return BridgeClient(target, OdooCredentials(db_name, login, secret))


def _owned(db: Session, user: User, cid: uuid.UUID) -> OdooConnection:
    c = db.scalar(
        select(OdooConnection).where(
            OdooConnection.id == cid, OdooConnection.tenant_id == user.tenant_id
        )
    )
    if c is None:  # identical response for "missing" and "someone else's": no enumeration
        raise api_error(404, "not_found", "Connection not found")
    return c


def _probe(client: BridgeClient) -> dict[str, Any]:
    try:
        return client.call_bridge("capabilities")
    except OdooError as exc:
        raise api_error(422, "odoo_unavailable", str(exc)) from exc


def _apply_manifest(c: OdooConnection, m: dict[str, Any]) -> None:
    compat = assess(m)
    c.capability_manifest = m
    c.manifest_fetched_at = datetime.now(UTC)
    c.odoo_series = m.get("odoo", {}).get("series")
    c.odoo_edition = m.get("odoo", {}).get("edition")
    c.compatibility_status = compat.status
    c.last_health_ok_at = datetime.now(UTC)


@router.post("", status_code=201)
def create_connection(
    body: ConnectionIn,
    request: Request,
    user: User = Depends(require(P_CONNECTIONS)),
    db: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
    vault: SecretVault = Depends(get_vault),
) -> ConnectionOut:
    client = _client(body.base_url, body.db_name, body.login, body.secret, s)
    try:
        client.server_version()
        manifest = _probe(client)
    except OdooError as exc:
        raise api_error(422, "odoo_unavailable", str(exc)) from exc
    conn = OdooConnection(
        tenant_id=user.tenant_id, name=body.name, base_url=body.base_url.rstrip("/"),
        db_name=body.db_name, login=body.login, secret_ciphertext=vault.encrypt(body.secret),
    )  # fmt: skip
    _apply_manifest(conn, manifest)
    db.add(conn)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise api_error(409, "name_taken", "A connection with this name exists") from exc
    audit.record(db, request, action="connection.create", outcome="success", actor=user,
                 target_type="connection", target_id=conn.id,
                 after={"name": conn.name, "base_url": conn.base_url, "db": conn.db_name})  # fmt: skip
    db.commit()
    return _out(conn)


class CurrentConnection(BaseModel):
    id: str
    name: str
    odoo_series: str | None
    capabilities: dict[str, bool] | None


@router.get("/current")
def current_connection(
    user: User = Depends(current_user), db: Session = Depends(get_session)
) -> CurrentConnection:
    """The shop's active Odoo connection, for ANY signed-in user (cashiers and clerks need it to work).
    Deliberately minimal: no URL, database name or login; those stay with connection managers."""
    c = db.scalar(
        select(OdooConnection)
        .where(OdooConnection.tenant_id == user.tenant_id, OdooConnection.status == "active")
        .order_by(OdooConnection.created_at)
    )
    if c is None:
        raise api_error(404, "no_connection", "No active connection")
    caps = (c.capability_manifest or {}).get("capabilities")
    return CurrentConnection(
        id=str(c.id), name=c.name, odoo_series=c.odoo_series, capabilities=caps
    )


@router.get("")
def list_connections(
    user: User = Depends(require(P_CONNECTIONS)), db: Session = Depends(get_session)
) -> list[ConnectionOut]:
    rows = db.scalars(select(OdooConnection).where(OdooConnection.tenant_id == user.tenant_id))
    return [_out(c) for c in rows]


@router.get("/{cid}/health")
def health(
    cid: uuid.UUID,
    request: Request,
    user: User = Depends(require(P_CONNECTIONS)),
    db: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
    vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:
    """Safe diagnostics only: no URLs of internals, credentials, or raw Odoo errors."""
    c = _owned(db, user, cid)
    if c.status != "active" or c.secret_ciphertext is None:
        return {"status": "revoked", "ok": False}
    client = _client(c.base_url, c.db_name, c.login, vault.decrypt(c.secret_ciphertext), s)
    try:
        manifest = client.call_bridge("capabilities")
    except OdooError as exc:
        audit.record(db, request, action="connection.health", outcome="failure", actor=user,
                     target_type="connection", target_id=c.id)  # fmt: skip
        db.commit()
        return {"status": "unreachable", "ok": False, "detail": str(exc)}
    _apply_manifest(c, manifest)
    db.commit()
    return {
        "status": "ok", "ok": True, "compatibility": c.compatibility_status,
        "odoo_series": c.odoo_series, "odoo_edition": c.odoo_edition,
        "checked_at": c.last_health_ok_at,
    }  # fmt: skip


@router.get("/{cid}/readiness")
def readiness(
    cid: uuid.UUID,
    request: Request,
    user: User = Depends(require(P_CONFIG)),
    db: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
    vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:
    """Read-only diagnostic scan. Refreshes the capability manifest; changes nothing in Odoo."""
    c = _owned(db, user, cid)
    if c.status != "active" or c.secret_ciphertext is None:
        raise api_error(409, "connection_revoked", "Connection is revoked")
    client = _client(c.base_url, c.db_name, c.login, vault.decrypt(c.secret_ciphertext), s)
    try:
        manifest = client.call_bridge("capabilities")
        snapshot = client.call_bridge("readiness_snapshot")
    except OdooError as exc:
        audit.record(db, request, action="readiness.scan", outcome="failure", actor=user,
                     target_type="connection", target_id=c.id)  # fmt: skip
        db.commit()
        raise api_error(502, "odoo_unavailable", str(exc)) from exc
    _apply_manifest(c, manifest)
    findings = evaluate(manifest, snapshot)
    summary = summarize(findings)
    env = classify_environment(manifest, snapshot)
    audit.record(db, request, action="readiness.scan", outcome="success", actor=user,
                 target_type="connection", target_id=c.id,
                 after={"environment": env.value, **summary})  # fmt: skip
    db.commit()
    return {
        "ruleset_version": RULESET_VERSION,
        "scanned_at": datetime.now(UTC),
        "read_only": True,
        "environment": env.value,
        "summary": summary,
        "findings": [f.to_dict() for f in findings],
    }


@router.put("/{cid}/credentials")
def rotate_credentials(
    cid: uuid.UUID,
    body: RotateIn,
    request: Request,
    user: User = Depends(require(P_CONNECTIONS)),
    db: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
    vault: SecretVault = Depends(get_vault),
) -> ConnectionOut:
    c = _owned(db, user, cid)
    manifest = _probe(_client(c.base_url, c.db_name, c.login, body.secret, s))  # verify first
    c.secret_ciphertext = vault.encrypt(body.secret)
    c.status = "active"
    _apply_manifest(c, manifest)
    audit.record(db, request, action="connection.rotate", outcome="success", actor=user,
                 target_type="connection", target_id=c.id)  # fmt: skip
    db.commit()
    return _out(c)


@router.delete("/{cid}", status_code=204)
def revoke(
    cid: uuid.UUID,
    request: Request,
    user: User = Depends(require(P_CONNECTIONS)),
    db: Session = Depends(get_session),
) -> None:
    """Revoke: the stored secret is destroyed; the row stays for audit/operation history."""
    c = _owned(db, user, cid)
    c.status, c.secret_ciphertext = "revoked", None
    audit.record(db, request, action="connection.revoke", outcome="success", actor=user,
                 target_type="connection", target_id=c.id)  # fmt: skip
    db.commit()
