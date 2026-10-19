"""Connection management against real Odoo Community 18/19 + real PostgreSQL."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.conftest import make_owner

from elblasy_api.db import get_engine
from elblasy_api.main import create_app

TARGETS = [("18.0", "http://localhost:8118", "ce18"), ("19.0", "http://localhost:8119", "ce19")]


def body(url, db, name="Main", secret="admin"):
    return {"name": name, "base_url": url, "db_name": db, "login": "admin", "secret": secret}


@pytest.fixture(params=TARGETS, ids=[t[0] for t in TARGETS])
def target(request, client):
    import httpx

    series, url, db = request.param
    try:
        httpx.get(url + "/web/login", timeout=3)
    except Exception:
        pytest.skip(f"Odoo {series} unreachable")
    make_owner(client, f"{uuid.uuid4().hex[:8]}@example.com")
    return series, url, db


def test_connect_health_rotate_revoke(client, target):
    series, url, db = target
    r = client.post("/connections", json=body(url, db))
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["odoo_series"] == series and c["compatibility_status"] == "supported"
    assert c["capabilities"]["pos"] is True and "secret" not in str(c).lower()
    with get_engine().connect() as conn:
        ct = conn.execute(
            text("select secret_ciphertext from odoo_connections where id=:i"), {"i": c["id"]}
        ).scalar()
    assert b"admin" not in bytes(ct)

    h = client.get(f"/connections/{c['id']}/health").json()
    assert h["ok"] and h["compatibility"] == "supported"

    assert (
        client.put(f"/connections/{c['id']}/credentials", json={"secret": "nope"}).status_code
        == 422
    )
    assert client.get(f"/connections/{c['id']}/health").json()["ok"]  # old secret untouched
    assert (
        client.put(f"/connections/{c['id']}/credentials", json={"secret": "admin"}).status_code
        == 200
    )

    assert client.delete(f"/connections/{c['id']}").status_code == 204
    assert client.get(f"/connections/{c['id']}/health").json()["status"] == "revoked"
    with get_engine().connect() as conn:
        assert (
            conn.execute(
                text("select secret_ciphertext from odoo_connections where id=:i"), {"i": c["id"]}
            ).scalar()
            is None
        )


def test_bad_credentials_and_unsafe_url(client, target):
    _, url, db = target
    assert client.post("/connections", json=body(url, db, secret="wrong")).status_code == 422
    r = client.post("/connections", json=body("http://169.254.169.254", db))
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsafe_url"
    r = client.post("/connections", json=body("file:///etc/passwd", db))
    assert r.json()["error"]["code"] == "unsafe_url"


def test_tenant_isolation(client, target):
    _, url, db = target
    cid = client.post("/connections", json=body(url, db, name="A")).json()["id"]
    other = TestClient(create_app())
    make_owner(other, f"{uuid.uuid4().hex[:8]}@example.com", business="Other")
    assert other.get("/connections").json() == []
    assert other.get(f"/connections/{cid}/health").status_code == 404
    assert other.delete(f"/connections/{cid}").status_code == 404
    assert other.put(f"/connections/{cid}/credentials", json={"secret": "admin"}).status_code == 404


def test_duplicate_name_conflict(client, target):
    _, url, db = target
    assert client.post("/connections", json=body(url, db, name="Dup")).status_code == 201
    assert client.post("/connections", json=body(url, db, name="Dup")).status_code == 409


def _fingerprint(url, db):
    """Max write_date / counts on configuration-bearing models, via direct RPC."""
    import xmlrpc.client as x

    uid = x.ServerProxy(url + "/xmlrpc/2/common").authenticate(db, "admin", "admin", {})
    m = x.ServerProxy(url + "/xmlrpc/2/object", allow_none=True)
    out = {}
    for model in ("res.company", "account.journal", "account.tax", "product.template",
                  "stock.warehouse", "pos.config", "ir.config_parameter", "account.move"):  # fmt: skip
        rows = m.execute_kw(db, uid, "admin", model, "search_read", [[]],
                            {"fields": ["write_date"], "order": "write_date desc", "limit": 1})  # fmt: skip
        out[model] = (m.execute_kw(db, uid, "admin", model, "search_count", [[]]),
                      rows[0]["write_date"] if rows else None)  # fmt: skip
    return out


def test_readiness_scan_is_read_only_and_reports_real_state(client, target):
    series, url, db = target
    cid = client.post("/connections", json=body(url, db)).json()["id"]
    before = _fingerprint(url, db)
    r = client.get(f"/connections/{cid}/readiness")
    assert r.status_code == 200, r.text
    data = r.json()
    assert _fingerprint(url, db) == before  # nothing changed in Odoo
    assert data["read_only"] and data["environment"] == "new_installation"
    ids = {f["id"] for f in data["findings"]}
    assert "POS-001" in ids  # fresh DB has POS installed but no POS configured
    assert not any(f["classification"] == "unable_to_verify" for f in data["findings"])
    for f in data["findings"]:
        assert f["verification"] and f["recommended_action"] and f["required_permission"]
    with get_engine().connect() as conn:
        n = conn.execute(
            text(
                "select count(*) from audit_events where action='readiness.scan' and outcome='success'"
            )
        ).scalar()
    assert n >= 1


def test_readiness_requires_permission(client, target):
    _, url, db = target
    cid = client.post("/connections", json=body(url, db, name="R")).json()["id"]
    client.post(
        "/users",
        json={
            "email": "till.user@example.com",
            "password": "cashier-password-1",
            "role": "cashier",
        },
    )
    cash = TestClient(create_app())
    cash.post(
        "/auth/login", json={"email": "till.user@example.com", "password": "cashier-password-1"}
    )
    assert cash.get(f"/connections/{cid}/readiness").status_code == 403


def test_any_signed_in_user_gets_a_minimal_current_connection(client, target):
    import uuid as _u

    _, url, db = target
    assert client.get("/connections/current").status_code == 404  # none yet
    cid = client.post("/connections", json=body(url, db)).json()["id"]
    email = f"cur{_u.uuid4().hex[:8]}@example.com"
    client.post(
        "/users", json={"email": email, "password": "cashier-password-1", "role": "cashier"}
    )
    cash = TestClient(create_app())
    cash.post("/auth/login", json={"email": email, "password": "cashier-password-1"})
    assert cash.get("/connections").status_code == 403  # the full list stays restricted
    r = cash.get("/connections/current")
    assert r.status_code == 200 and r.json()["id"] == cid
    assert set(r.json()) == {
        "id",
        "name",
        "odoo_series",
        "capabilities",
    }  # no URL, database or login
    other = TestClient(create_app())
    make_owner(other, f"{_u.uuid4().hex[:8]}@example.com", business="Other")
    assert other.get("/connections/current").status_code == 404  # another shop never sees it
    assert TestClient(create_app()).get("/connections/current").status_code == 401
