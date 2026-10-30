"""Answer-built profiles (no business type) executed on real Odoo CE 18/19."""

import uuid

from tests.conftest import make_owner
from tests.integration.test_connections_api import body
from tests.integration.test_sales_live import idem
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401


def run_plan(client, cid, answers):
    plan = client.post(f"/connections/{cid}/setup/plans", json={"answers": answers})
    assert plan.status_code == 201, plan.text
    p = plan.json()
    assert p["plan"]["template"]["id"] == "business_profile"
    if p["plan"]["summary"]["to_apply"]:
        assert client.post(f"/connections/{cid}/setup/plans/{p['id']}/approve").status_code == 200
        assert client.post(f"/connections/{cid}/setup/plans/{p['id']}/execute").status_code == 202
    done = client.get(f"/connections/{cid}/setup/plans/{p['id']}").json()
    assert done["status"] in ("completed", "draft"), done.get("execution")
    return p, done


def test_tax_included_prices_and_wholesale_price_lists(client, fresh):  # noqa: F811
    _, url, db = fresh
    make_owner(client, f"{uuid.uuid4().hex[:8]}@example.com")
    cid = client.post("/connections", json=body(url, db)).json()["id"]
    answers = {
        "sells": ["goods"],
        "channels": ["counter", "orders"],
        "wholesale_prices": True,
        "vat": "included",
        "payment_methods": ["cash"],
    }
    p, done = run_plan(client, cid, answers)
    assert done["status"] == "completed", done.get("execution")
    feats = set(p["plan"]["features"])
    assert {"pricelists", "tax_included_prices", "sales_orders"} <= feats
    c = rpc(url, db)
    company = c("res.company", "search_read", [], fields=["account_price_include"], limit=1)[0]
    assert company["account_price_include"] == "tax_included"
    # "completed" means every step, the price-list setting included, was re-read from Odoo as applied
    assert {st["key"] for st in p["plan"]["steps"]} >= {
        "feature_pricelists",
        "feature_tax_included",
    }
    # a product priced 100 now sells for 100 at the till: tax is inside the price
    st = client.get(f"/connections/{cid}/sales/state").json()
    cfg = st["configs"][0]["id"]
    made = client.post(
        f"/connections/{cid}/catalog/products", json={"name": "شامل", "price": 100}, headers=idem()
    ).json()
    q = client.post(
        f"/connections/{cid}/sales/quote",
        json={"config_id": cfg, "lines": [{"product_id": made["variant_ids"][0], "qty": 1}]},
    ).json()
    assert abs(q["total"] - 100) < 0.01 and q["tax"] > 0, q


def test_not_registered_shop_creates_products_without_tax_and_can_sell_services(client, fresh):  # noqa: F811
    _, url, db = fresh
    make_owner(client, f"{uuid.uuid4().hex[:8]}@example.com")
    cid = client.post("/connections", json=body(url, db)).json()["id"]
    p, done = run_plan(
        client,
        cid,
        {"sells": ["goods", "services"], "vat": "not_registered", "payment_methods": ["cash"]},
    )
    assert done["status"] == "completed", done.get("execution")
    assert {"no_sales_tax", "services"} <= set(p["plan"]["features"])
    goods = client.post(
        f"/connections/{cid}/catalog/products", json={"name": "علبة", "price": 50}, headers=idem()
    ).json()
    svc = client.post(
        f"/connections/{cid}/catalog/products",
        json={"name": "تركيب", "price": 80, "kind": "service"},
        headers=idem(),
    )
    assert svc.status_code == 201, svc.text
    c = rpc(url, db)
    rows = c(
        "product.template",
        "read",
        [goods["template_id"], svc.json()["template_id"]],
        fields=["taxes_id", "type"],
    )
    assert rows[0]["taxes_id"] == [] and rows[1]["taxes_id"] == [] and rows[1]["type"] == "service"
    listed = {x["name"] for x in client.get(f"/connections/{cid}/catalog/products").json()["items"]}
    assert {"علبة", "تركيب"} <= listed
    st = client.get(f"/connections/{cid}/sales/state").json()
    cfg = st["configs"][0]["id"]
    q = client.post(
        f"/connections/{cid}/sales/quote",
        json={"config_id": cfg, "lines": [{"product_id": svc.json()["variant_ids"][0], "qty": 1}]},
    ).json()
    assert q["total"] == 80 and q["tax"] == 0
