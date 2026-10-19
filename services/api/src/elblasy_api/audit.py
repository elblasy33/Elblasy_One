from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from elblasy_api.models import AuditEvent, User

# Never persisted, whatever a caller passes in.
_REDACT = {"password", "secret", "api_key", "token", "password_hash", "secret_ciphertext"}


def _clean(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if d is None:
        return None
    return {k: ("[redacted]" if k.lower() in _REDACT else v) for k, v in d.items()}


def record(
    db: Session,
    request: Request,
    *,
    action: str,
    outcome: str,
    actor: User | None = None,
    tenant_id: Any = None,
    target_type: str | None = None,
    target_id: Any = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            tenant_id=tenant_id or (actor.tenant_id if actor else None),
            actor_id=actor.id if actor else None,
            action=action,
            outcome=outcome,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            before=_clean(before),
            after=_clean(after),
            correlation_id=getattr(request.state, "correlation_id", None),
        )
    )
