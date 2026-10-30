"""Kits (sold as one item, components leave stock at the sale) and editable recipes with their cost."""

from tests.integration.test_purchasing_live import login
from tests.integration.test_sales_live import idem, on_hand, open_register, product, sell, shop  # noqa: F401
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401


def install_mrp(url, db):
    c = rpc(url, db)
    c(
        "ir.module.module",
        "button_immediate_install",
        c("ir.module.module", "search", [["name", "=", "mrp"]]),
    )


def test_kit_sold_at_the_till_takes_its_components_out_of_stock(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    install_mrp(url, db)
    sugar, s_ = product(client, cid, url, db, name="سكر", price=30, stock=50, cost=20)
    tea, t_ = product(client, cid, url, db, name="شاي", price=40, stock=50, cost=25)
    box, b_ = product(client, cid, url, db, name="سلة رمضان", price=150, stock=0)
    recipe = {
        "template_id": b_["template_id"],
        "quantity": 1,
        "kind": "kit",
        "components": [
            {"template_id": s_["template_id"], "qty": 2},
            {"template_id": t_["template_id"], "qty": 1},
        ],
    }
    r = client.post(f"/connections/{cid}/catalog/recipes", json=recipe, headers=idem())
    assert r.status_code == 201, r.text
    got = r.json()["recipe"]
    assert (
        got["kind"] == "kit" and got["unit_cost"] == 65 and got["margin"] == 85
    )  # 2x20 + 1x25 against 150
    clerk = login(client, cid, "cashier")
    hidden = clerk.get(f"/connections/{cid}/catalog/recipes/{b_['template_id']}").json()
    assert "unit_cost" not in hidden and "cost" not in hidden["components"][0]

    open_register(client, cid, cfg)
    q, sale = sell(client, cid, cfg, cash, box, qty=3, pay=1000)
    assert sale.status_code == 201, sale.text
    assert (
        on_hand(url, db, sugar) == 44 and on_hand(url, db, tea) == 47
    )  # the kit's parts left the shelf

    # change the kit for future sales: now 1 sugar + 2 tea
    edit = {
        **recipe,
        "replace": True,
        "components": [
            {"template_id": s_["template_id"], "qty": 1},
            {"template_id": t_["template_id"], "qty": 2},
        ],
    }
    e = client.post(f"/connections/{cid}/catalog/recipes", json=edit, headers=idem())
    assert (
        e.status_code == 201
        and e.json()["outcome"] == "updated"
        and e.json()["recipe"]["unit_cost"] == 70
    )
    q, sale2 = sell(client, cid, cfg, cash, box, qty=1, pay=1000)
    assert sale2.status_code == 201
    assert on_hand(url, db, sugar) == 43 and on_hand(url, db, tea) == 45
    no_replace = client.post(f"/connections/{cid}/catalog/recipes", json=recipe, headers=idem())
    assert (
        no_replace.status_code == 422 and "edit it instead" in no_replace.json()["error"]["message"]
    )
