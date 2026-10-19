"""Expenses and the money overview.

An expense is a posted vendor bill on an operating-expense account (the document); paying it is a
separate payment (the cash movement). The platform never assumes an expense is paid. Expenses above
a threshold entered by someone other than the owner/manager wait for approval."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from elblasy_api import audit, operations
from elblasy_api.config import Settings, get_settings
from elblasy_api.db import get_session
from elblasy_api.deps import api_error, get_vault, require, require_any
from elblasy_api.models import ExpenseCategory, OdooConnection, Operation, User
from elblasy_api.odoo.client import BridgeClient, OdooError, OdooRejectedError
from elblasy_api.routers.connections import _client, _owned
from elblasy_api.security.rbac import (
    P_CONFIG,
    P_EXPENSE_APPROVE,
    P_EXPENSES,
    P_PAYMENTS,
    P_REPORTS,
    Role,
)  # fmt: skip
from elblasy_api.security.vault import SecretVault

router = APIRouter(prefix="/connections/{cid}/money", tags=["money"])
IDEM = Annotated[
    str, Header(alias="Idempotency-Key", min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
]
TOL = 0.005
EXP_TYPE = "money.expense.create"
SEE_MONEY = (P_REPORTS, P_PAYMENTS, P_EXPENSES)


class CategoryIn(BaseModel):
    account_id: int = Field(gt=0)
    label: str = Field(min_length=1, max_length=120)


class PayNow(BaseModel):
    journal_type: Literal["cash", "bank"] = "cash"


class ExpenseIn(BaseModel):
    category_id: uuid.UUID
    amount: float = Field(gt=0, le=1e9)
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    description: str = Field(min_length=1, max_length=300)
    ref: str | None = Field(default=None, max_length=100)
    partner_id: int | None = Field(default=None, gt=0)
    pay_now: PayNow | None = None  # None = on credit: it stays a payable until paid


class PayIn(BaseModel):
    amount: float = Field(gt=0, le=1e9)
    journal_type: Literal["cash", "bank"] = "cash"


class DecisionIn(BaseModel):
    note: str | None = Field(default=None, max_length=200)


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
            422, "money_rejected", str(exc).removeprefix("Odoo rejected the call: ")
        ) from exc
    except OdooError as exc:
        raise api_error(502, "odoo_unavailable", str(exc)) from exc


def _fail(what: str) -> Exception:
    return api_error(
        502,
        "verification_failed",
        f"Odoo does not show the {what} as requested. Check it in Odoo before retrying.",
    )


# ---------------- categories ----------------
@router.get("/expense-accounts")
def expense_accounts(
    cid: uuid.UUID, user: User = Depends(require(P_CONFIG)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    """Odoo's operating-expense accounts (cost of goods sold is deliberately not offered)."""
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "expense_accounts")


@router.get("/categories")
def list_categories(
    cid: uuid.UUID, user: User = Depends(require_any(*SEE_MONEY)), db: Session = Depends(get_session)
) -> dict[str, Any]:  # fmt: skip
    _owned(db, user, cid)
    rows = db.scalars(select(ExpenseCategory).where(ExpenseCategory.tenant_id == user.tenant_id,
                                                    ExpenseCategory.connection_id == cid,
                                                    ExpenseCategory.active.is_(True)).order_by(ExpenseCategory.label))  # fmt: skip
    return {
        "items": [
            {
                "id": str(r.id),
                "label": r.label,
                "account_id": r.account_id,
                "account": r.account_label,
            }
            for r in rows
        ]
    }


