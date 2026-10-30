"""Wholesale price lists with quantity breaks and a list per customer, applied by Odoo at the till and in orders."""

from tests.integration.test_purchasing_live import login
from tests.integration.test_sales_live import idem, open_register, product, shop  # noqa: F401
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401


def enable_pricelists(url, db):
    c = rpc(url, db)
    c(
        "res.config.settings",
        "execute",
        [c("res.config.settings", "create", {"group_product_pricelist": True})],
    )


def test_wholesale_list_quantity_break_and_customer_list(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    enable_pricelists(url, db)
    pid, p = product(client, cid, url, db, name="أرز", price=40, stock=100)
    tid = p["template_id"]
    base = f"/connections/{cid}"
    h = idem()
    pl = client.post(f"{base}/pricelists", json={"name": "جملة"}, headers=h)
    assert pl.status_code == 201, pl.text
    plid = pl.json()["pricelist"]["id"]
    assert (
        client.post(f"{base}/pricelists", json={"name": "جملة"}, headers=h).json()["replayed"]
        is True
    )
    assert (
        client.post(f"{base}/pricelists", json={"name": "جملة"}, headers=idem()).status_code == 422
    )  # same name

    for min_qty, price in ((0, 35), (10, 32)):  # wholesale price, cheaper from 10 pieces
        r = client.put(
            f"{base}/pricelists/{plid}/prices",
            json={"template_id": tid, "min_qty": min_qty, "price": price},
            headers=idem(),
        )
        assert r.status_code == 200, r.text
    rules = client.get(f"{base}/pricelists/{plid}").json()["pricelist"]["rules"]
    assert sorted((x["min_qty"], x["price"]) for x in rules) == [(0, 35), (10, 32)]

    cust = client.post(f"{base}/customers", json={"name": "تاجر"}, headers=idem()).json()[
        "customer"
    ]["id"]
    assert (
        client.put(
            f"{base}/customers/{cust}/pricelist", json={"pricelist_id": plid}, headers=idem()
        ).status_code
        == 200
    )
    open_register(client, cid, cfg)
    q = lambda qty, partner=None: client.post(  # noqa: E731
        f"{base}/sales/quote",
        json={
            "config_id": cfg,
            "lines": [{"product_id": pid, "qty": qty}],
            **({"partner_id": partner} if partner else {}),
        },
    ).json()["lines"][0]["price_unit"]
    assert (
        q(1) == 40 and q(1, cust) == 35 and q(12, cust) == 32
    )  # walk-in vs trader vs trader buying 12
    line = {"product_id": pid, "qty": 12}
    quote = client.post(
        f"{base}/sales/quote", json={"config_id": cfg, "lines": [line], "partner_id": cust}
    ).json()
    sale = client.post(
        f"{base}/sales/orders",
        json={
            "config_id": cfg,
            "lines": [line],
            "partner_id": cust,
            "expected_total": quote["total"],
            "payments": [{"payment_method_id": cash, "amount": quote["total"]}],
        },
        headers=idem(),
    )
    assert sale.status_code == 201, sale.text
    assert sale.json()["order"]["lines"][0]["price_unit"] == 32
    so = client.post(
        f"{base}/sales-orders",
        json={"partner_id": cust, "lines": [{"product_id": pid, "qty": 3}]},
        headers=idem(),
    )
    assert (
        so.status_code == 201 and so.json()["order"]["lines"][0]["price_unit"] == 35
    )  # orders follow the customer's list too

    # removing the customer's list brings the shelf price back; removing a price drops the rule
    assert (
        client.put(
            f"{base}/customers/{cust}/pricelist", json={"pricelist_id": None}, headers=idem()
        ).status_code
        == 200
    )
    assert q(1, cust) == 40
    assert (
        client.put(
            f"{base}/pricelists/{plid}/prices",
            json={"template_id": tid, "min_qty": 10, "price": None},
            headers=idem(),
        ).status_code
        == 200
    )
    assert [
        x["min_qty"] for x in client.get(f"{base}/pricelists/{plid}").json()["pricelist"]["rules"]
    ] == [0]
    cashier = login(client, cid, "cashier")
    assert (
        cashier.put(
            f"{base}/pricelists/{plid}/prices",
            json={"template_id": tid, "price": 1},
            headers=idem(),
        ).status_code
        == 403
    )
