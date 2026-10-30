"""Price lists: retail/wholesale prices, quantity breaks and a list per customer, kept in Odoo and applied by
Odoo's price engine at the till and in sales orders. Every change is verified by asking Odoo for the price."""

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
from elblasy_api.security.rbac import P_PRICE, P_PRODUCTS_VIEW
from elblasy_api.security.vault import SecretVault

router = APIRouter(prefix="/connections/{cid}", tags=["pricelists"])
IDEM = Annotated[
    str, Header(alias="Idempotency-Key", min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
]


class PricelistIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class PriceIn(BaseModel):
    template_id: int = Field(gt=0)
    min_qty: float = Field(default=0, ge=0, le=1e7)
    price: float | None = Field(default=None, ge=0, le=1e9)  # None removes this price


class CustomerListIn(BaseModel):
    pricelist_id: int | None = Field(default=None, gt=0)  # None: back to the till's normal prices


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


@router.get("/pricelists")
def list_pricelists(
    cid: uuid.UUID, user: User = Depends(require(P_PRODUCTS_VIEW)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "pricelists_list")


@router.get("/pricelists/{pricelist_id}")
def get_pricelist(
    cid: uuid.UUID, pricelist_id: int, user: User = Depends(require(P_PRODUCTS_VIEW)),
    db: Session = Depends(get_session), s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    got = _read(client, "pricelist_get", pricelist_id)
    if not got.get("found"):
        raise api_error(404, "not_found", "Price list not found")
    return {"pricelist": got["pricelist"]}


@router.post("/pricelists", status_code=201)
def create_pricelist(
    cid: uuid.UUID, body: PricelistIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_PRICE)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)

    def verify(res: dict[str, Any], _b: Any) -> dict[str, Any]:
        got = _read(client, "pricelist_get", res["refs"]["pricelist"]["id"])
        if not got.get("found") or got["pricelist"]["name"] != body.name.strip():
            raise api_error(502, "verification_failed", "Odoo does not show the price list")
        return {"pricelist": got["pricelist"], "outcome": res["outcome"], "replayed": False}

    return operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="pricelist.create", idem=idem, payload=body.model_dump(),
        method="pricelist_create", spec=body.model_dump(), verify=verify, what="price list", audit_action="pricelist.create",
        target_type="pricelist", target_id=lambda o: o["pricelist"]["id"], audit_after=lambda o: {"name": body.name},
        rejected_code="pricelist_rejected",
    )  # fmt: skip


@router.put("/pricelists/{pricelist_id}/prices")
def set_price(
    cid: uuid.UUID, pricelist_id: int, body: PriceIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_PRICE)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    spec = {"pricelist_id": pricelist_id, **body.model_dump()}

    def verify(res: dict[str, Any], _b: Any) -> dict[str, Any]:
        got = _read(client, "pricelist_get", pricelist_id)
        rule = next((r for r in got.get("pricelist", {}).get("rules", []) if r["template_id"] == body.template_id
                     and abs(r["min_qty"] - body.min_qty) < 1e-9 and r["managed"]), None)  # fmt: skip
        if (body.price is None) != (rule is None) or (
            rule is not None and abs(rule["price"] - (body.price or 0)) > 0.005
        ):
            raise api_error(502, "verification_failed", "Odoo does not show the price as requested")
        if body.price is not None:  # and Odoo's own engine now charges it from that quantity
            chk = _read(client, "price_check", pricelist_id, body.template_id, max(body.min_qty, 1))
            if abs(chk.get("price", -1) - body.price) > 0.005:
                raise api_error(
                    502, "verification_failed", "Odoo's price engine does not apply the new price"
                )
        return {"pricelist": got["pricelist"], "outcome": res["outcome"], "replayed": False}

    return operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="pricelist.price", idem=idem, payload=spec,
        method="pricelist_set_price", spec=spec, verify=verify, what="price", audit_action="pricelist.price",
        target_type="pricelist", target_id=lambda o: pricelist_id,
        audit_after=lambda o: {"product": body.template_id, "min_qty": body.min_qty, "price": body.price},
        rejected_code="pricelist_rejected",
    )  # fmt: skip


@router.put("/customers/{partner_id}/pricelist")
def set_customer_pricelist(
    cid: uuid.UUID, partner_id: int, body: CustomerListIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_PRICE)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    spec = {"partner_id": partner_id, **body.model_dump()}

    def verify(res: dict[str, Any], _b: Any) -> dict[str, Any]:
        st = _read(client, "customer_statement", partner_id)
        if not st.get("found") or st["customer"].get("pricelist_id") != body.pricelist_id:
            raise api_error(
                502, "verification_failed", "Odoo does not show the customer's price list"
            )
        return {"customer": st["customer"], "outcome": res["outcome"], "replayed": False}

    return operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="customer.pricelist", idem=idem, payload=spec,
        method="customer_set_pricelist", spec=spec, verify=verify, what="customer price list",
        audit_action="customer.pricelist", target_type="partner", target_id=lambda o: partner_id,
        audit_after=lambda o: {"pricelist_id": body.pricelist_id}, rejected_code="pricelist_rejected",
    )  # fmt: skip
