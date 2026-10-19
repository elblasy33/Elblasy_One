"""Stock: visibility, minimum levels, reorder suggestions, counts/adjustments (with approval) and
the separate, owner-only opening-balance workflow. Stock only changes through Odoo's inventory
adjustment flow, always with a reason code that travels with the stock move."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from elblasy_api import audit, operations
from elblasy_api.config import Settings, get_settings
from elblasy_api.db import get_session
from elblasy_api.deps import api_error, get_vault, require, require_any
from elblasy_api.models import OdooConnection, Operation, User
from elblasy_api.odoo.client import BridgeClient, OdooError, OdooRejectedError
from elblasy_api.routers.connections import _client, _owned
from elblasy_api.security.rbac import (
    P_COST_VISIBLE,
    P_PRODUCTS,
    P_PURCHASING_VIEW,
    P_STOCK_ADJUST,
    P_STOCK_APPROVE,
    Role,
    has_permission,
)  # fmt: skip
from elblasy_api.security.vault import SecretVault

router = APIRouter(prefix="/connections/{cid}/stock", tags=["stock"])
IDEM = Annotated[
    str, Header(alias="Idempotency-Key", min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
]
TOL = 0.0005
Reason = Literal["count_correction", "damaged", "expired", "lost", "found", "theft"]
ADJ_TYPE = "stock.adjust"
OPEN_TYPE = "stock.opening"
VIEW_PERMS = (P_STOCK_ADJUST, P_PURCHASING_VIEW, P_PRODUCTS)


class CountLine(BaseModel):
    product_id: int = Field(gt=0)
    counted_qty: float = Field(ge=0, le=1e8)
    lot_name: str | None = Field(default=None, max_length=80)


class AdjustIn(BaseModel):
    reason: Reason = "count_correction"
    note: str | None = Field(default=None, max_length=200)
    lines: list[CountLine] = Field(min_length=1, max_length=200)


class MinIn(BaseModel):
    min_qty: float = Field(ge=0, le=1e8)
    max_qty: float | None = Field(default=None, ge=0, le=1e8)


class DecisionIn(BaseModel):
    note: str | None = Field(default=None, max_length=200)


class OpeningIn(BaseModel):
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=500)


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
            422, "stock_rejected", str(exc).removeprefix("Odoo rejected the call: ")
        ) from exc
    except OdooError as exc:
        raise api_error(502, "odoo_unavailable", str(exc)) from exc


def _fail(what: str) -> Exception:
    return api_error(
        502,
        "verification_failed",
        f"Odoo does not show the {what} as requested. Check it in Odoo before retrying.",
    )


def _levels(client: BridgeClient, ids: list[int]) -> dict[str, dict[str, float]]:
    levels: dict[str, dict[str, float]] = _read(client, "stock_levels", sorted(set(ids))).get(
        "levels", {}
    )
    return levels


# ---------------- overview / minimums / suggestions ----------------
@router.get("/overview")
def overview(
    cid: uuid.UUID, q: str = Query("", max_length=100), low: bool = False,
    limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0, le=100_000),
    user: User = Depends(require_any(*VIEW_PERMS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    res = _read(client, "stock_overview", q, low, limit, offset)
    if not has_permission(
        user.role, P_COST_VISIBLE
    ):  # cost and inventory value are finance information
        for it in res.get("items", []):
            it.pop("cost", None)
            it.pop("value", None)
    return res


@router.get("/suggestions")
def suggestions(
    cid: uuid.UUID, user: User = Depends(require_any(*VIEW_PERMS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    """Recommendations only. Nothing here is an order; creating a purchase order is a separate, explicit step."""
    _, client = _conn(db, user, cid, s, vault)
    res = _read(client, "stock_suggestions")
    res["note"] = "recommendations, not orders"
    return res


@router.put("/products/{product_id}/minimum")
def set_minimum(
    cid: uuid.UUID, product_id: int, body: MinIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_STOCK_ADJUST)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    spec = {
        "product_id": product_id,
        "min_qty": body.min_qty,
        **({"max_qty": body.max_qty} if body.max_qty is not None else {}),
    }

    def verify(res: dict[str, Any], _: Any) -> dict[str, Any]:
        row = _read(client, "stock_overview", "", False, 1, 0, product_id).get("items", [])
        if not row or abs((row[0].get("min") or -1) - body.min_qty) > TOL:
            raise _fail("minimum level")
        return {"product_id": product_id, "min": row[0]["min"], "max": row[0]["max"]}

    return operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="stock.minimum.set", idem=idem,
        payload={"product_id": product_id, **body.model_dump()}, method="stock_set_minimum", spec=spec,
        verify=verify, what="minimum level", audit_action="stock.minimum.set", target_type="product",
        target_id=lambda o: o["product_id"], audit_after=lambda o: {"min": o["min"], "max": o["max"]},
        rejected_code="stock_rejected",
    )  # fmt: skip


# ---------------- counts / adjustments ----------------
def _needs_approval(user: User, value_change: float, s: Settings) -> bool:
    if user.role in (Role.OWNER.value, Role.MANAGER.value):
        return False
    return abs(value_change) > s.stock_adjust_approval_value


def _apply_adjustment(
    db: Session, request: Request, *, actor: User, requester: User, c: OdooConnection, client: BridgeClient,
    idem: str, payload: dict[str, Any], reason: str, approval_ref: str | None = None,
) -> dict[str, Any]:  # fmt: skip
    ids = [ln["product_id"] for ln in payload["lines"]]
    note = f"{payload.get('note') or ''} | by {requester.email}" + (
        f" | approved by {actor.email}" if approval_ref else ""
    )
    spec = {"reason": reason, "note": note.strip(" |"), "lines": payload["lines"]}

    def before() -> dict[str, Any]:
        return {"levels": _levels(client, ids)}

    def verify(res: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
        after = _levels(client, ids)
        planned: dict[int, float] = {}
        for ln in res["refs"]["lines"]:
            planned[ln["product_id"]] = planned.get(ln["product_id"], 0.0) + ln["diff"]
        for pid, diff in planned.items():
            was = prior["levels"].get(str(pid), {}).get("on_hand", 0.0)
            if (
                res.get("outcome") != "already_exists"
                and abs(after.get(str(pid), {}).get("on_hand", -1e9) - (was + diff)) > TOL
            ):
                raise _fail("stock level")
        return {
            "lines": res["refs"]["lines"],
            "levels": after,
            "value_change": sum(ln["value_change"] for ln in res["refs"]["lines"]),
        }

    return operations.run_write(
        db, request, user=actor, conn=c, client=client, op_type=ADJ_TYPE, idem=idem, payload=payload,
        method="stock_adjust", spec=spec, verify=verify, before=before, what="adjustment",
        audit_action="stock.adjust" if not approval_ref else "stock.adjust.approved", target_type="stock_adjustment",
        target_id=lambda o: idem[:12], audit_after=lambda o: {"reason": reason, "lines": len(o["lines"]), "value_change": o["value_change"], "approval_ref": approval_ref},
        rejected_code="adjustment_rejected",
    )  # fmt: skip


@router.post("/adjustments")
def create_adjustment(
    cid: uuid.UUID, body: AdjustIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_STOCK_ADJUST)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> Any:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    payload = body.model_dump(exclude_none=True)
    existing = db.scalar(select(Operation).where(Operation.tenant_id == user.tenant_id, Operation.connection_id == c.id,
                                                 Operation.type == ADJ_TYPE, Operation.idempotency_key == idem))  # fmt: skip
    if existing and existing.status == "awaiting_approval":
        if existing.request_fingerprint != operations.fingerprint(payload):
            raise api_error(
                409,
                "idempotency_conflict",
                "This Idempotency-Key was used with a different request",
            )
        return _json(
            202,
            {
                "operation_id": str(existing.id),
                "status": "awaiting_approval",
                "preview": existing.verification,
            },
        )
    preview = _read(client, "stock_preview", {"reason": body.reason, "lines": payload["lines"]})
    if _needs_approval(user, preview["value_change"], s):
        op = Operation(tenant_id=user.tenant_id, connection_id=c.id, type=ADJ_TYPE, idempotency_key=idem,
                       request_fingerprint=operations.fingerprint(payload), actor_id=user.id,
                       status="awaiting_approval", payload=payload, verification=preview)  # fmt: skip
        db.add(op)
        audit.record(db, request, action="stock.adjust.requested", outcome="success", actor=user,
                     target_type="stock_adjustment", target_id=idem[:12],
                     after={"reason": body.reason, "value_change": preview["value_change"], "needs_approval": True})  # fmt: skip
        db.commit()
        return _json(
            202, {"operation_id": str(op.id), "status": "awaiting_approval", "preview": preview}
        )
    out = _apply_adjustment(
        db,
        request,
        actor=user,
        requester=user,
        c=c,
        client=client,
        idem=idem,
        payload=payload,
        reason=body.reason,
    )
    return _json(201, out)


def _json(status: int, body: dict[str, Any]) -> Any:
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status, content=jsonable_encoder(body))


def _pending(db: Session, user: User, cid: uuid.UUID, op_id: uuid.UUID) -> Operation:
    op = db.scalar(select(Operation).where(Operation.id == op_id, Operation.connection_id == cid,
                                           Operation.tenant_id == user.tenant_id, Operation.type == ADJ_TYPE))  # fmt: skip
    if op is None:
        raise api_error(404, "not_found", "Request not found")
    return op


@router.get("/adjustments")
def list_adjustments(
    cid: uuid.UUID, status: str | None = Query(default=None, max_length=24),
    user: User = Depends(require(P_STOCK_ADJUST)), db: Session = Depends(get_session),
) -> dict[str, Any]:  # fmt: skip
    _owned(db, user, cid)
    q = (
        select(Operation, User.email)
        .join(User, User.id == Operation.actor_id)
        .where(
            Operation.tenant_id == user.tenant_id,
            Operation.connection_id == cid,
            Operation.type == ADJ_TYPE,
        )
        .order_by(Operation.created_at.desc())
        .limit(100)
    )
    if status:
        q = q.where(Operation.status == status)
    items = []
    for op, email in db.execute(q):
        payload = op.payload or {}
        items.append({"id": str(op.id), "status": op.status, "requested_by": email, "created_at": op.created_at,
                      "reason": payload.get("reason"), "note": payload.get("note"), "lines": len(payload.get("lines", [])),
                      "value_change": (op.verification or {}).get("value_change") if op.payload else None})  # fmt: skip
    return {"items": items}


@router.post("/adjustments/{op_id}/approve")
def approve_adjustment(
    cid: uuid.UUID, op_id: uuid.UUID, request: Request,
    user: User = Depends(require(P_STOCK_APPROVE)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    op = _pending(db, user, c.id, op_id)
    if op.status != "awaiting_approval" or not op.payload:
        raise api_error(409, "not_pending", f"This request is {op.status}")
    if op.actor_id == user.id:  # segregation of duties
        raise api_error(403, "self_approval", "You cannot approve your own request")
    requester = db.get(User, op.actor_id)
    assert requester is not None  # noqa: S101
    op.decided_by = user.id
    db.commit()
    return _apply_adjustment(db, request, actor=user, requester=requester, c=c, client=client, idem=op.idempotency_key,
                             payload=op.payload, reason=op.payload["reason"], approval_ref=str(op.id))  # fmt: skip


@router.post("/adjustments/{op_id}/reject")
def reject_adjustment(
    cid: uuid.UUID, op_id: uuid.UUID, body: DecisionIn, request: Request,
    user: User = Depends(require(P_STOCK_APPROVE)), db: Session = Depends(get_session),
) -> dict[str, Any]:  # fmt: skip
    _owned(db, user, cid)
    op = _pending(db, user, cid, op_id)
    if op.status != "awaiting_approval":
        raise api_error(409, "not_pending", f"This request is {op.status}")
    op.status, op.decided_by, op.safe_error = "rejected", user.id, (body.note or "rejected")[:500]
    audit.record(db, request, action="stock.adjust.rejected", outcome="success", actor=user,
                 target_type="stock_adjustment", target_id=str(op.id), after={"note": body.note})  # fmt: skip
    db.commit()
    return {"id": str(op.id), "status": "rejected"}


# ---------------- opening balances (explicit, validated, owner-only) ----------------
def _opening_rows(
    client: BridgeClient, rows: list[dict[str, Any]], already_posted: set[int] | None = None
) -> list[dict[str, Any]]:
    codes = [str(r.get("barcode") or "").strip() for r in rows if r.get("barcode")]
    found = _read(client, "stock_resolve_barcodes", codes).get("found", {}) if codes else {}
    hist = (
        set(
            _read(client, "stock_has_history", [v["product_id"] for v in found.values()]).get(
                "with_history", []
            )
        )
        if found
        else set()
    )
    seen: set[int] = set()
    out = []
    for i, r in enumerate(rows):
        errs: list[str] = []
        code = str(r.get("barcode") or "").strip()
        hit = found.get(code)
        if not code:
            errs.append("barcode is required")
        elif not hit:
            errs.append("no stocked product has this barcode")
        qty = cost = None
        try:
            qty = float(str(r.get("qty", "")).replace(",", "."))
            if qty < 0:
                errs.append("qty cannot be negative")
        except ValueError:
            errs.append("qty must be a number")
        if r.get("unit_cost") not in (None, ""):
            try:
                cost = float(str(r["unit_cost"]).replace(",", "."))
                if cost < 0:
                    errs.append("unit_cost cannot be negative")
            except ValueError:
                errs.append("unit_cost must be a number")
        if hit:
            if hit["product_id"] in seen:
                errs.append("product repeated in this file")
            seen.add(hit["product_id"])
            if hit["product_id"] in hist and hit["product_id"] not in (already_posted or set()):
                errs.append(
                    "this product already has stock movement: use a count, not an opening balance"
                )
        out.append({"row": i + 1, "ok": not errs, "errors": errs, "product_id": hit["product_id"] if hit else None,
                    "name": hit["name"] if hit else None, "qty": qty, "unit_cost": cost})  # fmt: skip
    return out


@router.post("/opening/validate")
def opening_validate(
    cid: uuid.UUID, body: OpeningIn, user: User = Depends(require(P_STOCK_ADJUST)),
    db: Session = Depends(get_session), s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    """Nothing is posted. Rows for products that already moved are rejected."""
    _, client = _conn(db, user, cid, s, vault)
    rows = _opening_rows(client, body.rows)
    return {
        "import_id": uuid.uuid4().hex,
        "valid": sum(r["ok"] for r in rows),
        "invalid": sum(not r["ok"] for r in rows),
        "rows": rows,
    }


@router.post("/opening/commit")
def opening_commit(
    cid: uuid.UUID, body: OpeningIn, request: Request, import_id: str = Query(pattern=r"^[0-9a-f]{32}$"),
    user: User = Depends(require(P_STOCK_APPROVE)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    """Owner/manager only. Valid rows are posted in batches of 50, each a tracked, verified, idempotent operation
    (key = import_id + batch). Re-sending the same import_id never posts a batch twice."""
    c, client = _conn(db, user, cid, s, vault)
    # Products already posted by an earlier (possibly answer-less) attempt of THIS import are replayed, not rejected.
    done = db.scalars(select(Operation).where(Operation.tenant_id == user.tenant_id, Operation.connection_id == c.id,
                                              Operation.type == OPEN_TYPE, Operation.status == "succeeded",
                                              Operation.idempotency_key.like(f"open-{import_id}-%")))  # fmt: skip
    already = {ln["product_id"] for op in done for ln in (op.payload or {}).get("lines", [])}
    rows = [r for r in _opening_rows(client, body.rows, already) if r["ok"]]
    results = []
    for n in range(0, len(rows), 50):
        batch = rows[n : n + 50]
        payload = {
            "reason": "opening_balance",
            "lines": [
                {
                    "product_id": r["product_id"],
                    "counted_qty": r["qty"],
                    **({"unit_cost": r["unit_cost"]} if r["unit_cost"] is not None else {}),
                }
                for r in batch
            ],
        }
        ids = [r["product_id"] for r in batch]

        def before(ids: list[int] = ids) -> dict[str, Any]:
            return {"levels": _levels(client, ids)}

        def verify(
            res: dict[str, Any], prior: dict[str, Any], ids: list[int] = ids
        ) -> dict[str, Any]:
            after = _levels(client, ids)
            for ln in res["refs"]["lines"]:
                was = prior["levels"].get(str(ln["product_id"]), {}).get("on_hand", 0.0)
                if (
                    res.get("outcome") != "already_exists"
                    and abs(
                        after.get(str(ln["product_id"]), {}).get("on_hand", -1e9)
                        - (was + ln["diff"])
                    )
                    > TOL
                ):
                    raise _fail("opening stock")
            return {
                "lines": len(res["refs"]["lines"]),
                "value_change": sum(ln["value_change"] for ln in res["refs"]["lines"]),
            }

        spec = {"reason": "opening_balance", "note": f"opening balance import {import_id[:8]} by {user.email}",
                "lines": [{"product_id": r["product_id"], "counted_qty": r["qty"], **({"unit_cost": r["unit_cost"]} if r["unit_cost"] is not None else {})} for r in batch]}  # fmt: skip
        try:
            out = operations.run_write(
                db, request, user=user, conn=c, client=client, op_type=OPEN_TYPE, idem=f"open-{import_id}-{n // 50:04d}",
                payload=payload, method="stock_adjust", spec=spec, verify=verify, before=before, what="opening balance",
                audit_action="stock.opening.commit", target_type="stock_adjustment", target_id=lambda o: import_id[:12],
                audit_after=lambda o: {"lines": o["lines"], "value_change": o["value_change"]}, rejected_code="opening_rejected", keep_payload=True,
            )  # fmt: skip
            results.append(
                {
                    "batch": n // 50 + 1,
                    "status": "replayed" if out.get("replayed") else "posted",
                    "lines": out["lines"],
                }
            )
        except Exception as exc:  # noqa: BLE001 - one failed batch is reported, never hidden
            detail = getattr(exc, "detail", None)
            results.append(
                {
                    "batch": n // 50 + 1,
                    "status": "failed",
                    "error": detail.get("message") if isinstance(detail, dict) else "error",
                }
            )
    return {"import_id": import_id, "posted_rows": sum(r["lines"] for r in results if r["status"] in ("posted", "replayed")),
            "skipped_invalid": len(body.rows) - len(rows), "batches": results, "finished_at": datetime.now(UTC).isoformat()}  # fmt: skip
