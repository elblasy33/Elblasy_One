import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from elblasy_api import audit
from elblasy_api.config import Settings, get_settings
from elblasy_api.db import get_engine, get_session
from elblasy_api.deps import api_error, current_user, get_vault, require
from elblasy_api.models import AuditEvent, OdooConnection, SetupPlan, User
from elblasy_api.odoo.client import BridgeClient, OdooError
from elblasy_api.routers.connections import _apply_manifest, _client, _owned
from elblasy_api.security.rbac import P_CONFIG, Role
from elblasy_api.security.vault import SecretVault
from elblasy_api.setup.executor import DriftError, execute_plan
from elblasy_api.setup.planner import build_plan
from elblasy_api.setup.profile import BusinessProfile, build_profile, visible_questions
from elblasy_api.setup.templates import TEMPLATES

router = APIRouter(tags=["setup"])


class AnswersIn(BaseModel):
    answers: dict[str, Any]


@router.get("/setup/templates")
def list_templates(_: User = Depends(current_user)) -> list[dict[str, Any]]:
    return [
        {
            "id": t.id,
            "version": t.version,
            "vertical": t.vertical,
            "name": t.name,
            "summary": t.summary,
        }
        for t in TEMPLATES.values()
    ]


@router.post("/setup/questionnaire")
def questionnaire(body: AnswersIn, _: User = Depends(current_user)) -> dict[str, Any]:
    """Stateless: send the answers so far, get the questions that currently apply."""
    qs = visible_questions(body.answers)
    answered = {q.id for q in qs if q.id in body.answers}
    complete = "vertical" in body.answers and all(
        q.id in answered or q.default is not None for q in qs
    )
    profile = None
    if complete:
        try:
            profile = build_profile(body.answers).model_dump()
        except ValidationError as exc:
            raise api_error(422, "invalid_answers", str(exc.errors()[0]["msg"])) from exc
    return {
        "questions": [
            {
                "id": q.id,
                "kind": q.kind,
                "text": q.text,
                "options": list(q.options),
                "default": q.default,
                "answered": q.id in body.answers,
            }
            for q in qs
        ],  # fmt: skip
        "complete": complete,
        "profile": profile,
    }


def _plan_out(p: SetupPlan) -> dict[str, Any]:
    return {
        "id": str(p.id), "connection_id": str(p.connection_id), "status": p.status,
        "template": {"id": p.template_id, "version": p.template_version},
        "plan_hash": p.plan_hash, "approvals": p.approvals, "created_at": p.created_at,
        "updated_at": p.updated_at, "plan": p.plan, "execution": p.execution,
    }  # fmt: skip


def _get_plan(db: Session, user: User, cid: uuid.UUID, pid: uuid.UUID) -> SetupPlan:
    p = db.scalar(
        select(SetupPlan).where(
            SetupPlan.id == pid,
            SetupPlan.connection_id == cid,
            SetupPlan.tenant_id == user.tenant_id,
        )
    )
    if p is None:
        raise api_error(404, "not_found", "Plan not found")
    return p


