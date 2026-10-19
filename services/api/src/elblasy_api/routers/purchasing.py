"""Purchasing: suppliers, purchase orders, receiving goods, vendor bills, supplier payments.

Every write is a tracked, idempotent operation verified by a fresh read of Odoo. Ordered, received,
billed and on-hand quantities are reported separately and never mixed."""

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
from elblasy_api.odoo.client import BridgeClient, OdooError, OdooRejectedError
from elblasy_api.routers.connections import _client, _owned
from elblasy_api.security.rbac import (
    P_COST_VISIBLE,
    P_PAYMENTS,
    P_PURCHASING,
    P_PURCHASING_VIEW,
    P_REPORTS,
    has_permission,
)  # fmt: skip
from elblasy_api.security.vault import SecretVault

router = APIRouter(prefix="/connections/{cid}/purchasing", tags=["purchasing"])
IDEM = Annotated[
    str, Header(alias="Idempotency-Key", min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
]
TOL = 0.005
CONFIRMED = ("purchase", "done")


class SupplierIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    vat: str | None = Field(default=None, max_length=40)
    street: str | None = Field(default=None, max_length=200)


class PurchaseLineIn(BaseModel):
    product_id: int = Field(gt=0)
    qty: float = Field(gt=0, le=1e7)
    price_unit: float | None = Field(default=None, ge=0, le=1e9)


class PurchaseIn(BaseModel):
    partner_id: int = Field(gt=0)
    lines: list[PurchaseLineIn] = Field(min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class ReceiveLineIn(BaseModel):
    line_id: int = Field(gt=0)
    qty: float = Field(gt=0, le=1e7)
    lot_name: str | None = Field(default=None, max_length=80)
    expiry: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$")


class ReceiveIn(BaseModel):
    lines: list[ReceiveLineIn] = Field(min_length=1, max_length=100)


class PayIn(BaseModel):
    amount: float = Field(gt=0, le=1e9)
    journal_type: Literal["cash", "bank"] = "cash"


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
    except OdooRejectedError as exc:
        raise api_error(
            422, "purchasing_rejected", str(exc).removeprefix("Odoo rejected the call: ")
        ) from exc
    except OdooError as exc:
        raise api_error(502, "odoo_unavailable", str(exc)) from exc


def _verification_failed(what: str) -> Exception:
    return api_error(
        502,
        "verification_failed",
        f"Odoo does not show the {what} as requested. Check it in Odoo before retrying.",
    )


def _order_levels(client: BridgeClient, order: dict[str, Any]) -> dict[str, dict[str, float]]:
    ids = sorted({line["product_id"] for line in order["lines"]})
    levels: dict[str, dict[str, float]] = _read(client, "stock_levels", ids).get("levels", {})
    return levels


# ---------------- suppliers ----------------
@router.post("/suppliers", status_code=201)
def create_supplier(
    cid: uuid.UUID, body: SupplierIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_PURCHASING)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)

    def verify(res: dict[str, Any], _: Any) -> dict[str, Any]:
        sup = res["refs"]["supplier"]
        got = client.call_bridge("supplier_statement", sup["id"])
        if not got.get("found") or got["supplier"]["name"] != body.name.strip():
            raise _verification_failed("supplier")
        return {"supplier": got["supplier"]}

    return operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="purchasing.supplier.create", idem=idem,
        payload=body.model_dump(), method="suppliers_upsert", spec=body.model_dump(exclude_none=True),
        verify=verify, what="supplier", audit_action="purchasing.supplier.create", target_type="supplier",
        target_id=lambda o: o["supplier"]["id"], audit_after=lambda o: {"name": o["supplier"]["name"]},
        rejected_code="supplier_rejected",
    )  # fmt: skip


@router.get("/suppliers")
def list_suppliers(
    cid: uuid.UUID, q: str = Query("", max_length=100), limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100_000), user: User = Depends(require(P_PURCHASING_VIEW)),
    db: Session = Depends(get_session), s: Settings = Depends(get_settings),
    vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    res = _read(client, "suppliers_search", q, limit, offset)
    if not (has_permission(user.role, P_PAYMENTS) or has_permission(user.role, P_REPORTS)):
        for it in res.get("items", []):
            it.pop("balance", None)  # what we owe is finance information
    return res


