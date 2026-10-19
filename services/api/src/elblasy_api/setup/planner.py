"""Setup plan generation (Stage 1-2: discovery -> plan). Pure and deterministic; no I/O.

Plans are *additive only*: they create or enable what is missing and never modify or delete
existing configuration. Differences in existing configuration are listed under `existing_notes`
for human review. Every step carries a stable managed key so a retry or re-plan finds what
Elblasy One already created instead of duplicating it."""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from elblasy_api.readiness.engine import Environment, classify_environment
from elblasy_api.setup.profile import BusinessProfile
from elblasy_api.setup.templates import (
    FEATURE_MODULES,
    TEMPLATE_SCHEMA_VERSION,
    Template,
    resolve_features,
    template_for,
    unsupported_combinations,
)

PLANNER_VERSION = "1.0"
EXECUTABLE_KINDS = frozenset(
    {"install_module", "enable_feature", "ensure_journal", "ensure_pos_payment_method",
     "ensure_pos_config"}
)  # fmt: skip
# Deliberately NOT executable: loading a chart of accounts is financial and irreversible; the
# plan lists it and the owner/accountant does it deliberately. Revisit once live-tested.


@dataclass
class Step:
    key: str  # stable managed reference (also the XML id suffix for created records)
    kind: str
    title: dict[str, str]
    params: dict[str, Any]
    status: str  # to_apply | satisfied | blocked
    required: bool
    depends_on: list[str] = field(default_factory=list)
    approval: list[str] = field(default_factory=lambda: ["owner"])
    permission: str = "config.manage"
    risk: str = "low"  # low | medium | high
    impact: str = ""
    recovery: str = ""
    blocked_reason: str | None = None
    executable: bool = True
    existing: dict[str, Any] = field(default_factory=dict)


MODULE_LABELS: dict[str, tuple[str, str]] = {
    "account": ("المحاسبة", "Accounting"), "sale_management": ("المبيعات", "Sales"),
    "purchase": ("المشتريات", "Purchasing"), "stock": ("المخزون", "Inventory"),
    "stock_account": ("تقييم المخزون", "Inventory valuation"),
    "point_of_sale": ("نقطة البيع", "Point of Sale"), "mrp": ("التصنيع", "Manufacturing"),
    "product_expiry": ("تواريخ الصلاحية", "Expiry dates"), "barcodes": ("الباركود", "Barcodes"),
}  # fmt: skip


def _t(ar: str, en: str) -> dict[str, str]:
    return {"ar": ar, "en": en}


