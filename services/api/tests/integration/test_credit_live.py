"""Credit sales, customers and receivables against throwaway copies of Odoo CE 18/19."""

import uuid

import pytest
from tests.conftest import make_owner
from tests.integration.test_connections_api import body
from tests.integration.test_money_live import login  # noqa: F401
from tests.integration.test_purchasing_live import q  # noqa: F401
from tests.integration.test_sales_live import idem, on_hand, open_register, product  # noqa: F401
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401

from elblasy_api.odoo.client import BridgeClient, OdooUncertainError

CREDIT = {
    "vertical": "general",
    "payment_methods": ["cash"],
    "buys_on_credit": False,
    "sells_on_credit": True,
}


def run_setup(client, cid, answers):
    plan = client.post(f"/connections/{cid}/setup/plans", json={"answers": answers}).json()
    if plan["plan"]["summary"]["to_apply"]:
        client.post(f"/connections/{cid}/setup/plans/{plan['id']}/approve")
        assert (
            client.post(f"/connections/{cid}/setup/plans/{plan['id']}/execute").status_code == 202
        )
        done = client.get(f"/connections/{cid}/setup/plans/{plan['id']}").json()
        assert done["status"] == "completed", {
            k: v.get("error")
            for k, v in done["execution"]["steps"].items()
            if v["status"] != "succeeded"
        }
    return plan


@pytest.fixture
def cshop(client, fresh):  # noqa: F811
    _, url, db = fresh
    make_owner(client, f"{uuid.uuid4().hex[:8]}@example.com")
    cid = client.post("/connections", json=body(url, db)).json()["id"]
    run_setup(client, cid, CREDIT)
    cfg = client.get(f"/connections/{cid}/sales/state").json()["configs"][0]
    methods = {
        ("credit" if m["is_credit"] else "cash" if m["is_cash"] else "other"): m["id"]
        for m in cfg["payment_methods"]
    }
    return client, cid, url, db, cfg["id"], methods


def customer(c, cid, name="عميل آجل", **kw):
    r = c.post(
        f"/connections/{cid}/customers", json={"name": name, "phone": "0100", **kw}, headers=idem()
    )
    assert r.status_code == 201, r.text
    return r.json()["customer"]


def credit_sale(
    c, cid, cfg, methods, pid, partner=None, qty=2, cash=50.0, override=False, key=None
):
    quote = c.post(
        f"/connections/{cid}/sales/quote",
        json={"config_id": cfg, "lines": [{"product_id": pid, "qty": qty}]},
    ).json()
    total = quote["total"]
    pays = ([{"payment_method_id": methods["cash"], "amount": cash}] if cash else []) + [
        {"payment_method_id": methods["credit"], "amount": round(total - cash, 2)}
    ]
    data = {
        "config_id": cfg,
        "lines": [{"product_id": pid, "qty": qty}],
        "expected_total": total,
        "payments": pays,
        "override_credit_limit": override,
        **({"partner_id": partner} if partner else {}),
    }
    return total, c.post(
        f"/connections/{cid}/sales/orders",
        json=data,
        headers={"Idempotency-Key": key or uuid.uuid4().hex},
    )


def test_setup_adds_the_credit_method_and_can_attach_it_to_an_existing_pos(client, fresh):  # noqa: F811
    _, url, db = fresh
    make_owner(client, f"{uuid.uuid4().hex[:8]}@example.com")
    cid = client.post("/connections", json=body(url, db)).json()["id"]
    run_setup(
        client, cid, {"vertical": "general", "payment_methods": ["cash"], "buys_on_credit": False}
    )  # a cash-only shop first
    cfg = client.get(f"/connections/{cid}/sales/state").json()["configs"][0]
    assert not any(m["is_credit"] for m in cfg["payment_methods"])
    plan = run_setup(client, cid, CREDIT)  # later the owner decides to sell on credit
    steps = {s["key"]: s for s in plan["plan"]["steps"]}
    assert (
        steps["pos_pm_credit"]["status"] == "to_apply"
        and steps["pos_attach_credit"]["status"] == "to_apply"
    )
    cfg = client.get(f"/connections/{cid}/sales/state").json()["configs"][0]
    assert sum(m["is_credit"] for m in cfg["payment_methods"]) == 1 and any(
        m["is_cash"] for m in cfg["payment_methods"]
    )  # nothing removed
    again = client.post(f"/connections/{cid}/setup/plans", json={"answers": CREDIT}).json()
    assert again["plan"]["summary"]["to_apply"] == 0


