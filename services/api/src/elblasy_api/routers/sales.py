"""Sales on Odoo's POS. Every money-moving call is a tracked, idempotent operation, verified by a
fresh read of Odoo before it is reported as done. The platform never computes prices or taxes."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from elblasy_api import audit, operations
from elblasy_api.config import Settings, get_settings
from elblasy_api.db import get_session
from elblasy_api.deps import api_error, get_vault, require, require_any
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


def _apply_refund(
    db: Session, request: Request, *, actor: User, requested_by: User, c: OdooConnection, client: BridgeClient,
    idem: str, order_id: int, body: RefundIn, approval_ref: str | None = None,
) -> dict[str, Any]:  # fmt: skip
    payload = {"order_id": order_id, **body.model_dump()}
    op, replayed = operations.begin(db, tenant_id=actor.tenant_id, connection_id=c.id, actor_id=actor.id,
                                    op_type="sales.order.refund", idem=idem, payload=payload)  # fmt: skip
    if replayed:
        return {**(op.odoo_refs or {}), "replayed": True}
    key = operations.odoo_key(actor.tenant_id, c.id, idem)
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
    audit.record(db, request, action="sales.order.refund" if not approval_ref else "sales.order.refund.approved",
                 outcome="success", actor=actor, target_type="pos_order", target_id=order["id"],
                 before={"refunded_order": order_id},
                 after={"total": order["amount_total"], "partial": bool(body.lines),
                        "requested_by": requested_by.email, "approval_ref": approval_ref})  # fmt: skip
    db.commit()
    return out


@router.post("/orders/{order_id}/refund", status_code=201)
def refund(
    cid: uuid.UUID, order_id: int, body: RefundIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_RETURNS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    return _apply_refund(db, request, actor=user, requested_by=user, c=c, client=client, idem=idem,
                         order_id=order_id, body=body)  # fmt: skip


# ---- refund requests: a cashier asks, someone with the returns permission decides ----
REQ_TYPE = "sales.refund.request"


class DecisionIn(BaseModel):
    note: str = Field(default="", max_length=300)


@router.post("/orders/{order_id}/refund-request", status_code=202)
def request_refund(
    cid: uuid.UUID, order_id: int, body: RefundIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_SALES)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    payload = {"order_id": order_id, **body.model_dump()}
    existing = db.scalar(select(Operation).where(Operation.tenant_id == user.tenant_id, Operation.connection_id == c.id,
                                                 Operation.type == REQ_TYPE, Operation.idempotency_key == idem))  # fmt: skip
    if existing:
        if existing.request_fingerprint != operations.fingerprint(payload):
            raise api_error(
                409,
                "idempotency_conflict",
                "This Idempotency-Key was used with a different request",
            )
        return {"operation_id": str(existing.id), "status": existing.status, "replayed": True}
    got = _read(client, "sales_get_order", order_id)
    order = got.get("order") if got.get("found") else None
    if not order or order["state"] not in PAID_STATES or order["amount_total"] <= 0:
        raise api_error(422, "refund_rejected", "Only a paid sale can be refunded.")
    if all(ln.get("refunded_qty", 0) >= ln["qty"] - 1e-9 for ln in order["lines"]):
        raise api_error(422, "refund_rejected", "This sale was already refunded.")
    op = Operation(tenant_id=user.tenant_id, connection_id=c.id, type=REQ_TYPE, idempotency_key=idem,
                   request_fingerprint=operations.fingerprint(payload), actor_id=user.id,
                   status="awaiting_approval", payload=payload,
                   verification={"order": order["name"], "amount": order["amount_total"]})  # fmt: skip
    db.add(op)
    audit.record(db, request, action="sales.refund.requested", outcome="success", actor=user,
                 target_type="pos_order", target_id=order_id, after={"partial": bool(body.lines)})  # fmt: skip
    db.commit()
    return {"operation_id": str(op.id), "status": "awaiting_approval", "replayed": False}


@router.get("/refund-requests")
def list_refund_requests(
    cid: uuid.UUID, status: str | None = Query(default=None, max_length=24),
    user: User = Depends(require_any(P_SALES, P_RETURNS)), db: Session = Depends(get_session),
) -> dict[str, Any]:  # fmt: skip
    _owned(db, user, cid)
    q = (select(Operation, User.email).join(User, User.id == Operation.actor_id)
         .where(Operation.tenant_id == user.tenant_id, Operation.connection_id == cid, Operation.type == REQ_TYPE)
         .order_by(Operation.created_at.desc()).limit(100))  # fmt: skip
    if not has_permission(user.role, P_RETURNS):  # a cashier sees only their own
        q = q.where(Operation.actor_id == user.id)
    if status:
        q = q.where(Operation.status == status)
    return {"items": [{"id": str(op.id), "status": op.status, "requested_by": email, "created_at": op.created_at,
                       "order": (op.verification or {}).get("order"), "amount": (op.verification or {}).get("amount"),
                       "order_id": (op.payload or {}).get("order_id"), "partial": bool((op.payload or {}).get("lines")),
                       "note": op.safe_error if op.status == "rejected" else None}
                      for op, email in db.execute(q)]}  # fmt: skip


def _pending_request(db: Session, user: User, cid: uuid.UUID, op_id: uuid.UUID) -> Operation:
    op = db.scalar(select(Operation).where(Operation.id == op_id, Operation.connection_id == cid,
                                           Operation.tenant_id == user.tenant_id, Operation.type == REQ_TYPE))  # fmt: skip
    if op is None:
        raise api_error(404, "not_found", "Request not found")
    if op.status != "awaiting_approval" or not op.payload:
        raise api_error(409, "not_pending", f"This request is {op.status}")
    return op


@router.post("/refund-requests/{op_id}/approve")
def approve_refund(
    cid: uuid.UUID, op_id: uuid.UUID, request: Request,
    user: User = Depends(require(P_RETURNS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    op = _pending_request(db, user, c.id, op_id)
    if op.actor_id == user.id:  # segregation of duties
        raise api_error(403, "self_approval", "You cannot approve your own request")
    requester = db.get(User, op.actor_id)
    assert requester is not None  # noqa: S101
    payload = dict(op.payload or {})
    out = _apply_refund(db, request, actor=user, requested_by=requester, c=c, client=client,
                        idem=f"rr-{op.id.hex}", order_id=int(payload["order_id"]),
                        body=RefundIn.model_validate({k: v for k, v in payload.items() if k != "order_id"}),
                        approval_ref=str(op.id))  # fmt: skip
    op.status, op.decided_by = "succeeded", user.id
    db.commit()
    return out


@router.post("/refund-requests/{op_id}/reject")
def reject_refund(
    cid: uuid.UUID, op_id: uuid.UUID, body: DecisionIn, request: Request,
    user: User = Depends(require(P_RETURNS)), db: Session = Depends(get_session),
) -> dict[str, Any]:  # fmt: skip
    _owned(db, user, cid)
    op = _pending_request(db, user, cid, op_id)
    op.status, op.decided_by, op.safe_error = "rejected", user.id, (body.note or "rejected")[:500]
    audit.record(db, request, action="sales.refund.rejected", outcome="success", actor=user,
                 target_type="pos_order", target_id=(op.payload or {}).get("order_id"), after={"note": body.note})  # fmt: skip
    db.commit()
    return {"id": str(op.id), "status": "rejected"}


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