@router.post("/connections/{cid}/setup/plans", status_code=201)
def create_plan(
    cid: uuid.UUID,
    body: AnswersIn,
    request: Request,
    user: User = Depends(require(P_CONFIG)),
    db: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
    vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:
    """Dry run: inspects Odoo read-only and stores a draft plan. Nothing is changed in Odoo."""
    c: OdooConnection = _owned(db, user, cid)
    if c.status != "active" or c.secret_ciphertext is None:
        raise api_error(409, "connection_revoked", "Connection is revoked")
    try:
        profile: BusinessProfile = build_profile(body.answers)
    except ValidationError as exc:
        raise api_error(422, "invalid_answers", str(exc.errors()[0]["msg"])) from exc
    client = _client(c.base_url, c.db_name, c.login, vault.decrypt(c.secret_ciphertext), s)
    try:
        manifest = client.call_bridge("capabilities")
        snapshot = client.call_bridge("readiness_snapshot")
    except OdooError as exc:
        raise api_error(502, "odoo_unavailable", str(exc)) from exc
    _apply_manifest(c, manifest)
    plan = build_plan(profile, manifest, snapshot)
    db.execute(
        update(SetupPlan)
        .where(SetupPlan.connection_id == c.id, SetupPlan.status.in_(("draft", "approved")))
        .values(status="superseded")
    )
    row = SetupPlan(
        tenant_id=user.tenant_id, connection_id=c.id, template_id=plan["template"]["id"],
        template_version=plan["template"]["version"], profile=plan["profile"], plan=plan,
        plan_hash=plan["plan_hash"], snapshot_hash=plan["snapshot_hash"], created_by=user.id,
    )  # fmt: skip
    db.add(row)
    db.flush()
    audit.record(db, request, action="setup.plan.create", outcome="success", actor=user,
                 target_type="setup_plan", target_id=row.id,
                 after={"template": row.template_id, "hash": row.plan_hash, **plan["summary"]})  # fmt: skip
    db.commit()
    return _plan_out(row)


@router.get("/connections/{cid}/setup/plans")
def list_plans(
    cid: uuid.UUID, user: User = Depends(require(P_CONFIG)), db: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    _owned(db, user, cid)
    rows = db.scalars(
        select(SetupPlan)
        .where(SetupPlan.connection_id == cid, SetupPlan.tenant_id == user.tenant_id)
        .order_by(SetupPlan.created_at.desc())
    )
    return [
        {"id": str(p.id), "status": p.status, "template": p.template_id, "created_at": p.created_at,
         "summary": p.plan["summary"], "plan_hash": p.plan_hash}
        for p in rows
    ]  # fmt: skip


@router.get("/connections/{cid}/setup/plans/{pid}")
def get_plan(
    cid: uuid.UUID,
    pid: uuid.UUID,
    user: User = Depends(require(P_CONFIG)),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    return _plan_out(_get_plan(db, user, cid, pid))


@router.get("/connections/{cid}/setup/plans/{pid}/export")
def export_plan(
    cid: uuid.UUID,
    pid: uuid.UUID,
    request: Request,
    user: User = Depends(require(P_CONFIG)),
    db: Session = Depends(get_session),
) -> Response:
    p = _get_plan(db, user, cid, pid)
    audit.record(db, request, action="setup.plan.export", outcome="success", actor=user,
                 target_type="setup_plan", target_id=p.id)  # fmt: skip
    db.commit()
    doc = {"exported_at": datetime.now(UTC).isoformat(), **_plan_out(p)}
    return Response(
        json.dumps(doc, default=str, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"content-disposition": f'attachment; filename="setup-plan-{p.id}.json"'},
    )


_ROLE_FOR_APPROVAL = {"owner": Role.OWNER.value, "accountant": Role.ACCOUNTANT.value}


@router.post("/connections/{cid}/setup/plans/{pid}/approve")
def approve_plan(
    cid: uuid.UUID,
    pid: uuid.UUID,
    request: Request,
    user: User = Depends(require(P_CONFIG)),
    db: Session = Depends(get_session),
) -> dict[str, Any]:
    """Records the caller's approval for their role. The plan is `approved` once every required
    role has approved this exact plan hash. Approval never executes anything."""
    p = _get_plan(db, user, cid, pid)
    plan = p.plan
    if p.status not in ("draft", "approved"):
        raise api_error(409, "plan_not_open", f"Plan is {p.status}")
    if not plan["applicable"]:
        raise api_error(
            409, "plan_not_applicable", "Plan has conflicts, unsupported choices or blocked steps"
        )
    if plan["summary"]["to_apply"] == 0:
        raise api_error(409, "nothing_to_apply", "Nothing needs to be changed")
    role = next((a for a, r in _ROLE_FOR_APPROVAL.items() if r == user.role), None)
    if role is None or role not in plan["required_approvals"]:
        audit.record(db, request, action="setup.plan.approve", outcome="denied", actor=user,
                     target_type="setup_plan", target_id=p.id)  # fmt: skip
        db.commit()
        raise api_error(403, "approval_role", "Your role cannot approve this plan")
    if any(a["role"] == role for a in p.approvals):
        raise api_error(409, "already_approved", "Already approved for this role")
    p.approvals = [*p.approvals, {"role": role, "user_id": str(user.id),
                                  "plan_hash": p.plan_hash, "at": datetime.now(UTC).isoformat()}]  # fmt: skip
    if set(plan["required_approvals"]) <= {a["role"] for a in p.approvals}:
        p.status = "approved"
    audit.record(db, request, action="setup.plan.approve", outcome="success", actor=user,
                 target_type="setup_plan", target_id=p.id,
                 after={"role": role, "status": p.status, "plan_hash": p.plan_hash})  # fmt: skip
    db.commit()
    return _plan_out(p)


STALE_EXECUTION = timedelta(minutes=10)
log = logging.getLogger("elblasy.setup")


def _run_in_background(
    plan_id: uuid.UUID, actor_id: uuid.UUID, client: BridgeClient, cid_hdr: str | None
) -> None:
    """Own session: the request that started this has already returned."""
    with sessionmaker(get_engine(), expire_on_commit=False)() as db:
        p = db.get(SetupPlan, plan_id)
        if p is None:
            return
        try:
            result = execute_plan(db, p, actor_id, client)
            outcome = "success" if result["status"] == "completed" else "failure"
            after: dict[str, Any] = {"status": result["status"],
                                     "steps": {k: v["status"] for k, v in result["steps"].items()}}  # fmt: skip
        except DriftError as exc:
            db.rollback()
            p = db.get(SetupPlan, plan_id)
            assert p is not None  # noqa: S101
            p.status, outcome, after = "needs_review", "failure", {"error": "plan_drift"}
            p.execution = {
                **(p.execution or {}),
                "error": str(exc),
                "finished_at": datetime.now(UTC).isoformat(),
            }
        except Exception:  # noqa: BLE001 - never leave a plan stuck in "executing"
            log.exception("setup execution crashed cid=%s", cid_hdr)
            db.rollback()
            p = db.get(SetupPlan, plan_id)
            assert p is not None  # noqa: S101
            p.status, outcome, after = "needs_review", "failure", {"error": "internal"}
            p.execution = {**(p.execution or {}), "error": "Execution stopped unexpectedly; "
                           "re-run to resume (steps are idempotent).",
                           "finished_at": datetime.now(UTC).isoformat()}  # fmt: skip
        db.add(AuditEvent(tenant_id=p.tenant_id, actor_id=actor_id, action="setup.execute.finish",
                          outcome=outcome, target_type="setup_plan", target_id=str(p.id),
                          after=after, correlation_id=cid_hdr))  # fmt: skip
        db.commit()


@router.post("/connections/{cid}/setup/plans/{pid}/execute", status_code=202)
def execute(
    cid: uuid.UUID,
    pid: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    user: User = Depends(require(P_CONFIG)),
    db: Session = Depends(get_session),
    s: Settings = Depends(get_settings),
    vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:
    """Starts execution in the background and returns at once; poll the plan for live step
    status. Safe to call again after a failure or timeout: finished steps are skipped and the rest
    are idempotent. A run stuck in `executing` for >10 min is treated as dead and may be resumed."""
    p = _get_plan(db, user, cid, pid)
    stale = p.status == "executing" and datetime.now(UTC) - p.updated_at > STALE_EXECUTION
    if p.status not in ("approved", "failed", "needs_review") and not stale:
        raise api_error(409, "plan_not_approved", f"Plan is {p.status}; approve it first")
    approved = {a["role"] for a in p.approvals if a["plan_hash"] == p.plan_hash}
    if not set(p.plan["required_approvals"]) <= approved:
        raise api_error(409, "approvals_missing", "Not every required role has approved this plan")
    c: OdooConnection = _owned(db, user, cid)
    if c.status != "active" or c.secret_ciphertext is None:
        raise api_error(409, "connection_revoked", "Connection is revoked")
    client = _client(c.base_url, c.db_name, c.login, vault.decrypt(c.secret_ciphertext), s)
    p.status = "executing"
    audit.record(db, request, action="setup.execute.start", outcome="success", actor=user,
                 target_type="setup_plan", target_id=p.id, after={"hash": p.plan_hash})  # fmt: skip
    db.commit()
    background.add_task(
        _run_in_background, p.id, user.id, client, getattr(request.state, "correlation_id", None)
    )
    return {"id": str(p.id), "status": "executing"}
