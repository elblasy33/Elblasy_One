"""Audit log, operation history and the alerts centre.

Everything here is tenant-scoped. The audit log is append-only in the database; this router only reads
it (and records that an export happened). Alerts are permission-aware: a user only sees alerts they
could act on."""

import csv
import io
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from elblasy_api import audit
from elblasy_api.config import Settings, get_settings
from elblasy_api.db import get_session
from elblasy_api.deps import current_user, get_vault, require
from elblasy_api.models import AuditEvent, OdooConnection, Operation, SetupPlan, User
from elblasy_api.routers.connections import _client
from elblasy_api.security.rbac import (
    P_AUDIT,
    P_EXPENSE_APPROVE,
    P_PAYMENTS,
    P_PURCHASING_VIEW,
    P_SALES,
    P_STOCK_ADJUST,
    P_STOCK_APPROVE,
    has_permission,
)  # fmt: skip
from elblasy_api.security.vault import SecretVault

router = APIRouter(tags=["oversight"])
log = logging.getLogger("elblasy.alerts")
_HIDE = {"_before"}


def _scrub(d: dict[str, Any] | None) -> dict[str, Any] | None:
    return None if d is None else {k: v for k, v in d.items() if k not in _HIDE}


def _filters(user: User, action: str | None, outcome: str | None, actor: str | None,
             date_from: str | None, date_to: str | None) -> list[Any]:  # fmt: skip
    conds: list[Any] = [AuditEvent.tenant_id == user.tenant_id]
    if action:
        conds.append(AuditEvent.action.like(f"{action}%"))
    if outcome:
        conds.append(AuditEvent.outcome == outcome)
    if actor:
        conds.append(User.email == actor.lower())
    if date_from:
        conds.append(AuditEvent.ts >= datetime.fromisoformat(date_from).replace(tzinfo=UTC))
    if date_to:
        conds.append(
            AuditEvent.ts
            < datetime.fromisoformat(date_to)
            .replace(tzinfo=UTC)
            .replace(hour=23, minute=59, second=59)
        )
    return conds


@router.get("/audit")
def audit_log(
    action: str | None = Query(default=None, max_length=64), outcome: str | None = Query(default=None, pattern="^(success|denied|failure)$"),
    actor: str | None = Query(default=None, max_length=320),
    date_from: str | None = Query(default=None, alias="from", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, alias="to", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0, le=1_000_000),
    user: User = Depends(require(P_AUDIT)), db: Session = Depends(get_session),
) -> dict[str, Any]:  # fmt: skip
    conds = _filters(user, action, outcome, actor, date_from, date_to)
    base = (
        select(AuditEvent, User.email).outerjoin(User, User.id == AuditEvent.actor_id).where(*conds)
    )
    total = (
        db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .outerjoin(User, User.id == AuditEvent.actor_id)
            .where(*conds)
        )
        or 0
    )
    rows = db.execute(base.order_by(AuditEvent.id.desc()).limit(limit).offset(offset))
    return {"total": total, "items": [
        {"id": e.id, "ts": e.ts, "action": e.action, "outcome": e.outcome, "actor": email, "target_type": e.target_type,
         "target_id": e.target_id, "before": _scrub(e.before), "after": _scrub(e.after), "correlation_id": e.correlation_id}
        for e, email in rows
    ]}  # fmt: skip