def canonical_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def build_plan(
    profile: BusinessProfile,
    manifest: dict[str, Any],
    snapshot: dict[str, Any],
    template: Template | None = None,
) -> dict[str, Any]:
    tpl = template or template_for(profile)
    features = resolve_features(tpl, profile)
    env = classify_environment(manifest, snapshot)
    mods = snapshot.get("modules", {})
    acc = snapshot.get("accounting", {})
    pos = snapshot.get("pos", {})
    feat = snapshot.get("features", {})
    steps: list[Step] = []
    notes: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []

    unsupported = unsupported_combinations(profile, features)
    if env == Environment.INCOMPATIBLE:
        conflicts.append({"code": "incompatible_environment",
                          "reason": "This Odoo is not a verified target; no plan can be applied."})  # fmt: skip

    # --- modules ---
    needed = list(tpl.required_modules)
    for f in sorted(features):
        needed += [m for m in FEATURE_MODULES.get(f, ()) if m not in needed]
    for m in needed:
        state = (
            mods.get(m, "absent")
            if isinstance(mods, dict) and "unavailable" not in mods
            else "unknown"
        )
        s = Step(f"module_{m}", "install_module", _t(f"تفعيل: {MODULE_LABELS.get(m, (m, m))[0]}",
                                                         f"Enable: {MODULE_LABELS.get(m, (m, m))[1]}"),
                 {"module": m}, "satisfied" if state == "installed" else "to_apply", True,
                 risk="medium", impact="Adds the app's menus, models and data to this database.",
                 recovery="Apps can be uninstalled in Odoo, but data created by them may be lost; "
                          "take a database backup first.")  # fmt: skip
        if state in ("absent", "uninstallable", "unknown"):
            s.status, s.blocked_reason = (
                "blocked",
                f"Module '{m}' is not available on this Odoo ({state}).",
            )
        elif state not in ("installed", "uninstalled"):
            s.status, s.blocked_reason = "blocked", f"Module '{m}' is in state '{state}'."
        steps.append(s)

    mod_keys = {s.key for s in steps}

    # --- accounting basics ---
    if (
        isinstance(acc, dict)
        and acc.get("installed")
        and (not acc.get("chart_template") or acc.get("account_count", 0) == 0)
    ):
        fp = snapshot.get("footprint", {})
        posted = fp.get("posted_moves", 0) if isinstance(fp, dict) else 0
        s = Step("chart_of_accounts", "load_chart_of_accounts",
                 _t("تحميل دليل الحسابات", "Load chart of accounts"),
                 {"country": snapshot.get("company", {}).get("country")}, "to_apply", True,
                 approval=["owner", "accountant"], risk="high", executable=False,
                 impact="Creates the accounts, taxes and journals of the country's standard chart.",
                 recovery="Not reversible once entries are posted. Restore from backup if wrong.")  # fmt: skip
        if posted:
            s.status, s.blocked_reason = (
                "blocked",
                "Posted entries exist; a chart is never loaded over them.",
            )
        steps.append(s)
    elif isinstance(acc, dict) and acc.get("installed"):
        notes.append({"area": "accounting", "note": "Existing chart of accounts and taxes are kept "
                      "untouched; review them with your accountant."})  # fmt: skip

    # --- cash journal ---
    pay = set(profile.payment_methods)
    journals = acc.get("journals", {}) if isinstance(acc, dict) else {}
    if "cash" in pay:
        have = journals.get("cash", 0) > 0
        steps.append(Step("cash_journal", "ensure_journal",
                          _t("دفتر النقدية (الخزنة)", "Cash journal (cash register)"),
                          {"type": "cash", "name": "Cash"}, "satisfied" if have else "to_apply", True,
                          depends_on=["chart_of_accounts"] if any(s.key == "chart_of_accounts" for s in steps) else [],
                          impact="Adds one cash journal and its account.",
                          recovery="Archive the journal if it has no entries."))  # fmt: skip
    if pay - {"cash"}:
        have = journals.get("bank", 0) > 0
        steps.append(Step("bank_journal", "ensure_journal", _t("دفتر البنك", "Bank journal"),
                          {"type": "bank", "name": "Bank"}, "satisfied" if have else "to_apply", True,
                          impact="Adds one bank journal and its account.",
                          recovery="Archive the journal if it has no entries."))  # fmt: skip

    # --- POS ---
    if isinstance(pos, dict) and pos.get("installed") or "module_point_of_sale" in mod_keys:
        methods = pos.get("payment_methods", []) if isinstance(pos, dict) else []
        have_cash = any(m.get("is_cash_count") for m in methods)
        have_bank = any(not m.get("is_cash_count") for m in methods)
        pm_keys = []
        if "cash" in pay:
            pm_keys.append("pos_pm_cash")
            steps.append(Step("pos_pm_cash", "ensure_pos_payment_method", _t("طريقة دفع: نقدًا", "Payment method: Cash"),
                              {"kind": "cash"}, "satisfied" if have_cash else "to_apply", True,
                              depends_on=["cash_journal"], impact="Adds a cash payment method for the POS.",
                              recovery="Archive it if unused."))  # fmt: skip
        if pay - {"cash"}:
            pm_keys.append("pos_pm_bank")
            steps.append(Step("pos_pm_bank", "ensure_pos_payment_method",
                              _t("طريقة دفع: بطاقة/محفظة/تحويل", "Payment method: card/wallet/transfer"),
                              {"kind": "bank", "wanted": sorted(pay - {"cash"})},
                              "satisfied" if have_bank else "to_apply", True, depends_on=["bank_journal"],
                              impact="Adds a non-cash payment method (no terminal integration).",
                              recovery="Archive it if unused."))  # fmt: skip
        have_cfg = bool(pos.get("configs")) if isinstance(pos, dict) else False
        steps.append(Step("pos_main", "ensure_pos_config", _t("نقطة البيع الرئيسية", "Main point of sale"),
                          {"name": "Main", "payment_method_keys": pm_keys},
                          "satisfied" if have_cfg else "to_apply", True, depends_on=pm_keys,
                          impact="Creates one POS and attaches the payment methods above.",
                          recovery="Archive the POS if it has no sessions."))  # fmt: skip
        if have_cfg:
            notes.append({"area": "pos", "note": "Existing POS configuration is kept as is; "
                          "payment-method gaps are reported by the readiness scan."})  # fmt: skip

    # --- features that are Odoo settings ---
    for fkey, label in (("variants", _t("المقاسات والألوان", "Sizes & colours (variants)")),
                        ("uom", _t("وحدات القياس المتعددة", "Multiple units of measure")),
                        ("lots", _t("تتبع الدفعات/الصلاحية", "Lots / expiry tracking"))):  # fmt: skip
        if fkey in features:
            on = feat.get(fkey) if isinstance(feat, dict) else None
            deps = [
                f"module_{m}"
                for m in FEATURE_MODULES.get("expiry", ())
                if fkey == "lots" and f"module_{m}" in mod_keys
            ]
            steps.append(Step(f"feature_{fkey}", "enable_feature", label, {"feature": fkey},
                              "satisfied" if on else "to_apply", True, depends_on=deps,
                              impact="Turns on an Odoo setting; existing products are unaffected.",
                              recovery="The setting can be turned off in Odoo if no data depends on it."))  # fmt: skip

    # --- stock must follow every sale (company-wide POS setting; changes only with approval) ---
    if (
        isinstance(feat, dict)
        and feat.get("pos_stock_realtime") is not None
        and ((isinstance(pos, dict) and pos.get("installed")) or "module_point_of_sale" in mod_keys)
    ):
        steps.append(Step("feature_realtime_stock", "enable_feature",
                          _t("تحديث المخزون عند كل بيع", "Update stock at every sale"),
                          {"feature": "realtime_stock"},
                          "satisfied" if feat.get("pos_stock_realtime") else "to_apply", True, risk="medium",
                          impact="Stock is deducted when each sale is made instead of when the session closes.",
                          recovery="The setting can be switched back in Odoo; stock already deducted is not reversed."))  # fmt: skip

    # --- weighing scale (native Odoo weight-barcode rule) ---
    if "weighing" in features:
        bc = snapshot.get("barcode", {})
        patterns = bc.get("weight_rule_patterns", []) if isinstance(bc, dict) else []
        if patterns:
            notes.append({"area": "barcode", "note": f"Weighing-scale barcodes are supported natively "
                          f"(rule {patterns[0]}). Elblasy One will generate scale codes for products."})  # fmt: skip
        else:
            conflicts.append({"code": "no_weight_barcode_rule", "reason":
                              "No weight barcode rule found; the company uses a custom nomenclature. "
                              "Review manually before using a scale."})  # fmt: skip

    # --- bring dependency resolution + summary together ---
    keys = {s.key: s for s in steps}
    for s in steps:
        s.depends_on = [d for d in s.depends_on if d in keys]
        for d in s.depends_on:
            if keys[d].status == "blocked" and s.status != "satisfied":
                s.status, s.blocked_reason = "blocked", f"Depends on blocked step '{d}'."
    plan_steps = [asdict(s) for s in steps]
    approvals = sorted({r for s in steps if s.status == "to_apply" for r in s.approval})
    summary = {
        "to_apply": sum(s.status == "to_apply" for s in steps),
        "satisfied": sum(s.status == "satisfied" for s in steps),
        "blocked": sum(s.status == "blocked" for s in steps),
    }
    body = {
        "schema_version": TEMPLATE_SCHEMA_VERSION,
        "planner_version": PLANNER_VERSION,
        "template": {"id": tpl.id, "version": tpl.version},
        "profile": profile.model_dump(),
        "features": sorted(features),
        "environment": env.value,
        "mode": "additive_only",
        "steps": plan_steps,
        "existing_notes": notes,
        "conflicts": conflicts,
        "unsupported": unsupported,
        "required_approvals": approvals,
        "verification_checks": list(tpl.verification_checks),
        "summary": summary,
        "applicable": not conflicts and not unsupported and summary["blocked"] == 0,
    }
    body["plan_hash"] = canonical_hash(
        {k: body[k] for k in ("template", "profile", "steps", "mode")}
    )
    body["snapshot_hash"] = canonical_hash(
        {k: snapshot.get(k) for k in ("modules", "accounting", "pos", "features", "inventory")}
    )
    return body
