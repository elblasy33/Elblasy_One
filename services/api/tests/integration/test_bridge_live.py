"""Real Odoo Community instances only (infrastructure/docker/compose.odoo-community.yml). Skipped unless the targets are reachable (local docker)."""

import os

import pytest

from elblasy_api.odoo.client import BridgeClient, OdooAuthError, OdooCredentials
from elblasy_api.odoo.compat import assess
from elblasy_api.security.ssrf import validate_odoo_url

TARGETS = [
    ("18.0", os.getenv("ODOO18_URL", "http://localhost:8118"), "ce18"),
    ("19.0", os.getenv("ODOO19_URL", "http://localhost:8119"), "ce19"),
]


def client(url, db, secret="admin"):
    t = validate_odoo_url(url, production=False, allow_private=True, allow_insecure_http=True)
    return BridgeClient(t, OdooCredentials(db, "admin", secret), timeout=10)


@pytest.fixture(params=TARGETS, ids=[t[0] for t in TARGETS])
def target(request):
    series, url, db = request.param
    c = client(url, db)
    try:
        c.server_version()
    except Exception:
        pytest.skip(f"Odoo {series} not reachable")
    return series, c, url, db


def test_version_and_capabilities(target):
    series, c, *_ = target
    assert c.server_version()["server_serie"] == series
    m = c.call_bridge("capabilities")
    assert m["odoo"]["series"] == series and m["odoo"]["edition"] == "community"
    assert assess(m).status == "supported"
    assert m["capabilities"]["pos"] and m["capabilities"]["inventory_valuation"]
    assert m["allowed_companies"] and m["current_company_id"]


def test_ping_and_bad_credentials(target):
    _, c, url, db = target
    assert c.call_bridge("ping")["ok"] is True
    with pytest.raises(OdooAuthError):
        client(url, db, secret="wrong").call_bridge("ping")
