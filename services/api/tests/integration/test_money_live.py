"""Expenses and the money overview against throwaway copies of Odoo CE 18/19."""

import datetime
import uuid

from fastapi.testclient import TestClient
from tests.conftest import make_owner
from tests.integration.test_purchasing_live import login, q  # noqa: F401
from tests.integration.test_sales_live import idem, shop  # noqa: F401
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401

from elblasy_api.main import create_app
from elblasy_api.odoo.client import BridgeClient, OdooUncertainError

TODAY = datetime.date.today().isoformat()


def M(cid, path=""):
    return f"/connections/{cid}/money{path}"


def category(client, cid, label="إيجار", index=0):
    accts = client.get(M(cid, "/expense-accounts")).json()["items"]
    r = client.post(M(cid, "/categories"), json={"account_id": accts[index]["id"], "label": label})
    assert r.status_code == 201, r.text
    return r.json()


def expense(c, cid, cat, amount=500, pay=None, headers=None, **kw):
    body = {
        "category_id": cat["id"],
        "amount": amount,
        "description": "إيجار أكتوبر",
        "date": TODAY,
        **kw,
    }
    if pay:
        body["pay_now"] = {"journal_type": pay}
    return c.post(M(cid, "/expenses"), json=body, headers=headers or idem())


def cash_balance(client, cid):
    return next(
        a["balance"]
        for a in client.get(M(cid, "/overview")).json()["accounts"]
        if a["type"] == "cash"
    )


