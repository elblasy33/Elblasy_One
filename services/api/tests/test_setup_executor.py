"""Executor behaviour against a fake Odoo (failure modes) and real PostgreSQL."""

import copy
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from elblasy_api.db import get_engine
from elblasy_api.models import OdooConnection, Operation, SetupPlan, Tenant, User
from elblasy_api.odoo.client import OdooRejectedError, OdooUncertainError
from elblasy_api.setup.executor import DriftError, execute_plan
from elblasy_api.setup.planner import build_plan
from elblasy_api.setup.profile import BusinessProfile
from tests.test_readiness_engine import MANIFEST
from tests.test_setup_planner import snap

PROFILE = BusinessProfile(vertical="grocery", makes_own_products=True, tracks_expiry=True)


class FakeOdoo:
    """Minimal stateful Odoo: install_module/enable_feature mutate the snapshot."""

    def __init__(self):
        self.snap = snap()
        self.calls = []
        self.fail = {}  # key -> "uncertain" | "reject" | "uncertain_after" | "noop"

    def call_bridge(self, method, *args, timeout=None):
        if method == "capabilities":
            return copy.deepcopy(MANIFEST)
        if method == "readiness_snapshot":
            return copy.deepcopy(self.snap)
        assert method == "apply_step"
        op_id, kind, key, params = args
        self.calls.append(key)
        mode = self.fail.get(key)
        if mode == "reject":
            raise OdooRejectedError("Odoo rejected the call: nope")
        if mode == "uncertain":
            raise OdooUncertainError("Odoo connection problem: TimeoutError")
        if mode != "noop":
            self._apply(kind, params)
        if mode == "uncertain_after":  # applied, but the answer was lost
            self.fail.pop(key)
            raise OdooUncertainError("Odoo connection problem: ConnectionResetError")
        return {"outcome": "created", "refs": {"k": key}}

    def _apply(self, kind, p):
        if kind == "install_module":
            self.snap["modules"][p["module"]] = "installed"
        elif kind == "enable_feature":
            self.snap["features"][p["feature"]] = True
        elif kind == "ensure_pos_payment_method":
            self.snap["pos"]["payment_methods"].append(
                {"name": p["kind"], "is_cash_count": p["kind"] == "cash"}
            )


@pytest.fixture
def world(pg_url):
    odoo = FakeOdoo()
    plan = build_plan(PROFILE, MANIFEST, odoo.snap)
    with Session(get_engine(), expire_on_commit=False) as db:
        t = Tenant(name="T")
        db.add(t)
        db.flush()
        u = User(
            tenant_id=t.id, email=f"{uuid.uuid4().hex[:8]}@x.com", password_hash="x", role="owner"
        )
        db.add(u)
        db.flush()
        c = OdooConnection(tenant_id=t.id, name="c", base_url="http://x", db_name="d", login="l")
        db.add(c)
        db.flush()
        row = SetupPlan(
            tenant_id=t.id, connection_id=c.id, template_id=plan["template"]["id"],
            template_version="1", profile=plan["profile"], plan=plan, plan_hash=plan["plan_hash"],
            snapshot_hash=plan["snapshot_hash"], status="approved", created_by=u.id,
        )  # fmt: skip
        db.add(row)
        db.commit()
        yield db, row, u, odoo


def ops(db, row):
    return {
        o.idempotency_key.split(":")[1]: o
        for o in db.scalars(select(Operation).where(Operation.connection_id == row.connection_id))
    }


def test_happy_path_executes_only_needed_steps_and_verifies(world):
    db, row, u, odoo = world
    r = execute_plan(db, row, u.id, odoo)
    assert r["status"] == "completed" and r["verification"]["complete"]
    assert set(odoo.calls) == {
        "module_mrp",
        "module_product_expiry",
        "feature_lots",
        "pos_pm_cash",
    }  # satisfied steps never sent
    assert all(
        o.status == "succeeded" and o.verification["verified"] for o in ops(db, row).values()
    )


def test_dependency_order(world):
    db, row, u, odoo = world
    execute_plan(db, row, u.id, odoo)
    assert odoo.calls.index("module_product_expiry") < odoo.calls.index("feature_lots")


def test_timeout_is_needs_review_and_rerun_resumes_without_duplicates(world):
    db, row, u, odoo = world
    odoo.fail["module_mrp"] = "uncertain_after"  # Odoo applied it, response lost
    r = execute_plan(db, row, u.id, odoo)
    assert r["status"] == "needs_review" and r["steps"]["module_mrp"]["status"] == "needs_review"
    assert r["steps"]["feature_lots"]["status"] == "succeeded"  # independent steps still ran
    first_ops = {k: o.id for k, o in ops(db, row).items()}
    r2 = execute_plan(db, row, u.id, odoo)
    assert r2["status"] == "completed"
    assert {k: o.id for k, o in ops(db, row).items()} == first_ops  # same operations, no duplicates
    assert odoo.calls.count("feature_lots") == 1  # finished work not repeated


def test_rejection_fails_and_skips_dependents(world):
    db, row, u, odoo = world
    odoo.fail["module_product_expiry"] = "reject"
    r = execute_plan(db, row, u.id, odoo)
    assert r["status"] == "failed"
    assert (
        r["steps"]["module_product_expiry"]["status"] == "failed"
        and "nope" in r["steps"]["module_product_expiry"]["error"]
    )
    assert r["steps"]["feature_lots"]["status"] == "skipped"
    assert r["steps"]["module_mrp"]["status"] == "succeeded"
    assert "feature_lots" not in odoo.calls


def test_bridge_claiming_success_is_not_trusted(world):
    db, row, u, odoo = world
    odoo.fail["module_mrp"] = "noop"  # says created, but Odoo state did not change
    r = execute_plan(db, row, u.id, odoo)
    assert (
        r["steps"]["module_mrp"]["status"] == "needs_review"
        and r["steps"]["module_mrp"]["verified"] is False
    )
    assert r["status"] == "needs_review" and not r["verification"]["complete"]


def test_drift_refuses_to_run(world):
    db, row, u, odoo = world
    odoo.snap["accounting"]["journals"]["cash"] = 0  # someone changed Odoo after review
    with pytest.raises(DriftError):
        execute_plan(db, row, u.id, odoo)
    assert odoo.calls == []


def test_manual_step_leaves_plan_open(world):
    db, row, u, odoo = world
    plan = copy.deepcopy(row.plan)
    plan["steps"].append({**plan["steps"][0], "key": "chart_of_accounts", "kind": "load_chart_of_accounts",
                          "status": "to_apply", "executable": False, "depends_on": [], "approval": ["owner"]})  # fmt: skip
    row.plan = plan
    r = execute_plan(db, row, u.id, odoo)
    assert (
        r["steps"]["chart_of_accounts"]["status"] == "manual_required"
        and r["status"] == "needs_review"
    )
    assert "chart_of_accounts" not in odoo.calls
