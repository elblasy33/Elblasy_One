"""Real execution against throwaway copies of the CE 18 / 19 template databases."""

import uuid
import xmlrpc.client as x

import httpx
import pytest
from tests.conftest import make_owner
from tests.integration.test_connections_api import body

from elblasy_api.odoo.client import BridgeClient, OdooCredentials, OdooRejectedError
from elblasy_api.security.ssrf import validate_odoo_url

TARGETS = [("18.0", "http://localhost:8118", "ce18"), ("19.0", "http://localhost:8119", "ce19")]
MASTER = "dev-master"
GROCERY = {
    "vertical": "grocery", "makes_own_products": True, "uses_weighing_scale": True,
    "tracks_expiry": True, "payment_methods": ["cash", "card"], "sells_on_credit": True,
}  # fmt: skip


@pytest.fixture(params=TARGETS, ids=[t[0] for t in TARGETS])
def fresh(request):
    series, url, template = request.param
    try:
        httpx.get(url + "/web/login", timeout=3)
    except Exception:
        pytest.skip(f"Odoo {series} unreachable")
    name = f"t_{uuid.uuid4().hex[:8]}"
    dbs = x.ServerProxy(url + "/xmlrpc/2/db")
    dbs.duplicate_database(MASTER, template, name)
    try:
        yield series, url, name
    finally:
        dbs.drop(MASTER, name)


def rpc(url, db):
    uid = x.ServerProxy(url + "/xmlrpc/2/common").authenticate(db, "admin", "admin", {})
    m = x.ServerProxy(url + "/xmlrpc/2/object", allow_none=True)
    return lambda model, meth, *a, **k: m.execute_kw(db, uid, "admin", model, meth, list(a), k)


def test_full_setup_executes_and_is_verified_independently(client, fresh):
    series, url, db = fresh
    make_owner(client, f"{uuid.uuid4().hex[:8]}@example.com")
    cid = client.post("/connections", json=body(url, db)).json()["id"]
    plan = client.post(f"/connections/{cid}/setup/plans", json={"answers": GROCERY}).json()
    keys = {s["key"]: s["status"] for s in plan["plan"]["steps"]}
    assert keys["module_mrp"] == "to_apply" and keys["pos_main"] == "to_apply"

    # cannot execute before approval
    assert client.post(f"/connections/{cid}/setup/plans/{plan['id']}/execute").status_code == 409
    client.post(f"/connections/{cid}/setup/plans/{plan['id']}/approve")
    r = client.post(f"/connections/{cid}/setup/plans/{plan['id']}/execute")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "completed", out
    assert out["verification"]["complete"] and out["verification"]["remaining_steps"] == []

    # independent evidence straight from Odoo (not via the bridge's own answers)
    c = rpc(url, db)
    states = {
        m["name"]: m["state"]
        for m in c(
            "ir.module.module",
            "search_read",
            [["name", "in", ["mrp", "product_expiry"]]],
            fields=["name", "state"],
        )
    }
    assert states == {"mrp": "installed", "product_expiry": "installed"}
    cfgs = c("pos.config", "search_read", [], fields=["name", "payment_method_ids"])
    assert len(cfgs) == 1 and len(cfgs[0]["payment_method_ids"]) >= 1
    methods = c("pos.payment.method", "search_read", [], fields=["is_cash_count"])
    assert any(m["is_cash_count"] for m in methods)
    managed = {
        d["name"]
        for d in c(
            "ir.model.data", "search_read", [["module", "=", "elblasy_one"]], fields=["name"]
        )
    }
    assert {"pos_main", "pos_pm_cash"} <= managed

    # re-plan: everything is satisfied, nothing left to approve
    again = client.post(f"/connections/{cid}/setup/plans", json={"answers": GROCERY}).json()
    assert again["plan"]["summary"]["to_apply"] == 0
    assert client.post(f"/connections/{cid}/setup/plans/{again['id']}/approve").status_code == 409

    # post-setup scan no longer reports the missing POS
    ids = {f["id"] for f in client.get(f"/connections/{cid}/readiness").json()["findings"]}
    assert "POS-001" not in ids


def bridge(url, db, login="admin", secret="admin"):
    t = validate_odoo_url(url, production=False, allow_private=True, allow_insecure_http=True)
    return BridgeClient(t, OdooCredentials(db, login, secret), timeout=60)


def test_bridge_steps_are_idempotent_by_key(fresh):
    _, url, db = fresh
    b = bridge(url, db)
    c = rpc(url, db)
    before = c("pos.config", "search_count", [])
    b.call_bridge(
        "apply_step", "op0", "ensure_journal", "cash_journal", {"type": "cash", "name": "Cash"}
    )
    pm = b.call_bridge(
        "apply_step",
        "op1",
        "ensure_pos_payment_method",
        "pos_pm_cash",
        {"kind": "cash"},
        timeout=120,
    )
    cfg = {"name": "Main", "payment_method_keys": ["pos_pm_cash"]}
    r1 = b.call_bridge("apply_step", "op2", "ensure_pos_config", "pos_main", cfg)
    r2 = b.call_bridge("apply_step", "op3", "ensure_pos_config", "pos_main", cfg)  # retry
    assert pm["outcome"] in ("created", "already_exists")
    assert r1["outcome"] == "created" and r2["outcome"] == "already_exists"
    assert r1["refs"]["pos_config_id"] == r2["refs"]["pos_config_id"]
    assert c("pos.config", "search_count", []) == before + 1


def test_bridge_rejects_unlisted_things(fresh):
    _, url, db = fresh
    b = bridge(url, db)
    for kind, key, params in (
        ("unlink_everything", "bad_kind", {}),
        ("install_module", "bad_mod", {"module": "base"}),
        ("install_module", "bad_mod2", {"module": "hr_payroll"}),
        ("enable_feature", "bad_feat", {"feature": "group_system"}),
        ("ensure_journal", "bad_j", {"type": "general"}),
        ("ensure_pos_config", "Bad Key!", {}),
    ):
        with pytest.raises(OdooRejectedError):
            b.call_bridge("apply_step", "op", kind, key, params)


def test_unprivileged_odoo_user_cannot_apply(fresh):
    _, url, db = fresh
    c = rpc(url, db)
    c(
        "res.users",
        "create",
        [
            {
                "name": "Low",
                "login": "low",
                "password": "low-pass-123",
                "group_ids" if False else "groups_id": [],
            }
        ],
    ) if False else None
    uid = c("res.users", "create", [{"name": "Low", "login": "low", "password": "low-pass-123"}])
    assert uid
    low = bridge(url, db, "low", "low-pass-123")
    with pytest.raises(OdooRejectedError):
        low.call_bridge("apply_step", "op", "install_module", "mod_mrp", {"module": "mrp"})
    assert (
        rpc(url, db)("ir.module.module", "search_read", [["name", "=", "mrp"]], fields=["state"])[
            0
        ]["state"]
        == "uninstalled"
    )
