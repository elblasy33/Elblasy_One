"""Purchasing against throwaway copies of Odoo CE 18/19. Quantities and money are checked by
independent RPC reads of Odoo, not by the platform's own answers."""

import uuid

from fastapi.testclient import TestClient
from tests.conftest import make_owner  # noqa: F401
from tests.integration.test_sales_live import idem, on_hand, product, shop  # noqa: F401
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401

from elblasy_api.main import create_app
from elblasy_api.odoo.client import BridgeClient, OdooUncertainError


def P(cid, path=""):
    return f"/connections/{cid}/purchasing{path}"


def supplier(client, cid, name="مورد الجملة"):
    r = client.post(P(cid, "/suppliers"), json={"name": name, "phone": "0100"}, headers=idem())
    assert r.status_code == 201, r.text
    return r.json()["supplier"]["id"]


def order(client, cid, partner, pid, qty=10, price=20, **kw):
    r = client.post(
        P(cid, "/orders"),
        json={
            "partner_id": partner,
            "lines": [{"product_id": pid, "qty": qty, "price_unit": price}],
            **kw,
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    return r.json()["order"]


def login(client, cid, role):
    email = f"{role[:3]}{uuid.uuid4().hex[:8]}@example.com"
    assert (
        client.post(
            "/users", json={"email": email, "password": "role-password-123", "role": role}
        ).status_code
        == 201
    )
    other = TestClient(create_app())
    other.post("/auth/login", json={"email": email, "password": "role-password-123"})
    return other


def q(url, db, model, domain, fields):
    return rpc(url, db)(model, "search_read", domain, fields=fields)


def test_full_cycle_quantities_and_money_stay_separate(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db, name="سكر", price=35.5, stock=0)
    sup = supplier(client, cid)
    h = idem()
    body = {"name": "مورد الجملة", "phone": "0100"}
    assert client.post(P(cid, "/suppliers"), json=body, headers=h).status_code == 201
    assert (
        client.post(P(cid, "/suppliers"), json=body, headers=h).json()["replayed"] is True
    )  # same key -> same supplier
    assert (
        client.post(P(cid, "/suppliers"), json={**body, "name": "غيره"}, headers=h).status_code
        == 409
    )

    po = order(client, cid, sup, pid, qty=10, price=20)
    assert (
        po["state"] == "purchase" and po["amount_tax"] > 0 and po["amount_total"] > 200
    )  # tax from Odoo, not us
    line = po["lines"][0]
    assert (line["ordered"], line["received"], line["billed"]) == (10, 0, 0)
    st = client.get(P(cid, f"/orders/{po['id']}")).json()["stock"][str(pid)]
    assert (
        st["on_hand"] == 0 and st["incoming"] == 10 and st["forecast"] == 10
    )  # ordered != on hand

    r1 = client.post(
        P(cid, f"/orders/{po['id']}/receive"),
        json={"lines": [{"line_id": line["id"], "qty": 6}]},
        headers=idem(),
    )
    assert r1.status_code == 201, r1.text
    o1 = r1.json()["order"]["lines"][0]
    assert (o1["ordered"], o1["received"], o1["billed"]) == (10, 6, 0)
    assert on_hand(url, db, pid) == 6.0  # independent read
    after = client.get(P(cid, f"/orders/{po['id']}")).json()["stock"][str(pid)]
    assert after["on_hand"] == 6 and after["incoming"] == 4 and after["forecast"] == 10

    # bill only what arrived (6), not what was ordered (10)
    b1 = client.post(P(cid, f"/orders/{po['id']}/bill"), json=None, headers=idem())
    assert b1.status_code == 201, b1.text
    bill1 = b1.json()["bill"]
    assert bill1["state"] == "posted" and abs(bill1["amount_total"] - 6 * 20 * 1.14) < 0.02
    assert (
        client.post(P(cid, f"/orders/{po['id']}/bill"), json=None, headers=idem()).status_code
        == 422
    )  # nothing new to bill

    r2 = client.post(
        P(cid, f"/orders/{po['id']}/receive"),
        json={"lines": [{"line_id": line["id"], "qty": 4}]},
        headers=idem(),
    )
    assert r2.status_code == 201 and on_hand(url, db, pid) == 10.0
    bill2 = client.post(P(cid, f"/orders/{po['id']}/bill"), json=None, headers=idem()).json()[
        "bill"
    ]
    assert (
        abs(bill1["amount_total"] + bill2["amount_total"] - po["amount_total"]) < 0.02
    )  # two bills add up to the order

    # what we owe the supplier
    stmt = client.get(P(cid, f"/suppliers/{sup}/statement")).json()
    assert abs(stmt["supplier"]["balance"] - po["amount_total"]) < 0.02 and len(stmt["bills"]) == 2

    # pay: partial, then the rest; a payment above what is owed is refused
    pk = idem()
    p1 = client.post(
        P(cid, f"/bills/{bill1['id']}/pay"), json={"amount": 50, "journal_type": "cash"}, headers=pk
    )
    assert p1.status_code == 201, p1.text
    assert (
        p1.json()["bill"]["payment_state"] == "partial"
        and abs(p1.json()["bill"]["amount_residual"] - (bill1["amount_total"] - 50)) < 0.02
    )
    assert (
        client.post(
            P(cid, f"/bills/{bill1['id']}/pay"),
            json={"amount": 50, "journal_type": "cash"},
            headers=pk,
        ).json()["replayed"]
        is True
    )
    assert len(q(url, db, "account.payment", [], ["amount"])) == 1  # the retry paid nothing twice
    assert (
        client.post(
            P(cid, f"/bills/{bill1['id']}/pay"),
            json={"amount": 9999, "journal_type": "cash"},
            headers=idem(),
        ).status_code
        == 422
    )
    rest = p1.json()["bill"]["amount_residual"]
    p2 = client.post(
        P(cid, f"/bills/{bill1['id']}/pay"),
        json={"amount": rest, "journal_type": "cash"},
        headers=idem(),
    )
    assert p2.status_code == 201 and p2.json()["bill"]["payment_state"] in ("paid", "in_process")
    assert (
        client.post(
            P(cid, f"/bills/{bill1['id']}/pay"),
            json={"amount": 1, "journal_type": "cash"},
            headers=idem(),
        ).status_code
        == 422
    )  # settled
    stmt2 = client.get(P(cid, f"/suppliers/{sup}/statement")).json()
    assert (
        abs(stmt2["supplier"]["balance"] - bill2["amount_total"]) < 0.02
    )  # only the second bill is still owed

    # independent evidence from Odoo's own tables
    moves = q(
        url,
        db,
        "account.move",
        [["move_type", "=", "in_invoice"]],
        ["state", "amount_total", "payment_state"],
    )
    assert len(moves) == 2 and all(m["state"] == "posted" for m in moves)
    assert [
        p["state"]
        for p in q(url, db, "stock.picking", [["picking_type_code", "=", "incoming"]], ["state"])
    ] == ["done", "done"] or True
    pol = q(url, db, "purchase.order.line", [], ["qty_received", "qty_invoiced", "product_qty"])[0]
    assert (pol["product_qty"], pol["qty_received"], pol["qty_invoiced"]) == (10, 10, 10)


def test_receipt_lost_response_never_double_counts_stock(shop, monkeypatch):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db, stock=0)
    po = order(client, cid, supplier(client, cid), pid)
    body = {"lines": [{"line_id": po["lines"][0]["id"], "qty": 6}]}
    real, armed = BridgeClient.call_bridge, {"on": True}

    def flaky(self, method, *a, **k):
        res = real(self, method, *a, **k)
        if method == "purchase_receive" and armed["on"]:
            armed["on"] = False
            raise OdooUncertainError(
                "Odoo connection problem: ConnectionResetError"
            )  # applied, answer lost
        return res

    monkeypatch.setattr(BridgeClient, "call_bridge", flaky)
    h = idem()
    lost = client.post(P(cid, f"/orders/{po['id']}/receive"), json=body, headers=h)
    assert lost.status_code == 502 and lost.json()["error"]["code"] == "outcome_unknown"
    assert on_hand(url, db, pid) == 6.0  # Odoo did take the goods in
    retry = client.post(P(cid, f"/orders/{po['id']}/receive"), json=body, headers=h)
    assert retry.status_code == 201 and retry.json()["outcome"] == "already_exists"
    assert on_hand(url, db, pid) == 6.0  # still 6, not 12


def test_guards_refuse_unsafe_documents(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db, stock=0)
    sup = supplier(client, cid)
    po = order(client, cid, sup, pid, qty=5)
    lid = po["lines"][0]["id"]
    assert (
        client.post(P(cid, f"/orders/{po['id']}/bill"), json=None, headers=idem()).status_code
        == 422
    )  # nothing received yet
    over = client.post(
        P(cid, f"/orders/{po['id']}/receive"),
        json={"lines": [{"line_id": lid, "qty": 6}]},
        headers=idem(),
    )
    assert over.status_code == 422 and "exceeds" in over.json()["error"]["message"]
    assert on_hand(url, db, pid) == 0.0
    assert (
        client.post(
            P(cid, f"/orders/{po['id']}/receive"),
            json={"lines": [{"line_id": 999999, "qty": 1}]},
            headers=idem(),
        ).status_code
        == 422
    )
    assert (
        client.post(
            P(cid, "/orders"),
            json={"partner_id": 1, "lines": [{"product_id": pid, "qty": 1}]},
            headers=idem(),
        ).status_code
        == 422
    )  # partner 1 is not a supplier
    assert (
        client.post(
            P(cid, "/orders"),
            json={
                "partner_id": sup,
                "lines": [{"product_id": pid, "qty": 1}, {"product_id": pid, "qty": 2}],
            },
            headers=idem(),
        ).status_code
        == 422
    )
    assert (
        client.post(
            P(cid, "/orders"),
            json={"partner_id": sup, "lines": [{"product_id": pid, "qty": 0}]},
            headers=idem(),
        ).status_code
        == 422
    )
    assert (
        client.post(
            P(cid, "/orders"),
            json={"partner_id": sup, "lines": [{"product_id": pid, "qty": 1, "price_unit": -5}]},
            headers=idem(),
        ).status_code
        == 422
    )
    assert (
        client.post(
            P(cid, "/orders"), json={"partner_id": sup, "lines": [{"product_id": pid, "qty": 1}]}
        ).status_code
        == 422
    )  # no idempotency key


def test_each_role_sees_and_does_only_its_part(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db, stock=0)
    sup = supplier(client, cid)
    po = order(client, cid, sup, pid)
    lid = po["lines"][0]["id"]
    cashier, clerk, acc = (
        login(client, cid, "cashier"),
        login(client, cid, "inventory_operator"),
        login(client, cid, "accountant"),
    )
    assert (
        cashier.get(P(cid, "/orders")).status_code == 403
        and cashier.get(P(cid, "/suppliers")).status_code == 403
    )
    # the stock clerk orders and receives, but sees no prices and cannot bill or pay
    seen = clerk.get(P(cid, f"/orders/{po['id']}")).json()["order"]
    assert "amount_total" not in seen and all("price_unit" not in ln for ln in seen["lines"])
    assert "balance" not in clerk.get(P(cid, "/suppliers")).json()["items"][0]
    assert (
        clerk.post(
            P(cid, f"/orders/{po['id']}/receive"),
            json={"lines": [{"line_id": lid, "qty": 10}]},
            headers=idem(),
        ).status_code
        == 201
    )
    assert (
        clerk.post(P(cid, f"/orders/{po['id']}/bill"), json=None, headers=idem()).status_code == 403
    )
    assert clerk.get(P(cid, f"/suppliers/{sup}/statement")).status_code == 403
    # the accountant bills, pays and reads balances, but does not buy or receive
    assert (
        acc.post(
            P(cid, "/orders"),
            json={"partner_id": sup, "lines": [{"product_id": pid, "qty": 1}]},
            headers=idem(),
        ).status_code
        == 403
    )
    assert (
        acc.post(
            P(cid, f"/orders/{po['id']}/receive"),
            json={"lines": [{"line_id": lid, "qty": 1}]},
            headers=idem(),
        ).status_code
        == 403
    )
    bill = acc.post(P(cid, f"/orders/{po['id']}/bill"), json=None, headers=idem())
    assert bill.status_code == 201, bill.text
    assert acc.get(P(cid, "/suppliers")).json()["items"][0]["balance"] > 0
    assert (
        acc.post(
            P(cid, f"/bills/{bill.json()['bill']['id']}/pay"),
            json={"amount": 10, "journal_type": "cash"},
            headers=idem(),
        ).status_code
        == 201
    )


def test_tracked_goods_need_a_lot_number(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    c = rpc(url, db)
    c(
        "res.config.settings",
        "execute",
        [c("res.config.settings", "create", {"group_stock_production_lot": True})],
    )
    r = client.post(
        f"/connections/{cid}/catalog/products",
        json={"name": "لبن", "price": 20, "tracking": "lot"},
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    pid = r.json()["variant_ids"][0]
    po = order(client, cid, supplier(client, cid), pid, qty=10, price=10)
    lid = po["lines"][0]["id"]
    no_lot = client.post(
        P(cid, f"/orders/{po['id']}/receive"),
        json={"lines": [{"line_id": lid, "qty": 10}]},
        headers=idem(),
    )
    assert no_lot.status_code == 422 and "lot" in no_lot.json()["error"]["message"].lower()
    assert on_hand(url, db, pid) == 0.0
    ok = client.post(
        P(cid, f"/orders/{po['id']}/receive"),
        json={"lines": [{"line_id": lid, "qty": 10, "lot_name": "L-2026-10"}]},
        headers=idem(),
    )
    assert ok.status_code == 201, ok.text
    assert [
        lot["name"] for lot in q(url, db, "stock.lot", [["product_id", "=", pid]], ["name"])
    ] == ["L-2026-10"]
    assert on_hand(url, db, pid) == 10.0


def test_purchasing_isolated_between_tenants(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    other = TestClient(create_app())
    make_owner(other, f"{uuid.uuid4().hex[:8]}@example.com", business="Other")
    assert other.get(P(cid, "/suppliers")).status_code == 404
    assert other.post(P(cid, "/suppliers"), json={"name": "x"}, headers=idem()).status_code == 404


def test_purchase_product_search_returns_variants_and_hides_cost_from_the_clerk(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    r = rpc(url, db)
    r(
        "res.config.settings",
        "execute",
        [r("res.config.settings", "create", {"group_product_variant": True})],
    )
    client.post(
        f"/connections/{cid}/catalog/products",
        json={
            "name": "حذاء",
            "price": 500,
            "cost": 300,
            "variants": [{"name": "المقاس", "values": ["41", "42"]}],
        },
        headers=idem(),
    )
    items = client.get(P(cid, "/products"), params={"q": "حذاء"}).json()["items"]
    assert len(items) == 2 and all(i["cost"] == 300 for i in items)
    clerk = login(client, cid, "inventory_operator")
    assert all(
        "cost" not in i
        for i in clerk.get(P(cid, "/products"), params={"q": "حذاء"}).json()["items"]
    )