@router.get("/suppliers/{supplier_id}/statement")
def statement(
    cid: uuid.UUID, supplier_id: int, user: User = Depends(require(P_PAYMENTS)),
    db: Session = Depends(get_session), s: Settings = Depends(get_settings),
    vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    res = _read(client, "supplier_statement", supplier_id)
    if not res.get("found"):
        raise api_error(404, "not_found", "Supplier not found")
    return res


# ---------------- purchase orders ----------------
def _hide_costs(user: User, order: dict[str, Any]) -> dict[str, Any]:
    if has_permission(user.role, P_COST_VISIBLE) or has_permission(user.role, P_PAYMENTS):
        return order
    for key in ("amount_untaxed", "amount_tax", "amount_total"):
        order.pop(key, None)
    for line in order.get("lines", []):
        line.pop("price_unit", None)
        line.pop("subtotal", None)
    order.pop("bills", None)
    return order


@router.post("/orders", status_code=201)
def create_order(
    cid: uuid.UUID, body: PurchaseIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_PURCHASING)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)

    def verify(res: dict[str, Any], _: Any) -> dict[str, Any]:
        got = client.call_bridge("purchase_get", res["refs"]["order"]["id"])
        o = got.get("order") if got.get("found") else None
        if (
            not o
            or o["state"] not in CONFIRMED
            or o["partner_id"] != body.partner_id
            or len(o["lines"]) != len(body.lines)
        ):
            raise _verification_failed("order")
        return {"order": o}

    out = operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="purchasing.order.create", idem=idem,
        payload=body.model_dump(), method="purchase_create_order", spec=body.model_dump(exclude_none=True),
        verify=verify, what="order", audit_action="purchasing.order.create", target_type="purchase_order",
        target_id=lambda o: o["order"]["id"],
        audit_after=lambda o: {"total": o["order"]["amount_total"], "lines": len(o["order"]["lines"])},
        rejected_code="order_rejected",
    )  # fmt: skip
    out["order"] = _hide_costs(user, out["order"])
    return out


