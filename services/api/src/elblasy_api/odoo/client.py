"""Transport to the Odoo bridge. Only the bridge facade is callable (no generic model access).

Odoo 18 and 19 both serve /xmlrpc/2 today; Odoo 19 deprecates it (removal in 22), so this
transport is the single place to swap for /json/2 later.
"""

import xmlrpc.client
from dataclasses import dataclass
from typing import Any

from elblasy_api.security.ssrf import ValidatedUrl

ALLOWED_BRIDGE_METHODS = frozenset({"ping", "capabilities", "readiness_snapshot"})


class OdooError(Exception):
    """Safe, user-presentable Odoo failure (never carries credentials)."""


class OdooAuthError(OdooError):
    pass


@dataclass(frozen=True)
class OdooCredentials:
    db: str
    login: str
    secret: str  # API key or password; decrypted from the vault just-in-time


class BridgeClient:
    def __init__(self, target: ValidatedUrl, creds: OdooCredentials, timeout: float = 15.0) -> None:
        self._base = target.url
        self._creds = creds
        self._timeout = timeout
        self._uid: int | None = None

    def _proxy(self, path: str) -> Any:
        transport: xmlrpc.client.Transport = (
            xmlrpc.client.SafeTransport()
            if self._base.startswith("https")
            else xmlrpc.client.Transport()
        )
        transport.timeout = self._timeout  # type: ignore[attr-defined]
        return xmlrpc.client.ServerProxy(
            f"{self._base}/xmlrpc/2/{path}", transport=transport, allow_none=True
        )

    def server_version(self) -> dict[str, Any]:
        try:
            return dict(self._proxy("common").version())
        except (OSError, xmlrpc.client.Error) as exc:
            raise OdooError(f"Odoo unreachable: {type(exc).__name__}") from exc

    def _authenticate(self) -> int:
        if self._uid is None:
            try:
                uid: Any = self._proxy("common").authenticate(
                    self._creds.db, self._creds.login, self._creds.secret, {}
                )
            except (OSError, xmlrpc.client.Error) as exc:
                raise OdooError(f"Odoo unreachable: {type(exc).__name__}") from exc
            if not uid:
                raise OdooAuthError("Odoo rejected the credentials")
            self._uid = int(uid)
        return self._uid

    def call_bridge(self, method: str) -> dict[str, Any]:
        if method not in ALLOWED_BRIDGE_METHODS:
            raise OdooError(f"bridge method not allowlisted: {method}")
        uid = self._authenticate()
        try:
            result = self._proxy("object").execute_kw(
                self._creds.db, uid, self._creds.secret, "elblasy.bridge", method, []
            )
        except xmlrpc.client.Fault as exc:
            if "elblasy.bridge" in exc.faultString and "not found" in exc.faultString.lower():
                raise OdooError("elblasy_one_bridge is not installed on this database") from exc
            raise OdooError("Odoo rejected the bridge call") from exc
        except OSError as exc:
            raise OdooError(f"Odoo unreachable: {type(exc).__name__}") from exc
        return dict(result)
