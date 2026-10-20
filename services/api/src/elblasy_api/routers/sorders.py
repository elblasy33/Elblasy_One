"""Manual sales orders (wholesale / on credit) on Odoo's Sales app, delivered and invoiced as separate,
verified steps. Collecting what the customer owes uses the receivables screens (customers router)."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from elblasy_api import operations
from elblasy_api.config import Settings, get_settings
from elblasy_api.db import get_session
from elblasy_api.deps import api_error, get_vault, require
from elblasy_api.models import OdooConnection, User
from elblasy_api.odoo.client import BridgeClient, OdooError, OdooRejectedError
from elblasy_api.routers.connections import _client, _owned
from elblasy_api.security.rbac import P_CREDIT, P_SALES_ORDERS, has_permission
from elblasy_api.security.vault import SecretVault

router = APIRouter(prefix="/connections/{cid}/sales-orders", tags=["sales-orders"])
IDEM = Annotated[
    str, Header(alias="Idempotency-Key", min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
]
TOL = 0.005


class OrderLineIn(BaseModel):
    product_id: int = Field(gt=0)
    qty: float = Field(gt=0, le=1e7)
    price_unit: float | None = Field(default=None, ge=0, le=1e9)  # None: the product's sale price
    discount: float = Field(default=0, ge=0, le=100)


class QuoteIn(BaseModel):
    partner_id: int | None = Field(default=None, gt=0)
    lines: list[OrderLineIn] = Field(min_length=1, max_length=100)


class CreateIn(QuoteIn):
    partner_id: int = Field(gt=0)
    deliver_now: bool = False
    invoice_now: bool = False
    due_days: int | None = Field(default=None, ge=0, le=365)  # the credit period of the invoice
    note: str = Field(default="", max_length=500)
    override_credit_limit: bool = False


class InvoiceIn(BaseModel):
    due_days: int | None = Field(default=None, ge=0, le=365)
    override_credit_limit: bool = False


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
            422, "sales_order_rejected", str(exc).removeprefix("Odoo rejected the call: ")
        ) from exc
    except OdooError as exc:
        raise api_error(502, "odoo_unavailable", str(exc)) from exc


_CODES = (("CUSTOMER_REQUIRED", 422, "customer_required"), ("CREDIT_LIMIT_EXCEEDED", 409, "credit_limit_exceeded"),
          ("STOCK_SHORT", 409, "stock_short"), ("TRACKED_DELIVERY", 422, "tracked_delivery"))  # fmt: skip


def _map_rejection(exc: Exception) -> Exception | None:
    """Business refusals from the bridge carry a code prefix; give them a stable API error code."""
    if (
        isinstance(exc, HTTPException)
        and isinstance(exc.detail, dict)
        and exc.detail.get("code") == "sales_order_rejected"
    ):
        msg = str(exc.detail.get("message", ""))
        for prefix, status, code in _CODES:
            if msg.startswith(prefix):
                return api_error(status, code, msg.removeprefix(prefix + ": "))
    return None


@router.get("/products")
def products(
    cid: uuid.UUID, q: str = Query("", max_length=100), limit: int = Query(10, ge=1, le=30),
    user: User = Depends(require(P_SALES_ORDERS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "sorder_products", q, limit)


@router.post("/quote")
def quote(
    cid: uuid.UUID, body: QuoteIn, user: User = Depends(require(P_SALES_ORDERS)),
    db: Session = Depends(get_session), s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "sorder_quote", body.model_dump(exclude_none=True))


@router.get("")
def list_orders(
    cid: uuid.UUID, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0, le=100_000),
    user: User = Depends(require(P_SALES_ORDERS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "sorder_list", limit, offset)


@router.get("/{order_id}")
def get_order(
    cid: uuid.UUID, order_id: int, user: User = Depends(require(P_SALES_ORDERS)),
    db: Session = Depends(get_session), s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    got = _read(client, "sorder_get", order_id)
    if not got.get("found"):
        raise api_error(404, "not_found", "Order not found")
    return {"order": got["order"]}


def _check_override(user: User, wanted: bool) -> None:
    if wanted and not has_permission(user.role, P_CREDIT):
        raise api_error(403, "forbidden", "You may not override a customer's credit limit")


@router.post("", status_code=201)
def create_order(
    cid: uuid.UUID, body: CreateIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_SALES_ORDERS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    _check_override(user, body.override_credit_limit)
    spec = body.model_dump(exclude_none=True)
    spec["credit_override"] = spec.pop("override_credit_limit", False)
    lines = body.lines

    def verify(res: dict[str, Any], _before: Any) -> dict[str, Any]:
        got = client.call_bridge("sorder_get", res["refs"]["order"]["id"])
        o = got["order"] if got.get("found") else None
        ok = (
            o is not None and o["state"] in ("sale", "done") and o["partner_id"] == body.partner_id
            and len(o["lines"]) == len(lines)
            and all(abs(a["qty"] - b.qty) < TOL and (b.price_unit is None or abs(a["price_unit"] - b.price_unit) < TOL)
                    for a, b in zip(o["lines"], lines, strict=True))
        )  # fmt: skip
        if ok and o is not None and body.deliver_now:
            ok = o["delivery_status"] == "done" and all(
                ln["delivered"] >= ln["qty"] - TOL for ln in o["lines"]
            )
        if ok and o is not None and body.invoice_now:
            ok = (
                bool(o["invoices"])
                and all(b["state"] == "posted" for b in o["invoices"])
                and abs(sum(b["amount_total"] for b in o["invoices"]) - o["amount_total"]) < TOL
            )
        if not ok:
            raise api_error(
                502,
                "verification_failed",
                "Odoo does not show the order as requested. Check it in Odoo before retrying.",
            )
        return {"order": o, "outcome": res["outcome"], "replayed": False}

    try:
        return operations.run_write(
            db, request, user=user, conn=c, client=client, op_type="salesorder.create", idem=idem, payload=spec,
            method="sorder_create", spec=spec, verify=verify, what="sales order", audit_action="salesorder.create",
            target_type="sale_order", target_id=lambda o: o["order"]["id"],
            audit_after=lambda o: {"total": o["order"]["amount_total"], "delivered": body.deliver_now,
                                   "invoiced": body.invoice_now, "credit_override": body.override_credit_limit},
            rejected_code="sales_order_rejected",
        )  # fmt: skip
    except Exception as exc:
        mapped = _map_rejection(exc)
        raise (mapped or exc) from exc


@router.post("/{order_id}/deliver", status_code=201)
def deliver(
    cid: uuid.UUID, order_id: int, idem: IDEM, request: Request,
    user: User = Depends(require(P_SALES_ORDERS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)

    def before() -> dict[str, Any]:
        got = _read(client, "sorder_get", order_id)
        if not got.get("found"):
            raise api_error(404, "not_found", "Order not found")
        order: dict[str, Any] = got["order"]
        return order

    def verify(res: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
        got = client.call_bridge("sorder_get", order_id)
        o = got["order"] if got.get("found") else None
        if (
            o is None
            or o["delivery_status"] != "done"
            or any(ln["delivered"] < ln["qty"] - TOL for ln in o["lines"])
        ):
            raise api_error(
                502, "verification_failed", "Odoo does not show the delivery as completed."
            )
        return {"order": o}

    try:
        return operations.run_write(
            db, request, user=user, conn=c, client=client, op_type="salesorder.deliver", idem=idem,
            payload={"order_id": order_id}, method="sorder_deliver", spec={"order_id": order_id}, verify=verify, before=before,
            what="delivery", audit_action="salesorder.deliver", target_type="sale_order", target_id=lambda o: o["order"]["id"],
            audit_after=lambda o: {"order": order_id}, rejected_code="sales_order_rejected",
        )  # fmt: skip
    except Exception as exc:
        mapped = _map_rejection(exc)
        raise (mapped or exc) from exc


@router.post("/{order_id}/invoice", status_code=201)
def invoice(
    cid: uuid.UUID, order_id: int, body: InvoiceIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_SALES_ORDERS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    _check_override(user, body.override_credit_limit)
    spec = {"order_id": order_id, **body.model_dump(exclude_none=True)}
    spec["credit_override"] = spec.pop("override_credit_limit", False)

    def before() -> dict[str, Any]:
        got = _read(client, "sorder_get", order_id)
        if not got.get("found"):
            raise api_error(404, "not_found", "Order not found")
        order: dict[str, Any] = got["order"]
        return order

    def verify(res: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
        inv = client.call_bridge("invoice_get", res["refs"]["invoice"]["id"])
        b = inv.get("invoice") if inv.get("found") else None
        if b is None or b["state"] != "posted" or b["partner_id"] != prior["partner_id"] or b["amount_total"] <= 0 \
                or abs(b["amount_residual"] - b["amount_total"]) > TOL:  # fmt: skip
            raise api_error(
                502, "verification_failed", "Odoo does not show the invoice as posted and open."
            )
        got = client.call_bridge("sorder_get", order_id)
        return {"invoice": b, "order": got["order"]}

    try:
        return operations.run_write(
            db, request, user=user, conn=c, client=client, op_type="salesorder.invoice", idem=idem, payload=spec,
            method="sorder_invoice", spec=spec, verify=verify, before=before, what="invoice", audit_action="salesorder.invoice",
            target_type="sale_order", target_id=lambda o: order_id,
            audit_after=lambda o: {"total": o["invoice"]["amount_total"], "credit_override": body.override_credit_limit},
            rejected_code="sales_order_rejected",
        )  # fmt: skip
    except Exception as exc:
        mapped = _map_rejection(exc)
        raise (mapped or exc) from exc


@router.post("/{order_id}/cancel", status_code=201)
def cancel(
    cid: uuid.UUID, order_id: int, idem: IDEM, request: Request,
    user: User = Depends(require(P_SALES_ORDERS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)

    def verify(res: dict[str, Any], _b: Any) -> dict[str, Any]:
        got = client.call_bridge("sorder_get", order_id)
        if not got.get("found") or got["order"]["state"] != "cancel":
            raise api_error(
                502, "verification_failed", "Odoo does not show the order as cancelled."
            )
        return {"order": got["order"]}

    return operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="salesorder.cancel", idem=idem,
        payload={"order_id": order_id}, method="sorder_cancel", spec={"order_id": order_id}, verify=verify,
        what="cancellation", audit_action="salesorder.cancel", target_type="sale_order", target_id=lambda o: order_id,
        audit_after=lambda o: {"order": order_id}, rejected_code="sales_order_rejected",
    )  # fmt: skip