def test_a_credit_sale_becomes_an_open_invoice_collected_later(cshop):
    client, cid, url, db, cfg, methods = cshop
    pid, _ = product(client, cid, url, db, name="سكر", price=100, stock=50)
    cust = customer(client, cid)
    open_register(client, cid, cfg)
    total, r = credit_sale(client, cid, cfg, methods, pid, cust["id"], qty=2, cash=50)
    assert r.status_code == 201, r.text
    out = r.json()
    assert (
        out["order"]["credit_amount"] == round(total - 50, 2)
        and out["order"]["invoice"]["state"] == "posted"
    )
    assert (
        out["order"]["invoice"]["amount_residual"] == round(total - 50, 2)
        and out["receipt"]["customer"] == "عميل آجل"
    )
    assert out["receipt"]["on_account"] == round(total - 50, 2) and on_hand(url, db, pid) == 48.0
    inv_id = out["order"]["invoice"]["id"]
    inv = q(
        url,
        db,
        "account.move",
        [["id", "=", inv_id]],
        ["move_type", "state", "payment_state", "amount_residual", "partner_id"],
    )[0]
    assert (inv["move_type"], inv["state"], inv["payment_state"], inv["partner_id"][1]) == (
        "out_invoice",
        "posted",
        "partial",
        "عميل آجل",
    )

    st = client.get(f"/connections/{cid}/customers/{cust['id']}/statement").json()
    assert st["customer"]["receivable"] == round(total - 50, 2) and len(st["invoices"]) == 1
    acc = login(client, cid, "accountant")
    h = idem()
    p1 = acc.post(
        f"/connections/{cid}/customers/invoices/{inv_id}/receive",
        json={"amount": 100, "journal_type": "cash"},
        headers=h,
    )
    assert p1.status_code == 201, p1.text
    assert p1.json()["invoice"]["amount_residual"] == round(total - 150, 2)
    assert (
        acc.post(
            f"/connections/{cid}/customers/invoices/{inv_id}/receive",
            json={"amount": 100, "journal_type": "cash"},
            headers=h,
        ).json()["replayed"]
        is True
    )
    assert (
        acc.post(
            f"/connections/{cid}/customers/invoices/{inv_id}/receive",
            json={"amount": 9999, "journal_type": "cash"},
            headers=idem(),
        ).status_code
        == 422
    )
    rest = p1.json()["invoice"]["amount_residual"]
    assert (
        acc.post(
            f"/connections/{cid}/customers/invoices/{inv_id}/receive",
            json={"amount": rest, "journal_type": "cash"},
            headers=idem(),
        ).status_code
        == 201
    )
    assert (
        client.get(f"/connections/{cid}/customers/{cust['id']}/statement").json()["customer"][
            "receivable"
        ]
        == 0
    )
    assert (
        acc.post(
            f"/connections/{cid}/customers/invoices/{inv_id}/receive",
            json={"amount": 1, "journal_type": "cash"},
            headers=idem(),
        ).status_code
        == 422
    )  # settled

    # the register still closes cleanly and its accounting posts, with an invoiced order inside the session
    sess = client.get(f"/connections/{cid}/sales/state").json()["configs"][0]["session"]
    closed = client.post(
        f"/connections/{cid}/sales/sessions/{sess['id']}/close",
        json={"counted_cash": 50},
        headers=idem(),
    )
    assert closed.status_code == 200, closed.text


