"""Stock against throwaway copies of Odoo CE 18/19: counts, approvals, opening balances, suggestions."""

import uuid

from fastapi.testclient import TestClient
from tests.conftest import make_owner
from tests.integration.test_purchasing_live import login, q  # noqa: F401
from tests.integration.test_sales_live import idem, on_hand, product, shop  # noqa: F401
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401

from elblasy_api.main import create_app
from elblasy_api.odoo.client import BridgeClient, OdooUncertainError


def S(cid, path=""):
    return f"/connections/{cid}/stock{path}"


def adjust(c, cid, pid, counted, reason="count_correction", note=None, headers=None):
    body = {
        "reason": reason,
        "lines": [{"product_id": pid, "counted_qty": counted}],
        **({"note": note} if note else {}),
    }
    return c.post(S(cid, "/adjustments"), json=body, headers=headers or idem())


def test_overview_keeps_quantities_apart_and_suggestions_never_order(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db, name="سكر", stock=0)
    assert adjust(client, cid, pid, 12, "found").status_code == 201
    r = client.put(S(cid, f"/products/{pid}/minimum"), json={"min_qty": 20}, headers=idem())
    assert r.status_code == 200, r.text
    row = client.get(S(cid, "/overview"), params={"q": "سكر"}).json()["items"][0]
    assert (row["on_hand"], row["free"], row["incoming"], row["forecast"], row["min"]) == (
        12,
        12,
        0,
        12,
        20,
    ) and row["low"] is True
    assert row["value"] == 12 * row["cost"]
    sug = client.get(S(cid, "/suggestions")).json()
    assert (
        sug["note"] == "recommendations, not orders"
        and sug["items"][0]["product_id"] == pid
        and sug["items"][0]["suggested_qty"] >= 8
    )
    c = rpc(url, db)
    assert c("purchase.order", "search_count", []) == 0  # a suggestion is not an order
    assert [
        o["trigger"] for o in c("stock.warehouse.orderpoint", "search_read", [], fields=["trigger"])
    ] == ["manual"]
    assert client.get(S(cid, "/overview"), params={"low": "true"}).json()["total"] == 1
    assert (
        client.put(
            S(cid, f"/products/{pid}/minimum"), json={"min_qty": 20, "max_qty": 5}, headers=idem()
        ).status_code
        == 422
    )


def test_adjustment_changes_stock_with_a_reason_and_never_twice(shop, monkeypatch):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db, stock=0)
    h = idem()
    a = adjust(client, cid, pid, 10, "found", "وُجدت في الرف", h)
    assert a.status_code == 201, a.text
    assert on_hand(url, db, pid) == 10.0
    refs = [
        m["reference"] for m in q(url, db, "stock.move", [["product_id", "=", pid]], ["reference"])
    ]
    assert any(
        "found" in r and "وُجدت" in r for r in refs
    )  # the reason is stored on the stock move itself
    assert adjust(client, cid, pid, 10, "found", "وُجدت في الرف", h).json()["replayed"] is True
    assert on_hand(url, db, pid) == 10.0
    assert (
        adjust(client, cid, pid, 10, "found", None, h).status_code == 409
    )  # same key, different request

    real, armed = BridgeClient.call_bridge, {"on": True}

    def flaky(self, method, *a, **k):
        res = real(self, method, *a, **k)
        if method == "stock_adjust" and armed["on"]:
            armed["on"] = False
            raise OdooUncertainError("Odoo connection problem: ConnectionResetError")
        return res

    monkeypatch.setattr(BridgeClient, "call_bridge", flaky)
    h2 = idem()
    lost = adjust(client, cid, pid, 7, "damaged", "كسر", h2)
    assert lost.status_code == 502 and lost.json()["error"]["code"] == "outcome_unknown"
    assert on_hand(url, db, pid) == 7.0  # Odoo applied the count
    retry = adjust(client, cid, pid, 7, "damaged", "كسر", h2)
    assert retry.status_code == 201 and retry.json()["outcome"] == "already_exists"
    assert (
        on_hand(url, db, pid) == 7.0
        and len(q(url, db, "stock.move", [["product_id", "=", pid]], ["id"])) == 2
    )  # one move per count
    assert adjust(client, cid, pid, 7, "invented").status_code == 422  # unknown reason
    assert adjust(client, cid, 999999, 1).status_code == 422


