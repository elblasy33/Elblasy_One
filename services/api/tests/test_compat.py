import pytest

from elblasy_api.odoo.client import BridgeClient, OdooCredentials, OdooError
from elblasy_api.odoo.compat import assess
from elblasy_api.security.ssrf import ValidatedUrl


def test_assess():
    ok = {"odoo": {"series": "19.0"}, "contract_version": 1}
    assert assess(ok).status == "supported"
    assert (
        assess({"odoo": {"series": "17.0"}, "contract_version": 1}).status == "unsupported_version"
    )
    assert (
        assess({"odoo": {"series": "18.0"}, "contract_version": 9}).status == "unsupported_contract"
    )


def test_client_refuses_non_allowlisted_method():
    c = BridgeClient(ValidatedUrl("http://x", "x", 80, ()), OdooCredentials("d", "l", "s"))
    with pytest.raises(OdooError):
        c.call_bridge("unlink_everything")
