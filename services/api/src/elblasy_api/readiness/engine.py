"""Pure readiness evaluation: (capability manifest, bridge snapshot) -> findings.

No I/O and no mutation, so every rule is unit-testable. Rules never call a setting "wrong"
just because it differs from a template: differences are `valid_alternative` or
`review_required` unless they demonstrably break a workflow (`confirmed_issue`).
"""

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from elblasy_api.odoo.compat import assess

RULESET_VERSION = "1.0"


class Severity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class Classification(StrEnum):
    CONFIRMED_ISSUE = "confirmed_issue"
    MISSING_CONFIGURATION = "missing_configuration"
    VALID_ALTERNATIVE = "valid_alternative"
    REVIEW_REQUIRED = "review_required"
    UNABLE_TO_VERIFY = "unable_to_verify"


class Environment(StrEnum):
    NEW_INSTALLATION = "new_installation"
    EXISTING_CLEAN = "existing_clean"
    EXISTING_WITH_TRANSACTIONS = "existing_with_transactions"
    EXISTING_CUSTOMIZED = "existing_customized"
    INCOMPATIBLE = "incompatible"


@dataclass
class Finding:
    id: str
    severity: Severity
    subsystem: str  # core | accounting | inventory | pos
    classification: Classification
    description: str
    evidence: dict[str, Any]
    confidence: str  # high | medium | low
    recommended_action: str
    auto_remediation_safe: bool
    required_permission: str
    verification: str
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _unavailable(section: Any) -> bool:
    return isinstance(section, dict) and "unavailable" in section


def classify_environment(manifest: dict[str, Any], snap: dict[str, Any]) -> Environment:
    required = ("accounting", "sales", "inventory")
    caps = manifest.get("capabilities", {})
    if assess(manifest).status != "supported" or not all(caps.get(c) for c in required):
        return Environment.INCOMPATIBLE
    fp = snap.get("footprint", {})
    if _unavailable(fp):
        return Environment.INCOMPATIBLE
    if fp.get("non_standard_module_count", 0) > 0:
        return Environment.EXISTING_CUSTOMIZED
    activity = sum(
        fp.get(k, 0) for k in ("posted_moves", "sale_orders", "pos_orders", "done_stock_moves")
    )
    if activity > 0:
        return Environment.EXISTING_WITH_TRANSACTIONS
    return (
        Environment.NEW_INSTALLATION if fp.get("products", 0) <= 2 else Environment.EXISTING_CLEAN
    )


