"""Transport to the Odoo bridge. Only the bridge facade is callable (no generic model access).

Odoo 18 and 19 both serve /xmlrpc/2 today; Odoo 19 deprecates it (removal in 22), so this
transport is the single place to swap for /json/2 later.
"""

import re
import xmlrpc.client
from dataclasses import dataclass
from typing import Any

from elblasy_api.security.pinned import PinnedTransport
from elblasy_api.security.ssrf import ValidatedUrl

READ_METHODS = frozenset(
    {
        "ping",
        "capabilities",
        "readiness_snapshot",
        "catalog_search",
        "catalog_get",
        "catalog_categories",
        "production_recipes",
        "insights_snapshot",
        "sorder_products",
        "sorder_quote",
        "sorder_get",
        "sorder_list",
        "production_get",
        "production_history",
        "catalog_barcodes_taken",
        "sales_state",
        "sales_quote",
        "sales_lookup",
        "sales_get_order",
        "sales_list_orders",
        "sales_get_session",
        "sales_summary",
        "sales_search",
        "suppliers_search",
        "supplier_statement",
        "stock_levels",
        "purchase_get",
        "purchase_list",
        "purchase_get_bill",
        "purchase_products",
        "stock_overview",
        "stock_suggestions",
        "stock_preview",
        "stock_has_history",
        "stock_resolve_barcodes",
        "expense_accounts",
        "expense_get",
        "expense_list",
        "expense_summary",
        "money_overview",
        "money_report",
        "expense_attachments",
        "expense_attachment_get",
        "money_ledger",
        "alerts_snapshot",
        "customers_search",
        "customer_statement",
        "invoice_get",
        "receivables_overview",
    }
)
# additive, idempotent, keyed operations only
WRITE_METHODS = frozenset(
    {
        "apply_step",
        "catalog_upsert_product",
        "catalog_set_bom",
        "catalog_update_product",
        "production_produce",
        "sales_open_session",
        "sales_checkout",
        "sales_refund",
        "sales_close_session",
        "suppliers_upsert",
        "purchase_create_order",
        "purchase_receive",
        "purchase_set_price",
        "purchase_return",
        "purchase_create_bill",
        "purchase_pay_bill",
        "stock_set_minimum",
        "stock_adjust",
        "expense_create",
        "expense_attach",
        "sorder_create",
        "sorder_deliver",
        "sorder_invoice",
        "sorder_cancel",
        "customers_upsert",
        "customers_set_credit_limit",
        "receivable_receive",
    }
)
ALLOWED_BRIDGE_METHODS = READ_METHODS | WRITE_METHODS


class OdooError(Exception):
    """Safe, user-presentable Odoo failure (never carries credentials)."""


class OdooUncertainError(OdooError):
    """The call may or may not have taken effect (timeout / connection lost). Never assume failure."""


class OdooRejectedError(OdooError):
    """Odoo definitively refused the call (validation/access error); nothing was applied."""


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
        self._ips = target.resolved_ips
        self._creds = creds
        self._timeout = timeout
        self._uid: int | None = None

    def _proxy(self, path: str, timeout: float | None = None) -> Any:
        https = self._base.startswith("https")
        t = timeout or self._timeout
        # Connect to the address that was validated, never to a fresh DNS answer (DNS rebinding).
        transport: xmlrpc.client.Transport
        if self._ips:
            transport = PinnedTransport(self._ips[0], https, t)
        else:  # only tests build a client without a validated address
            transport = xmlrpc.client.SafeTransport() if https else xmlrpc.client.Transport()
            transport.timeout = t  # type: ignore[attr-defined]
        url = f"{self._base}/xmlrpc/2/{path}"
        return xmlrpc.client.ServerProxy(url, transport=transport, allow_none=True)

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

    def call_bridge(self, method: str, *args: Any, timeout: float | None = None) -> dict[str, Any]:
        if method not in ALLOWED_BRIDGE_METHODS:
            raise OdooError(f"bridge method not allowlisted: {method}")
        uid = self._authenticate()
        write = method in WRITE_METHODS
        try:
            result = self._proxy("object", timeout).execute_kw(
                self._creds.db, uid, self._creds.secret, "elblasy.bridge", method, list(args)
            )
        except xmlrpc.client.Fault as exc:
            text = exc.faultString or ""
            if "elblasy.bridge" in text and "not found" in text.lower():
                raise OdooError("elblasy_one_bridge is not installed on this database") from exc
            reason = _fault_summary(text)
            raise OdooRejectedError(f"Odoo rejected the call: {reason}") from exc
        except (OSError, xmlrpc.client.ProtocolError) as exc:
            msg = f"Odoo connection problem: {type(exc).__name__}"
            if write:  # request may have been processed: caller must verify, not assume
                raise OdooUncertainError(msg) from exc
            raise OdooError(msg) from exc
        return dict(result)


_EXC_PREFIX = re.compile(r"^(?:[A-Za-z_][\w.]*\.)?[A-Za-z_]\w*(?:Error|Exception|Warning): ")


def _fault_summary(text: str) -> str:
    """Last line of an Odoo fault (the human message), bounded; tracebacks are never exposed.
    Only a leading exception-class prefix is removed, so messages containing ': ' stay whole."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    last = lines[-1] if lines else "unknown error"
    return _EXC_PREFIX.sub("", last, count=1)[:300]
