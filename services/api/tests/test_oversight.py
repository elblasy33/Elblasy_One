"""Audit log, operation history, alerts (platform facts). Real PostgreSQL, no Odoo."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from elblasy_api.db import get_engine
from elblasy_api.main import create_app
from tests.conftest import make_owner


def mail():
    return f"{uuid.uuid4().hex[:8]}@example.com"


def staff(client, role):
    e = mail()
    assert (
        client.post(
            "/users", json={"email": e, "password": "staff-password-12", "role": role}
        ).status_code
        == 201
    )
    c = TestClient(create_app())
    assert (
        c.post("/auth/login", json={"email": e, "password": "staff-password-12"}).status_code == 200
    )
    return c, e


def test_audit_log_lists_filters_exports_and_stays_in_its_tenant(client):
    owner = mail()
    make_owner(client, owner)
    staff(client, "cashier")
    r = client.get("/audit", params={"limit": 50}).json()
    actions = {e["action"] for e in r["items"]}
    assert {"tenant.bootstrap", "user.create", "auth.login"} <= actions
    assert all(e["actor"] in (owner, None) or e["actor"] for e in r["items"])
    only = client.get("/audit", params={"action": "user."}).json()
    assert only["total"] >= 1 and all(e["action"].startswith("user.") for e in only["items"])
    assert client.get("/audit", params={"actor": owner}).json()["total"] >= 2
    assert client.get("/audit", params={"outcome": "denied"}).status_code == 200
    csv = client.get("/audit/export")
    assert (
        csv.status_code == 200
        and csv.headers["content-type"].startswith("text/csv")
        and "user.create" in csv.text
    )
    assert (
        client.get("/audit", params={"action": "audit.export"}).json()["total"] >= 1
    )  # exporting is itself audited
    other = TestClient(create_app())
    make_owner(other, mail(), business="Other")
    seen = {e["action"] for e in other.get("/audit").json()["items"]}
    assert "user.create" not in seen  # another shop's events are never visible
    assert client.get("/audit", params={"limit": 500}).status_code == 422


def test_only_roles_with_audit_permission_see_the_log(client):
    make_owner(client, mail())
    cashier, _ = staff(client, "cashier")
    clerk, _ = staff(client, "inventory_operator")
    acc, _ = staff(client, "accountant")
    assert (
        cashier.get("/audit").status_code == 403 and cashier.get("/operations").status_code == 403
    )
    assert clerk.get("/audit/export").status_code == 403
    assert acc.get("/audit").status_code == 200  # the accountant may audit
    assert client.get("/audit", params={"from": "not-a-date"}).status_code == 422


def test_operations_history_hides_internals_and_alerts_follow_permissions(client):
    me = make_owner(client, mail())
    tenant = me["tenant_id"]
    with get_engine().begin() as c:
        conn = uuid.uuid4()
        c.execute(
            text(
                "insert into odoo_connections (id, tenant_id, name, base_url, db_name, login, status, compatibility_status) values (:i,:t,'x','http://x','d','l','revoked','unknown')"
            ),
            {"i": conn, "t": tenant},
        )
        for status, typ in (
            ("needs_review", "sales.order.create"),
            ("failed", "stock.adjust"),
            ("succeeded", "catalog.product.create"),
            ("awaiting_approval", "stock.adjust"),
            ("awaiting_approval", "money.expense.create"),
        ):
            c.execute(
                text(
                    "insert into operations (id, tenant_id, connection_id, type, idempotency_key, request_fingerprint, actor_id, status, odoo_refs, safe_error) values (:i,:t,:c,:ty,:k,'f',:a,:s, cast(:r as jsonb), :e)"
                ),
                {
                    "i": uuid.uuid4(),
                    "t": tenant,
                    "c": conn,
                    "ty": typ,
                    "k": uuid.uuid4().hex,
                    "a": me["id"],
                    "s": status,
                    "r": '{"_before": {"secret": 1}}',
                    "e": "boom" if status == "failed" else None,
                },
            )
    ops = client.get("/operations", params={"status": "needs_review"}).json()
    assert (
        ops["total"] == 1
        and ops["items"][0]["needs_attention"] is True
        and "_before" not in str(ops)
    )
    assert client.get("/operations", params={"type": "stock."}).json()["total"] == 2
    keys = {a["key"]: a for a in client.get("/alerts").json()["items"]}
    assert (
        keys["operations_need_review"]["severity"] == "critical"
        and keys["operations_need_review"]["count"] == 1
    )
    assert (
        keys["stock_adjustments_waiting"]["count"] == 1 and keys["expenses_waiting"]["count"] == 1
    )
    cashier, _ = staff(client, "cashier")
    assert cashier.get("/alerts").json()["items"] == []  # nothing here is theirs to act on
    clerk, _ = staff(client, "inventory_operator")
    assert "operations_need_review" not in {a["key"] for a in clerk.get("/alerts").json()["items"]}
    assert TestClient(create_app()).get("/alerts").status_code == 401
