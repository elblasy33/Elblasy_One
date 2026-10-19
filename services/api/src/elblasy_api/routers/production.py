"""Producing made products (own recipes): a batch consumes the recipe's components and adds the finished
product, through Odoo's manufacturing orders. Verified by a fresh read of the order and of both stocks."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from elblasy_api import operations
from elblasy_api.config import Settings, get_settings
from elblasy_api.db import get_session
from elblasy_api.deps import api_error, get_vault, require
from elblasy_api.models import OdooConnection, User
from elblasy_api.odoo.client import BridgeClient, OdooError
from elblasy_api.routers.connections import _client, _owned
from elblasy_api.security.rbac import P_PRODUCTS
from elblasy_api.security.vault import SecretVault

router = APIRouter(prefix="/connections/{cid}/production", tags=["production"])
IDEM = Annotated[
    str, Header(alias="Idempotency-Key", min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
]
TOL = 0.0005


class ProduceIn(BaseModel):
    template_id: int = Field(gt=0)
    qty: float = Field(gt=0, le=1_000_000)


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


@router.get("/recipes")
def recipes(
    cid: uuid.UUID, user: User = Depends(require(P_PRODUCTS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "production_recipes")


@router.get("/history")
def history(
    cid: uuid.UUID, user: User = Depends(require(P_PRODUCTS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "production_history", 20)


@router.post("/batches", status_code=201)
def produce(
    cid: uuid.UUID, body: ProduceIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_PRODUCTS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    spec = body.model_dump()

    def stock_of(tid: int) -> float:
        got = client.call_bridge("catalog_get", tid)
        return float(got.get("on_hand") or 0)

    def before() -> dict[str, Any]:
        recipe = next(
            (
                r
                for r in client.call_bridge("production_recipes")["items"]
                if r["template_id"] == body.template_id
            ),
            None,
        )
        if recipe is None:
            raise api_error(422, "production_rejected", "This product has no recipe.")
        return {"finished": stock_of(body.template_id),
                "components": {str(ln["template_id"]): ln["on_hand"] for ln in recipe["components"]},
                "per_unit": {str(ln["template_id"]): ln["per_unit"] for ln in recipe["components"]}}  # fmt: skip

    def verify(res: dict[str, Any], prior: Any) -> dict[str, Any]:
        mo = _read(client, "production_get", res["refs"]["order"]["id"])
        if not mo.get("found") or mo["state"] != "done" or abs(mo["qty_produced"] - body.qty) > TOL:
            raise api_error(502, "verification_failed", "Odoo does not show the batch as produced.")
        now = stock_of(body.template_id)
        if abs(now - (prior["finished"] + body.qty)) > TOL:
            raise api_error(502, "verification_failed", "Finished stock does not match the batch.")
        for tid, per in prior["per_unit"].items():
            used = float(per) * body.qty
            left = float(_read(client, "catalog_get", int(tid)).get("on_hand") or 0)
            if abs(left - (prior["components"][tid] - used)) > TOL:
                raise api_error(
                    502, "verification_failed", "Component stock does not match the batch."
                )
        return {"order": mo and {k: mo[k] for k in ("id", "name", "state", "product", "qty", "qty_produced")},
                "outcome": res["outcome"], "replayed": False}  # fmt: skip

    return operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="production.batch", idem=idem,
        payload=spec, method="production_produce", spec=spec, verify=verify, before=before,
        what="production batch", audit_action="production.batch", target_type="mrp_production",
        target_id=lambda o: o["order"]["id"],
        audit_after=lambda o: {"product": o["order"]["product"], "qty": o["order"]["qty_produced"]},
        rejected_code="production_rejected",
    )  # fmt: skip