@router.post("/categories", status_code=201)
def create_category(
    cid: uuid.UUID, body: CategoryIn, request: Request, user: User = Depends(require(P_CONFIG)),
    db: Session = Depends(get_session), s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    accounts = {a["id"]: a for a in _read(client, "expense_accounts").get("items", [])}
    acct = accounts.get(body.account_id)
    if not acct:
        raise api_error(
            422, "not_an_expense_account", "This account is not an operating-expense account"
        )
    row = ExpenseCategory(tenant_id=user.tenant_id, connection_id=c.id, account_id=acct["id"],
                          account_label=f"{acct['code']} {acct['name']}", label=body.label.strip())  # fmt: skip
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise api_error(409, "category_exists", "A category already uses this account") from exc
    audit.record(db, request, action="money.category.create", outcome="success", actor=user,
                 target_type="expense_category", target_id=row.id, after={"label": row.label, "account": row.account_label})  # fmt: skip
    db.commit()
    return {
        "id": str(row.id),
        "label": row.label,
        "account_id": row.account_id,
        "account": row.account_label,
    }


@router.delete("/categories/{category_id}", status_code=204)
def delete_category(
    cid: uuid.UUID, category_id: uuid.UUID, request: Request, user: User = Depends(require(P_CONFIG)),
    db: Session = Depends(get_session),
) -> None:  # fmt: skip
    """Deactivates only; expenses already booked keep their Odoo account."""
    _owned(db, user, cid)
    row = db.scalar(select(ExpenseCategory).where(ExpenseCategory.id == category_id, ExpenseCategory.connection_id == cid,
                                                  ExpenseCategory.tenant_id == user.tenant_id))  # fmt: skip
    if row is None:
        raise api_error(404, "not_found", "Category not found")
    row.active = False
    audit.record(db, request, action="money.category.delete", outcome="success", actor=user,
                 target_type="expense_category", target_id=row.id)  # fmt: skip
    db.commit()


# ---------------- expenses ----------------
def _category(db: Session, user: User, cid: uuid.UUID, category_id: uuid.UUID) -> ExpenseCategory:
    row = db.scalar(select(ExpenseCategory).where(ExpenseCategory.id == category_id, ExpenseCategory.connection_id == cid,
                                                  ExpenseCategory.tenant_id == user.tenant_id, ExpenseCategory.active.is_(True)))  # fmt: skip
    if row is None:
        raise api_error(422, "unknown_category", "Choose one of the expense categories")
    return row


def _needs_approval(user: User, amount: float, s: Settings) -> bool:
    return (
        user.role not in (Role.OWNER.value, Role.MANAGER.value)
        and amount > s.expense_approval_value
    )


def _spec(body: ExpenseIn, cat: ExpenseCategory, note: str) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "account_id": cat.account_id,
        "amount": body.amount,
        "description": f"{body.description} ({note})" if note else body.description,
    }
    for k in ("date", "ref", "partner_id"):
        v = getattr(body, k)
        if v is not None:
            spec[k] = v
    if body.pay_now:
        spec["pay_now"] = body.pay_now.model_dump()
    return spec


def _apply(
    db: Session, request: Request, *, actor: User, requester: User, c: OdooConnection, client: BridgeClient,
    idem: str, payload: dict[str, Any], approval_ref: str | None = None,
) -> dict[str, Any]:  # fmt: skip
    body = ExpenseIn(**payload)
    cat = _category(db, actor, c.id, body.category_id)
    note = f"entered by {requester.email}" + (
        f", approved by {actor.email}" if approval_ref else ""
    )
    paid = body.pay_now is not None

    def verify(res: dict[str, Any], _: Any) -> dict[str, Any]:
        got = client.call_bridge("expense_get", res["refs"]["expense"]["id"])
        e = got.get("expense") if got.get("found") else None
        if (
            not e or e["state"] != "posted" or abs(e["amount_total"] - body.amount) > TOL or e["account_id"] != cat.account_id
            or (paid and e["payment_state"] not in ("paid", "in_payment"))
            or (not paid and e["payment_state"] != "not_paid")
        ):  # fmt: skip
            raise _fail("expense")
        return {"expense": e, "category": cat.label, "taxes_applied": False}

    return operations.run_write(
        db, request, user=actor, conn=c, client=client, op_type=EXP_TYPE, idem=idem, payload=payload,
        method="expense_create", spec=_spec(body, cat, note), verify=verify, what="expense",
        audit_action="money.expense.approved" if approval_ref else "money.expense.create", target_type="vendor_bill",
        target_id=lambda o: o["expense"]["id"],
        audit_after=lambda o: {"category": cat.label, "amount": body.amount, "paid_now": paid, "approval_ref": approval_ref},
        rejected_code="expense_rejected", keep_payload=True,
    )  # fmt: skip


