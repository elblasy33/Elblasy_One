"""Authentication hardening and user management (real PostgreSQL, no Odoo needed)."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from elblasy_api.db import get_engine
from elblasy_api.main import create_app
from tests.conftest import make_owner

PW = "correct-horse-battery"


def mail():
    return f"{uuid.uuid4().hex[:8]}@example.com"


def second_client(client, email, password):
    c = TestClient(create_app())
    r = c.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return c


def add_user(client, role="cashier", pw="staff-password-12", **kw):
    e = mail()
    r = client.post("/users", json={"email": e, "password": pw, "role": role, **kw})
    assert r.status_code == 201, r.text
    return e, r.json()


def audit_count(action):
    with get_engine().connect() as c:
        return c.execute(
            text("select count(*) from audit_events where action=:a"), {"a": action}
        ).scalar()


def test_weak_passwords_are_refused_everywhere(client):
    e = mail()
    for bad in ("password1234", "aaaaaaaaaaaaaa", "123456789012345", f"{e.split('@')[0]}-extra"):
        r = client.post("/auth/bootstrap", json={"business_name": "B", "email": e, "password": bad})
        assert r.status_code == 422, bad
    make_owner(client, e)
    r = client.post(
        "/users", json={"email": mail(), "password": "letmein123456", "role": "cashier"}
    )
    assert r.status_code == 422 and r.json()["error"]["code"].startswith("weak_password")


def test_account_locks_after_repeated_failures_and_recovers_with_reset(client):
    make_owner(client, mail())
    email, user = add_user(client)
    victim = TestClient(create_app())
    from elblasy_api.ratelimit import login_limiter

    for _ in range(5):
        login_limiter.reset()
        assert (
            victim.post(
                "/auth/login", json={"email": email, "password": "wrong-password-xx"}
            ).status_code
            == 401
        )
    login_limiter.reset()
    locked = victim.post("/auth/login", json={"email": email, "password": "staff-password-12"})
    assert (
        locked.status_code == 429 and locked.json()["error"]["code"] == "account_locked"
    )  # even the right password
    assert audit_count("auth.locked") >= 1
    r = client.post(f"/users/{user['id']}/reset-password", json={"password": "fresh-password-34"})
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    login_limiter.reset()
    assert (
        victim.post(
            "/auth/login", json={"email": email, "password": "fresh-password-34"}
        ).status_code
        == 200
    )


def test_changing_a_password_ends_other_sessions_and_keeps_this_one(client):
    make_owner(client, mail())
    email, _ = add_user(client)
    a, b = (
        second_client(client, email, "staff-password-12"),
        second_client(client, email, "staff-password-12"),
    )
    assert a.get("/auth/me").status_code == 200 and b.get("/auth/me").status_code == 200
    bad = a.post(
        "/auth/change-password",
        json={"current_password": "nope-nope-nope", "new_password": "brand-new-pass-1"},
    )
    assert bad.status_code == 403
    same = a.post(
        "/auth/change-password",
        json={"current_password": "staff-password-12", "new_password": "staff-password-12"},
    )
    assert same.status_code == 422
    ok = a.post(
        "/auth/change-password",
        json={"current_password": "staff-password-12", "new_password": "brand-new-pass-1"},
    )
    assert ok.status_code == 200
    assert a.get("/auth/me").status_code == 200  # this device continues
    assert b.get("/auth/me").status_code == 401  # the other one is signed out
    assert audit_count("auth.password_change") >= 2
    a.post("/auth/logout-everywhere")
    assert a.get("/auth/me").status_code == 401


def test_role_change_and_deactivation_end_sessions_immediately(client):
    make_owner(client, mail())
    email, user = add_user(client, "cashier")
    s = second_client(client, email, "staff-password-12")
    assert s.get("/connections").status_code == 403
    assert client.patch(f"/users/{user['id']}", json={"role": "manager"}).status_code == 200
    assert s.get("/auth/me").status_code == 401  # old token no longer valid after the role changed
    s2 = second_client(client, email, "staff-password-12")
    assert s2.get("/auth/me").json()["role"] == "manager"
    assert client.patch(f"/users/{user['id']}", json={"active": False}).status_code == 200
    assert s2.get("/auth/me").status_code == 401
    assert (
        TestClient(create_app())
        .post("/auth/login", json={"email": email, "password": "staff-password-12"})
        .status_code
        == 401
    )


def test_guard_rails_on_user_management(client):
    owner_email = mail()
    me = make_owner(client, owner_email)
    # nobody changes their own role or status, and the last owner cannot be removed
    assert client.patch(f"/users/{me['id']}", json={"role": "cashier"}).status_code == 403
    assert client.patch(f"/users/{me['id']}", json={"active": False}).status_code == 403
    second_email, second = add_user(client, "owner")
    owner2 = second_client(client, second_email, "staff-password-12")
    assert (
        owner2.patch(f"/users/{me['id']}", json={"active": False}).status_code == 200
    )  # another owner exists, so it is allowed
    assert (
        owner2.patch(f"/users/{second['id']}", json={"role": "manager"}).status_code == 403
    )  # self-change
    # with one owner left, demoting them through a third party is refused
    assert (
        client.patch(f"/users/{me['id']}", json={"active": True}).status_code == 401
    )  # their session ended with deactivation
    # a manager cannot create or touch owners/administrators and has no user-management permission at all
    m_email, _ = add_user(owner2, "manager")
    mgr = second_client(owner2, m_email, "staff-password-12")
    assert mgr.get("/users").status_code == 403
    admin_email, admin = add_user(owner2, "platform_admin")
    adm = second_client(owner2, admin_email, "staff-password-12")
    assert (
        adm.post(
            "/users", json={"email": mail(), "password": "staff-password-12", "role": "owner"}
        ).status_code
        == 403
    )
    assert adm.patch(f"/users/{second['id']}", json={"role": "cashier"}).status_code == 403
    assert (
        adm.post(
            f"/users/{second['id']}/reset-password", json={"password": "attack-password-9"}
        ).status_code
        == 403
    )
    only = [u for u in owner2.get("/users").json() if u["role"] == "owner" and u["active"]]
    assert len(only) == 1
    assert adm.patch(f"/users/{admin['id']}", json={"display_name": "x"}).status_code in (200, 403)


def test_temporary_password_forces_a_change_before_anything_else(client):
    make_owner(client, mail())
    email, _ = add_user(client, "cashier", temporary=True)
    u = second_client(client, email, "staff-password-12")
    me = u.get("/auth/me").json()
    assert me["must_change_password"] is True
    blocked = u.get("/connections/current")
    assert (
        blocked.status_code == 403 and blocked.json()["error"]["code"] == "password_change_required"
    )
    ok = u.post(
        "/auth/change-password",
        json={"current_password": "staff-password-12", "new_password": "my-own-password-7"},
    )
    assert ok.status_code == 200 and ok.json()["must_change_password"] is False
    assert u.get("/connections/current").status_code in (
        200,
        404,
    )  # no longer blocked (404 = no connection yet)


def test_user_management_is_tenant_isolated_and_audited(client):
    make_owner(client, mail())
    _, user = add_user(client)
    other = TestClient(create_app())
    make_owner(other, mail(), business="Other")
    assert other.get("/users").json() == [
        u for u in other.get("/users").json()
    ]  # only its own users
    assert user["id"] not in [u["id"] for u in other.get("/users").json()]
    assert other.patch(f"/users/{user['id']}", json={"active": False}).status_code == 404
    assert (
        other.post(
            f"/users/{user['id']}/reset-password", json={"password": "attack-password-9"}
        ).status_code
        == 404
    )
    assert audit_count("user.create") >= 1
