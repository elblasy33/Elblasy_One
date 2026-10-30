"""DNS-rebinding defence: the client connects to the validated IP, whatever the name resolves to later."""

import threading
import xmlrpc.client
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from elblasy_api.odoo.client import BridgeClient, OdooCredentials, OdooError
from elblasy_api.security.ssrf import ValidatedUrl


class Handler(BaseHTTPRequestHandler):
    seen_hosts: list[str] = []

    def do_POST(self):  # noqa: N802
        Handler.seen_hosts.append(self.headers.get("Host", ""))
        body = xmlrpc.client.dumps(
            ({"server_version": "18.0", "server_serie": "18.0"},), methodresponse=True
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # silence
        pass


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def creds():
    return OdooCredentials("d", "l", "s")


def test_connects_to_the_validated_ip_even_if_the_name_does_not_resolve(server):
    Handler.seen_hosts.clear()
    # "rebind.invalid" can never resolve; only the pinned address makes this request possible.
    target = ValidatedUrl(
        f"http://rebind.invalid:{server}", "rebind.invalid", server, ("127.0.0.1",)
    )
    assert BridgeClient(target, creds(), timeout=5).server_version()["server_serie"] == "18.0"
    assert Handler.seen_hosts and Handler.seen_hosts[0].startswith(
        "rebind.invalid"
    )  # the Host header keeps the name


def test_without_a_pinned_address_the_name_is_resolved_normally_and_fails(server):
    target = ValidatedUrl(f"http://rebind.invalid:{server}", "rebind.invalid", server, ())
    with pytest.raises(OdooError):
        BridgeClient(target, creds(), timeout=3).server_version()


def test_a_pinned_ip_that_refuses_the_connection_is_reported_safely():
    target = ValidatedUrl(
        "http://x.invalid:9", "x.invalid", 9, ("127.0.0.1",)
    )  # nothing listens on :9
    with pytest.raises(OdooError) as exc:
        BridgeClient(target, creds(), timeout=3).server_version()
    assert "unreachable" in str(exc.value)


def test_uid_is_cached_per_credentials_and_dropped_on_access_denied(monkeypatch):
    import xmlrpc.client

    from elblasy_api.odoo import client as cl

    cl.clear_uid_cache()
    calls = {"auth": 0}

    class Common:
        def authenticate(self, *a):
            calls["auth"] += 1
            return 7

    class Obj:
        deny = False

        def execute_kw(self, *a):
            if Obj.deny:
                raise xmlrpc.client.Fault(3, "odoo.exceptions.AccessDenied: Access Denied")
            return {"ok": True}

    def proxy(self, path, timeout=None):
        return Common() if path == "common" else Obj()

    monkeypatch.setattr(cl.BridgeClient, "_proxy", proxy)
    target = type("T", (), {"url": "http://odoo.test", "resolved_ips": []})()
    mk = lambda secret="k": cl.BridgeClient(target, cl.OdooCredentials("db", "admin", secret))  # noqa: E731
    mk().call_bridge("ping")
    mk().call_bridge("ping")
    assert calls["auth"] == 1  # second request reuses the uid
    mk("other").call_bridge("ping")
    assert calls["auth"] == 2  # a different secret is a different key
    Obj.deny = True
    import pytest

    with pytest.raises(cl.OdooRejectedError):
        mk().call_bridge("ping")
    Obj.deny = False
    mk().call_bridge("ping")
    assert calls["auth"] == 3  # access denied dropped the cached uid
    cl.clear_uid_cache()
