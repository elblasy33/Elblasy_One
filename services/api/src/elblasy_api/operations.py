"""Tracked, idempotent business operations (catalogue now; sales/payments later).

Contract: the same (connection, type, Idempotency-Key) with the same payload never produces a
second effect. A different payload under the same key is refused. A timeout leaves the operation
`needs_review`, and retrying with the same key is safe because the Odoo side is keyed too."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from elblasy_api.deps import api_error
from elblasy_api.models import Operation

IN_PROGRESS_WINDOW = timedelta(seconds=60)


def fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def odoo_key(tenant_id: uuid.UUID, connection_id: uuid.UUID, idem: str) -> str:
    """Stable, Odoo-safe key derived from the client's idempotency key."""
    return hashlib.sha256(f"{tenant_id}:{connection_id}:{idem}".encode()).hexdigest()[:32]


def begin(
    db: Session, *, tenant_id: uuid.UUID, connection_id: uuid.UUID, actor_id: uuid.UUID,
    op_type: str, idem: str, payload: Any,
) -> tuple[Operation, bool]:  # fmt: skip
    """Returns (operation, replayed). `replayed` means a finished result already exists."""
    fp = fingerprint(payload)
    q = select(Operation).where(
        Operation.tenant_id == tenant_id, Operation.connection_id == connection_id,
        Operation.type == op_type, Operation.idempotency_key == idem,
    )  # fmt: skip
    op = db.scalar(q)
    if op is None:
        op = Operation(
            tenant_id=tenant_id, connection_id=connection_id, type=op_type, idempotency_key=idem,
            request_fingerprint=fp, actor_id=actor_id, status="executing",
        )  # fmt: skip
        db.add(op)
        try:
            db.flush()
            db.commit()
            return op, False
        except IntegrityError:
            db.rollback()
            op = db.scalar(q)
            if op is None:
                raise
    if op.request_fingerprint != fp:
        raise api_error(
            409, "idempotency_conflict", "This Idempotency-Key was used with a different request"
        )
    if op.status == "succeeded":
        return op, True
    fresh = datetime.now(UTC) - op.updated_at < IN_PROGRESS_WINDOW
    if op.status == "executing" and fresh:
        raise api_error(409, "in_progress", "This operation is still running")
    op.status = "executing"
    db.commit()
    return op, False


def succeed(db: Session, op: Operation, refs: dict[str, Any], verification: dict[str, Any]) -> None:
    op.status, op.odoo_refs, op.verification, op.safe_error = "succeeded", refs, verification, None
    db.commit()


def fail(db: Session, op: Operation, status: str, message: str) -> None:
    op.status, op.safe_error = status, message[:500]
    db.commit()


# ---------------------------------------------------------------------------------------------
# Generic runner for money/stock-moving writes: track -> call Odoo -> verify from a fresh read.
# ---------------------------------------------------------------------------------------------
from collections.abc import Callable  # noqa: E402

from fastapi import Request  # noqa: E402

from elblasy_api import audit  # noqa: E402
from elblasy_api.models import OdooConnection, User  # noqa: E402
from elblasy_api.odoo.client import (  # noqa: E402
    BridgeClient,
    OdooError,
    OdooRejectedError,
    OdooUncertainError,
)


def map_write_error(
    db: Session, op: Operation, exc: Exception, what: str, rejected_code: str
) -> Exception:
    """Timeout/lost connection -> needs_review (outcome unknown); refusal -> failed (nothing applied)."""
    if isinstance(exc, OdooUncertainError):
        fail(db, op, "needs_review", str(exc))
        return api_error(
            502,
            "outcome_unknown",
            f"The {what} may have been recorded. Retry with the same Idempotency-Key.",
        )
    if isinstance(exc, OdooRejectedError):
        msg = str(exc).removeprefix("Odoo rejected the call: ")
        fail(db, op, "failed", msg)
        return api_error(422, rejected_code, msg)
    fail(db, op, "needs_review", str(exc))
    return api_error(502, "odoo_unavailable", str(exc))


def run_write(
    db: Session,
    request: Request,
    *,
    user: User,
    conn: OdooConnection,
    client: BridgeClient,
    op_type: str,
    idem: str,
    payload: Any,
    method: str,
    spec: dict[str, Any],
    verify: Callable[[dict[str, Any], Any], dict[str, Any]],
    what: str,
    audit_action: str,
    target_type: str,
    target_id: Callable[[dict[str, Any]], Any],
    audit_after: Callable[[dict[str, Any]], dict[str, Any]],
    before: Callable[[], Any] | None = None,
    rejected_code: str = "rejected",
    timeout: float = 60,
) -> dict[str, Any]:
    """Idempotent write. `verify(bridge_result, before_state)` must read Odoo again and return the
    final response, or raise api_error(502, ...) when Odoo does not show the intended state."""
    prev = db.scalar(
        select(Operation).where(
            Operation.tenant_id == user.tenant_id, Operation.connection_id == conn.id,
            Operation.type == op_type, Operation.idempotency_key == idem,
        )
    )  # fmt: skip
    was_unknown = prev is not None and prev.status == "needs_review"
    stored_before = (prev.odoo_refs or {}).get("_before") if was_unknown and prev else None
    op, replayed = begin(db, tenant_id=user.tenant_id, connection_id=conn.id, actor_id=user.id,
                         op_type=op_type, idem=idem, payload=payload)  # fmt: skip
    if replayed:
        return {**(op.odoo_refs or {}), "replayed": True}
    key = odoo_key(user.tenant_id, conn.id, idem)
    try:
        # A retry after an *unknown* outcome must be judged against the state from before the first
        # attempt (the first attempt may already have applied); otherwise the change would be counted twice.
        prior = stored_before if stored_before is not None else (before() if before else None)
        if before and stored_before is None:
            op.odoo_refs = {"_before": prior}
            db.commit()
        res = client.call_bridge(method, str(op.id), key, spec, timeout=timeout)
        out = verify(res, prior)
    except OdooError as exc:
        raise map_write_error(db, op, exc, what, rejected_code) from exc
    except Exception as exc:  # verification refused: record, never claim success
        status = getattr(exc, "status_code", 500)
        if status == 502:
            fail(db, op, "needs_review", "Odoo does not show the result as requested")
        raise
    out = {**out, "outcome": res.get("outcome"), "replayed": False}
    succeed(db, op, out, {"verified": True, "method": "fresh read after write"})
    audit.record(db, request, action=audit_action, outcome="success", actor=user,
                 target_type=target_type, target_id=target_id(out), after=audit_after(out))  # fmt: skip
    db.commit()
    return out
