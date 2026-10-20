"""POS sales against throwaway copies of Odoo CE 18/19. Money, stock and accounting are verified by
independent RPC reads of Odoo, not by the platform's own answers."""

import uuid

import pytest
from fastapi.testclient import TestClient
from tests.conftest import make_owner
from tests.integration.test_connections_api import body
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401

from elblasy_api.catalog_barcode import ean13_check_digit
from elblasy_api.main import create_app
from elblasy_api.odoo.client import BridgeClient, OdooUncertainError

CASH_ONLY = {"vertical": "general", "payment_methods": ["cash"], "buys_on_credit": False}


def idem():
    return {"Idempotency-Key": uuid.uuid4().hex}


def set_stock(url, db, product_id, qty):
    c = rpc(url, db)
    loc = c("stock.warehouse", "search_read", [], fields=["lot_stock_id"])[0]["lot_stock_id"][0]
    q = c(
        "stock.quant",
        "create",
        {"product_id": product_id, "location_id": loc, "inventory_quantity": qty},
    )
    try:
        c("stock.quant", "action_apply_inventory", [q])
    except Exception as exc:  # noqa: BLE001 - Odoo cannot marshal the None this method returns
        assert "marshal None" in str(exc)


def on_hand(url, db, pid):
    return rpc(url, db)("product.product", "read", [pid], fields=["qty_available"])[0][
        "qty_available"
    ]


@pytest.fixture
def shop(client, fresh):  # noqa: F811
    """An owner with a connected, fully set-up shop (set up through the real plan executor)."""
    _, url, db = fresh
    make_owner(client, f"{uuid.uuid4().hex[:8]}@example.com")
    cid = client.post("/connections", json=body(url, db)).json()["id"]
    plan = client.post(f"/connections/{cid}/setup/plans", json={"answers": CASH_ONLY}).json()
    if plan["plan"]["summary"]["to_apply"]:
        client.post(f"/connections/{cid}/setup/plans/{plan['id']}/approve")
        assert (
            client.post(f"/connections/{cid}/setup/plans/{plan['id']}/execute").status_code == 202
        )
        done = client.get(f"/connections/{cid}/setup/plans/{plan['id']}").json()
        assert done["status"] == "completed", done["execution"]
    st = client.get(f"/connections/{cid}/sales/state").json()
    assert "configs" in st, st
    cfg = st["configs"][0]
    cash = next(m["id"] for m in cfg["payment_methods"] if m["is_cash"])
    return client, cid, url, db, cfg["id"], cash


