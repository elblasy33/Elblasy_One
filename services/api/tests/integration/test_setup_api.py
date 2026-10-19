"""Setup plans against real Odoo Community 18/19 + PostgreSQL. Dry-run only: asserts Odoo is untouched."""

import uuid

from fastapi.testclient import TestClient
from tests.conftest import make_owner
from tests.integration.test_connections_api import _fingerprint, body, target  # noqa: F401

from elblasy_api.main import create_app

GROCERY = {"vertical": "grocery", "makes_own_products": True, "uses_weighing_scale": True,
           "tracks_expiry": True, "payment_methods": ["cash", "card"], "sells_on_credit": True}  # fmt: skip


def connect(client, url, db):
    return client.post("/connections", json=body(url, db, name=f"c{uuid.uuid4().hex[:4]}")).json()[
        "id"
    ]


def test_questionnaire_flow(client, target):  # noqa: F811
    r = client.post("/setup/questionnaire", json={"answers": {}}).json()
    assert [q["id"] for q in r["questions"]] == ["vertical"] or r["questions"][0][
        "id"
    ] == "vertical"
    assert not r["complete"]
    r = client.post("/setup/questionnaire", json={"answers": {"vertical": "shoes"}}).json()
    assert "uses_weighing_scale" not in {q["id"] for q in r["questions"]}
    assert client.get("/setup/templates").json()[0]["id"].endswith("_starter")


def test_plan_dry_run_export_approve(client, target):  # noqa: F811
    series, url, db = target
    cid = connect(client, url, db)
    before = _fingerprint(url, db)
    r = client.post(f"/connections/{cid}/setup/plans", json={"answers": GROCERY})
    assert r.status_code == 201, r.text
    plan = r.json()
    assert _fingerprint(url, db) == before and plan["status"] == "draft"
    steps = {s["key"]: s for s in plan["plan"]["steps"]}
    assert (
        steps["module_mrp"]["status"] == "to_apply"
        and steps["module_product_expiry"]["status"] == "to_apply"
    )
    assert steps["module_stock"]["status"] == "satisfied"
    assert steps["pos_main"]["status"] == "to_apply"  # fresh DB has no POS configured
    assert plan["plan"]["applicable"] and plan["plan"]["mode"] == "additive_only"

    ex = client.get(f"/connections/{cid}/setup/plans/{plan['id']}/export")
    assert ex.status_code == 200 and "attachment" in ex.headers["content-disposition"]
    assert ex.json()["plan_hash"] == plan["plan_hash"]

    ap = client.post(f"/connections/{cid}/setup/plans/{plan['id']}/approve")
    assert ap.status_code == 200 and ap.json()["status"] == "approved"
    assert client.post(f"/connections/{cid}/setup/plans/{plan['id']}/approve").status_code == 409

    # a new plan supersedes the approved one: approval cannot silently carry over
    p2 = client.post(f"/connections/{cid}/setup/plans", json={"answers": GROCERY}).json()
    old = client.get(f"/connections/{cid}/setup/plans/{plan['id']}").json()
    assert old["status"] == "superseded" and p2["status"] == "draft"


def test_unsupported_plan_cannot_be_approved(client, target):  # noqa: F811
    _, url, db = target
    cid = connect(client, url, db)
    p = client.post(
        f"/connections/{cid}/setup/plans", json={"answers": {"vertical": "general", "branches": 3}}
    ).json()
    assert not p["plan"]["applicable"]
    assert client.post(f"/connections/{cid}/setup/plans/{p['id']}/approve").status_code == 409


def test_permissions_and_isolation(client, target):  # noqa: F811
    _, url, db = target
    cid = connect(client, url, db)
    pid = client.post(
        f"/connections/{cid}/setup/plans", json={"answers": {"vertical": "shoes"}}
    ).json()["id"]
    client.post(
        "/users",
        json={"email": "acc@example.com", "password": "accountant-pass-1", "role": "accountant"},
    )
    acc = TestClient(create_app())
    acc.post("/auth/login", json={"email": "acc@example.com", "password": "accountant-pass-1"})
    assert acc.get(f"/connections/{cid}/setup/plans/{pid}").status_code == 403  # no config.manage
    other = TestClient(create_app())
    make_owner(other, f"{uuid.uuid4().hex[:8]}@example.com", business="Other")
    assert other.get(f"/connections/{cid}/setup/plans/{pid}").status_code == 404
    assert other.post(f"/connections/{cid}/setup/plans/{pid}/approve").status_code == 404
