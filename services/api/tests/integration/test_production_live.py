"""Producing made products on Odoo's manufacturing orders; stock verified by independent reads."""

from tests.integration.test_catalog_live import env, prod  # noqa: F401
from tests.integration.test_sales_live import idem, on_hand, rpc, set_stock
from tests.integration.test_setup_execution_live import fresh  # noqa: F401


def test_batch_consumes_components_adds_product_and_is_idempotent(env):  # noqa: F811
    client, cid, url, db = env
    c = rpc(url, db)
    c(
        "ir.module.module",
        "button_immediate_install",
        c("ir.module.module", "search", [["name", "=", "mrp"]]),
    )

    def mk(n, stock):
        r = client.post(f"/connections/{cid}/catalog/products", json=prod(name=n), headers=idem())
        assert r.status_code == 201, r.text
        if stock:
            set_stock(url, db, r.json()["variant_ids"][0], stock)
        return r.json()

    flour, sugar, cake = mk("دقيق", 100), mk("سكر خام", 5), mk("كيك", 0)
    recipe = {
        "template_id": cake["template_id"],
        "quantity": 10,
        "components": [
            {"template_id": flour["template_id"], "qty": 2},
            {"template_id": sugar["template_id"], "qty": 1.5},
        ],
    }
    assert (
        client.post(f"/connections/{cid}/catalog/recipes", json=recipe, headers=idem()).status_code
        == 201
    )

    listed = client.get(f"/connections/{cid}/production/recipes").json()["items"]
    row = next(r for r in listed if r["template_id"] == cake["template_id"])
    assert row["yield"] == 10 and abs(row["can_make"] - 33.33) < 0.1 * 10  # sugar limits: 5 / 0.15
    assert {x["name"] for x in row["components"]} == {"دقيق", "سكر خام"}

    h = idem()
    body = {"template_id": cake["template_id"], "qty": 20}
    r = client.post(f"/connections/{cid}/production/batches", json=body, headers=h)
    assert r.status_code == 201, r.text
    assert on_hand(url, db, cake["variant_ids"][0]) == 20
    assert on_hand(url, db, flour["variant_ids"][0]) == 96  # 20/10 * 2 = 4 used
    assert on_hand(url, db, sugar["variant_ids"][0]) == 2  # 20/10 * 1.5 = 3 used
    again = client.post(f"/connections/{cid}/production/batches", json=body, headers=h)
    assert again.json()["replayed"] is True and on_hand(url, db, cake["variant_ids"][0]) == 20

    short = client.post(
        f"/connections/{cid}/production/batches", json={**body, "qty": 40}, headers=idem()
    )
    assert short.status_code == 422 and "Not enough components" in short.json()["error"]["message"]
    assert on_hand(url, db, cake["variant_ids"][0]) == 20  # nothing half-produced
    assert (
        client.post(
            f"/connections/{cid}/production/batches",
            json={"template_id": flour["template_id"], "qty": 1},
            headers=idem(),
        ).status_code
        == 422
    )

    hist = client.get(f"/connections/{cid}/production/history").json()["items"]
    assert len(hist) == 1 and hist[0]["qty_produced"] == 20 and hist[0]["state"] == "done"
    assert any(a["action"] == "production.batch" for a in client.get("/audit").json()["items"])