def product(client, cid, url, db, name="سكر", price=35.5, stock=100, **kw):
    r = client.post(
        f"/connections/{cid}/catalog/products",
        json={"name": name, "price": price, **kw},
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    pid = r.json()["variant_ids"][0]
    if stock:
        set_stock(url, db, pid, stock)
    return pid, r.json()


def open_register(client, cid, cfg):
    r = client.post(
        f"/connections/{cid}/sales/sessions",
        json={"config_id": cfg, "opening_cash": 0},
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    return r.json()["session"]


def sell(client, cid, cfg, cash, pid, qty=2, pay=100, **kw):
    q = client.post(
        f"/connections/{cid}/sales/quote",
        json={"config_id": cfg, "lines": [{"product_id": pid, "qty": qty}]},
    ).json()
    data = {
        "config_id": cfg,
        "lines": [{"product_id": pid, "qty": qty}],
        "expected_total": q["total"],
        "payments": [{"payment_method_id": cash, "amount": pay}],
    }
    h = kw.pop("headers", None) or idem()
    return q, client.post(f"/connections/{cid}/sales/orders", json={**data, **kw}, headers=h)


def test_full_sale_is_verified_against_odoo(shop):
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db)
    assert (
        client.post(
            f"/connections/{cid}/sales/quote",
            json={"config_id": cfg, "lines": [{"product_id": pid, "qty": 1}]},
        ).status_code
        == 200
    )
    # no session yet: refused with a clear code, nothing recorded
    q, r = sell(client, cid, cfg, cash, pid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_open_session", r.text

    sess = open_register(client, cid, cfg)
    again = client.post(
        f"/connections/{cid}/sales/sessions",
        json={"config_id": cfg, "opening_cash": 0},
        headers=idem(),
    ).json()
    assert (
        again["outcome"] == "already_exists" and again["session"]["id"] == sess["id"]
    )  # one register, one session

    q, r = sell(client, cid, cfg, cash, pid, qty=2, pay=100)
    assert r.status_code == 201, r.text
    out = r.json()
    o = out["order"]
    assert (
        o["state"] in ("paid", "done")
        and o["amount_total"] == q["total"]
        and out["stock_updated"] is True
    )
    assert o["amount_paid"] == o["amount_total"] and round(o["amount_return"], 2) == round(
        100 - q["total"], 2
    )
    assert out["receipt"]["change"] == o["amount_return"] and len(out["receipt"]["payments"]) == 1

    # independent evidence straight from Odoo
    c = rpc(url, db)
    all_fields = c("pos.order", "fields_get", attributes=["type"])
    note_field = "internal_note" if "internal_note" in all_fields else "general_note"
    od = c(
        "pos.order",
        "read",
        [o["id"]],
        fields=[
            "amount_total",
            "amount_tax",
            "state",
            "lines",
            "payment_ids",
            note_field,
            "picking_ids",
        ],
    )[0]
    assert od["amount_total"] == q["total"] and od["amount_tax"] > 0
    assert "Elblasy cashier" in od[note_field]  # who sold it travels with the order in Odoo
    assert len(od["lines"]) == 1 and len(od["payment_ids"]) == 2  # tendered + change line
    assert all(
        p["state"] == "done"
        for p in c("stock.picking", "read", od["picking_ids"], fields=["state"])
    )
    assert on_hand(url, db, pid) == 98.0
    assert (
        abs(q["total"] - 71.0 * 1.14) < 0.01 or q["tax"] > 0
    )  # taxes came from Odoo's engine, not from us


def test_checkout_is_idempotent_and_survives_a_lost_response(shop, monkeypatch):
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db)
    open_register(client, cid, cfg)
    h = idem()
    q, a = sell(client, cid, cfg, cash, pid, headers=h)
    _, b = sell(client, cid, cfg, cash, pid, headers=h)
    assert a.status_code == b.status_code == 201 and b.json()["replayed"] is True
    assert a.json()["order"]["id"] == b.json()["order"]["id"]
    assert rpc(url, db)("pos.order", "search_count", []) == 1 and on_hand(url, db, pid) == 98.0
    # same key, different cart -> refused, never a silent second sale
    other = client.post(
        f"/connections/{cid}/sales/orders",
        json={
            "config_id": cfg,
            "lines": [{"product_id": pid, "qty": 5}],
            "expected_total": 1,
            "payments": [{"payment_method_id": cash, "amount": 1000}],
        },
        headers=h,
    )
    assert other.status_code == 409

    real, armed = BridgeClient.call_bridge, {"on": True}

    def flaky(self, method, *a, **k):
        res = real(self, method, *a, **k)
        if method == "sales_checkout" and armed["on"]:
            armed["on"] = False
            raise OdooUncertainError(
                "Odoo connection problem: ConnectionResetError"
            )  # applied, answer lost
        return res

    monkeypatch.setattr(BridgeClient, "call_bridge", flaky)
    h2 = idem()
    _, lost = sell(client, cid, cfg, cash, pid, qty=1, pay=50, headers=h2)
    assert lost.status_code == 502 and lost.json()["error"]["code"] == "outcome_unknown"
    assert rpc(url, db)("pos.order", "search_count", []) == 2  # Odoo did record it
    _, retry = sell(client, cid, cfg, cash, pid, qty=1, pay=50, headers=h2)
    assert retry.status_code == 201 and retry.json()["outcome"] == "already_exists"
    assert (
        rpc(url, db)("pos.order", "search_count", []) == 2 and on_hand(url, db, pid) == 97.0
    )  # still exactly one


def test_guards_price_change_underpayment_and_permissions(shop):
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db)
    open_register(client, cid, cfg)
    line = {"product_id": pid, "qty": 1}
    stale = client.post(
        f"/connections/{cid}/sales/orders",
        json={
            "config_id": cfg,
            "lines": [line],
            "expected_total": 5.0,
            "payments": [{"payment_method_id": cash, "amount": 100}],
        },
        headers=idem(),
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "price_changed"
    short = client.post(
        f"/connections/{cid}/sales/orders",
        json={
            "config_id": cfg,
            "lines": [line],
            "expected_total": 40.47,
            "payments": [{"payment_method_id": cash, "amount": 10}],
        },
        headers=idem(),
    )
    assert short.status_code == 422
    assert rpc(url, db)("pos.order", "search_count", []) == 0 and on_hand(url, db, pid) == 100.0

    email = f"k{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/users", json={"email": email, "password": "cashier-password-1", "role": "cashier"}
    )
    cashier = TestClient(create_app())
    cashier.post("/auth/login", json={"email": email, "password": "cashier-password-1"})
    # a cashier can sell but not discount, refund, or read the report
    disc = cashier.post(
        f"/connections/{cid}/sales/quote",
        json={"config_id": cfg, "lines": [{**line, "discount": 10}]},
    )
    assert disc.status_code == 403
    q, r = sell(cashier, cid, cfg, cash, pid, qty=1, pay=50)
    assert r.status_code == 201
    oid = r.json()["order"]["id"]
    assert (
        cashier.post(
            f"/connections/{cid}/sales/orders/{oid}/refund",
            json={"payment_method_id": cash},
            headers=idem(),
        ).status_code
        == 403
    )
    assert cashier.get(f"/connections/{cid}/sales/summary").status_code == 403
    # the owner can discount: Odoo applies it and the total drops
    full = client.post(
        f"/connections/{cid}/sales/quote", json={"config_id": cfg, "lines": [line]}
    ).json()["total"]
    disc = client.post(
        f"/connections/{cid}/sales/quote",
        json={"config_id": cfg, "lines": [{**line, "discount": 10}]},
    ).json()["total"]
    assert abs(disc - full * 0.9) < 0.02


