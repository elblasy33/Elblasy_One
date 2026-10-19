import copy

from elblasy_api.setup.planner import EXECUTABLE_KINDS, build_plan
from elblasy_api.setup.profile import BusinessProfile, build_profile, visible_questions
from tests.test_readiness_engine import MANIFEST, SNAP

MODS_ALL = {
    m: "installed"
    for m in (
        "account",
        "sale_management",
        "purchase",
        "stock",
        "stock_account",
        "point_of_sale",
        "barcodes",
    )
}


def snap(**over):
    s = copy.deepcopy(SNAP)
    s.update({"modules": {**MODS_ALL, "mrp": "uninstalled", "product_expiry": "uninstalled"},
              "features": {"variants": False, "uom": False, "lots": False},
              "barcode": {"installed": True, "weight_rule_patterns": ["21.....{NNDDD}"]}})  # fmt: skip
    s.update(over)
    return s


def steps(plan):
    return {s["key"]: s for s in plan["steps"]}


def test_questionnaire_is_conditional():
    ids = lambda a: {q.id for q in visible_questions(a)}  # noqa: E731
    assert "uses_weighing_scale" in ids({"vertical": "grocery"})
    assert "uses_weighing_scale" not in ids({"vertical": "shoes"})
    p = build_profile({"vertical": "shoes", "uses_weighing_scale": True})  # hidden answer ignored
    assert p.uses_weighing_scale is False


def test_grocery_with_manufacturing_scale_expiry_plans_additions_only():
    p = BusinessProfile(vertical="grocery", makes_own_products=True, uses_weighing_scale=True,
                        tracks_expiry=True, payment_methods=["cash", "card"])  # fmt: skip
    sn = snap()
    sn["accounting"] = {**sn["accounting"], "journals": {**sn["accounting"]["journals"], "bank": 0}}
    plan = build_plan(p, MANIFEST, sn)
    st = steps(plan)
    assert (
        st["module_mrp"]["status"] == "to_apply"
        and st["module_product_expiry"]["status"] == "to_apply"
    )
    assert st["module_stock"]["status"] == "satisfied"
    assert st["feature_lots"]["depends_on"] == ["module_product_expiry"]
    assert (
        st["bank_journal"]["status"] == "to_apply" and st["cash_journal"]["status"] == "satisfied"
    )
    assert plan["mode"] == "additive_only" and plan["applicable"]
    assert all(s["kind"] in EXECUTABLE_KINDS for s in plan["steps"])
    assert plan["required_approvals"] == ["owner"]
    assert any("Weighing-scale" in n["note"] for n in plan["existing_notes"])


def test_shoes_get_variants_by_default_not_scale():
    plan = build_plan(BusinessProfile(vertical="shoes"), MANIFEST, snap())
    st = steps(plan)
    assert st["feature_variants"]["status"] == "to_apply"
    assert plan["template"]["id"] == "shoes_starter" and "module_mrp" not in st


def test_plan_is_deterministic_and_hash_changes_with_input():
    p = BusinessProfile(vertical="clothing")
    a, b = build_plan(p, MANIFEST, snap()), build_plan(p, MANIFEST, snap())
    assert a["plan_hash"] == b["plan_hash"]
    c = build_plan(
        BusinessProfile(vertical="clothing", sells_on_credit=True, makes_own_products=True),
        MANIFEST,
        snap(),
    )
    assert c["plan_hash"] != a["plan_hash"]


def test_unavailable_module_blocks_and_propagates():
    s = snap()
    s["modules"]["mrp"] = "absent"
    plan = build_plan(BusinessProfile(vertical="grocery", makes_own_products=True), MANIFEST, s)
    assert steps(plan)["module_mrp"]["status"] == "blocked" and not plan["applicable"]