def _json(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status, content=jsonable_encoder(body))


@router.post("/expenses")
def create_expense(
    cid: uuid.UUID, body: ExpenseIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_EXPENSES)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> Any:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    _category(db, user, c.id, body.category_id)
    payload = body.model_dump(mode="json")
    existing = db.scalar(select(Operation).where(Operation.tenant_id == user.tenant_id, Operation.connection_id == c.id,
                                                 Operation.type == EXP_TYPE, Operation.idempotency_key == idem))  # fmt: skip
    if existing and existing.status == "awaiting_approval":
        if existing.request_fingerprint != operations.fingerprint(payload):
            raise api_error(
                409,
                "idempotency_conflict",
                "This Idempotency-Key was used with a different request",
            )
        return _json(202, {"operation_id": str(existing.id), "status": "awaiting_approval"})
    if _needs_approval(user, body.amount, s):
        op = Operation(tenant_id=user.tenant_id, connection_id=c.id, type=EXP_TYPE, idempotency_key=idem,
                       request_fingerprint=operations.fingerprint(payload), actor_id=user.id,
                       status="awaiting_approval", payload=payload)  # fmt: skip
        db.add(op)
        audit.record(db, request, action="money.expense.requested", outcome="success", actor=user,
                     target_type="vendor_bill", target_id=idem[:12], after={"amount": body.amount, "needs_approval": True})  # fmt: skip
        db.commit()
        return _json(202, {"operation_id": str(op.id), "status": "awaiting_approval"})
    out = _apply(
        db, request, actor=user, requester=user, c=c, client=client, idem=idem, payload=payload
    )
    return _json(201, out)


