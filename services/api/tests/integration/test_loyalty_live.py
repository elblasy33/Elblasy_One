"""Promotions and loyalty points applied at the till, written to Odoo the loyalty app's way."""

from tests.integration.test_purchasing_live import login
from tests.integration.test_sales_live import idem, open_register, product, shop  # noqa: F401
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401


def install(url, db, name):
    c = rpc(url, db)
    c(
        "ir.module.module",
        "button_immediate_install",
        c("ir.module.module", "search", [["name", "=", name]]),
    )


def test_buy_x_get_y_discounts_points_earned_and_redeemed(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    install(url, db, "loyalty")
    base = f"/connections/{cid}"
    tea, _ = product(client, cid, url, db, name="شاي", price=50, stock=100)
    rice, _ = product(client, cid, url, db, name="أرز", price=100, stock=100)
    mk = lambda body: client.post(f"{base}/loyalty/programs", json=body, headers=idem())  # noqa: E731
    r = mk({"kind": "bxgy", "name": "اشتري 2 والتالت هدية", "product_id": tea, "buy": 2, "free": 1})
    assert r.status_code == 201, r.text
    assert (
        mk(
            {"kind": "product_discount", "name": "خصم الأرز", "product_ids": [rice], "percent": 10}
        ).status_code
        == 201
    )
    pts = mk(
        {
            "kind": "points",
            "name": "نقاطي",
            "points_per_unit": 1,
            "point_value": 0.1,
            "min_redeem": 50,
        }
    )
    assert pts.status_code == 201, pts.text
    assert (
        mk({"kind": "points", "name": "تاني", "points_per_unit": 1, "point_value": 1}).status_code
        == 422
    )  # one points programme
    assert mk({"kind": "bxgy", "name": "ناقص"}).status_code == 422  # incomplete
    progs = client.get(f"{base}/loyalty/programs").json()["items"]
    till = {x["name"] for x in client.get(f"{base}/sales/products", params={"config_id": cfg, "limit": 50}).json()["items"]}
    assert till == {"شاي", "أرز"}  # the loyalty app's own gift-card / e-wallet / discount products stay off the till
    assert {p["kind"] for p in progs} == {"bxgy", "product_discount", "points"}

    open_register(client, cid, cfg)
    cust = client.post(f"{base}/customers", json={"name": "عميل وفي"}, headers=idem()).json()[
        "customer"
    ]["id"]
    lines = [{"product_id": tea, "qty": 3}, {"product_id": rice, "qty": 1}]
    q = client.post(
        f"{base}/sales/quote", json={"config_id": cfg, "lines": lines, "partner_id": cust}
    ).json()
    gross = sum(x["subtotal_incl"] for x in q["lines"])
    rewards = sum(x["incl"] for x in q["rewards"])
    assert abs(rewards + (50 * 1.14) + (100 * 1.14 * 0.10)) < 0.02, q[
        "rewards"
    ]  # one tea free, 10% off rice
    assert abs(q["total"] - (gross + rewards)) < 0.01
    assert q["points"]["balance"] == 0 and q["points"]["earned"] == int(q["total"])

    h = idem()
    body = {
        "config_id": cfg,
        "lines": lines,
        "partner_id": cust,
        "expected_total": q["total"],
        "payments": [{"payment_method_id": cash, "amount": q["total"]}],
    }
    sale = client.post(f"{base}/sales/orders", json=body, headers=h)
    assert sale.status_code == 201, sale.text
    assert sum(1 for ln in sale.json()["order"]["lines"] if ln["is_reward"]) == 2
    assert client.post(f"{base}/sales/orders", json=body, headers=h).json()["replayed"] is True
    c = rpc(url, db)
    card = c("loyalty.card", "search_read", [["partner_id", "=", cust]], fields=["points"])
    assert len(card) == 1 and card[0]["points"] == int(
        q["total"]
    )  # earned once, even with the retry
    assert client.get(f"{base}/customers/{cust}/points").json()["points"] == int(q["total"])

    # redeem 100 points (worth 10) on the next sale
    q2 = client.post(
        f"{base}/sales/quote",
        json={
            "config_id": cfg,
            "lines": [{"product_id": rice, "qty": 1}],
            "partner_id": cust,
            "redeem_points": 100,
        },
    ).json()
    assert (
        q2["points"]["used"] == 100
        and abs(sum(x["incl"] for x in q2["rewards"]) + 11.4 + 10) < 0.02
    )
    s2 = client.post(
        f"{base}/sales/orders",
        json={
            "config_id": cfg,
            "lines": [{"product_id": rice, "qty": 1}],
            "partner_id": cust,
            "redeem_points": 100,
            "expected_total": q2["total"],
            "payments": [{"payment_method_id": cash, "amount": q2["total"]}],
        },
        headers=idem(),
    )
    assert s2.status_code == 201, s2.text
    after = c(
        "loyalty.card",
        "read",
        [c("loyalty.card", "search", [["partner_id", "=", cust]])[0]],
        fields=["points"],
    )[0]["points"]
    assert after == int(q["total"]) - 100 + q2["points"]["earned"]
    hist = c(
        "loyalty.history",
        "search_read",
        [["card_id.partner_id", "=", cust]],
        fields=["issued", "used"],
    )
    assert sorted(h_["used"] for h_ in hist) == [0, 100]
    too_many = client.post(
        f"{base}/sales/quote",
        json={
            "config_id": cfg,
            "lines": [{"product_id": rice, "qty": 1}],
            "partner_id": cust,
            "redeem_points": 99999,
        },
    )
    assert too_many.status_code == 422 and "POINTS_SHORT" in too_many.json()["error"]["message"]

    # switching a promotion off stops it at the next sale
    bx = next(p for p in progs if p["kind"] == "bxgy")
    assert (
        client.put(
            f"{base}/loyalty/programs/{bx['id']}/active", json={"active": False}, headers=idem()
        ).status_code
        == 200
    )
    q3 = client.post(
        f"{base}/sales/quote", json={"config_id": cfg, "lines": [{"product_id": tea, "qty": 3}]}
    ).json()
    assert q3["rewards"] == []
    assert (
        login(client, cid, "cashier")
        .post(
            f"{base}/loyalty/programs",
            json={"kind": "order_discount", "name": "x", "percent": 5},
            headers=idem(),
        )
        .status_code
        == 403
    )