def test_chart_never_loaded_over_posted_entries():
    s = snap()
    s["accounting"] = {**s["accounting"], "chart_template": None, "account_count": 0}
    s["footprint"] = {**s["footprint"], "posted_moves": 5}
    plan = build_plan(BusinessProfile(vertical="general"), MANIFEST, s)
    c = steps(plan)["chart_of_accounts"]
    assert c["status"] == "blocked" and c["approval"] == ["owner", "accountant"]
    s["footprint"]["posted_moves"] = 0
    plan = build_plan(BusinessProfile(vertical="general"), MANIFEST, s)
    assert steps(plan)["chart_of_accounts"]["status"] == "to_apply"
    assert plan["required_approvals"] == ["accountant", "owner"]


def test_existing_config_is_kept_not_modified():
    plan = build_plan(BusinessProfile(vertical="general"), MANIFEST, snap())
    assert plan["summary"]["to_apply"] == 0 or all(
        s["status"] != "to_apply" or s["kind"] != "load_chart_of_accounts" for s in plan["steps"]
    )
    assert any(n["area"] == "accounting" for n in plan["existing_notes"])


def test_unsupported_combinations_and_incompatible_env():
    plan = build_plan(BusinessProfile(vertical="general", branches=3), MANIFEST, snap())
    assert not plan["applicable"] and plan["unsupported"][0]["code"] == "multi_branch"
    bad = build_plan(BusinessProfile(vertical="general"), {**MANIFEST, "capabilities": {}}, snap())
    assert bad["environment"] == "incompatible" and not bad["applicable"]


def test_custom_nomenclature_without_weight_rule_is_a_conflict():
    s = snap(barcode={"installed": True, "weight_rule_patterns": []})
    plan = build_plan(BusinessProfile(vertical="grocery", uses_weighing_scale=True), MANIFEST, s)
    assert plan["conflicts"][0]["code"] == "no_weight_barcode_rule"


def test_realtime_stock_step_appears_only_when_known_and_is_satisfied_once_on():
    off = snap()
    off["features"]["pos_stock_realtime"] = False
    on = snap()
    on["features"]["pos_stock_realtime"] = True
    p = BusinessProfile(vertical="general")
    assert steps(build_plan(p, MANIFEST, off))["feature_realtime_stock"]["status"] == "to_apply"
    assert steps(build_plan(p, MANIFEST, on))["feature_realtime_stock"]["status"] == "satisfied"
    assert "feature_realtime_stock" not in steps(
        build_plan(p, MANIFEST, snap())
    )  # unknown -> not guessed


def test_credit_sales_plan_creates_the_method_and_attaches_it_to_an_existing_pos():
    s = snap()
    s["pos"]["payment_methods"] = [
        {"name": "Cash", "type": "cash", "is_cash_count": True, "is_credit": False}
    ]
    s["pos"]["configs"] = [
        {
            "id": 1,
            "name": "Main",
            "payment_methods": 1,
            "has_cash_method": True,
            "has_credit_method": False,
            "has_journal": True,
        }
    ]
    plan = build_plan(BusinessProfile(vertical="general", sells_on_credit=True), MANIFEST, s)
    st = steps(plan)
    assert st["pos_pm_credit"]["status"] == "to_apply" and st["pos_pm_credit"]["params"] == {
        "kind": "credit"
    }
    assert st["pos_attach_credit"]["status"] == "to_apply" and st["pos_attach_credit"][
        "depends_on"
    ] == ["pos_pm_credit"]
    assert "pos_pm_bank" not in st  # a credit method is not a bank method
    s["pos"]["payment_methods"].append(
        {"name": "Customer account", "type": "pay_later", "is_cash_count": False, "is_credit": True}
    )
    s["pos"]["configs"][0]["has_credit_method"] = True
    done = steps(build_plan(BusinessProfile(vertical="general", sells_on_credit=True), MANIFEST, s))
    assert (
        done["pos_pm_credit"]["status"] == "satisfied"
        and done["pos_attach_credit"]["status"] == "satisfied"
    )
    off = steps(build_plan(BusinessProfile(vertical="general"), MANIFEST, snap()))
    assert "pos_pm_credit" not in off  # a shop that does not sell on credit is never offered it