@router.get("/orders")
def list_orders(
    cid: uuid.UUID, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0, le=100_000),
    user: User = Depends(require(P_PURCHASING_VIEW)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    res = _read(client, "purchase_list", limit, offset)
    res["items"] = [_hide_costs(user, o) for o in res.get("items", [])]
    return res


@router.get("/orders/{order_id}")
def get_order(
    cid: uuid.UUID, order_id: int, user: User = Depends(require(P_PURCHASING_VIEW)),
    db: Session = Depends(get_session), s: Settings = Depends(get_settings),
    vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    res = _read(client, "purchase_get", order_id)
    if not res.get("found"):
        raise api_error(404, "not_found", "Order not found")
    levels = _order_levels(client, res["order"])
    return {"order": _hide_costs(user, res["order"]), "stock": levels}


@router.post("/orders/{order_id}/receive", status_code=201)
def receive(
    cid: uuid.UUID, order_id: int, body: ReceiveIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_PURCHASING)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    wanted = {ln.line_id: ln.qty for ln in body.lines}
    if len(wanted) != len(body.lines):
        raise api_error(422, "validation", "A line appears twice")

    def before() -> dict[str, Any]:
        got = _read(client, "purchase_get", order_id)
        if not got.get("found"):
            raise api_error(404, "not_found", "Order not found")
        return {"order": got["order"], "levels": _order_levels(client, got["order"])}

    def verify(res: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
        got = client.call_bridge("purchase_get", order_id)
        after = got["order"] if got.get("found") else None
        if not after:
            raise _verification_failed("receipt")
        prev = {line["id"]: line for line in prior["order"]["lines"]}
        by_product: dict[int, float] = {}
        for ln in after["lines"]:
            if ln["id"] in wanted:
                if abs(ln["received"] - (prev[ln["id"]]["received"] + wanted[ln["id"]])) > TOL:
                    raise _verification_failed("received quantity")
                by_product[ln["product_id"]] = (
                    by_product.get(ln["product_id"], 0.0) + wanted[ln["id"]]
                )
        levels = _order_levels(client, after)
        for pid, qty in by_product.items():  # the goods are really on the shelf
            was = prior["levels"].get(str(pid), {}).get("on_hand", 0.0)
            if abs(levels.get(str(pid), {}).get("on_hand", -1) - (was + qty)) > TOL:
                raise _verification_failed("stock level")
        return {"order": after, "stock": levels, "received": by_product}

    out = operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="purchasing.order.receive", idem=idem,
        payload={"order_id": order_id, **body.model_dump()}, method="purchase_receive",
        spec={"order_id": order_id, **body.model_dump(exclude_none=True)}, verify=verify, before=before,
        what="receipt", audit_action="purchasing.order.receive", target_type="purchase_order",
        target_id=lambda o: o["order"]["id"], audit_after=lambda o: {"received": o["received"]},
        rejected_code="receipt_rejected",
    )  # fmt: skip
    out["order"] = _hide_costs(user, out["order"])
    return out


@router.post("/orders/{order_id}/bill", status_code=201)
def create_bill(
    cid: uuid.UUID, order_id: int, idem: IDEM, request: Request,
    user: User = Depends(require(P_PAYMENTS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)

    def before() -> dict[str, Any]:
        got = _read(client, "purchase_get", order_id)
        if not got.get("found"):
            raise api_error(404, "not_found", "Order not found")
        order: dict[str, Any] = got["order"]
        return order

    def verify(res: dict[str, Any], order: dict[str, Any]) -> dict[str, Any]:
        bill = client.call_bridge("purchase_get_bill", res["refs"]["bill"]["id"])
        b = bill.get("bill") if bill.get("found") else None
        billed_now = {line["product_id"]: line["qty"] for line in (b or {}).get("lines", [])}
        expected = {
            ln["product_id"]: ln["received"] - ln["billed"]
            for ln in order["lines"]
            if ln["received"] - ln["billed"] > TOL
        }
        if (
            not b or b["state"] != "posted" or b["partner_id"] != order["partner_id"] or b["amount_total"] <= 0
            or set(billed_now) != set(expected)
            or any(abs(billed_now[p] - expected[p]) > TOL for p in expected)
        ):  # fmt: skip
            raise _verification_failed("bill")
        return {"bill": b}

    return operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="purchasing.bill.create", idem=idem,
        payload={"order_id": order_id}, method="purchase_create_bill", spec={"order_id": order_id},
        verify=verify, before=before, what="bill", audit_action="purchasing.bill.create",
        target_type="vendor_bill", target_id=lambda o: o["bill"]["id"],
        audit_after=lambda o: {"total": o["bill"]["amount_total"], "order": order_id}, rejected_code="bill_rejected",
    )  # fmt: skip


@router.post("/bills/{bill_id}/pay", status_code=201)
def pay_bill(
    cid: uuid.UUID, bill_id: int, body: PayIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_PAYMENTS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)

    def before() -> dict[str, Any]:
        got = _read(client, "purchase_get_bill", bill_id)
        if not got.get("found"):
            raise api_error(404, "not_found", "Bill not found")
        bill: dict[str, Any] = got["bill"]
        return bill

    def verify(res: dict[str, Any], bill: dict[str, Any]) -> dict[str, Any]:
        got = client.call_bridge("purchase_get_bill", bill_id)
        b = got.get("bill") if got.get("found") else None
        if (
            not b
            or abs(b["amount_residual"] - (bill["amount_residual"] - body.amount)) > TOL
            or b["payment_state"] not in ("paid", "partial", "in_payment")
        ):
            raise _verification_failed("payment")
        return {"bill": b, "payment_id": res["refs"]["payment_id"]}

    return operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="purchasing.bill.pay", idem=idem,
        payload={"bill_id": bill_id, **body.model_dump()}, method="purchase_pay_bill",
        spec={"bill_id": bill_id, **body.model_dump()}, verify=verify, before=before, what="payment",
        audit_action="purchasing.bill.pay", target_type="vendor_bill", target_id=lambda o: o["bill"]["id"],
        audit_after=lambda o: {"amount": body.amount, "journal": body.journal_type,
                               "residual": o["bill"]["amount_residual"]}, rejected_code="payment_rejected",
    )  # fmt: skip


@router.get("/products")
def search_products(
    cid: uuid.UUID, q: str = Query("", max_length=100), limit: int = Query(20, ge=1, le=50),
    user: User = Depends(require(P_PURCHASING)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    res = _read(client, "purchase_products", q, limit)
    if not has_permission(user.role, P_COST_VISIBLE):
        for it in res.get("items", []):
            it.pop("cost", None)
    return res


@router.get("/stock")
def stock(
    cid: uuid.UUID, product_ids: str = Query(pattern=r"^\d+(,\d+){0,99}$"),
    user: User = Depends(require(P_PURCHASING_VIEW)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "stock_levels", [int(i) for i in product_ids.split(",")])