def test_weighed_item_scanned_from_scale_label(shop):
    client, cid, url, db, cfg, cash = shop
    r = client.post(
        f"/connections/{cid}/catalog/products",
        json={"name": "طماطم", "price": 20, "kind": "weight", "auto_barcode": "scale"},
        headers=idem(),
    ).json()
    pid, code = r["variant_ids"][0], r["barcode"]
    set_stock(url, db, pid, 50)
    open_register(client, cid, cfg)
    printed = code[:7] + "01250"
    printed += str(ean13_check_digit(printed))  # label for 1.250 kg
    hit = client.get(
        f"/connections/{cid}/sales/lookup", params={"config_id": cfg, "code": printed}
    ).json()
    assert (
        hit["found"]
        and hit["product_id"] == pid
        and abs(hit["qty"] - 1.25) < 1e-9
        and hit["by_weight"] is True
    )
    plain = client.get(
        f"/connections/{cid}/sales/lookup", params={"config_id": cfg, "code": "0000000000000"}
    ).json()
    assert plain["found"] is False
    q, sale = sell(client, cid, cfg, cash, pid, qty=hit["qty"], pay=100)
    assert sale.status_code == 201 and sale.json()["order"]["lines"][0]["qty"] == 1.25
    assert on_hand(url, db, pid) == 48.75


def test_refund_restores_stock_and_cannot_repeat(shop):
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db)
    open_register(client, cid, cfg)
    q, sale = sell(client, cid, cfg, cash, pid, qty=3, pay=200)
    oid, total = sale.json()["order"]["id"], sale.json()["order"]["amount_total"]
    assert on_hand(url, db, pid) == 97.0
    h = idem()
    ref = client.post(
        f"/connections/{cid}/sales/orders/{oid}/refund", json={"payment_method_id": cash}, headers=h
    )
    assert ref.status_code == 201, ref.text
    assert ref.json()["order"]["amount_total"] == -total
    assert on_hand(url, db, pid) == 100.0  # goods are back on the shelf
    assert (
        client.post(
            f"/connections/{cid}/sales/orders/{oid}/refund",
            json={"payment_method_id": cash},
            headers=h,
        ).json()["replayed"]
        is True
    )
    again = client.post(
        f"/connections/{cid}/sales/orders/{oid}/refund",
        json={"payment_method_id": cash},
        headers=idem(),
    )
    assert again.status_code == 422 and "already refunded" in again.json()["error"]["message"]
    assert on_hand(url, db, pid) == 100.0
    s = client.get(f"/connections/{cid}/sales/summary").json()
    assert (
        s["gross_sales"] == total
        and s["refunds"] == -total
        and s["net_sales"] == 0
        and s["cash_collected"] == 0
    )


