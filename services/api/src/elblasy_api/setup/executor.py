"""Setup execution (Stage 3) and independent verification (Stage 4).

Safety model
- Only steps the plan marked `to_apply` and `executable` run; satisfied/blocked/manual never do.
- Every step is a tracked `Operation` with idempotency key `<plan>:<step>`. The bridge operation is
  keyed too, so re-running after a timeout cannot create a second record.
- A transport failure is `needs_review` (outcome unknown), never "failed" or "succeeded".
- Success is only recorded after a *fresh* read of Odoo shows the intended state (the plan is
  rebuilt from a new snapshot and the step must now be `satisfied`). The bridge's own answer
  is evidence, not proof.
- No automatic rollback is attempted: created records stay and are reported with recovery text.
"""

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from elblasy_api.models import Operation, SetupPlan
from elblasy_api.odoo.client import OdooRejectedError, OdooUncertainError
from elblasy_api.setup.planner import EXECUTABLE_KINDS, build_plan
from elblasy_api.setup.profile import BusinessProfile

OP_TYPE = "setup.step"


class Bridge(Protocol):
    def call_bridge(
        self, method: str, *args: Any, timeout: float | None = None
    ) -> dict[str, Any]: ...


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _fingerprint(step: dict[str, Any]) -> str:
    raw = json.dumps([step["kind"], step["key"], step["params"]], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def order_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {s["key"]: s for s in steps}
    done: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(s: dict[str, Any], stack: tuple[str, ...] = ()) -> None:
        if s["key"] in seen:
            return
        if s["key"] in stack:
            raise ValueError("dependency cycle in plan")
        for d in s["depends_on"]:
            visit(by_key[d], (*stack, s["key"]))
        seen.add(s["key"])
        done.append(s)

    for s in steps:
        visit(s)
    return done


def _operation(
    db: Session, plan: SetupPlan, step: dict[str, Any], actor_id: uuid.UUID
) -> Operation:
    idem = f"{plan.id}:{step['key']}"
    q = select(Operation).where(
        Operation.tenant_id == plan.tenant_id, Operation.connection_id == plan.connection_id,
        Operation.type == OP_TYPE, Operation.idempotency_key == idem,
    )  # fmt: skip
    op = db.scalar(q)
    if op:
        return op
    op = Operation(
        tenant_id=plan.tenant_id, connection_id=plan.connection_id, type=OP_TYPE,
        idempotency_key=idem, request_fingerprint=_fingerprint(step), actor_id=actor_id,
        status="requested",
    )  # fmt: skip
    db.add(op)
    try:
        db.flush()
    except IntegrityError:  # concurrent executor created it first
        db.rollback()
        op = db.scalar(q)
        if op is None:
            raise
    return op


def execute_plan(
    db: Session,
    plan_row: SetupPlan,
    actor_id: uuid.UUID,
    bridge: Bridge,
    *,
    on_event: Callable[[str, dict[str, Any]], None] = lambda *_: None,
    step_timeout: float = 240.0,
) -> dict[str, Any]:
    plan = plan_row.plan
    profile = BusinessProfile(**plan["profile"])
    exe = dict(plan_row.execution or {})
    first_run = not exe.get("steps")
    exe.setdefault("started_at", _now())
    exe["steps"] = dict(exe.get("steps", {}))

    # drift guard: the world must still look like the world that was reviewed
    manifest = bridge.call_bridge("capabilities")
    snapshot = bridge.call_bridge("readiness_snapshot")
    if first_run:
        fresh = build_plan(profile, manifest, snapshot)
        if fresh["snapshot_hash"] != plan_row.snapshot_hash:
            raise DriftError(
                "Odoo changed since this plan was reviewed; create and approve a new plan."
            )

    plan_row.status = "executing"
    plan_row.execution = exe
    db.commit()

    results: dict[str, str] = {}
    for step in order_steps(plan["steps"]):
        key = step["key"]
        prior = exe["steps"].get(key, {})
        if step["status"] == "satisfied":
            results[key] = "satisfied"
            continue
        if step["status"] == "blocked":
            results[key] = "blocked"
            continue
        if step["kind"] not in EXECUTABLE_KINDS or not step.get("executable", True):
            results[key] = "manual_required"
            exe["steps"][key] = {"status": "manual_required"}
            continue
        if prior.get("status") == "succeeded":
            results[key] = "succeeded"
            continue
        if any(results.get(d) not in ("succeeded", "satisfied") for d in step["depends_on"]):
            results[key] = "skipped"
            exe["steps"][key] = {
                "status": "skipped",
                "reason": "a prerequisite step did not succeed",
            }
            continue

        op = _operation(db, plan_row, step, actor_id)
        op.status = "executing"
        exe["steps"][key] = {"status": "executing", "operation_id": str(op.id), "at": _now()}
        plan_row.execution = dict(exe)
        db.commit()
        on_event("step.start", {"step": key, "operation_id": str(op.id)})
        try:
            res = bridge.call_bridge(
                "apply_step", str(op.id), step["kind"], key, step["params"], timeout=step_timeout
            )
        except OdooUncertainError as exc:
            op.status, op.safe_error = "needs_review", str(exc)[:500]
            exe["steps"][key].update(status="needs_review", error=op.safe_error,
                                     recovery="Outcome unknown. Re-run execution: steps are idempotent and "
                                              "will detect what already exists.")  # fmt: skip
            results[key] = "needs_review"
        except OdooRejectedError as exc:
            op.status, op.safe_error = "failed", str(exc)[:500]
            exe["steps"][key].update(
                status="failed", error=op.safe_error, recovery=step["recovery"]
            )
            results[key] = "failed"
        else:
            op.odoo_refs = res.get("refs")
            exe["steps"][key].update(outcome=res.get("outcome"), refs=res.get("refs"))
            # The bridge's answer is evidence, not proof: re-read Odoo and re-plan. Dependents
            # only run once this step is *seen* satisfied.
            fresh = build_plan(
                profile,
                bridge.call_bridge("capabilities"),
                bridge.call_bridge("readiness_snapshot"),
            )
            ok = {x["key"]: x["status"] for x in fresh["steps"]}.get(key) == "satisfied"
            op.verification = {
                "verified": ok,
                "checked_at": _now(),
                "method": "fresh snapshot replan",
            }
            op.status = "succeeded" if ok else "needs_review"
            exe["steps"][key].update(status=op.status, verified=ok)
            if not ok:
                op.safe_error = "Odoo does not show the intended state after the step."
                exe["steps"][key]["error"] = op.safe_error
            results[key] = op.status
        plan_row.execution = dict(exe)
        db.commit()
        on_event("step.end", {"step": key, "result": results[key]})

    # ---- Stage 4: independent verification from a fresh read ----
    manifest = bridge.call_bridge("capabilities")
    snapshot = bridge.call_bridge("readiness_snapshot")
    after = build_plan(profile, manifest, snapshot)
    statuses = set(results.values())
    if "failed" in statuses:
        final = "failed"
    elif statuses & {"needs_review", "skipped", "manual_required", "blocked"}:
        final = "needs_review"
    else:
        final = "completed"
    remaining = [s["key"] for s in after["steps"] if s["status"] == "to_apply"]
    exe["verification"] = {
        "checked_at": _now(), "remaining_steps": remaining,
        "complete": final == "completed" and not remaining,
        "environment": after["environment"],
    }  # fmt: skip
    if final == "completed" and remaining:
        final = "needs_review"
    exe["finished_at"] = _now()
    plan_row.status, plan_row.execution = final, dict(exe)
    db.commit()
    return {"status": final, "steps": exe["steps"], "verification": exe["verification"]}


class DriftError(Exception):
    pass
