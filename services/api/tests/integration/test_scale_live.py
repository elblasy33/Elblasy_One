"""Labels printed by the shop's existing scales: weight or price inside the barcode, in the shop's own format."""

from tests.integration.test_purchasing_live import login
from tests.integration.test_sales_live import idem, on_hand, open_register, shop  # noqa: F401
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401


def ean13(d12):
    return d12 + str((10 - sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(d12)) % 10) % 10)


def test_legacy_price_and_weight_labels_sell_the_right_product(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    base = f"/connections/{cid}"
    # the old system prints "27" + 4-digit item number + price with 2 decimals (6 digits): 27 PPPP VVVVVV C
    h = idem()
    price_rule = {
        "prefix": "27",
        "plu_digits": 4,
        "kind": "price",
        "int_digits": 4,
        "dec_digits": 2,
    }
    r = client.post(f"{base}/scale/rules", json=price_rule, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["rule"]["pattern"] == "27....{NNNNDD}"
    assert client.post(f"{base}/scale/rules", json=price_rule, headers=h).json()["replayed"] is True
    bad = client.post(f"{base}/scale/rules", json={**price_rule, "plu_digits": 5}, headers=idem())
    assert bad.status_code == 422  # 13 digits: refused, nothing written
    # and a weight format: "28" + 5-digit item + grams (5 digits: kg with 3 decimals)
    w = client.post(
        f"{base}/scale/rules",
        json={"prefix": "28", "plu_digits": 5, "kind": "weight", "int_digits": 2, "dec_digits": 3},
        headers=idem(),
    )
    assert w.status_code == 201, w.text
    rules = {
        x["format"]["prefix"]: x
        for x in client.get(f"{base}/scale/rules").json()["items"]
        if x["format"]
    }
    assert {"27", "28"} <= set(rules)

    # products get the barcode their labels point to, from their item number on the scale
    cheese = client.post(
        f"{base}/catalog/products",
        json={
            "name": "جبنة رومي",
            "price": 200,
            "kind": "weight",
            "scale_rule_id": rules["27"]["id"],
            "scale_plu": "0042",
        },
        headers=idem(),
    )
    assert cheese.status_code == 201, cheese.text
    meat = client.post(
        f"{base}/catalog/products",
        json={
            "name": "لحمة",
            "price": 400,
            "kind": "weight",
            "scale_rule_id": rules["28"]["id"],
            "scale_plu": "123",
        },
        headers=idem(),
    )
    assert meat.status_code == 201, meat.text
    c = rpc(url, db)
    assert c("product.product", "read", [cheese.json()["variant_ids"][0]], fields=["barcode"])[0][
        "barcode"
    ] == ean13("270042000000")

    # a label for 150.00 of cheese (0.75 kg at 200/kg), and 1.250 kg of meat
    label = ean13("270042015000")
    parsed = client.get(f"{base}/scale/parse", params={"code": label}).json()
    assert parsed["type"] == "price" and parsed["value"] == 150 and parsed["product"] == "جبنة رومي"
    hit = client.get(f"{base}/sales/lookup", params={"config_id": cfg, "code": label}).json()
    assert hit["found"] and hit["qty"] == 0.75
    hit2 = client.get(
        f"{base}/sales/lookup", params={"config_id": cfg, "code": ean13("280012301250")}
    ).json()
    assert (
        hit2["found"]
        and hit2["product_id"] == meat.json()["variant_ids"][0]
        and hit2["qty"] == 1.25
    )
    assert (
        login(client, cid, "inventory_operator")
        .post(f"{base}/scale/rules", json=price_rule, headers=idem())
        .status_code
        == 403
    )