def test_close_register_reports_cash_difference_and_posts_accounting(shop):
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db)
    sess = open_register(client, cid, cfg)
    q, sale = sell(client, cid, cfg, cash, pid, qty=2, pay=100)
    total = sale.json()["order"]["amount_total"]
    st = client.get(f"/connections/{cid}/sales/state").json()["configs"][0]["session"]
    assert abs(st["expected_cash"] - total) < 0.01, st
    h = idem()
    closed = client.post(
        f"/connections/{cid}/sales/sessions/{sess['id']}/close",
        json={"counted_cash": total - 5},
        headers=h,
    )
    assert closed.status_code == 200, closed.text
    out = closed.json()
    assert (
        out["session"]["state"] == "closed"
        and out["has_difference"] is True
        and abs(out["cash_difference"] + 5) < 0.01
    )
    # accounting is posted in Odoo, verified independently
    c = rpc(url, db)
    s = c(
        "pos.session", "read", [sess["id"]], fields=["state", "move_id", "cash_register_difference"]
    )[0]
    assert s["state"] == "closed" and s["move_id"]
    assert c("account.move", "read", [s["move_id"][0]], fields=["state"])[0]["state"] == "posted"
    assert (
        client.post(
            f"/connections/{cid}/sales/sessions/{sess['id']}/close",
            json={"counted_cash": total - 5},
            headers=h,
        ).json()["replayed"]
        is True
    )
    # after closing, selling needs a new session
    assert sell(client, cid, cfg, cash, pid)[1].status_code == 409


def test_sales_isolated_between_tenants(shop):
    client, cid, url, db, cfg, cash = shop
    other = TestClient(create_app())
    make_owner(other, f"{uuid.uuid4().hex[:8]}@example.com", business="Other")
    assert other.get(f"/connections/{cid}/sales/state").status_code == 404
    assert (
        other.post(
            f"/connections/{cid}/sales/sessions", json={"config_id": cfg}, headers=idem()
        ).status_code
        == 404
    )


def test_setup_plan_switches_stock_to_every_sale_only_with_approval(client, fresh):  # noqa: F811
    """A shop whose Odoo deducts stock only at session close gets an explicit, approved plan step."""
    _, url, db = fresh
    c = rpc(url, db)
    c("res.company", "write", [1], {"point_of_sale_update_stock_quantities": "closing"})
    make_owner(client, f"{uuid.uuid4().hex[:8]}@example.com")
    cid = client.post("/connections", json=body(url, db)).json()["id"]
    plan = client.post(f"/connections/{cid}/setup/plans", json={"answers": CASH_ONLY}).json()
    step = next(s for s in plan["plan"]["steps"] if s["key"] == "feature_realtime_stock")
    assert step["status"] == "to_apply" and step["risk"] == "medium"
    cfg_before = c("res.company", "read", [1], fields=["point_of_sale_update_stock_quantities"])[0]
    assert (
        cfg_before["point_of_sale_update_stock_quantities"] == "closing"
    )  # planning changed nothing
    client.post(f"/connections/{cid}/setup/plans/{plan['id']}/approve")
    assert client.post(f"/connections/{cid}/setup/plans/{plan['id']}/execute").status_code == 202
    done = client.get(f"/connections/{cid}/setup/plans/{plan['id']}").json()
    summary = {
        k: (v["status"], v.get("error"))
        for k, v in done["execution"]["steps"].items()
        if v["status"] != "succeeded"
    }
    assert done["status"] == "completed", summary
    assert (
        c("res.company", "read", [1], fields=["point_of_sale_update_stock_quantities"])[0][
            "point_of_sale_update_stock_quantities"
        ]
        == "real"
    )
    again = client.post(f"/connections/{cid}/setup/plans", json={"answers": CASH_ONLY}).json()
    assert (
        next(s for s in again["plan"]["steps"] if s["key"] == "feature_realtime_stock")["status"]
        == "satisfied"
    )


