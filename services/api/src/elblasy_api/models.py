"""Platform-owned data only. Balances, stock and posted documents live in Odoo."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from elblasy_api.db import Base

_uuid = lambda: uuid.uuid4()  # noqa: E731
_now = func.now()


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lower-case
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)


class OdooConnection(Base):
    __tablename__ = "odoo_connections"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str] = mapped_column(String(500))
    db_name: Mapped[str] = mapped_column(String(120))
    login: Mapped[str] = mapped_column(String(200))
    secret_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | revoked
    odoo_series: Mapped[str | None] = mapped_column(String(16))
    odoo_edition: Mapped[str | None] = mapped_column(String(16))
    compatibility_status: Mapped[str] = mapped_column(String(32), default="unknown")
    capability_manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    manifest_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_health_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)


class Operation(Base):
    """Business-operation tracking + idempotency (used from the sales/setup phases on)."""

    __tablename__ = "operations"
    __table_args__ = (UniqueConstraint("tenant_id", "connection_id", "type", "idempotency_key"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("odoo_connections.id"))
    type: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(24), default="requested")
    odoo_refs: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    safe_error: Mapped[str | None] = mapped_column(String(500))
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Request kept only for operations that wait for a human decision (e.g. stock adjustments).
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=_now, onupdate=_now
    )


class AuditEvent(Base):
    """Append-only (enforced by a DB trigger in the migration)."""

    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    approval_ref: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16))  # success | denied | failure
    correlation_id: Mapped[str | None] = mapped_column(String(64))


class SetupPlan(Base):
    """A reviewed, hash-bound setup plan. Approval applies to exactly `plan_hash`."""

    __tablename__ = "setup_plans"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("odoo_connections.id"), index=True)
    template_id: Mapped[str] = mapped_column(String(64))
    template_version: Mapped[str] = mapped_column(String(16))
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB)
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB)
    plan_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    # draft | approved | superseded | executing | completed | failed | needs_review
    status: Mapped[str] = mapped_column(String(16), default="draft")
    approvals: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    execution: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=_now, onupdate=_now
    )


class BarcodeSequence(Base):
    """Per-connection counters for platform-generated barcodes (scale codes, in-store codes)."""

    __tablename__ = "barcode_sequences"
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("odoo_connections.id"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)  # scale | internal
    next_value: Mapped[int] = mapped_column(BigInteger, default=1)
