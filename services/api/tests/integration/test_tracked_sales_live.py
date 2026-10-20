"""Selling lot-tracked (first expiry first, never expired) and serial-tracked goods at the till."""

from tests.integration.test_purchasing_live import P, order, supplier
from tests.integration.test_sales_live import idem, on_hand, open_register, sell, shop  # noqa: F401
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401


def enable_lots(url, db):
    c = rpc(url, db)
    c(
        "res.config.settings",
        "execute",
        [c("res.config.settings", "create", {"group_stock_production_lot": True})],
    )


def new_product(client, cid, tracking, name):
    r = client.post(
        f"/connections/{cid}/catalog/products",
        json={"name": name, "price": 20, "tracking": tracking},
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    return r.json()["variant_ids"][0]


def receive(client, cid, pid, qty, **line):
    po = order(client, cid, supplier(client, cid), pid, qty=qty, price=10)
    body = {"lines": [{"line_id": po["lines"][0]["id"], "qty": qty, **line}]}
    return client.post(P(cid, f"/orders/{po['id']}/receive"), json=body, headers=idem())


def lot_qty(url, db, pid):
    rows = rpc(url, db)(
        "stock.quant",
        "search_read",
        [["product_id", "=", pid], ["location_id.usage", "=", "internal"]],
        fields=["lot_id", "quantity"],
    )
    return {r["lot_id"][1]: r["quantity"] for r in rows if r["lot_id"]}


def test_lot_goods_sell_first_expiry_first_and_never_from_expired_lots(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    c = rpc(url, db)
    enable_lots(url, db)
    c(
        "ir.module.module",
        "button_immediate_install",
        c("ir.module.module", "search", [["name", "=", "product_expiry"]]),
    )
    pid = new_product(client, cid, "lot", "لبن")
    assert receive(client, cid, pid, 5, lot_name="LATE", expiry="2031-01-01").status_code == 201
    assert receive(client, cid, pid, 5, lot_name="SOON", expiry="2030-06-01").status_code == 201
    assert (
        receive(client, cid, pid, 4, lot_name="OLD", expiry="2020-01-01").status_code == 201
    )  # already expired
    open_register(client, cid, cfg)
    q, sale = sell(client, cid, cfg, cash, pid, qty=7, pay=500)
    assert sale.status_code == 201, sale.text
    assert lot_qty(url, db, pid) == {
        "LATE": 3.0,
        "SOON": 0.0,
        "OLD": 4.0,
    }  # SOON first, then LATE, OLD untouched
    assert on_hand(url, db, pid) == 7.0
    q2, over = sell(client, cid, cfg, cash, pid, qty=4, pay=500)  # only 3 usable (non-expired) left
    assert over.status_code == 409 and over.json()["error"]["code"] == "lot_stock_short", over.text
    q3, frac = sell(client, cid, cfg, cash, pid, qty=1.5, pay=500)
    assert frac.status_code == 422


def test_serial_goods_need_exact_serials_and_refund_returns_them(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    enable_lots(url, db)
    pid = new_product(client, cid, "serial", "هاتف")
    bad = receive(client, cid, pid, 3, serials=["A1", "A2"])
    assert bad.status_code == 422 and "serial" in bad.json()["error"]["message"].lower()
    assert on_hand(url, db, pid) == 0.0
    assert receive(client, cid, pid, 3, serials=["A1", "A2", "A3"]).status_code == 201
    assert lot_qty(url, db, pid) == {"A1": 1.0, "A2": 1.0, "A3": 1.0}
    dup = receive(client, cid, pid, 1, serials=["A1"])
    assert dup.status_code == 422 and "already registered" in dup.json()["error"]["message"]

    open_register(client, cid, cfg)
    no_sn = sell(client, cid, cfg, cash, pid, qty=2, pay=500)[1]
    assert no_sn.status_code == 422 and no_sn.json()["error"]["code"] == "serials_required"
    base = f"/connections/{cid}/sales"
    line = {"product_id": pid, "qty": 2, "serials": ["A1", "A3"]}
    quote = client.post(f"{base}/quote", json={"config_id": cfg, "lines": [line]}).json()
    pay = [{"payment_method_id": cash, "amount": 500}]
    unknown = client.post(
        f"{base}/orders",
        json={
            "config_id": cfg,
            "lines": [{**line, "serials": ["A1", "ZZ"]}],
            "expected_total": quote["total"],
            "payments": pay,
        },
        headers=idem(),
    )
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "serial_not_in_stock"
    ok = client.post(
        f"{base}/orders",
        json={"config_id": cfg, "lines": [line], "expected_total": quote["total"], "payments": pay},
        headers=idem(),
    )
    assert ok.status_code == 201, ok.text
    assert lot_qty(url, db, pid) == {"A1": 0.0, "A2": 1.0, "A3": 0.0}
    sold = client.post(
        f"{base}/orders",
        json={
            "config_id": cfg,
            "lines": [{**line, "qty": 1, "serials": ["A1"]}],
            "expected_total": quote["total"] / 2,
            "payments": pay,
        },
        headers=idem(),
    )
    assert (
        sold.status_code == 422 and sold.json()["error"]["code"] == "serial_not_in_stock"
    )  # already sold

    oid, line_id = ok.json()["order"]["id"], ok.json()["order"]["lines"][0]["id"]
    one = client.post(
        f"{base}/orders/{oid}/refund",
        json={"payment_method_id": cash, "lines": [{"line_id": line_id, "qty": 1}]},
        headers=idem(),
    )
    assert one.status_code == 201, one.text
    assert sorted(k for k, v in lot_qty(url, db, pid).items() if v == 1.0) == [
        "A1",
        "A2",
    ]  # first serial is back
    rest = client.post(
        f"{base}/orders/{oid}/refund", json={"payment_method_id": cash}, headers=idem()
    )
    assert rest.status_code == 201, rest.text
    assert lot_qty(url, db, pid) == {"A1": 1.0, "A2": 1.0, "A3": 1.0}