@router.get("/audit/export")
def audit_export(
    request: Request, action: str | None = Query(default=None, max_length=64),
    outcome: str | None = Query(default=None, pattern="^(success|denied|failure)$"),
    date_from: str | None = Query(default=None, alias="from", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, alias="to", pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user: User = Depends(require(P_AUDIT)), db: Session = Depends(get_session),
) -> Response:  # fmt: skip
    conds = _filters(user, action, outcome, None, date_from, date_to)
    rows = db.execute(select(AuditEvent, User.email).outerjoin(User, User.id == AuditEvent.actor_id).where(*conds)
                      .order_by(AuditEvent.id.desc()).limit(10_000))  # fmt: skip
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "id",
            "timestamp",
            "action",
            "outcome",
            "actor",
            "target_type",
            "target_id",
            "correlation_id",
            "after",
        ]
    )
    for e, email in rows:
        w.writerow([e.id, e.ts.isoformat(), e.action, e.outcome, email or "", e.target_type or "", e.target_id or "",
                    e.correlation_id or "", str(_scrub(e.after) or "")])  # fmt: skip
    audit.record(
        db,
        request,
        action="audit.export",
        outcome="success",
        actor=user,
        after={"rows_limit": 10_000},
    )
    db.commit()
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"content-disposition": 'attachment; filename="audit-log.csv"'})  # fmt: skip


@router.get("/operations")
def operations_list(
    status: str | None = Query(default=None, max_length=24), type: str | None = Query(default=None, max_length=64, alias="type"),
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0, le=1_000_000),
    user: User = Depends(require(P_AUDIT)), db: Session = Depends(get_session),
) -> dict[str, Any]:  # fmt: skip
    conds: list[Any] = [Operation.tenant_id == user.tenant_id]
    if status:
        conds.append(Operation.status == status)
    if type:
        conds.append(Operation.type.like(f"{type}%"))
    total = db.scalar(select(func.count()).select_from(Operation).where(*conds)) or 0
    rows = db.execute(select(Operation, User.email).join(User, User.id == Operation.actor_id).where(*conds)
                      .order_by(Operation.created_at.desc()).limit(limit).offset(offset))  # fmt: skip
    return {"total": total, "items": [
        {"id": str(o.id), "type": o.type, "status": o.status, "actor": email, "created_at": o.created_at, "updated_at": o.updated_at,
         "safe_error": o.safe_error, "verified": bool((o.verification or {}).get("verified")), "connection_id": str(o.connection_id),
         "needs_attention": o.status in ("needs_review", "failed")}
        for o, email in rows
    ]}  # fmt: skip


def _alert(
    key: str, severity: str, count: int, perm: str, link: str, detail: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "key": key,
        "severity": severity,
        "count": count,
        "permission": perm,
        "link": link,
        "detail": detail or {},
    }


