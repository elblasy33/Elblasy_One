"""Alerts that come from Odoo itself (overdue supplier bills, low stock)."""

from tests.integration.test_money_live import category, expense, login  # noqa: F401
from tests.integration.test_sales_live import idem, product, shop  # noqa: F401
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401


def keys(c):
    return {a["key"] for a in c.get("/alerts").json()["items"]}


def test_overdue_bills_and_low_stock_become_alerts_for_the_right_people(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    cat = category(client, cid)
    bill = expense(client, cid, cat, 400, description="قديم")
    assert bill.status_code == 201
    bill_id = bill.json()["expense"]["id"]
    assert "overdue_supplier_bills" not in keys(client)  # due today, not overdue yet
    # Odoo gives a bill without a payment term a due date of today; make this one genuinely past due
    rpc(url, db)("account.move", "write", [bill_id], {"invoice_date_due": "2020-01-15"})
    pid, _ = product(client, cid, url, db, name="سكر", stock=2)
    minimum = client.put(
        f"/connections/{cid}/stock/products/{pid}/minimum", json={"min_qty": 10}, headers=idem()
    )
    assert minimum.status_code == 200
    body = client.get("/alerts").json()
    items = {a["key"]: a for a in body["items"]}
    assert items["overdue_supplier_bills"]["count"] == 1
    assert items["overdue_supplier_bills"]["detail"]["amount"] == 400
    assert items["low_stock"]["count"] == 1 and items["low_stock"]["link"].startswith(
        "/inventory/stock"
    )
    assert body["odoo_reachable"] is True
    clerk, acc = login(client, cid, "inventory_operator"), login(client, cid, "accountant")
    assert "low_stock" in keys(clerk) and "overdue_supplier_bills" not in keys(
        clerk
    )  # finance only
    assert "overdue_supplier_bills" in keys(acc) and "low_stock" not in keys(
        acc
    )  # accountants do not adjust stock