def test_register_search_finds_variants_by_name_barcode_and_attribute(shop):
    client, cid, url, db, cfg, cash = shop
    enable = rpc(url, db)
    enable(
        "res.config.settings",
        "execute",
        [enable("res.config.settings", "create", {"group_product_variant": True})],
    )
    r = client.post(
        f"/connections/{cid}/catalog/products",
        json={
            "name": "حذاء رياضي",
            "price": 500,
            "variants": [
                {"name": "المقاس", "values": ["41", "42"]},
                {"name": "اللون", "values": ["أسود", "أبيض"]},
            ],
        },
        headers=idem(),
    )
    assert r.status_code == 201 and r.json()["variant_count"] == 4
    open_register(client, cid, cfg)

    def search(q):
        r = client.get(f"/connections/{cid}/sales/products", params={"config_id": cfg, "q": q})
        assert r.status_code == 200, r.text
        return r.json()["items"]

    by_name = search("حذاء")
    assert len(by_name) == 4 and all("حذاء رياضي" in i["name"] for i in by_name)
    by_attr = search("42")
    assert len(by_attr) == 2  # size 42 in both colours
    one = by_attr[0]
    set_stock(url, db, one["product_id"], 5)
    q, sale = sell(client, cid, cfg, cash, one["product_id"], qty=1, pay=1000)
    assert sale.status_code == 201 and on_hand(url, db, one["product_id"]) == 4.0
    assert search("لا يوجد") == []


def test_partial_refund_by_line_quantity_until_nothing_is_left(shop):
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db)
    open_register(client, cid, cfg)
    q, sale = sell(client, cid, cfg, cash, pid, qty=4, pay=400)
    order = sale.json()["order"]
    line = order["lines"][0]
    unit = order["amount_total"] / 4
    url_ = f"/connections/{cid}/sales/orders/{order['id']}/refund"

    def go(qty):
        body = {"payment_method_id": cash, "lines": [{"line_id": line["id"], "qty": qty}]}
        return client.post(url_, json=body, headers=idem())

    first = go(1)
    assert first.status_code == 201, first.text
    assert abs(first.json()["order"]["amount_total"] + unit) < 0.01
    assert on_hand(url, db, pid) == 97.0  # 100 - 4 sold + 1 back
    too_many = go(4)  # only 3 left to give back
    assert (
        too_many.status_code == 422 and "more than was sold" in too_many.json()["error"]["message"]
    )
    rest = client.post(url_, json={"payment_method_id": cash}, headers=idem())  # everything left
    assert rest.status_code == 201, rest.text
    assert abs(rest.json()["order"]["amount_total"] + 3 * unit) < 0.01
    assert on_hand(url, db, pid) == 100.0
    done = client.post(url_, json={"payment_method_id": cash}, headers=idem())
    assert done.status_code == 422 and "already refunded" in done.json()["error"]["message"]
    view = client.get(
        f"/connections/{cid}/sales/orders", params={"session_id": order["session_id"]}
    ).json()
    original = next(o for o in view["items"] if o["id"] == order["id"])
    assert original["lines"][0]["refunded_qty"] == 4


