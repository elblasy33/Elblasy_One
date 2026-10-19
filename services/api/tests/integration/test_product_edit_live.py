"""Editing, categorising and archiving products; verified by independent reads of Odoo."""

from tests.integration.test_money_live import login  # noqa: F401
from tests.integration.test_sales_live import idem, product, rpc, shop  # noqa: F401
from tests.integration.test_setup_execution_live import fresh  # noqa: F401


def patch(client, cid, tid, **body):
    return client.patch(f"/connections/{cid}/catalog/products/{tid}", json=body, headers=idem())


def test_edit_fields_archive_rules_and_permissions(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    pid, made = product(client, cid, url, db, name="ارز", price=20, stock=5)
    tid = made["template_id"]
    other, _ = product(client, cid, url, db, name="سكر", price=10, stock=0, barcode="7777001")

    ok = patch(
        client, cid, tid, name="ارز مصري", price=22.5, cost=15, category="بقالة", sku="RICE-1"
    )
    assert ok.status_code == 200, ok.text
    t = rpc(url, db)(
        "product.template",
        "read",
        [tid],
        fields=["name", "list_price", "standard_price", "categ_id", "default_code"],
    )[0]
    assert (t["name"], t["list_price"], t["standard_price"], t["default_code"]) == (
        "ارز مصري",
        22.5,
        15,
        "RICE-1",
    )
    assert t["categ_id"][1].endswith("بقالة")
    assert "بقالة" in client.get(f"/connections/{cid}/catalog/categories").json()["items"][
        0
    ] or any(
        "بقالة" in c for c in client.get(f"/connections/{cid}/catalog/categories").json()["items"]
    )

    clash = patch(client, cid, tid, barcode="7777001")
    assert clash.status_code == 422 and "already used" in clash.json()["error"]["message"]
    assert patch(client, cid, tid, barcode="7777002").status_code == 200
    assert patch(client, cid, tid).status_code == 422  # nothing to change

    blocked = patch(client, cid, tid, active=False)  # 5 on the shelf
    assert blocked.status_code == 422 and "still has stock" in blocked.json()["error"]["message"]
    c = rpc(url, db)
    quants = c(
        "stock.quant",
        "search",
        [["product_id", "=", made["variant_ids"][0]], ["location_id.usage", "=", "internal"]],
    )
    c("stock.quant", "write", quants, {"inventory_quantity": 0})
    try:
        c("stock.quant", "action_apply_inventory", quants)
    except Exception as exc:  # noqa: BLE001 - Odoo cannot marshal the None this method returns
        assert "marshal None" in str(exc)
    assert patch(client, cid, tid, active=False).status_code == 200
    names = [p["name"] for p in client.get(f"/connections/{cid}/catalog/products").json()["items"]]
    assert "ارز مصري" not in names
    arch = client.get(f"/connections/{cid}/catalog/products", params={"archived": True}).json()
    assert [p["name"] for p in arch["items"]] == ["ارز مصري"]
    assert patch(client, cid, tid, active=True).status_code == 200
    assert any(
        p["name"] == "ارز مصري"
        for p in client.get(f"/connections/{cid}/catalog/products").json()["items"]
    )

    clerk = login(client, cid, "inventory_operator")
    assert patch(clerk, cid, tid, price=1).status_code == 200  # may edit products
    assert patch(clerk, cid, tid, cost=1).status_code == 403  # but not costs
    cashier = login(client, cid, "cashier")
    assert patch(cashier, cid, tid, price=1).status_code == 403
    audit = client.get("/audit").json()["items"]
    assert any(a["action"] == "catalog.product.archive" for a in audit)
