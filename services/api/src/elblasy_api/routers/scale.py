"""Scale label formats: read labels printed by the shop's existing scales (weight or price inside the barcode)."""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from elblasy_api import operations
from elblasy_api.config import Settings, get_settings
from elblasy_api.db import get_session
from elblasy_api.deps import api_error, get_vault, require
from elblasy_api.models import OdooConnection, User
from elblasy_api.odoo.client import BridgeClient, OdooError
from elblasy_api.routers.connections import _client, _owned
from elblasy_api.security.rbac import P_CONFIG, P_PRODUCTS_VIEW
from elblasy_api.security.vault import SecretVault

router = APIRouter(prefix="/connections/{cid}/scale", tags=["scale"])
IDEM = Annotated[
    str, Header(alias="Idempotency-Key", min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
]


class RuleIn(BaseModel):
    prefix: str = Field(pattern=r"^\d{1,3}$")
    plu_digits: int = Field(ge=1, le=10)
    kind: Literal["weight", "price"]
    int_digits: int = Field(ge=1, le=10)
    dec_digits: int = Field(ge=0, le=5)


def _conn(
    db: Session, user: User, cid: uuid.UUID, s: Settings, vault: SecretVault
) -> tuple[OdooConnection, BridgeClient]:
    c = _owned(db, user, cid)
    if c.status != "active" or c.secret_ciphertext is None:
        raise api_error(409, "connection_revoked", "Connection is revoked")
    return c, _client(c.base_url, c.db_name, c.login, vault.decrypt(c.secret_ciphertext), s)


def _read(client: BridgeClient, method: str, *args: Any) -> dict[str, Any]:
    try:
        return client.call_bridge(method, *args)
    except OdooError as exc:
        raise api_error(502, "odoo_unavailable", str(exc)) from exc


@router.get("/rules")
def rules(
    cid: uuid.UUID, user: User = Depends(require(P_PRODUCTS_VIEW)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "scale_rules")


@router.get("/parse")
def parse(
    cid: uuid.UUID, code: str = Query(min_length=8, max_length=14, pattern=r"^\d+$"),
    user: User = Depends(require(P_PRODUCTS_VIEW)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "scale_parse", code)


@router.post("/rules", status_code=201)
def add_rule(
    cid: uuid.UUID, body: RuleIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_CONFIG)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    if len(body.prefix) + body.plu_digits + body.int_digits + body.dec_digits != 12:
        raise api_error(422, "validation", "Prefix, item number and value must make 12 digits")

    def verify(res: dict[str, Any], _b: Any) -> dict[str, Any]:
        got = _read(client, "scale_rules")
        rid = res["refs"]["rule"]["id"]
        rule = next((r for r in got.get("items", []) if r["id"] == rid), None)
        want = {
            "prefix": body.prefix,
            "plu_digits": body.plu_digits,
            "int_digits": body.int_digits,
            "dec_digits": body.dec_digits,
        }
        if not rule or rule["type"] != body.kind or rule["format"] != want:
            raise api_error(
                502, "verification_failed", "Odoo does not show the label format as requested"
            )
        return {"rule": rule, "outcome": res["outcome"], "replayed": False}

    return operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="scale.rule", idem=idem, payload=body.model_dump(),
        method="scale_rule_upsert", spec=body.model_dump(), verify=verify, what="scale label format",
        audit_action="scale.rule", target_type="barcode_rule", target_id=lambda o: o["rule"]["id"],
        audit_after=lambda o: {"pattern": o["rule"]["pattern"], "type": body.kind}, rejected_code="scale_rejected",
    )  # fmt: skip
