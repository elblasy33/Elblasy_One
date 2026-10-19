"""Insights come from Odoo's own sales and stock."""

from tests.integration.test_sales_live import idem, on_hand, open_register, product, sell, shop  # noqa: F401
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401


def test_week_of_sales_best_sellers_slow_stock_and_roles(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    fast, _ = product(client, cid, url, db, name="شاي", price=10, stock=50)
    idle, _ = product(client, cid, url, db, name="بهارات", price=10, stock=8)
    open_register(client, cid, cfg)
    q, sale = sell(client, cid, cfg, cash, fast, qty=3, pay=100)
    assert sale.status_code == 201
    total = sale.json()["order"]["amount_total"]
    r = client.get(f"/connections/{cid}/sales/insights")
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["sales_by_day"]) == 7 and d["sales_by_day"][-1]["net"] == total
    assert d["top_products"][0]["name"] == "شاي" and d["top_products"][0]["qty"] == 3
    slow = {i["name"] for i in d["slow_moving"]["items"]}
    assert "بهارات" in slow and "شاي" not in slow
    assert client.get(f"/connections/{cid}/sales/insights", params={"days": 99}).status_code == 422
