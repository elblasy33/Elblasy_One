"""Financial report: figures must match independent reads of the accounting entries."""

from tests.integration.test_money_live import category, expense, login
from tests.integration.test_sales_live import idem, open_register, product, sell, shop  # noqa: F401
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401


def test_income_statement_and_cash_flow_follow_posted_entries(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    pid, _ = product(client, cid, url, db, price=100, stock=50, cost=40)
    sess = open_register(client, cid, cfg)
    q, sale = sell(client, cid, cfg, cash, pid, qty=2, pay=1000)
    total = sale.json()["order"]["amount_total"]
    before = client.get(f"/connections/{cid}/money/report").json()
    assert (
        before["unclosed_sessions"] == 1 and before["income"]["total"] == 0
    )  # not in accounting yet
    closed = client.post(
        f"/connections/{cid}/sales/sessions/{sess['id']}/close",
        json={"counted_cash": total},
        headers=idem(),
    )
    assert closed.status_code == 200, closed.text
    cat = category(client, cid)
    assert expense(client, cid, cat, 30, pay="cash", description="كهرباء").status_code == 201

    rep = client.get(f"/connections/{cid}/money/report").json()
    assert rep["unclosed_sessions"] == 0
    untaxed = total - sale.json()["order"]["amount_tax"]
    assert abs(rep["income"]["total"] - untaxed) < 0.02, rep["income"]
    c = rpc(url, db)
    lines = c(
        "account.move.line",
        "search_read",
        [
            ["parent_state", "=", "posted"],
            ["account_id.account_type", "in", ["income", "income_other"]],
        ],
        fields=["balance"],
    )
    assert abs(rep["income"]["total"] + sum(x["balance"] for x in lines)) < 0.02  # independent read
    assert (
        abs(
            rep["net_profit"]
            - (rep["income"]["total"] - rep["cogs"]["total"] - rep["expenses"]["total"])
        )
        < 0.02
    )
    cashrow = next(r for r in rep["cash_flow"] if r["type"] == "cash")
    assert (
        cashrow["in"] >= total - 0.01
        and abs(cashrow["closing"] - (cashrow["opening"] + cashrow["in"] - cashrow["out"])) < 0.01
    )

    assert (
        client.get(
            f"/connections/{cid}/money/report", params={"from": "2030-02-01", "to": "2030-01-01"}
        ).status_code
        == 422
    )
    empty = client.get(
        f"/connections/{cid}/money/report", params={"from": "2001-01-01", "to": "2001-01-31"}
    ).json()
    assert empty["income"]["total"] == 0 and empty["net_profit"] == 0
    assert client.get(f"/connections/{cid}/money/report").status_code == 200
    assert login(client, cid, "cashier").get(f"/connections/{cid}/money/report").status_code == 403
