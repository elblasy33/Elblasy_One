"""Security headers, CSRF origin check, rate limits and structured logs (own app instances per setting)."""

import json
import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from elblasy_api.config import get_settings
from elblasy_api.main import create_app


@pytest.fixture
def app_with(pg_url, monkeypatch):
    def make(base_url="http://testserver", **env):
        for k, v in env.items():
            monkeypatch.setenv(f"ELBLASY_{k.upper()}", v)
        get_settings.cache_clear()
        return TestClient(create_app(), base_url=base_url)

    yield make
    get_settings.cache_clear()


def signup(c):
    c.cookies.clear()  # a fresh browser: an earlier session cookie would (rightly) trigger the CSRF check
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    r = c.post(
        "/auth/bootstrap",
        json={"business_name": "B", "email": email, "password": "correct-horse-battery"},
    )
    assert r.status_code == 201, r.text
    return email


def test_every_response_carries_security_headers_and_a_correlation_id(app_with):
    c = app_with()
    r = c.get("/healthz", headers={"x-correlation-id": "abc-123"})
    h = r.headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert (
        h["referrer-policy"] == "no-referrer"
        and h["cache-control"] == "no-store"
        and h["x-correlation-id"] == "abc-123"
    )
    assert (
        "camera=()" in h["permissions-policy"] and "strict-transport-security" not in h
    )  # HSTS only in production
    assert c.get("/auth/me").headers["x-content-type-options"] == "nosniff"  # also on errors


def test_production_enables_hsts_and_hides_the_docs(app_with):
    c = app_with(
        base_url="https://testserver",
        environment="production",
        allowed_origins='["https://shop.example.com"]',
        cookie_secure="true",
    )
    assert "max-age" in c.get("/healthz").headers["strict-transport-security"]
    assert c.get("/docs").status_code == 404


def test_csrf_origin_check_for_cookie_sessions(app_with):
    c = app_with(
        base_url="https://testserver",
        environment="production",
        allowed_origins='["https://shop.example.com"]',
        cookie_secure="true",
    )
    signup(c)
    assert c.cookies.get("elblasy_session")
    evil = c.post("/auth/logout", headers={"origin": "https://evil.example.org"})
    assert evil.status_code == 403 and evil.json()["error"]["code"] == "csrf_blocked"
    assert c.post("/auth/logout", headers={"origin": "https://shop.example.com"}).status_code == 204
    signup(c)
    assert (
        c.post("/auth/logout").status_code == 403
    )  # a cookie request with no Origin/Referer is refused in production
    signup(c)
    assert (
        c.post("/auth/logout", headers={"referer": "https://shop.example.com/settings"}).status_code
        == 204
    )
    signup(c)
    assert (
        c.post(
            "/auth/logout",
            headers={"origin": "https://shop.example.com", "sec-fetch-site": "cross-site"},
        ).status_code
        == 403
    )
    # safe methods and token (non-cookie) clients are not affected
    signup(c)
    assert c.get("/auth/me", headers={"origin": "https://evil.example.org"}).status_code == 200
    token = c.cookies.get("elblasy_session")
    api = TestClient(create_app(), base_url="https://testserver")
    assert (
        api.post(
            "/auth/logout",
            headers={"authorization": f"Bearer {token}", "origin": "https://evil.example.org"},
        ).status_code
        == 204
    )


def test_development_does_not_enforce_origins_when_none_are_configured(app_with):
    c = app_with()
    signup(c)
    assert c.post("/auth/logout", headers={"origin": "http://anything.example"}).status_code == 204


def test_write_and_auth_rate_limits(app_with):
    c = app_with(rate_limit_writes_per_min="5", rate_limit_auth_per_5min="0")
    codes = [
        c.post(
            "/auth/login", json={"email": "x@example.com", "password": "nope-nope-nope"}
        ).status_code
        for _ in range(7)
    ]
    assert codes[:5] == [401] * 5 and set(codes[5:]) == {429}
    assert c.get("/healthz").status_code == 200  # reads are not limited
    assert (
        c.post("/auth/login", json={"email": "x@example.com", "password": "n"}).json()["error"][
            "code"
        ]
        == "rate_limited"
    )
    d = app_with(rate_limit_writes_per_min="0", rate_limit_auth_per_5min="3")
    codes = [d.post("/auth/logout").status_code for _ in range(5)]
    assert codes[:3] == [204] * 3 and set(codes[3:]) == {429}


def test_access_log_is_json_with_correlation_id_and_never_logs_the_query_string(app_with):
    records: list[str] = []

    class Grab(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    from elblasy_api.security.middleware import JsonFormatter

    h = Grab()
    h.setFormatter(JsonFormatter())
    log = logging.getLogger("elblasy.access")
    log.addHandler(h)
    try:
        c = app_with()
        c.get("/healthz?token=SECRET-VALUE", headers={"x-correlation-id": "cid-42"})
    finally:
        log.removeHandler(h)
    assert records, "the access log produced nothing"
    line = json.loads(next(r for r in records if "cid-42" in r))
    assert (
        line["msg"] == "request"
        and line["path"] == "/healthz"
        and line["status"] == 200
        and line["cid"] == "cid-42"
    )
    assert "SECRET-VALUE" not in json.dumps(line)
