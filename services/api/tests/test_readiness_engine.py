import copy

from elblasy_api.readiness.engine import (
    Classification as C,
)
from elblasy_api.readiness.engine import (
    Environment,
    classify_environment,
    evaluate,
    summarize,
)

MANIFEST = {
    "contract_version": 1,
    "odoo": {"series": "19.0", "edition": "community"},
    "capabilities": {
        "accounting": True,
        "sales": True,
        "inventory": True,
        "pos": True,
        "purchase": True,
    },
}
SNAP = {
    "company": {"name": "Shop", "multi_company": False},
    "user_groups": {"account_manager": True, "stock_manager": True, "pos_manager": True},
    "accounting": {
        "installed": True, "chart_template": "eg", "account_count": 100,
        "journals": {"sale": 1, "purchase": 1, "cash": 1, "bank": 1}, "taxes": {"sale": 2, "purchase": 2},
        "default_sale_tax": True, "default_purchase_tax": True,
    },
    "inventory": {
        "installed": True, "warehouses": [{"code": "WH", "reception_steps": "one_step"}],
        "category_valuation": {"standard/manual_periodic": 1}, "products_tracked": 0, "feature_lots": False,
        "negative_quants": 0, "pending_pickings": 0,
    },
    "pos": {
        "installed": True,
        "configs": [{"id": 1, "name": "Main", "payment_methods": 2, "has_cash_method": True, "has_journal": True}],
        "open_sessions": 0,
    },
    "footprint": {"posted_moves": 0, "sale_orders": 0, "pos_orders": 0, "done_stock_moves": 0, "products": 0,
                  "non_standard_module_count": 0},
}  # fmt: skip


def ids(fs):
    return {f.id for f in fs}


def snap(**over):
    s = copy.deepcopy(SNAP)
    for path, v in over.items():
        a, _, b = path.partition(".")
        s[a][b] = v
    return s


def test_healthy_setup_has_no_blockers():
    fs = evaluate(MANIFEST, SNAP)
    assert summarize(fs)["blocking_issues_absent"]
    assert not {f.id for f in fs if f.severity == "critical"}


def test_every_finding_has_required_fields():
    fs = evaluate(
        {**MANIFEST, "capabilities": {}}, snap(**{"accounting.account_count": 0, "pos.configs": []})
    )
    assert fs
    for f in fs:
        d = f.to_dict()
        for k in ("id", "severity", "subsystem", "classification", "description", "evidence",
                  "confidence", "recommended_action", "auto_remediation_safe", "required_permission",
                  "verification"):  # fmt: skip
            assert k in d and d[k] not in (None, "") or k in ("evidence", "auto_remediation_safe")


def test_missing_chart_and_warehouse_are_missing_configuration():
    fs = evaluate(MANIFEST, snap(**{"accounting.account_count": 0, "accounting.chart_template": None,
                                    "inventory.warehouses": []}))  # fmt: skip
    by = {f.id: f for f in fs}
    assert by["ACC-001"].classification == C.MISSING_CONFIGURATION
    assert by["INV-001"].classification == C.MISSING_CONFIGURATION
    assert not summarize(fs)["blocking_issues_absent"]


def test_differences_from_template_are_not_called_errors():
    fs = evaluate(MANIFEST, snap(**{
        "accounting.journals": {"sale": 1, "purchase": 1, "cash": 1, "bank": 0},
        "accounting.default_sale_tax": False,
        "inventory.category_valuation": {"fifo/real_time": 1, "standard/manual_periodic": 2},
    }))  # fmt: skip
    by = {f.id: f for f in fs}
    assert by["ACC-J-BANK"].classification == C.VALID_ALTERNATIVE
    assert by["ACC-TAX-001"].classification == C.REVIEW_REQUIRED
    assert by["INV-VAL-001"].classification == C.REVIEW_REQUIRED
    assert not any(f.classification == C.CONFIRMED_ISSUE for f in fs)


def test_pos_without_payment_methods_is_confirmed_issue():
    cfg = {
        "id": 7,
        "name": "P",
        "payment_methods": 0,
        "has_cash_method": False,
        "has_journal": True,
    }
    by = {f.id: f for f in evaluate(MANIFEST, snap(**{"pos.configs": [cfg]}))}
    assert by["POS-PM-7"].classification == C.CONFIRMED_ISSUE


def test_unreadable_section_is_unable_to_verify_not_guessed():
    fs = evaluate(MANIFEST, snap(**{}) | {"accounting": {"unavailable": "AccessError"}})
    f = next(x for x in fs if x.id == "ACC-000")
    assert f.classification == C.UNABLE_TO_VERIFY and f.confidence == "low"
    assert summarize(fs)["blocking_issues_absent"]  # unknown is not reported as broken


def test_nothing_is_auto_remediable_yet():
    assert not any(
        f.auto_remediation_safe for f in evaluate(MANIFEST, snap(**{"accounting.account_count": 0}))
    )


def test_unsupported_version_blocks():
    m = {**MANIFEST, "odoo": {"series": "16.0", "edition": "community"}}
    assert "CORE-001" in ids(evaluate(m, SNAP))


def test_environment_classification():
    f = lambda **kw: snap(**{"footprint." + k: v for k, v in kw.items()})  # noqa: E731
    assert classify_environment(MANIFEST, f()) == Environment.NEW_INSTALLATION
    assert classify_environment(MANIFEST, f(products=40)) == Environment.EXISTING_CLEAN
    assert (
        classify_environment(MANIFEST, f(posted_moves=3)) == Environment.EXISTING_WITH_TRANSACTIONS
    )
    assert (
        classify_environment(MANIFEST, f(non_standard_module_count=2, posted_moves=3))
        == Environment.EXISTING_CUSTOMIZED
    )
    assert classify_environment({**MANIFEST, "capabilities": {}}, f()) == Environment.INCOMPATIBLE
