"""Customers, credit limits, customer statements and collecting what customers owe.

A credit sale (POS, 'Customer account') becomes an open invoice in Odoo; collecting is an inbound payment on
it. All writes are tracked, idempotent and verified by a fresh read."""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from elblasy_api import operations
from elblasy_api.config import Settings, get_settings
from elblasy_api.db import get_session
from elblasy_api.deps import api_error, get_vault, require, require_any
from elblasy_api.models import OdooConnection, User
from elblasy_api.odoo.client import BridgeClient, OdooError, OdooRejectedError
from elblasy_api.routers.connections import _client, _owned
from elblasy_api.security.rbac import (
    P_CREDIT,
    P_CUSTOMERS,
    P_PAYMENTS,
    P_REPORTS,
    P_SALES,
    has_permission,
)  # fmt: skip
from elblasy_api.security.vault import SecretVault

router = APIRouter(prefix="/connections/{cid}/customers", tags=["customers"])
IDEM = Annotated[
    str, Header(alias="Idempotency-Key", min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
]
TOL = 0.005


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    credit_limit: float | None = Field(default=None, ge=0, le=1e9)


class LimitIn(BaseModel):
    credit_limit: float = Field(ge=0, le=1e9)


class ReceiveIn(BaseModel):
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
            422, "customers_rejected", str(exc).removeprefix("Odoo rejected the call: ")
        ) from exc
    except OdooError as exc:
        raise api_error(502, "odoo_unavailable", str(exc)) from exc


def _fail(what: str) -> Exception:
    return api_error(
        502,
        "verification_failed",
        f"Odoo does not show the {what} as requested. Check it in Odoo before retrying.",
    )


def _sees_balances(user: User) -> bool:
    return any(has_permission(user.role, p) for p in (P_CREDIT, P_PAYMENTS, P_REPORTS))


@router.post("", status_code=201)
def create_customer(
    cid: uuid.UUID, body: CustomerIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_CUSTOMERS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    if body.credit_limit is not None and not has_permission(user.role, P_CREDIT):
        raise api_error(
            403, "forbidden", "Only roles that manage customer credit can set a credit limit"
        )
    c, client = _conn(db, user, cid, s, vault)

    def verify(res: dict[str, Any], _: Any) -> dict[str, Any]:
        got = client.call_bridge("customer_statement", res["refs"]["customer"]["id"])
        if not got.get("found") or got["customer"]["name"] != body.name.strip():
            raise _fail("customer")
        return {"customer": got["customer"]}

    out = operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="customers.create", idem=idem,
        payload=body.model_dump(), method="customers_upsert", spec=body.model_dump(exclude_none=True),
        verify=verify, what="customer", audit_action="customers.create", target_type="customer",
        target_id=lambda o: o["customer"]["id"], audit_after=lambda o: {"name": o["customer"]["name"], "credit_limit": body.credit_limit},
        rejected_code="customer_rejected",
    )  # fmt: skip
    if not _sees_balances(user):
        for k in ("receivable", "available_credit", "credit_limit"):
            out["customer"].pop(k, None)
    return out


@router.get("")
def list_customers(
    cid: uuid.UUID, q: str = Query("", max_length=100), limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100_000), user: User = Depends(require_any(P_CUSTOMERS, P_SALES, P_PAYMENTS)),
    db: Session = Depends(get_session), s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    res = _read(client, "customers_search", q, limit, offset, _sees_balances(user))
    if not _sees_balances(user):  # what customers owe, and their limits, are finance information
        for it in res.get("items", []):
            it.pop("credit_limit", None)
    return res


@router.get("/{customer_id}/statement")
def statement(
    cid: uuid.UUID, customer_id: int, user: User = Depends(require_any(P_PAYMENTS, P_REPORTS)),
    db: Session = Depends(get_session), s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    res = _read(client, "customer_statement", customer_id)
    if not res.get("found"):
        raise api_error(404, "not_found", "Customer not found")
    return res


@router.put("/{customer_id}/credit-limit")
def set_credit_limit(
    cid: uuid.UUID, customer_id: int, body: LimitIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_CREDIT)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)

    def verify(res: dict[str, Any], _: Any) -> dict[str, Any]:
        got = client.call_bridge("customer_statement", customer_id)
        if not got.get("found") or abs(got["customer"]["credit_limit"] - body.credit_limit) > TOL:
            raise _fail("credit limit")
        return {"customer": got["customer"]}

    return operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="customers.credit_limit", idem=idem,
        payload={"customer_id": customer_id, **body.model_dump()}, method="customers_set_credit_limit",
        spec={"partner_id": customer_id, **body.model_dump()}, verify=verify, what="credit limit",
        audit_action="customers.credit_limit", target_type="customer", target_id=lambda o: customer_id,
        audit_after=lambda o: {"credit_limit": body.credit_limit}, rejected_code="customer_rejected",
    )  # fmt: skip


@router.post("/invoices/{invoice_id}/receive", status_code=201)
def receive_payment(
    cid: uuid.UUID, invoice_id: int, body: ReceiveIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_PAYMENTS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)

    def before() -> dict[str, Any]:
        got = _read(client, "invoice_get", invoice_id)
        if not got.get("found"):
            raise api_error(404, "not_found", "Invoice not found")
        inv: dict[str, Any] = got["invoice"]
        return inv

    def verify(res: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
        got = client.call_bridge("invoice_get", invoice_id)
        inv = got.get("invoice") if got.get("found") else None
        if not inv or abs(inv["amount_residual"] - (prior["amount_residual"] - body.amount)) > TOL:
            raise _fail("payment")
        return {"invoice": inv, "payment_id": res["refs"]["payment_id"]}

    return operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="customers.receive", idem=idem,
        payload={"invoice_id": invoice_id, **body.model_dump()}, method="receivable_receive",
        spec={"invoice_id": invoice_id, **body.model_dump()}, verify=verify, before=before, what="payment",
        audit_action="customers.receive", target_type="customer_invoice", target_id=lambda o: invoice_id,
        audit_after=lambda o: {"amount": body.amount, "journal": body.journal_type, "residual": o["invoice"]["amount_residual"]},
        rejected_code="payment_rejected",
    )  # fmt: skip