def test_credit_needs_a_customer_and_respects_the_limit_with_a_recorded_override(cshop):
    client, cid, url, db, cfg, methods = cshop
    pid, _ = product(client, cid, url, db, name="سكر", price=100, stock=50)
    manager, cashier = login(client, cid, "manager"), login(client, cid, "cashier")
    open_register(client, cid, cfg)
    total, none = credit_sale(client, cid, cfg, methods, pid, None, cash=50)
    assert none.status_code == 422 and none.json()["error"]["code"] == "customer_required"
    assert rpc(url, db)("pos.order", "search_count", []) == 0 and on_hand(url, db, pid) == 50.0

    cust = customer(cashier, cid, "عميل بحد")  # a cashier may add a customer...
    assert (
        "receivable" not in cust and "credit_limit" not in cust
    )  # ...but sees no finance information about them
    assert (
        cashier.put(
            f"/connections/{cid}/customers/{cust['id']}/credit-limit",
            json={"credit_limit": 150},
            headers=idem(),
        ).status_code
        == 403
    )
    assert (
        manager.put(
            f"/connections/{cid}/customers/{cust['id']}/credit-limit",
            json={"credit_limit": 150},
            headers=idem(),
        ).status_code
        == 200
    )
    over = credit_sale(cashier, cid, cfg, methods, pid, cust["id"], cash=50)[
        1
    ]  # credit 178 > limit 150
    assert over.status_code == 409 and over.json()["error"]["code"] == "credit_limit_exceeded"
    assert (
        credit_sale(cashier, cid, cfg, methods, pid, cust["id"], cash=50, override=True)[
            1
        ].status_code
        == 403
    )  # the cashier cannot override
    assert rpc(url, db)("pos.order", "search_count", []) == 0
    ok = credit_sale(manager, cid, cfg, methods, pid, cust["id"], cash=50, override=True)[1]
    assert ok.status_code == 201, ok.text
    audit = client.get("/audit", params={"action": "sales.order.create"}).json()["items"][0][
        "after"
    ]
    assert (
        audit["credit_override"] is True and audit["on_credit"] > 0
    )  # the override is on the record
    # within the limit no override is needed (a smaller credit portion)
    cust2 = customer(client, cid, "عميل آخر", credit_limit=500)
    assert credit_sale(client, cid, cfg, methods, pid, cust2["id"], cash=150)[1].status_code == 201
    listed = {c["name"]: c for c in client.get(f"/connections/{cid}/customers").json()["items"]}
    assert listed["عميل بحد"]["receivable"] > 150 and listed["عميل آخر"]["available_credit"] < 500
    assert "receivable" not in cashier.get(f"/connections/{cid}/customers").json()["items"][0]


def test_credit_sale_response_lost_then_retry_creates_one_invoice(cshop, monkeypatch):
    client, cid, url, db, cfg, methods = cshop
    pid, _ = product(client, cid, url, db, name="سكر", price=100, stock=50)
    cust = customer(client, cid)
    open_register(client, cid, cfg)
    real, armed = BridgeClient.call_bridge, {"on": True}

    def flaky(self, method, *a, **k):
        res = real(self, method, *a, **k)
        if method == "sales_checkout" and armed["on"]:
            armed["on"] = False
            raise OdooUncertainError("Odoo connection problem: ConnectionResetError")
        return res

    monkeypatch.setattr(BridgeClient, "call_bridge", flaky)
    key = uuid.uuid4().hex
    assert credit_sale(client, cid, cfg, methods, pid, cust["id"], key=key)[1].status_code == 502
    retry = credit_sale(client, cid, cfg, methods, pid, cust["id"], key=key)[1]
    assert retry.status_code == 201 and retry.json()["outcome"] == "already_exists"
    assert (
        len(q(url, db, "account.move", [["move_type", "=", "out_invoice"]], ["id"])) == 1
        and on_hand(url, db, pid) == 48.0
    )


def test_receivables_show_in_money_alerts_and_credit_sales_are_not_refunded_blindly(cshop):
    client, cid, url, db, cfg, methods = cshop
    pid, _ = product(client, cid, url, db, name="سكر", price=100, stock=50)
    cust = customer(client, cid)
    open_register(client, cid, cfg)
    total, r = credit_sale(
        client, cid, cfg, methods, pid, cust["id"], cash=0
    )  # everything on credit
    assert r.status_code == 201 and r.json()["order"]["invoice"]["amount_residual"] == total
    ov = client.get(f"/connections/{cid}/money/overview").json()
    assert ov["receivables"]["total"] == total and ov["receivables"]["top"][0]["name"] == "عميل آجل"
    keys = {a["key"] for a in client.get("/alerts").json()["items"]}
    assert "overdue_customer_invoices" not in keys  # due today, not overdue
    rpc(url, db)(
        "account.move",
        "write",
        [r.json()["order"]["invoice"]["id"]],
        {"invoice_date_due": "2020-01-15"},
    )
    items = {a["key"]: a for a in client.get("/alerts").json()["items"]}
    assert items["overdue_customer_invoices"]["detail"]["amount"] == total
    refund = client.post(
        f"/connections/{cid}/sales/orders/{r.json()['order']['id']}/refund",
        json={"payment_method_id": methods["cash"]},
        headers=idem(),
    )
    assert refund.status_code == 422 and "credit note" in refund.json()["error"]["message"]
    assert on_hand(url, db, pid) == 48.0  # unchanged
    assert client.get(f"/connections/{cid}/sales/summary").status_code == 200