@router.get("/expenses")
def list_expenses(
    cid: uuid.UUID, date_from: str | None = Query(default=None, alias="from", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, alias="to", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0, le=100_000),
    user: User = Depends(require_any(*SEE_MONEY)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "expense_list", limit, offset, date_from or "", date_to or "")


@router.get("/expense-requests")
def pending_expenses(
    cid: uuid.UUID, user: User = Depends(require_any(P_EXPENSES, P_EXPENSE_APPROVE)),
    db: Session = Depends(get_session),
) -> dict[str, Any]:  # fmt: skip
    _owned(db, user, cid)
    q = (
        select(Operation, User.email)
        .join(User, User.id == Operation.actor_id)
        .where(
            Operation.tenant_id == user.tenant_id,
            Operation.connection_id == cid,
            Operation.type == EXP_TYPE,
            Operation.status == "awaiting_approval",
        )
        .order_by(Operation.created_at.desc())
        .limit(100)
    )
    return {"items": [{"id": str(op.id), "requested_by": email, "created_at": op.created_at, "amount": (op.payload or {}).get("amount"),
                       "description": (op.payload or {}).get("description"), "paid_now": bool((op.payload or {}).get("pay_now"))}
                      for op, email in db.execute(q)]}  # fmt: skip


def _pending(db: Session, user: User, cid: uuid.UUID, op_id: uuid.UUID) -> Operation:
    op = db.scalar(select(Operation).where(Operation.id == op_id, Operation.connection_id == cid,
                                           Operation.tenant_id == user.tenant_id, Operation.type == EXP_TYPE))  # fmt: skip
    if op is None:
        raise api_error(404, "not_found", "Request not found")
    return op


@router.post("/expense-requests/{op_id}/approve")
def approve_expense(
    cid: uuid.UUID, op_id: uuid.UUID, request: Request, user: User = Depends(require(P_EXPENSE_APPROVE)),
    db: Session = Depends(get_session), s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    op = _pending(db, user, c.id, op_id)
    if op.status != "awaiting_approval" or not op.payload:
        raise api_error(409, "not_pending", f"This request is {op.status}")
    if op.actor_id == user.id:
        raise api_error(403, "self_approval", "You cannot approve your own request")
    requester = db.get(User, op.actor_id)
    if requester is None:
        raise api_error(404, "not_found", "Requester not found")
    op.decided_by = user.id
    db.commit()
    return _apply(db, request, actor=user, requester=requester, c=c, client=client, idem=op.idempotency_key,
                  payload=op.payload, approval_ref=str(op.id))  # fmt: skip


@router.post("/expense-requests/{op_id}/reject")
def reject_expense(
    cid: uuid.UUID, op_id: uuid.UUID, body: DecisionIn, request: Request,
    user: User = Depends(require(P_EXPENSE_APPROVE)), db: Session = Depends(get_session),
) -> dict[str, Any]:  # fmt: skip
    _owned(db, user, cid)
    op = _pending(db, user, cid, op_id)
    if op.status != "awaiting_approval":
        raise api_error(409, "not_pending", f"This request is {op.status}")
    op.status, op.decided_by, op.safe_error = "rejected", user.id, (body.note or "rejected")[:500]
    audit.record(db, request, action="money.expense.rejected", outcome="success", actor=user,
                 target_type="vendor_bill", target_id=str(op.id), after={"note": body.note})  # fmt: skip
    db.commit()
    return {"id": str(op.id), "status": "rejected"}


@router.post("/expenses/{bill_id}/pay", status_code=201)
def pay_expense(
    cid: uuid.UUID, bill_id: int, body: PayIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_PAYMENTS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)

    def before() -> dict[str, Any]:
        got = _read(client, "expense_get", bill_id)
        if not got.get("found"):
            raise api_error(404, "not_found", "Expense not found")
        exp: dict[str, Any] = got["expense"]
        return exp

    def verify(res: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
        got = client.call_bridge("expense_get", bill_id)
        e = got.get("expense") if got.get("found") else None
        if not e or abs(e["amount_residual"] - (prior["amount_residual"] - body.amount)) > TOL:
            raise _fail("payment")
        return {"expense": e, "payment_id": res["refs"]["payment_id"]}

    return operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="money.expense.pay", idem=idem,
        payload={"bill_id": bill_id, **body.model_dump()}, method="purchase_pay_bill",
        spec={"bill_id": bill_id, **body.model_dump()}, verify=verify, before=before, what="payment",
        audit_action="money.expense.pay", target_type="vendor_bill", target_id=lambda o: bill_id,
        audit_after=lambda o: {"amount": body.amount, "journal": body.journal_type, "residual": o["expense"]["amount_residual"]},
        rejected_code="payment_rejected",
    )  # fmt: skip


# ---------------- money overview ----------------
def _month() -> tuple[str, str]:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-01"), now.strftime("%Y-%m-%d")


@router.get("/overview")
def overview(
    cid: uuid.UUID, user: User = Depends(require_any(P_REPORTS, P_PAYMENTS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    """Cash and bank balances, payables and this month's expenses: separate figures, each with its definition.
    Net profit is deliberately NOT computed here (sales minus cash expenses would be wrong)."""
    _, client = _conn(db, user, cid, s, vault)
    base = _read(client, "money_overview")
    d_from, d_to = _month()
    exp = _read(client, "expense_summary", d_from, d_to)
    return {**base, "expenses_month": exp,
            "net_profit": {"available": False, "reason": "Net profit needs revenue, cost of goods sold and all expenses from a closed accounting period; it is not estimated from cash movements."}}  # fmt: skip


@router.get("/ledger")
def ledger(
    cid: uuid.UUID, kind: Literal["cash", "bank"] = "cash", limit: int = Query(30, ge=1, le=100),
    user: User = Depends(require_any(P_REPORTS, P_PAYMENTS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "money_ledger", kind, limit)
