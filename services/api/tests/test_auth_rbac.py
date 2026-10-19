import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.conftest import make_owner

from elblasy_api.db import get_engine
from elblasy_api.main import create_app


def em():
    return f"{uuid.uuid4().hex[:8]}@example.com"


def test_bootstrap_login_me_logout(client):
    e = em()
    make_owner(client, e)
    assert client.get("/auth/me").json()["role"] == "owner"
    client.post("/auth/logout")
    assert client.get("/auth/me").status_code == 401
    assert (
        client.post(
            "/auth/login", json={"email": e.upper(), "password": "correct-horse-battery"}
        ).status_code
        == 200
    )


def test_bad_login_is_generic_and_audited(client):
    e = em()
    make_owner(client, e)
    client.post("/auth/logout")
    r = client.post("/auth/login", json={"email": e, "password": "wrong"})
    r2 = client.post("/auth/login", json={"email": em(), "password": "wrong"})
    assert r.status_code == r2.status_code == 401
    assert r.json()["error"]["code"] == r2.json()["error"]["code"]
    with get_engine().connect() as c:
        n = c.execute(
            text("select count(*) from audit_events where action='auth.login' and outcome='denied'")
        ).scalar()
    assert n >= 2


def test_login_rate_limit(client):
    e = em()
    for _ in range(10):
        client.post("/auth/login", json={"email": e, "password": "x"})
    assert client.post("/auth/login", json={"email": e, "password": "x"}).status_code == 429


def test_weak_password_rejected(client):
    r = client.post(
        "/auth/bootstrap", json={"business_name": "B", "email": em(), "password": "short"}
    )
    assert r.status_code == 422


def test_cashier_cannot_manage_connections_or_users(client):
    make_owner(client, em())
    ce = em()
    r = client.post(
        "/users", json={"email": ce, "password": "cashier-password-1", "role": "cashier"}
    )
    assert r.status_code == 201
    cashier = TestClient(create_app())
    cashier.post("/auth/login", json={"email": ce, "password": "cashier-password-1"})
    assert cashier.get("/connections").status_code == 403
    assert (
        cashier.post(
            "/users", json={"email": em(), "password": "another-password-1", "role": "owner"}
        ).status_code
        == 403
    )
    assert "sales.create" in cashier.get("/auth/me").json()["permissions"]
    with get_engine().connect() as c:
        assert (
            c.execute(
                text("select count(*) from audit_events where action='authz.denied'")
            ).scalar()
            >= 2
        )


def test_tampered_token_rejected(client):
    make_owner(client, em())
    tok = client.cookies.get("elblasy_session")
    client.cookies.clear()
    assert client.get("/auth/me", headers={"authorization": f"Bearer {tok}x"}).status_code == 401
    assert client.get("/auth/me", headers={"authorization": f"Bearer {tok}"}).status_code == 200


def test_audit_log_is_append_only(client):
    make_owner(client, em())
    with get_engine().begin() as c:
        try:
            c.execute(text("update audit_events set outcome='x'"))
            raise AssertionError("update must fail")
        except DBAPIError as exc:
            assert "append-only" in str(exc)
    with get_engine().begin() as c:
        try:
            c.execute(text("delete from audit_events"))
            raise AssertionError("delete must fail")
        except DBAPIError as exc:
            assert "append-only" in str(exc)