def evaluate(manifest: dict[str, Any], snap: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    add = out.append

    def F(  # noqa: N802
        id_: str,
        sev: Severity,
        sub: str,
        cls: Classification,
        desc: str,
        ev: dict[str, Any],
        action: str,
        *,
        conf: str = "high",
        safe: bool = False,
        perm: str = "config.manage",
        verify: str = "",
    ) -> None:
        add(Finding(id_, sev, sub, cls, desc, ev, conf, action, safe, perm, verify))

    # ---- core ----
    compat = assess(manifest)
    if compat.status != "supported":
        F("CORE-001", Severity.CRITICAL, "core", Classification.CONFIRMED_ISSUE,
          "This Odoo is not a verified target for Elblasy One.", {"reason": compat.reason},
          "Use a supported Odoo Community version or wait for verification.",
          verify="Re-run the scan after switching to a supported version.")  # fmt: skip
    caps = manifest.get("capabilities", {})
    for cap, label, sev in (("accounting", "Accounting", Severity.CRITICAL),
                            ("sales", "Sales", Severity.CRITICAL),
                            ("inventory", "Inventory", Severity.CRITICAL),
                            ("pos", "Point of Sale", Severity.WARNING),
                            ("purchase", "Purchasing", Severity.WARNING)):  # fmt: skip
        if not caps.get(cap):
            F(f"CORE-MOD-{cap.upper()}", sev, "core", Classification.MISSING_CONFIGURATION,
              f"{label} is not installed.", {"capability": cap, "available": False},
              f"Install the {label} app (installation is never done automatically).",
              perm="config.manage", verify=f"Capability '{cap}' becomes true in the manifest.")  # fmt: skip

    groups = snap.get("user_groups", {})
    if _unavailable(groups):
        F("CORE-USR-000", Severity.WARNING, "core", Classification.UNABLE_TO_VERIFY,
          "The connection user's permissions could not be read.", groups, "Check the service user.",
          conf="low", verify="Rerun scan.")  # fmt: skip
    else:
        missing = [
            k for k in ("account_manager", "stock_manager", "pos_manager") if groups.get(k) is False
        ]
        if missing:
            F("CORE-USR-001", Severity.WARNING, "core", Classification.REVIEW_REQUIRED,
              "The Odoo service user lacks manager rights in some apps, so some checks and "
              "operations will be limited.", {"missing_groups": missing},
              "Grant the service user the needed access in Odoo, or accept the limitation.",
              conf="medium", verify="Rerun scan; missing_groups becomes empty.")  # fmt: skip
    comp = snap.get("company", {})
    if not _unavailable(comp) and comp.get("multi_company"):
        F("CORE-CMP-001", Severity.INFO, "core", Classification.REVIEW_REQUIRED,
          "Multiple companies exist. Elblasy One works on one company per connection.",
          {"current_company": comp.get("name")}, "Confirm this connection points at the intended company.",
          conf="high", perm="connections.manage", verify="Company shown in connection details.")  # fmt: skip

    # ---- accounting ----
    acc = snap.get("accounting", {})
    if _unavailable(acc):
        F("ACC-000", Severity.WARNING, "accounting", Classification.UNABLE_TO_VERIFY,
          "Accounting configuration could not be read.", acc, "Grant read access or review in Odoo.",
          conf="low", verify="Rerun scan.")  # fmt: skip
    elif acc.get("installed"):
        if not acc.get("chart_template") or acc.get("account_count", 0) == 0:
            F("ACC-001", Severity.CRITICAL, "accounting", Classification.MISSING_CONFIGURATION,
              "No chart of accounts is loaded.", {"account_count": acc.get("account_count"),
              "chart_template": acc.get("chart_template")},
              "Load a chart of accounts for the company's country through the guided setup.",
              verify="Chart template set and accounts exist.")  # fmt: skip
        j = acc.get("journals", {})
        for t in ("sale", "purchase"):
            if j.get(t, 0) == 0:
                F(f"ACC-J-{t.upper()}", Severity.CRITICAL, "accounting", Classification.MISSING_CONFIGURATION,
                  f"No {t} journal exists.", {"journals": j}, f"Create a {t} journal.",
                  verify=f"A {t} journal exists.")  # fmt: skip
        if j.get("cash", 0) == 0:
            F("ACC-J-CASH", Severity.WARNING, "accounting", Classification.MISSING_CONFIGURATION,
              "No cash journal exists; cash sales and cash registers need one.", {"journals": j},
              "Create a cash journal (reviewed in the setup plan).", verify="A cash journal exists.")  # fmt: skip
        if j.get("bank", 0) == 0:
            F("ACC-J-BANK", Severity.INFO, "accounting", Classification.VALID_ALTERNATIVE,
              "No bank journal. Fine for a cash-only business.", {"journals": j},
              "Add a bank journal only if you accept bank or card payments.",
              verify="n/a")  # fmt: skip
        tax = acc.get("taxes", {})
        if not acc.get("default_sale_tax") and tax.get("sale", 0) > 0:
            F("ACC-TAX-001", Severity.INFO, "accounting", Classification.REVIEW_REQUIRED,
              "Sale taxes exist but no default sale tax is set. This is valid for tax-exempt "
              "businesses.", {"taxes": tax, "default_sale_tax": False},
              "Confirm whether sales should carry a default tax.", conf="medium",
              verify="Default sale tax set or exemption confirmed by the owner.")  # fmt: skip
        if tax.get("sale", 0) == 0 and tax.get("purchase", 0) == 0:
            F("ACC-TAX-002", Severity.WARNING, "accounting", Classification.REVIEW_REQUIRED,
              "No taxes are configured.", {"taxes": tax}, "Confirm the business is tax-exempt, or "
              "configure taxes with the accountant.", conf="medium", verify="Owner confirmation.")  # fmt: skip

    # ---- inventory ----
    inv = snap.get("inventory", {})
    if _unavailable(inv):
        F("INV-000", Severity.WARNING, "inventory", Classification.UNABLE_TO_VERIFY,
          "Inventory configuration could not be read.", inv, "Grant read access or review in Odoo.",
          conf="low", verify="Rerun scan.")  # fmt: skip
    elif inv.get("installed"):
        if not inv.get("warehouses"):
            F("INV-001", Severity.CRITICAL, "inventory", Classification.MISSING_CONFIGURATION,
              "No warehouse exists.", {}, "Create a warehouse in the setup plan.",
              verify="A warehouse exists.")  # fmt: skip
        val = inv.get("category_valuation", {})
        if len(val) > 1:
            F("INV-VAL-001", Severity.INFO, "inventory", Classification.REVIEW_REQUIRED,
              "Product categories use different cost/valuation methods.", {"category_valuation": val},
              "Confirm with the accountant that mixed valuation is intended.", conf="medium",
              verify="Owner/accountant confirmation.")  # fmt: skip
        elif val:
            F("INV-VAL-000", Severity.INFO, "inventory", Classification.VALID_ALTERNATIVE,
              "Inventory valuation method recorded (not judged against a template).",
              {"category_valuation": val}, "No action unless your accountant requires another method.",
              verify="n/a")  # fmt: skip
        steps = [w for w in inv.get("warehouses", []) if w.get("reception_steps") != "one_step"]
        if steps:
            F("INV-WH-001", Severity.INFO, "inventory", Classification.REVIEW_REQUIRED,
              "Some warehouses use multi-step receiving; the simple receiving screens assume one step.",
              {"warehouses": steps}, "Keep multi-step and use the full flow, or switch to one step.",
              conf="medium", verify="Owner decision.")  # fmt: skip
        if inv.get("products_tracked", 0) > 0 and not inv.get("feature_lots"):
            F("INV-TRK-001", Severity.WARNING, "inventory", Classification.CONFIRMED_ISSUE,
              "Products use lot/serial tracking but the lots feature is disabled.",
              {"products_tracked": inv.get("products_tracked")},
              "Review the tracked products and the lots setting.", conf="medium",
              verify="Lots feature enabled or products untracked.")  # fmt: skip
        if inv.get("negative_quants", 0) > 0:
            F("INV-NEG-001", Severity.WARNING, "inventory", Classification.CONFIRMED_ISSUE,
              "Some internal locations hold negative stock.", {"negative_quants": inv["negative_quants"]},
              "Investigate with a stock count; do not adjust blindly.", perm="inventory.adjust",
              verify="No negative quants remain after a reviewed count.")  # fmt: skip
        if inv.get("pending_pickings", 0) > 0:
            F("INV-PEND-001", Severity.INFO, "inventory", Classification.REVIEW_REQUIRED,
              "There are unfinished stock transfers.", {"pending_pickings": inv["pending_pickings"]},
              "Process or cancel them before opening-stock work.", perm="inventory.adjust",
              verify="Pending count is zero.")  # fmt: skip

    # ---- POS ----
    pos = snap.get("pos", {})
    if _unavailable(pos):
        F("POS-000", Severity.WARNING, "pos", Classification.UNABLE_TO_VERIFY,
          "POS configuration could not be read.", pos, "Grant read access.", conf="low",
          verify="Rerun scan.")  # fmt: skip
    elif pos.get("installed"):
        cfgs = pos.get("configs", [])
        if not cfgs:
            F("POS-001", Severity.WARNING, "pos", Classification.MISSING_CONFIGURATION,
              "No point-of-sale is configured.", {}, "Create a POS in the setup plan.",
              verify="A POS configuration exists.")  # fmt: skip
        for c in cfgs:
            ev = {"pos": c["name"], "payment_methods": c["payment_methods"]}
            if c["payment_methods"] == 0:
                F(f"POS-PM-{c['id']}", Severity.CRITICAL, "pos", Classification.CONFIRMED_ISSUE,
                  f"POS '{c['name']}' has no payment methods and cannot take payments.", ev,
                  "Attach payment methods.", verify="Payment method count > 0.")  # fmt: skip
            elif not c["has_cash_method"]:
                F(f"POS-CASH-{c['id']}", Severity.INFO, "pos", Classification.VALID_ALTERNATIVE,
                  f"POS '{c['name']}' has no cash method. Valid for card/bank-only shops.", ev,
                  "Add a cash method if you take cash.", verify="n/a")  # fmt: skip
            if not c["has_journal"]:
                F(f"POS-JRN-{c['id']}", Severity.WARNING, "pos", Classification.CONFIRMED_ISSUE,
                  f"POS '{c['name']}' has no journal.", ev, "Assign a journal.",
                  verify="Journal set.")  # fmt: skip
        if pos.get("open_sessions", 0) > 0:
            F("POS-SES-001", Severity.INFO, "pos", Classification.REVIEW_REQUIRED,
              "There are POS sessions that are not closed.", {"open_sessions": pos["open_sessions"]},
              "Close or reconcile them before changing POS settings.", perm="sales.create",
              verify="open_sessions is zero.")  # fmt: skip
    return out


def summarize(findings: list[Finding]) -> dict[str, Any]:
    by_sev: dict[str, int] = {}
    for f in findings:
        by_sev[f.severity.value] = by_sev.get(f.severity.value, 0) + 1
    ready = not any(
        f.severity == Severity.CRITICAL and f.classification != Classification.UNABLE_TO_VERIFY
        for f in findings
    )
    return {"by_severity": by_sev, "total": len(findings), "blocking_issues_absent": ready}
