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
