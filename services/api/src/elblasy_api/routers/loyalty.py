"""Loyalty points and promotions: programmes kept in Odoo's loyalty app, applied by Elblasy One at the till."""

import uuid
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from elblasy_api import operations
from elblasy_api.config import Settings, get_settings
from elblasy_api.db import get_session
from elblasy_api.deps import api_error, get_vault, require
from elblasy_api.models import OdooConnection, User
from elblasy_api.odoo.client import BridgeClient, OdooError
from elblasy_api.routers.connections import _client, _owned
from elblasy_api.security.rbac import P_PRICE, P_SALES
from elblasy_api.security.vault import SecretVault

router = APIRouter(prefix="/connections/{cid}", tags=["loyalty"])
IDEM = Annotated[
    str, Header(alias="Idempotency-Key", min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
]


class ProgramIn(BaseModel):
    kind: Literal["points", "bxgy", "product_discount", "order_discount"]
    name: str = Field(min_length=1, max_length=120)
    date_from: date | None = None
    date_to: date | None = None
    points_per_unit: float | None = Field(
        default=None, gt=0, le=1000
    )  # points: earned per currency unit
    point_value: float | None = Field(default=None, gt=0, le=1e6)  # points: what one point is worth
    min_redeem: float | None = Field(default=None, ge=1, le=1e9)
    product_id: int | None = Field(default=None, gt=0)  # bxgy
    buy: int | None = Field(default=None, ge=1, le=1000)
    free: int | None = Field(default=None, ge=1, le=1000)
    product_ids: list[int] = Field(default_factory=list, max_length=200)  # product discount
    category_id: int | None = Field(default=None, gt=0)
    percent: float | None = Field(default=None, gt=0, le=100)
    minimum_amount: float | None = Field(default=None, ge=0, le=1e9)

    @model_validator(mode="after")
    def complete(self) -> "ProgramIn":
        need = {"points": ("points_per_unit", "point_value"), "bxgy": ("product_id", "buy", "free"),
                "product_discount": ("percent",), "order_discount": ("percent",)}[self.kind]  # fmt: skip
        missing = [f for f in need if getattr(self, f) is None]
        if missing:
            raise ValueError(f"missing for this kind: {', '.join(missing)}")
        if self.kind == "product_discount" and not self.product_ids and not self.category_id:
            raise ValueError("choose the products or the category on offer")
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("the offer ends before it starts")
        return self


class ActiveIn(BaseModel):
    active: bool


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
    except OdooError as exc:
        raise api_error(502, "odoo_unavailable", str(exc)) from exc


@router.get("/loyalty/programs")
def programs(
    cid: uuid.UUID, user: User = Depends(require(P_SALES)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "loyalty_programs")


@router.get("/customers/{partner_id}/points")
def points(
    cid: uuid.UUID, partner_id: int, user: User = Depends(require(P_SALES)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    return _read(client, "loyalty_points_of", partner_id)


@router.post("/loyalty/programs", status_code=201)
def create_program(
    cid: uuid.UUID, body: ProgramIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_PRICE)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    spec = body.model_dump(mode="json", exclude_none=True)

    def verify(res: dict[str, Any], _b: Any) -> dict[str, Any]:
        got = _read(client, "loyalty_programs")
        pid = res["refs"]["program"]["id"]
        prog = next((p for p in got.get("items", []) if p["id"] == pid), None)
        if not prog or prog["kind"] != body.kind or prog["name"] != body.name.strip():
            raise api_error(
                502, "verification_failed", "Odoo does not show the programme as requested"
            )
        return {"program": prog, "outcome": res["outcome"], "replayed": False}

    return operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="loyalty.program", idem=idem, payload=spec,
        method="loyalty_program_create", spec=spec, verify=verify, what="programme", audit_action="loyalty.program.create",
        target_type="loyalty_program", target_id=lambda o: o["program"]["id"], audit_after=lambda o: {"kind": body.kind, "name": body.name},
        rejected_code="loyalty_rejected",
    )  # fmt: skip


@router.put("/loyalty/programs/{program_id}/active")
def set_active(
    cid: uuid.UUID, program_id: int, body: ActiveIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_PRICE)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    spec = {"program_id": program_id, "active": body.active}

    def verify(res: dict[str, Any], _b: Any) -> dict[str, Any]:
        got = _read(client, "loyalty_programs")
        prog = next((p for p in got.get("items", []) if p["id"] == program_id), None)
        if not prog or prog["active"] != body.active:
            raise api_error(502, "verification_failed", "Odoo does not show the change")
        return {"program": prog, "outcome": res["outcome"], "replayed": False}

    return operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="loyalty.active", idem=idem, payload=spec,
        method="loyalty_program_set_active", spec=spec, verify=verify, what="programme", audit_action="loyalty.program.active",
        target_type="loyalty_program", target_id=lambda o: program_id, audit_after=lambda o: {"active": body.active},
        rejected_code="loyalty_rejected",
    )  # fmt: skip