def test_categories_map_to_operating_expense_accounts_only(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    accts = client.get(M(cid, "/expense-accounts")).json()["items"]
    assert accts and not any(
        "Cost of Goods" in a["name"] for a in accts
    )  # cost of sales is a different figure
    cat = category(client, cid, "إيجار")
    assert (
        client.post(
            M(cid, "/categories"), json={"account_id": accts[0]["id"], "label": "تكرار"}
        ).status_code
        == 409
    )
    receivable = rpc(url, db)(
        "account.account", "search", [["account_type", "=", "asset_receivable"]]
    )[0]
    assert (
        client.post(
            M(cid, "/categories"), json={"account_id": receivable, "label": "خطأ"}
        ).status_code
        == 422
    )
    acc, clerk = login(client, cid, "accountant"), login(client, cid, "inventory_operator")
    assert (
        acc.post(
            M(cid, "/categories"), json={"account_id": accts[1]["id"], "label": "x"}
        ).status_code
        == 403
    )
    assert [c["label"] for c in acc.get(M(cid, "/categories")).json()["items"]] == [
        "إيجار"
    ]  # but may use them
    assert clerk.get(M(cid, "/categories")).status_code == 403
    assert client.delete(M(cid, f"/categories/{cat['id']}")).status_code == 204
    assert client.get(M(cid, "/categories")).json()["items"] == []
    assert expense(client, cid, cat).status_code == 422  # a deactivated category cannot be used


def test_an_expense_is_a_bill_not_automatically_a_payment(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    cat = category(client, cid)
    h = idem()
    r = expense(client, cid, cat, 500, headers=h, ref="R-77")
    assert r.status_code == 201, r.text
    e = r.json()["expense"]
    assert (
        e["state"] == "posted" and e["payment_state"] == "not_paid" and e["amount_residual"] == 500
    )  # owed, not paid
    assert r.json()["taxes_applied"] is False and e["amount_total"] == 500
    assert expense(client, cid, cat, 500, headers=h, ref="R-77").json()["replayed"] is True
    assert (
        expense(client, cid, cat, 999, headers=h).status_code == 409
    )  # same key, different request
    bills = q(
        url,
        db,
        "account.move",
        [["move_type", "=", "in_invoice"]],
        ["state", "amount_total", "amount_tax", "payment_state", "ref"],
    )
    assert (
        len(bills) == 1
        and bills[0]["amount_tax"] == 0
        and bills[0]["ref"] == "R-77"
        and bills[0]["payment_state"] == "not_paid"
    )
    assert cash_balance(client, cid) == 0  # nothing left the drawer yet
    ov = client.get(M(cid, "/overview")).json()
    assert (
        ov["payables"]["total"] == 500 and ov["net_profit"]["available"] is False
    )  # owed shows up as a payable

    paid = expense(client, cid, cat, 120, pay="cash", description="كهرباء")
    assert paid.status_code == 201 and paid.json()["expense"]["payment_state"] in (
        "paid",
        "in_payment",
    )
    assert cash_balance(client, cid) == -120  # the drawer fell by what was paid now
    led = client.get(M(cid, "/ledger"), params={"kind": "cash"}).json()["items"]
    assert led[0]["amount"] == -120

    s = client.get(M(cid, "/overview")).json()["expenses_month"]
    assert (s["incurred"], s["paid"], s["still_owed"]) == (620, 120, 500)  # three different numbers

    # pay the credit expense later, in two parts; overpaying is refused
    unpaid = e["id"]
    acc = login(client, cid, "accountant")
    p1 = acc.post(
        M(cid, f"/expenses/{unpaid}/pay"),
        json={"amount": 200, "journal_type": "cash"},
        headers=idem(),
    )
    assert p1.status_code == 201, p1.text
    assert p1.json()["expense"]["amount_residual"] == 300 and cash_balance(client, cid) == -320
    assert (
        acc.post(
            M(cid, f"/expenses/{unpaid}/pay"),
            json={"amount": 301, "journal_type": "cash"},
            headers=idem(),
        ).status_code
        == 422
    )
    assert (
        acc.post(
            M(cid, f"/expenses/{unpaid}/pay"),
            json={"amount": 300, "journal_type": "cash"},
            headers=idem(),
        ).status_code
        == 201
    )
    assert client.get(M(cid, "/overview")).json()["payables"]["total"] == 0
    assert q(url, db, "account.move", [["id", "=", unpaid]], ["payment_state"])[0][
        "payment_state"
    ] in ("paid", "in_payment")


def test_expense_lost_response_creates_exactly_one_bill(shop, monkeypatch):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    cat = category(client, cid)
    real, armed = BridgeClient.call_bridge, {"on": True}

    def flaky(self, method, *a, **k):
        res = real(self, method, *a, **k)
        if method == "expense_create" and armed["on"]:
            armed["on"] = False
            raise OdooUncertainError("Odoo connection problem: ConnectionResetError")
        return res

    monkeypatch.setattr(BridgeClient, "call_bridge", flaky)
    h = idem()
    lost = expense(client, cid, cat, 250, pay="cash", headers=h)
    assert lost.status_code == 502 and lost.json()["error"]["code"] == "outcome_unknown"
    assert len(q(url, db, "account.move", [["move_type", "=", "in_invoice"]], ["id"])) == 1
    retry = expense(client, cid, cat, 250, pay="cash", headers=h)
    assert retry.status_code == 201 and retry.json()["outcome"] == "already_exists"
    assert len(q(url, db, "account.move", [["move_type", "=", "in_invoice"]], ["id"])) == 1
    assert (
        len(q(url, db, "account.payment", [], ["id"])) == 1 and cash_balance(client, cid) == -250
    )  # paid once


def test_large_expenses_by_an_accountant_wait_for_the_owner(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    cat = category(client, cid)
    acc = login(client, cid, "accountant")
    assert expense(acc, cid, cat, 800).status_code == 201  # under the threshold: direct
    h = idem()
    big = expense(acc, cid, cat, 5000, headers=h)
    assert big.status_code == 202, big.text
    op = big.json()["operation_id"]
    assert (
        len(q(url, db, "account.move", [["move_type", "=", "in_invoice"]], ["id"])) == 1
    )  # nothing booked yet
    assert expense(acc, cid, cat, 5000, headers=h).status_code == 202
    assert (
        acc.post(M(cid, f"/expense-requests/{op}/approve")).status_code == 403
    )  # an accountant cannot approve
    assert len(client.get(M(cid, "/expense-requests")).json()["items"]) == 1
    ok = client.post(M(cid, f"/expense-requests/{op}/approve"))
    assert ok.status_code == 200, ok.text
    bills = q(
        url,
        db,
        "account.move",
        [["move_type", "=", "in_invoice"]],
        ["amount_total", "invoice_line_ids"],
    )
    assert sorted(b["amount_total"] for b in bills) == [800, 5000]
    names = [
        ln["name"]
        for ln in q(
            url,
            db,
            "account.move.line",
            [
                ["move_id.move_type", "=", "in_invoice"],
                ["display_type", "in", ["product", False]],
                ["account_id.account_type", "=", "expense"],
            ],
            ["name"],
        )
    ]
    assert any(
        "entered by" in n and "approved by" in n for n in names
    )  # both people are on the Odoo record
    assert client.post(M(cid, f"/expense-requests/{op}/approve")).status_code == 409
    again = expense(acc, cid, cat, 4000)
    rej = client.post(
        M(cid, f"/expense-requests/{again.json()['operation_id']}/reject"),
        json={"note": "غير مبرر"},
    )
    assert (
        rej.status_code == 200
        and len(q(url, db, "account.move", [["move_type", "=", "in_invoice"]], ["id"])) == 2
    )


def test_money_screens_are_finance_only_and_isolated(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    cat = category(client, cid)
    cashier, clerk, acc = (
        login(client, cid, "cashier"),
        login(client, cid, "inventory_operator"),
        login(client, cid, "accountant"),
    )
    for who in (cashier, clerk):
        assert (
            who.get(M(cid, "/overview")).status_code == 403
            and who.get(M(cid, "/expenses")).status_code == 403
        )
        assert expense(who, cid, cat).status_code == 403
    assert acc.get(M(cid, "/overview")).status_code == 200
    assert (
        expense(client, cid, cat, 0).status_code == 422
        and expense(client, cid, cat, -5).status_code == 422
    )
    assert (
        client.post(
            M(cid, "/expenses"), json={"category_id": cat["id"], "amount": 5, "description": "x"}
        ).status_code
        == 422
    )  # no key
    other = TestClient(create_app())
    make_owner(other, f"{uuid.uuid4().hex[:8]}@example.com", business="Other")
    assert (
        other.get(M(cid, "/overview")).status_code == 404
        and other.get(M(cid, "/categories")).status_code == 404
    )