def test_refund_request_flow_cashier_asks_manager_decides(shop):
    from tests.integration.test_purchasing_live import login as login_role

    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db)
    open_register(client, cid, cfg)
    cashier = login_role(client, cid, "cashier")
    q, sale = sell(cashier, cid, cfg, cash, pid, qty=2, pay=200)
    oid = sale.json()["order"]["id"]
    assert on_hand(url, db, pid) == 98.0
    base = f"/connections/{cid}/sales"
    body = {"payment_method_id": cash}
    h = idem()
    req = cashier.post(f"{base}/orders/{oid}/refund-request", json=body, headers=h)
    assert req.status_code == 202 and req.json()["status"] == "awaiting_approval", req.text
    assert (
        cashier.post(f"{base}/orders/{oid}/refund-request", json=body, headers=h).json()["replayed"]
        is True
    )
    assert on_hand(url, db, pid) == 98.0  # nothing moved yet
    rid = req.json()["operation_id"]
    mine = cashier.get(f"{base}/refund-requests").json()["items"]
    assert [m["id"] for m in mine] == [rid] and mine[0]["status"] == "awaiting_approval"
    # a cashier can neither approve (even their own) nor see the decision endpoints as allowed
    assert cashier.post(f"{base}/refund-requests/{rid}/approve").status_code == 403
    # the owner decides: first reject a second request, then approve this one
    second = cashier.post(f"{base}/orders/{oid}/refund-request", json=body, headers=idem()).json()[
        "operation_id"
    ]
    rej = client.post(f"{base}/refund-requests/{second}/reject", json={"note": "لا"})
    assert rej.status_code == 200 and rej.json()["status"] == "rejected"
    assert client.post(f"{base}/refund-requests/{second}/approve").status_code == 409
    ok = client.post(f"{base}/refund-requests/{rid}/approve")
    assert ok.status_code == 200, ok.text
    assert ok.json()["order"]["amount_total"] < 0 and on_hand(url, db, pid) == 100.0
    assert client.post(f"{base}/refund-requests/{rid}/approve").status_code == 409  # decided once
    statuses = {m["id"]: m["status"] for m in client.get(f"{base}/refund-requests").json()["items"]}
    assert statuses[rid] == "succeeded" and statuses[second] == "rejected"
    audit = {a["action"] for a in client.get("/audit").json()["items"]}
    assert {
        "sales.refund.requested",
        "sales.order.refund.approved",
        "sales.refund.rejected",
    } <= audit
    # requests for something that is not a paid sale are refused up front
    bad = cashier.post(f"{base}/orders/{oid}/refund-request", json=body, headers=idem())
    assert bad.status_code == 422


def test_register_browse_by_category_page_images_and_price_override(shop):
    import base64

    from tests.integration.test_purchasing_live import login as login_role

    client, cid, url, db, cfg, cash = shop
    a, _ = product(client, cid, url, db, name="شاي", price=50, category="مشروبات")
    b, _ = product(client, cid, url, db, name="عصير", price=20, category="مشروبات")
    c, _ = product(client, cid, url, db, name="رز", price=30, category="بقالة")
    base = f"/connections/{cid}/sales"
    cats = {
        x["name"]: x
        for x in client.get(f"{base}/categories", params={"config_id": cfg}).json()["items"]
    }
    assert cats["مشروبات"]["count"] == 2 and cats["بقالة"]["count"] == 1
    listed = client.get(
        f"{base}/products", params={"config_id": cfg, "category": cats["مشروبات"]["id"]}
    ).json()["items"]
    assert sorted(x["name"] for x in listed) == ["شاي", "عصير"]
    allp = client.get(f"{base}/products", params={"config_id": cfg}).json()[
        "items"
    ]  # no search text lists the till's products
    assert len(allp) == 3
    page2 = client.get(
        f"{base}/products", params={"config_id": cfg, "limit": 2, "offset": 2}
    ).json()["items"]
    assert len(page2) == 1

    assert client.get(f"{base}/products/{a}/image").status_code == 404
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    rpc(url, db)("product.product", "write", [a], {"image_1920": base64.b64encode(png).decode()})
    img = client.get(f"{base}/products/{a}/image")
    assert (
        img.status_code == 200
        and img.headers["content-type"] == "image/png"
        and img.content[:4] == b"\x89PNG"
    )
    assert next(
        x
        for x in client.get(
            f"{base}/products", params={"config_id": cfg, "category": cats["مشروبات"]["id"]}
        ).json()["items"]
        if x["product_id"] == a
    )["has_image"]

    # price override: authorised users only, applied by Odoo's tax engine, audited
    open_register(client, cid, cfg)
    line = {"product_id": a, "qty": 2, "price_override": 40}
    q = client.post(f"{base}/quote", json={"config_id": cfg, "lines": [line]}).json()
    assert q["lines"][0]["price_unit"] == 40 and abs(q["total"] - 80 * 1.14) < 0.02
    sale = client.post(
        f"{base}/orders",
        json={
            "config_id": cfg,
            "lines": [line],
            "expected_total": q["total"],
            "payments": [{"payment_method_id": cash, "amount": 200}],
        },
        headers=idem(),
    )
    assert sale.status_code == 201, sale.text
    assert sale.json()["order"]["lines"][0]["price_unit"] == 40
    cashier = login_role(client, cid, "cashier")
    assert (
        cashier.post(f"{base}/quote", json={"config_id": cfg, "lines": [line]}).status_code == 403
    )
    assert any(x["action"] == "sales.order.create" for x in client.get("/audit").json()["items"])
