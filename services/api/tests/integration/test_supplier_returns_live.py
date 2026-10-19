"""Returning goods to a supplier, with a credit note when the order was billed."""

from tests.integration.test_purchasing_live import P, login, order, supplier
from tests.integration.test_sales_live import idem, on_hand, product, shop  # noqa: F401
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401


def test_return_before_and_after_billing_with_credit_note(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db, name="سكر", price=35.5, stock=0)
    sup = supplier(client, cid)
    po = order(client, cid, sup, pid, qty=10, price=20)
    line = po["lines"][0]["id"]
    rec = client.post(
        P(cid, f"/orders/{po['id']}/receive"),
        json={"lines": [{"line_id": line, "qty": 10}]},
        headers=idem(),
    )
    assert rec.status_code == 201, rec.text
    assert on_hand(url, db, pid) == 10

    # unbilled: goods go back, no credit note
    h = idem()
    body = {"lines": [{"line_id": line, "qty": 3}], "reason": "تالف"}
    r = client.post(P(cid, f"/orders/{po['id']}/return"), json=body, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["credit_note"] is None and r.json()["order"]["lines"][0]["received"] == 7
    assert on_hand(url, db, pid) == 7
    assert (
        client.post(P(cid, f"/orders/{po['id']}/return"), json=body, headers=h).json()["replayed"]
        is True
    )
    assert on_hand(url, db, pid) == 7

    # more than received is refused
    over = client.post(
        P(cid, f"/orders/{po['id']}/return"),
        json={"lines": [{"line_id": line, "qty": 8}]},
        headers=idem(),
    )
    assert over.status_code == 422 and "cannot return" in over.json()["error"]["message"]

    # billed: a clerk may not (accounting), the owner can and a posted credit note appears
    bill = client.post(P(cid, f"/orders/{po['id']}/bill"), headers=idem())
    assert bill.status_code == 201, bill.text
    clerk = login(client, cid, "inventory_operator")
    denied = clerk.post(
        P(cid, f"/orders/{po['id']}/return"),
        json={"lines": [{"line_id": line, "qty": 1}]},
        headers=idem(),
    )
    assert denied.status_code == 403

    def owed():
        return client.get(P(cid, f"/suppliers/{sup}/statement")).json()["supplier"]["balance"]

    before = owed()
    ok = client.post(
        P(cid, f"/orders/{po['id']}/return"),
        json={"lines": [{"line_id": line, "qty": 2}]},
        headers=idem(),
    )
    assert ok.status_code == 201, ok.text
    note = ok.json()["credit_note"]
    assert (
        note["move_type"] == "in_refund" and note["state"] == "posted" and note["amount_total"] > 40
    )
    assert on_hand(url, db, pid) == 5
    notes = rpc(url, db)(
        "account.move",
        "search_read",
        [["move_type", "=", "in_refund"]],
        fields=["amount_total", "state"],
    )
    assert len(notes) == 1 and notes[0]["state"] == "posted"
    assert owed() < before  # the credit note reduced what is owed