@router.get("/alerts")
def alerts(
    user: User = Depends(current_user), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    """Actionable, permission-aware alerts. Platform facts always; Odoo facts when a connection answers."""
    out: list[dict[str, Any]] = []
    t = user.tenant_id

    def cnt(*c: Any) -> int:
        return int(
            db.scalar(
                select(func.count()).select_from(Operation).where(Operation.tenant_id == t, *c)
            )
            or 0
        )

    if has_permission(user.role, P_AUDIT):
        n = cnt(Operation.status == "needs_review")
        if n:
            out.append(
                _alert(
                    "operations_need_review",
                    "critical",
                    n,
                    P_AUDIT,
                    "/settings/audit?tab=operations&status=needs_review",
                )
            )
        n = cnt(
            Operation.status == "failed",
            Operation.updated_at > datetime.now(UTC).replace(hour=0, minute=0, second=0),
        )
        if n:
            out.append(
                _alert(
                    "operations_failed_today",
                    "warning",
                    n,
                    P_AUDIT,
                    "/settings/audit?tab=operations&status=failed",
                )
            )
    if has_permission(user.role, P_STOCK_APPROVE):
        n = cnt(Operation.status == "awaiting_approval", Operation.type == "stock.adjust")
        if n:
            out.append(
                _alert(
                    "stock_adjustments_waiting", "warning", n, P_STOCK_APPROVE, "/inventory/stock"
                )
            )
    if has_permission(user.role, P_EXPENSE_APPROVE):
        n = cnt(Operation.status == "awaiting_approval", Operation.type == "money.expense.create")
        if n:
            out.append(
                _alert("expenses_waiting", "warning", n, P_EXPENSE_APPROVE, "/money/expenses")
            )
    if has_permission(user.role, "config.manage"):
        n = int(
            db.scalar(
                select(func.count())
                .select_from(SetupPlan)
                .where(SetupPlan.tenant_id == t, SetupPlan.status.in_(("needs_review", "failed")))
            )
            or 0
        )
        if n:
            out.append(_alert("setup_needs_attention", "critical", n, "config.manage", "/settings"))
    conn = db.scalar(
        select(OdooConnection)
        .where(OdooConnection.tenant_id == t, OdooConnection.status == "active")
        .order_by(OdooConnection.created_at)
    )
    reachable = None
    if conn is not None and conn.secret_ciphertext is not None:
        try:
            facts = _client(
                conn.base_url, conn.db_name, conn.login, vault.decrypt(conn.secret_ciphertext), s
            ).call_bridge("alerts_snapshot")
            reachable = True
        except Exception:  # noqa: BLE001 - an unreachable Odoo is itself an alert
            facts, reachable = {}, False
        if reachable is False and has_permission(user.role, "connections.manage"):
            out.append(_alert("odoo_unreachable", "critical", 1, "connections.manage", "/settings"))
        if (
            facts.get("overdue_bills")
            and facts["overdue_bills"]["count"]
            and has_permission(user.role, P_PAYMENTS)
        ):
            out.append(
                _alert(
                    "overdue_supplier_bills",
                    "warning",
                    facts["overdue_bills"]["count"],
                    P_PAYMENTS,
                    "/inventory/suppliers",
                    {"amount": facts["overdue_bills"]["amount"], "currency": facts.get("currency")},
                )
            )
        if (
            facts.get("stale_sessions")
            and facts["stale_sessions"]["count"]
            and has_permission(user.role, P_SALES)
        ):
            out.append(
                _alert(
                    "register_open_too_long",
                    "warning",
                    facts["stale_sessions"]["count"],
                    P_SALES,
                    "/sales",
                    {"names": facts["stale_sessions"]["names"]},
                )
            )
        if (
            facts.get("negative_stock")
            and facts["negative_stock"]["count"]
            and has_permission(user.role, P_STOCK_ADJUST)
        ):
            out.append(
                _alert(
                    "negative_stock",
                    "warning",
                    facts["negative_stock"]["count"],
                    P_STOCK_ADJUST,
                    "/inventory/stock",
                )
            )
        if (
            facts.get("late_receipts")
            and facts["late_receipts"]["count"]
            and has_permission(user.role, P_PURCHASING_VIEW)
        ):
            out.append(
                _alert(
                    "late_receipts",
                    "info",
                    facts["late_receipts"]["count"],
                    P_PURCHASING_VIEW,
                    "/inventory/purchases",
                )
            )
        if has_permission(user.role, P_STOCK_ADJUST) or has_permission(
            user.role, "purchasing.manage"
        ):
            try:
                low = conn_low(conn, vault, s)
                if low:
                    out.append(
                        _alert(
                            "low_stock", "warning", low, P_STOCK_ADJUST, "/inventory/stock?low=1"
                        )
                    )
            except Exception:  # noqa: BLE001 - one failing fact must not hide the other alerts
                log.warning("low-stock alert unavailable", exc_info=True)
    order = {"critical": 0, "warning": 1, "info": 2}
    out.sort(key=lambda a: order[a["severity"]])
    return {"items": out, "odoo_reachable": reachable, "checked_at": datetime.now(UTC)}


def conn_low(conn: OdooConnection, vault: SecretVault, s: Settings) -> int:
    assert conn.secret_ciphertext is not None  # noqa: S101
    client = _client(
        conn.base_url, conn.db_name, conn.login, vault.decrypt(conn.secret_ciphertext), s
    )
    return int(client.call_bridge("stock_overview", "", True, 1, 0).get("total", 0))
