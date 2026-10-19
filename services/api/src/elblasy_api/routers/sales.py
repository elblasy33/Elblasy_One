"""Sales on Odoo's POS. Every money-moving call is a tracked, idempotent operation, verified by a
fresh read of Odoo before it is reported as done. The platform never computes prices or taxes."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from elblasy_api import audit, operations
from elblasy_api.config import Settings, get_settings
from elblasy_api.db import get_session
from elblasy_api.deps import api_error, get_vault, require
from elblasy_api.models import OdooConnection, Operation, User
from elblasy_api.odoo.client import BridgeClient, OdooError, OdooRejectedError, OdooUncertainError
from elblasy_api.routers.connections import _client, _owned
from elblasy_api.security.rbac import (
    P_CREDIT,
    P_DISCOUNT,
    P_REPORTS,
    P_RETURNS,
    P_SALES,
    has_permission,
)  # fmt: skip
from elblasy_api.security.vault import SecretVault

router = APIRouter(prefix="/connections/{cid}/sales", tags=["sales"])
IDEM = Annotated[
    str, Header(alias="Idempotency-Key", min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
]
MONEY_TOLERANCE = 0.005
PAID_STATES = ("paid", "done", "invoiced")


class SaleLine(BaseModel):
    product_id: int = Field(gt=0)
    qty: float = Field(gt=0, le=1_000_000)
    discount: float = Field(default=0, ge=0, le=100)


class QuoteIn(BaseModel):
    config_id: int = Field(gt=0)
    lines: list[SaleLine] = Field(min_length=1, max_length=200)


class PaymentIn(BaseModel):
    payment_method_id: int = Field(gt=0)
    amount: float = Field(gt=0, le=1e9)


class CheckoutIn(QuoteIn):
    expected_total: float = Field(gt=0, le=1e9)
    payments: list[PaymentIn] = Field(min_length=1, max_length=5)
    partner_id: int | None = Field(default=None, gt=0)
    override_credit_limit: bool = (
        False  # needs customers.credit.override; recorded in the audit log
    )

    @model_validator(mode="after")
    def payments_cover_total(self) -> "CheckoutIn":
        if sum(p.amount for p in self.payments) + MONEY_TOLERANCE < self.expected_total:
            raise ValueError("payments do not cover the total")
        return self


class OpenSessionIn(BaseModel):
    config_id: int = Field(gt=0)
    opening_cash: float = Field(default=0, ge=0, le=1e9)


class CloseSessionIn(BaseModel):
    counted_cash: float = Field(ge=0, le=1e9)


class RefundLineIn(BaseModel):
    line_id: int = Field(gt=0)
    qty: float = Field(gt=0, le=1_000_000)


class RefundIn(BaseModel):
    payment_method_id: int = Field(gt=0)
    lines: list[RefundLineIn] = Field(
        default_factory=list, max_length=200
    )  # empty = everything left


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
            422, "sales_rejected", str(exc).removeprefix("Odoo rejected the call: ")
        ) from exc
    except OdooError as exc:
        raise api_error(502, "odoo_unavailable", str(exc)) from exc


def _write_error(db: Session, op: Operation, exc: Exception, what: str) -> Exception:
    """Maps a failed money-moving call to an HTTP error and the right operation state."""
    if isinstance(exc, OdooUncertainError):
        operations.fail(db, op, "needs_review", str(exc))
        return api_error(
            502,
            "outcome_unknown",
            f"The {what} may have been recorded. Retry with the same Idempotency-Key.",
        )
    if isinstance(exc, OdooRejectedError):
        msg = str(exc).removeprefix("Odoo rejected the call: ")
        operations.fail(db, op, "failed", msg)
        if msg.startswith("PRICE_CHANGED"):
            return api_error(409, "price_changed", msg.removeprefix("PRICE_CHANGED: "))
        if msg.startswith("No open session"):
            return api_error(409, "no_open_session", msg)
        if msg.startswith("CUSTOMER_REQUIRED"):
            return api_error(422, "customer_required", msg.removeprefix("CUSTOMER_REQUIRED: "))
        if msg.startswith("CREDIT_LIMIT_EXCEEDED"):
            return api_error(
                409, "credit_limit_exceeded", msg.removeprefix("CREDIT_LIMIT_EXCEEDED: ")
            )
        return api_error(422, "sales_rejected", msg)
    operations.fail(db, op, "needs_review", str(exc))
    return api_error(502, "odoo_unavailable", str(exc))


def _check_discounts(user: User, lines: list[SaleLine]) -> None:
    if any(line.discount > 0 for line in lines) and not has_permission(user.role, P_DISCOUNT):
        raise api_error(403, "forbidden", "You do not have permission to give discounts")


def _receipt(order: dict[str, Any], company: str | None, cashier: str) -> dict[str, Any]:
    return {
        "company": company, "reference": order["name"], "date": order["date_order"], "cashier": cashier,
        "lines": order["lines"], "total": order["amount_total"], "tax": order["amount_tax"],
        "paid": order["amount_paid"], "change": order["amount_return"],
        "payments": [p for p in order["payments"] if not p["is_change"]], "state": order["state"],
        "customer": order.get("partner"), "on_account": order.get("credit_amount", 0.0),
    }  # fmt: skip


@router.get("/state")
def state(
    cid: uuid.UUID, user: User = Depends(require(P_SALES)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    out = _read(client, "sales_state")
    companies = (c.capability_manifest or {}).get("allowed_companies") or []
    out["company"] = companies[0]["name"] if companies else None
    return out


@router.get("/lookup")
def lookup(
    cid: uuid.UUID, config_id: int = Query(gt=0), code: str = Query(min_length=3, max_length=64),
    user: User = Depends(require(P_SALES)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "sales_lookup", config_id, code)


@router.get("/products")
def search_products(
    cid: uuid.UUID, config_id: int = Query(gt=0), q: str = Query("", max_length=100),
    limit: int = Query(24, ge=1, le=50), user: User = Depends(require(P_SALES)),
    db: Session = Depends(get_session), s: Settings = Depends(get_settings),
    vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "sales_search", config_id, q, limit)


@router.post("/quote")
def quote(
    cid: uuid.UUID, body: QuoteIn, user: User = Depends(require(P_SALES)),
    db: Session = Depends(get_session), s: Settings = Depends(get_settings),
    vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _check_discounts(user, body.lines)
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "sales_quote", body.model_dump())


@router.post("/sessions", status_code=201)
def open_session(
    cid: uuid.UUID, body: OpenSessionIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_SALES)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    op, replayed = operations.begin(db, tenant_id=user.tenant_id, connection_id=c.id, actor_id=user.id,
                                    op_type="sales.session.open", idem=idem, payload=body.model_dump())  # fmt: skip
    if replayed:
        return {**(op.odoo_refs or {}), "replayed": True}
    key = operations.odoo_key(user.tenant_id, c.id, idem)
    try:
        res = client.call_bridge(
            "sales_open_session",
            str(op.id),
            key,
            {**body.model_dump(), "note": f"Elblasy: {user.email}"},
            timeout=60,
        )
        got = client.call_bridge("sales_get_session", res["refs"]["session"]["id"])
    except OdooError as exc:
        raise _write_error(db, op, exc, "session") from exc
    if not (got.get("found") and got["session"]["state"] == "opened"):
        operations.fail(db, op, "needs_review", "Odoo does not show the session as open")
        raise api_error(502, "verification_failed", "Odoo does not show the session as open")
    out = {"session": got["session"], "outcome": res["outcome"], "replayed": False}
    operations.succeed(db, op, out, {"verified": True, "method": "sales_get_session readback"})
    audit.record(db, request, action="sales.session.open", outcome="success", actor=user,
                 target_type="pos_session", target_id=got["session"]["id"],
                 after={"opening_cash": body.opening_cash})  # fmt: skip
    db.commit()
    return out


@router.post("/orders", status_code=201)
def checkout(
    cid: uuid.UUID, body: CheckoutIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_SALES)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _check_discounts(user, body.lines)
    if body.override_credit_limit and not has_permission(user.role, P_CREDIT):
        raise api_error(403, "forbidden", "You do not have permission to override a credit limit")
    c, client = _conn(db, user, cid, s, vault)
    op, replayed = operations.begin(db, tenant_id=user.tenant_id, connection_id=c.id, actor_id=user.id,
                                    op_type="sales.order.create", idem=idem, payload=body.model_dump())  # fmt: skip
    companies = (c.capability_manifest or {}).get("allowed_companies") or []
    company = companies[0]["name"] if companies else None
    if replayed:
        out = dict(op.odoo_refs or {})
        return {**out, "replayed": True}
    key = operations.odoo_key(user.tenant_id, c.id, idem)
    spec = {**body.model_dump(exclude={"override_credit_limit"}), "credit_override": body.override_credit_limit,
            "note": f"Elblasy cashier: {user.email}"}  # fmt: skip
    try:
        res = client.call_bridge("sales_checkout", str(op.id), key, spec, timeout=60)
        got = client.call_bridge("sales_get_order", res["refs"]["order"]["id"])
    except OdooError as exc:
        raise _write_error(db, op, exc, "sale") from exc
    order = got.get("order") if got.get("found") else None
    tendered = sum(p.amount for p in body.payments)
    ok = bool(
        order and order["state"] in PAID_STATES
        and abs(order["amount_total"] - body.expected_total) < MONEY_TOLERANCE
        and abs(order["amount_paid"] - order["amount_total"]) < MONEY_TOLERANCE
        and len(order["lines"]) == len(body.lines)
        and abs(sum(p["amount"] for p in order["payments"] if not p["is_change"]) - tendered) < MONEY_TOLERANCE
        and (  # a credit sale must show a posted invoice that is still open for exactly the credit amount
            not order.get("credit_amount")
            or (order.get("invoice") and order["invoice"]["state"] == "posted"
                and abs(order["invoice"]["amount_residual"] - order["credit_amount"]) < MONEY_TOLERANCE)
        )
    )  # fmt: skip
    if not ok or order is None:
        operations.fail(db, op, "needs_review", "Odoo does not show the sale as requested")
        raise api_error(
            502,
            "verification_failed",
            "Odoo does not show the sale as requested. Do not repeat it; check the order list.",
        )
    stock_done = bool(order["picking_states"]) and all(
        st == "done" for st in order["picking_states"]
    )
    out = {"order": order, "receipt": _receipt(order, company, user.email), "outcome": res["outcome"],
           "stock_updated": stock_done, "replayed": False}  # fmt: skip
    operations.succeed(db, op, out, {"verified": True, "method": "sales_get_order readback"})
    audit.record(db, request, action="sales.order.create", outcome="success", actor=user,
                 target_type="pos_order", target_id=order["id"],
                 after={"total": order["amount_total"], "lines": len(order["lines"]),
                        "discount": any(line.discount > 0 for line in body.lines),
                        "on_credit": order.get("credit_amount", 0.0),
                        "credit_override": body.override_credit_limit})  # fmt: skip
    db.commit()
    return out


@router.get("/orders")
def list_orders(
    cid: uuid.UUID, session_id: int | None = Query(default=None, gt=0), limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100_000), user: User = Depends(require(P_SALES)),
    db: Session = Depends(get_session), s: Settings = Depends(get_settings),
    vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "sales_list_orders", session_id or 0, limit, offset)


@router.post("/orders/{order_id}/refund", status_code=201)
def refund(
    cid: uuid.UUID, order_id: int, body: RefundIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_RETURNS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    payload = {"order_id": order_id, **body.model_dump()}
    op, replayed = operations.begin(db, tenant_id=user.tenant_id, connection_id=c.id, actor_id=user.id,
                                    op_type="sales.order.refund", idem=idem, payload=payload)  # fmt: skip
    if replayed:
        return {**(op.odoo_refs or {}), "replayed": True}
    key = operations.odoo_key(user.tenant_id, c.id, idem)
    try:
        res = client.call_bridge("sales_refund", str(op.id), key, payload, timeout=60)
        got = client.call_bridge("sales_get_order", res["refs"]["order"]["id"])
    except OdooError as exc:
        raise _write_error(db, op, exc, "refund") from exc
    order = got.get("order") if got.get("found") else None
    if not order or order["state"] not in PAID_STATES or order["amount_total"] >= 0:
        operations.fail(db, op, "needs_review", "Odoo does not show the refund as requested")
        raise api_error(502, "verification_failed", "Odoo does not show the refund as requested.")
    out = {"order": order, "outcome": res["outcome"], "replayed": False}
    operations.succeed(db, op, out, {"verified": True, "method": "sales_get_order readback"})
    audit.record(db, request, action="sales.order.refund", outcome="success", actor=user,
                 target_type="pos_order", target_id=order["id"],
                 before={"refunded_order": order_id}, after={"total": order["amount_total"], "partial": bool(body.lines)})  # fmt: skip
    db.commit()
    return out


@router.post("/sessions/{session_id}/close")
def close_session(
    cid: uuid.UUID, session_id: int, body: CloseSessionIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_SALES)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    payload = {"session_id": session_id, **body.model_dump()}
    op, replayed = operations.begin(db, tenant_id=user.tenant_id, connection_id=c.id, actor_id=user.id,
                                    op_type="sales.session.close", idem=idem, payload=payload)  # fmt: skip
    if replayed:
        return {**(op.odoo_refs or {}), "replayed": True}
    key = operations.odoo_key(user.tenant_id, c.id, idem)
    try:
        res = client.call_bridge("sales_close_session", str(op.id), key, payload, timeout=120)
        got = client.call_bridge("sales_get_session", session_id)
    except OdooError as exc:
        raise _write_error(db, op, exc, "closing") from exc
    sess = got.get("session") if got.get("found") else None
    if (
        not sess
        or sess["state"] != "closed"
        or sess.get("move_state", "posted") not in ("posted", None)
    ):
        operations.fail(
            db, op, "needs_review", "Odoo does not show the session as closed with a posted entry"
        )
        raise api_error(
            502,
            "verification_failed",
            "Odoo does not show the session as closed. Check it in Odoo before retrying.",
        )
    diff = sess.get("cash_difference", 0.0)
    out = {"session": sess, "cash_difference": diff, "has_difference": abs(diff) >= MONEY_TOLERANCE,
           "outcome": res["outcome"], "replayed": False}  # fmt: skip
    operations.succeed(db, op, out, {"verified": True, "method": "sales_get_session readback"})
    audit.record(db, request, action="sales.session.close", outcome="success", actor=user,
                 target_type="pos_session", target_id=session_id,
                 after={"counted": body.counted_cash, "expected": sess.get("expected_cash"), "difference": diff})  # fmt: skip
    db.commit()
    return out


@router.get("/summary")
def summary(
    cid: uuid.UUID, day: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user: User = Depends(require(P_REPORTS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    out = _read(client, "sales_summary", day or False)
    out["definition"] = {
        "net_sales": "Paid POS orders of the day, tax included, refunds subtracted",
        "cash_collected": "Net cash payments on those orders (change given is subtracted)",
        "source": "Odoo pos.order / pos.payment, read live",
    }
    return out


@router.get("/insights")
def insights(
    cid: uuid.UUID, days: int = Query(7, ge=1, le=31),
    user: User = Depends(require(P_REPORTS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    """A week of sales, best sellers, slow-moving stock and goods near expiry, from Odoo, read live."""
    _, client = _conn(db, user, cid, s, vault)
    out = _read(client, "insights_snapshot", days)
    out["definition"] = {
        "sales_by_day": "Paid POS orders per local day, tax included, refunds subtracted",
        "slow_moving": "In stock but not sold at the till in the last 30 days, ranked by stock value",
        "expiring": "Lots with stock that expire within 30 days (or already have)",
    }
    return out
