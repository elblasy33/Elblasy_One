"""Manual wholesale / on-credit sales orders in Odoo's Sales app: price per line, delivery, invoice, collection."""

from tests.integration.test_purchasing_live import login
from tests.integration.test_sales_live import idem, on_hand, product, shop  # noqa: F401
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401


def S(cid, path=""):
    return f"/connections/{cid}/sales-orders{path}"


def customer(client, cid, name="تاجر الجملة", limit=None):
    body = {"name": name, **({"credit_limit": limit} if limit is not None else {})}
    r = client.post(f"/connections/{cid}/customers", json=body, headers=idem())
    assert r.status_code == 201, r.text
    return r.json()["customer"]["id"]


def test_wholesale_order_price_per_line_deliver_invoice_collect(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db, name="سكر", price=100, stock=20)
    cust = customer(client, cid, limit=1000)
    lines = [
        {"product_id": pid, "qty": 5, "price_unit": 60}
    ]  # wholesale price, not the shelf price
    q = client.post(S(cid, "/quote"), json={"partner_id": cust, "lines": lines}).json()
    assert q["untaxed"] == 300 and q["total"] > 300

    h = idem()
    r = client.post(S(cid), json={"partner_id": cust, "lines": lines}, headers=h)
    assert r.status_code == 201, r.text
    o = r.json()["order"]
    assert o["state"] == "sale" and o["lines"][0]["price_unit"] == 60 and o["amount_untaxed"] == 300
    assert o["delivery_status"] == "waiting" and o["invoices"] == []
    assert (
        client.post(S(cid), json={"partner_id": cust, "lines": lines}, headers=h).json()["replayed"]
        is True
    )
    assert on_hand(url, db, pid) == 20  # nothing left the shelf yet

    d = client.post(S(cid, f"/{o['id']}/deliver"), headers=idem())
    assert d.status_code == 201, d.text
    assert d.json()["order"]["delivery_status"] == "done" and on_hand(url, db, pid) == 15

    inv = client.post(S(cid, f"/{o['id']}/invoice"), json={"due_days": 30}, headers=idem())
    assert inv.status_code == 201, inv.text
    b = inv.json()["invoice"]
    assert b["state"] == "posted" and b["amount_residual"] == b["amount_total"] == o["amount_total"]
    moves = rpc(url, db)(
        "account.move", "read", [b["id"]], fields=["invoice_date", "invoice_date_due"]
    )[0]
    assert (  # the credit period is real: due 30 days after the invoice date
        __import__("datetime").date.fromisoformat(moves["invoice_date_due"])
        - __import__("datetime").date.fromisoformat(moves["invoice_date"])
    ).days == 30
    st = client.get(f"/connections/{cid}/customers/{cust}/statement").json()
    assert st["customer"]["receivable"] == o["amount_total"]
    again = client.post(S(cid, f"/{o['id']}/invoice"), json={}, headers=idem())
    assert again.status_code == 422  # nothing left to invoice

    pay = client.post(
        f"/connections/{cid}/customers/invoices/{b['id']}/receive",
        json={"amount": b["amount_total"], "journal_type": "cash"},
        headers=idem(),
    )
    assert pay.status_code == 201, pay.text
    assert client.get(S(cid, f"/{o['id']}")).json()["order"]["invoices"][0]["payment_state"] in (
        "paid",
        "in_payment",
    )
    assert (
        client.get(f"/connections/{cid}/customers/{cust}/statement").json()["customer"][
            "receivable"
        ]
        == 0
    )
    assert [x["id"] for x in client.get(S(cid)).json()["items"]] == [o["id"]]


def test_credit_limit_stock_shortage_cancel_and_roles(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db, name="أرز", price=100, stock=10)
    cust = customer(client, cid, name="عميل محدود", limit=200)
    big = {
        "partner_id": cust,
        "lines": [{"product_id": pid, "qty": 5, "price_unit": 100}],
    }  # 500 + tax > 200
    over = client.post(S(cid), json={**big, "invoice_now": True}, headers=idem())
    assert over.status_code == 409 and over.json()["error"]["code"] == "credit_limit_exceeded", (
        over.text
    )
    assert (
        rpc(url, db)("sale.order", "search_count", [["partner_id", "=", cust]]) == 0
    )  # nothing half-created
    ok = client.post(
        S(cid),
        json={**big, "invoice_now": True, "override_credit_limit": True, "due_days": 14},
        headers=idem(),
    )
    assert ok.status_code == 201, ok.text
    assert (
        ok.json()["order"]["invoices"][0]["state"] == "posted"
    )  # ordered quantities billed, stock still on the shelf
    assert on_hand(url, db, pid) == 10

    short = client.post(
        S(cid),
        json={"partner_id": cust, "lines": [{"product_id": pid, "qty": 50}], "deliver_now": True},
        headers=idem(),
    )
    assert short.status_code == 409 and short.json()["error"]["code"] == "stock_short", short.text
    count = rpc(url, db)("sale.order", "search_count", [["partner_id", "=", cust]])
    assert count == 1

    plain = client.post(
        S(cid), json={"partner_id": cust, "lines": [{"product_id": pid, "qty": 1}]}, headers=idem()
    ).json()["order"]
    c1 = client.post(S(cid, f"/{plain['id']}/cancel"), headers=idem())
    assert c1.status_code == 201 and c1.json()["order"]["state"] == "cancel"
    started = ok.json()["order"]
    bad = client.post(S(cid, f"/{started['id']}/cancel"), headers=idem())
    assert (
        bad.status_code == 422 and "already delivered or invoiced" in bad.json()["error"]["message"]
    )

    no_customer = client.post(
        S(cid), json={"partner_id": 99999, "lines": [{"product_id": pid, "qty": 1}]}, headers=idem()
    )
    assert no_customer.status_code == 422
    cashier = login(client, cid, "cashier")
    assert cashier.get(S(cid)).status_code == 403
    assert cashier.post(S(cid), json=big, headers=idem()).status_code == 403
    assert any(a["action"] == "salesorder.create" for a in client.get("/audit").json()["items"])