def test_large_adjustments_by_a_clerk_wait_for_a_different_person(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db, price=40, cost=20, stock=0)
    clerk = login(client, cid, "inventory_operator")
    small = adjust(clerk, cid, pid, 5, "found")  # value 100 <= threshold: allowed directly
    assert small.status_code == 201 and on_hand(url, db, pid) == 5.0
    h = idem()
    big = adjust(clerk, cid, pid, 1000, "found", "وجدت مخزن", h)  # value ~20,000 > 500
    assert big.status_code == 202, big.text
    op_id = big.json()["operation_id"]
    assert on_hand(url, db, pid) == 5.0  # nothing moved yet
    assert (
        adjust(clerk, cid, pid, 1000, "found", "وجدت مخزن", h).status_code == 202
    )  # same request, still pending
    assert (
        clerk.post(S(cid, f"/adjustments/{op_id}/approve")).status_code == 403
    )  # a clerk cannot approve
    pending = client.get(S(cid, "/adjustments"), params={"status": "awaiting_approval"}).json()[
        "items"
    ]
    assert (
        len(pending) == 1
        and pending[0]["requested_by"] == clerk.get("/auth/me").json()["email"]
        and abs(pending[0]["value_change"]) > 500
    )
    ok = client.post(S(cid, f"/adjustments/{op_id}/approve"))
    assert ok.status_code == 200, ok.text
    assert on_hand(url, db, pid) == 1000.0
    note = [
        m["reference"] for m in q(url, db, "stock.move", [["product_id", "=", pid]], ["reference"])
    ]
    assert any(
        "approved by" in r for r in note
    )  # requester and approver are both on the Odoo record
    assert (
        client.post(S(cid, f"/adjustments/{op_id}/approve")).status_code == 409
    )  # cannot be approved twice
    # a second request is rejected: stock unchanged, status recorded
    big2 = adjust(clerk, cid, pid, 3000, "found", None)
    rej = client.post(
        S(cid, f"/adjustments/{big2.json()['operation_id']}/reject"), json={"note": "غير مبرر"}
    )
    assert (
        rej.status_code == 200
        and rej.json()["status"] == "rejected"
        and on_hand(url, db, pid) == 1000.0
    )
    # an approver cannot approve a request they raised themselves
    mgr = login(client, cid, "manager")
    assert adjust(mgr, cid, pid, 1001, "found").status_code == 201  # managers act directly


def test_opening_balance_is_a_separate_validated_owner_step(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    p1, d1 = product(client, cid, url, db, name="رز", stock=0, auto_barcode="internal")
    p2, d2 = product(client, cid, url, db, name="عدس", stock=0, auto_barcode="internal")
    p3, d3 = product(
        client, cid, url, db, name="زيت", stock=5, auto_barcode="internal"
    )  # already moved
    clerk = login(client, cid, "inventory_operator")
    rows = [
        {"barcode": d1["barcode"], "qty": "40", "unit_cost": "12,5"},
        {"barcode": d2["barcode"], "qty": "-3"},
        {"barcode": d3["barcode"], "qty": "10"},
        {"barcode": "9999999999999", "qty": "1"},
        {"barcode": d1["barcode"], "qty": "9"},
    ]
    v = clerk.post(S(cid, "/opening/validate"), json={"rows": rows})
    assert v.status_code == 200, v.text
    vj = v.json()
    assert [r["ok"] for r in vj["rows"]] == [True, False, False, False, False]
    assert (
        "already has stock movement" in vj["rows"][2]["errors"][0]
        and "repeated" in vj["rows"][4]["errors"][0]
    )
    assert on_hand(url, db, p1) == 0.0  # validating posted nothing
    assert (
        clerk.post(
            S(cid, "/opening/commit"), params={"import_id": vj["import_id"]}, json={"rows": rows}
        ).status_code
        == 403
    )
    done = client.post(
        S(cid, "/opening/commit"), params={"import_id": vj["import_id"]}, json={"rows": rows}
    )
    assert done.status_code == 200, done.text
    assert done.json()["posted_rows"] == 1 and done.json()["batches"][0]["status"] == "posted"
    assert on_hand(url, db, p1) == 40.0 and on_hand(url, db, p3) == 5.0
    assert (
        rpc(url, db)("product.product", "read", [p1], fields=["standard_price"])[0][
            "standard_price"
        ]
        == 12.5
    )
    ov = client.get(S(cid, "/overview"), params={"q": "رز"}).json()["items"][0]
    assert ov["value"] == 500.0  # 40 x 12.5, valued at the opening cost
    again = client.post(
        S(cid, "/opening/commit"), params={"import_id": vj["import_id"]}, json={"rows": rows}
    ).json()
    assert (
        again["batches"][0]["status"] == "replayed" and on_hand(url, db, p1) == 40.0
    )  # never posted twice


def test_roles_and_cost_visibility_and_isolation(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db, stock=3)
    cashier, clerk, acc = (
        login(client, cid, "cashier"),
        login(client, cid, "inventory_operator"),
        login(client, cid, "accountant"),
    )
    assert cashier.get(S(cid, "/overview")).status_code == 403
    assert (
        acc.get(S(cid, "/overview")).status_code == 200
        and "value" in acc.get(S(cid, "/overview")).json()["items"][0]
    )
    row = clerk.get(S(cid, "/overview")).json()["items"][0]
    assert "cost" not in row and "value" not in row and row["on_hand"] == 3
    assert (
        acc.post(
            S(cid, "/adjustments"),
            json={"lines": [{"product_id": pid, "counted_qty": 1}]},
            headers=idem(),
        ).status_code
        == 403
    )
    other = TestClient(create_app())
    make_owner(other, f"{uuid.uuid4().hex[:8]}@example.com", business="Other")
    assert other.get(S(cid, "/overview")).status_code == 404
    assert other.get(S(cid, "/adjustments")).status_code == 404
