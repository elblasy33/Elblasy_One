"""Catalogue against throwaway copies of the CE 18/19 template DBs (real Odoo, real PostgreSQL)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from tests.conftest import make_owner
from tests.integration.test_connections_api import body
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401

from elblasy_api.catalog_barcode import ean13_check_digit, internal_barcode, scale_barcode
from elblasy_api.main import create_app
from elblasy_api.odoo.client import BridgeClient, OdooUncertainError


def idem():
    return {"Idempotency-Key": uuid.uuid4().hex}


def enable(url, db, field):
    c = rpc(url, db)
    sid = c("res.config.settings", "create", {field: True})
    c("res.config.settings", "execute", [sid])


@pytest.fixture
def env(client, fresh):  # noqa: F811
    series, url, db = fresh
    make_owner(client, f"{uuid.uuid4().hex[:8]}@example.com")
    cid = client.post("/connections", json=body(url, db)).json()["id"]
    return client, cid, url, db


def prod(**kw):
    return {"name": "سكر 1 كيلو", "price": 35.5, "cost": 30, **kw}


def count(url, db, name):
    return rpc(url, db)("product.template", "search_count", [["name", "=", name]])


def test_create_verify_search_and_cost_visibility(env):
    client, cid, url, db = env
    r = client.post(
        f"/connections/{cid}/catalog/products",
        json=prod(barcode="6221234567890", category="بقالة"),
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["outcome"] == "created" and p["barcode"] == "6221234567890" and p["replayed"] is False
    o = rpc(url, db)(
        "product.template",
        "read",
        [p["template_id"]],
        fields=[
            "name",
            "list_price",
            "standard_price",
            "barcode",
            "is_storable",
            "available_in_pos",
        ],
    )[0]
    assert (o["list_price"], o["standard_price"], o["barcode"]) == (35.5, 30.0, "6221234567890")
    assert o["is_storable"] and o["available_in_pos"]

    s = client.get(f"/connections/{cid}/catalog/products", params={"q": "سكر"}).json()
    assert s["total"] == 1 and s["items"][0]["cost"] == 30.0 and s["items"][0]["on_hand"] == 0.0
    assert (
        client.get(f"/connections/{cid}/catalog/products", params={"q": "6221234"}).json()["total"]
        == 1
    )  # barcode search

    # a cashier may look products up, never sees cost, and cannot create
    email = f"c{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/users",
        json={"email": email, "password": "cashier-password-1", "role": "cashier"},
    )
    cash = TestClient(create_app())
    cash.post("/auth/login", json={"email": email, "password": "cashier-password-1"})
    # cashier lacks connections.manage, but catalogue access is by products.view on the tenant's connection
    view = cash.get(f"/connections/{cid}/catalog/products", params={"q": "سكر"})
    assert view.status_code == 200 and "cost" not in view.json()["items"][0]
    assert (
        cash.post(
            f"/connections/{cid}/catalog/products", json=prod(name="x"), headers=idem()
        ).status_code
        == 403
    )


def test_idempotent_retry_and_key_reuse(env):
    client, cid, url, db = env
    h = idem()
    a = client.post(f"/connections/{cid}/catalog/products", json=prod(), headers=h)
    b = client.post(f"/connections/{cid}/catalog/products", json=prod(), headers=h)
    assert a.status_code == b.status_code == 201
    assert b.json()["replayed"] is True and a.json()["template_id"] == b.json()["template_id"]
    assert count(url, db, "سكر 1 كيلو") == 1
    other = client.post(f"/connections/{cid}/catalog/products", json=prod(price=40), headers=h)
    assert other.status_code == 409 and other.json()["error"]["code"] == "idempotency_conflict"
    assert (
        client.post(f"/connections/{cid}/catalog/products", json=prod()).status_code == 422
    )  # key is mandatory
    # a new key is a new product (the user's intent), not a replay
    assert (
        client.post(f"/connections/{cid}/catalog/products", json=prod(), headers=idem()).status_code
        == 201
    )
    assert count(url, db, "سكر 1 كيلو") == 2


def test_lost_response_then_retry_creates_exactly_one(env, monkeypatch):
    client, cid, url, db = env
    real = BridgeClient.call_bridge
    state = {"armed": True}

    def flaky(self, method, *a, **k):
        res = real(self, method, *a, **k)
        if method == "catalog_upsert_product" and state["armed"]:
            state["armed"] = False
            raise OdooUncertainError(
                "Odoo connection problem: ConnectionResetError"
            )  # applied, answer lost
        return res

    monkeypatch.setattr(BridgeClient, "call_bridge", flaky)
    h = idem()
    r1 = client.post(
        f"/connections/{cid}/catalog/products", json=prod(name="Lost response"), headers=h
    )
    assert r1.status_code == 502 and r1.json()["error"]["code"] == "outcome_unknown"
    assert count(url, db, "Lost response") == 1  # Odoo did apply it
    r2 = client.post(
        f"/connections/{cid}/catalog/products", json=prod(name="Lost response"), headers=h
    )
    assert r2.status_code == 201 and r2.json()["outcome"] == "already_exists"
    assert count(url, db, "Lost response") == 1  # still exactly one


def test_weighed_product_gets_scale_barcode_that_odoo_parses(env):
    client, cid, url, db = env
    a = client.post(
        f"/connections/{cid}/catalog/products",
        json=prod(name="طماطم", kind="weight", auto_barcode="scale", price=20),
        headers=idem(),
    ).json()
    b = client.post(
        f"/connections/{cid}/catalog/products",
        json=prod(name="خيار", kind="weight", auto_barcode="scale", price=15),
        headers=idem(),
    ).json()
    assert a["barcode"] == scale_barcode(1) and b["barcode"] == scale_barcode(2)
    o = rpc(url, db)(
        "product.template", "read", [a["template_id"]], fields=["uom_id", "to_weight"]
    )[0]
    assert o["uom_id"][1] == "kg" and o["to_weight"] is True
    # what a scale prints for 1.250 kg of tomatoes, parsed by Odoo's own barcode nomenclature
    printed = a["barcode"][:7] + "01250"
    printed += str(ean13_check_digit(printed))
    c = rpc(url, db)
    nom = c("barcode.nomenclature", "search", [["name", "=", "Default Nomenclature"]])[0]
    parsed = c("barcode.nomenclature", "parse_barcode", [nom], printed)
    assert parsed["type"] == "weight" and abs(parsed["value"] - 1.25) < 1e-9
    # and the zero-weight base resolves to our stored product barcode
    zeroed = printed[:7] + "00000"
    assert zeroed + str(ean13_check_digit(zeroed)) == a["barcode"]
    # 'scale' makes no sense for unit products
    assert (
        client.post(
            f"/connections/{cid}/catalog/products", json=prod(auto_barcode="scale"), headers=idem()
        ).status_code
        == 422
    )


def test_duplicate_barcode_rejected_and_auto_barcode_skips_collisions(env):
    client, cid, url, db = env
    assert (
        client.post(
            f"/connections/{cid}/catalog/products",
            json=prod(name="A", barcode="1112223334445"),
            headers=idem(),
        ).status_code
        == 201
    )
    dup = client.post(
        f"/connections/{cid}/catalog/products",
        json=prod(name="B", barcode="1112223334445"),
        headers=idem(),
    )
    assert dup.status_code == 422 and "already used" in dup.json()["error"]["message"]
    assert count(url, db, "B") == 0
    # someone already used the first in-store code; the automatic one moves on to the next
    assert (
        client.post(
            f"/connections/{cid}/catalog/products",
            json=prod(name="C", barcode=internal_barcode(1)),
            headers=idem(),
        ).status_code
        == 201
    )
    d = client.post(
        f"/connections/{cid}/catalog/products",
        json=prod(name="D", auto_barcode="internal"),
        headers=idem(),
    )
    assert d.status_code == 201 and d.json()["barcode"] == internal_barcode(2)


def test_variants_and_tracking_require_their_features(env):
    client, cid, url, db = env
    shoe = prod(
        name="حذاء رياضي",
        variants=[
            {"name": "المقاس", "values": ["40", "41", "42"]},
            {"name": "اللون", "values": ["أسود", "أبيض"]},
        ],
    )
    r = client.post(f"/connections/{cid}/catalog/products", json=shoe, headers=idem())
    assert r.status_code == 422 and "not enabled" in r.json()["error"]["message"]
    assert (
        client.post(
            f"/connections/{cid}/catalog/products",
            json=prod(name="Lot item", tracking="lot"),
            headers=idem(),
        ).status_code
        == 422
    )
    enable(url, db, "group_product_variant")
    ok = client.post(f"/connections/{cid}/catalog/products", json=shoe, headers=idem())
    assert ok.status_code == 201, ok.text
    assert ok.json()["variant_count"] == 6
    n = rpc(url, db)(
        "product.product", "search_count", [["product_tmpl_id", "=", ok.json()["template_id"]]]
    )
    assert n == 6
    assert (
        client.post(
            f"/connections/{cid}/catalog/products",
            json={**shoe, "barcode": "123456789"},
            headers=idem(),
        ).status_code
        == 422
    )
    big = {
        "name": "huge",
        "price": 1,
        "variants": [
            {"name": "a", "values": [str(i) for i in range(11)]},
            {"name": "b", "values": [str(i) for i in range(11)]},
        ],
    }
    assert (
        client.post(f"/connections/{cid}/catalog/products", json=big, headers=idem()).status_code
        == 422
    )  # 121 > 100


def test_manufactured_product_recipe(env):
    client, cid, url, db = env
    c = rpc(url, db)
    assert (
        client.post(
            f"/connections/{cid}/catalog/recipes",
            json={"template_id": 1, "components": [{"template_id": 2, "qty": 1}]},
            headers=idem(),
        ).status_code
        == 422
    )  # mrp not installed
    ids = c("ir.module.module", "search", [["name", "=", "mrp"]])
    c("ir.module.module", "button_immediate_install", ids)

    def mk(n):
        r = client.post(f"/connections/{cid}/catalog/products", json=prod(name=n), headers=idem())
        return r.json()["template_id"]

    flour, sugar, cake = mk("دقيق"), mk("سكر خام"), mk("كيك")
    h = idem()
    recipe = {
        "template_id": cake,
        "quantity": 10,
        "components": [{"template_id": flour, "qty": 2}, {"template_id": sugar, "qty": 1.5}],
    }
    r = client.post(f"/connections/{cid}/catalog/recipes", json=recipe, headers=h)
    assert r.status_code == 201, r.text
    assert (
        client.post(f"/connections/{cid}/catalog/recipes", json=recipe, headers=h).json()[
            "replayed"
        ]
        is True
    )
    boms = c(
        "mrp.bom",
        "search_read",
        [["product_tmpl_id", "=", cake]],
        fields=["product_qty", "bom_line_ids"],
    )
    assert len(boms) == 1 and boms[0]["product_qty"] == 10 and len(boms[0]["bom_line_ids"]) == 2
    again = client.post(f"/connections/{cid}/catalog/recipes", json=recipe, headers=idem())
    assert again.status_code == 422 and "already has a recipe" in again.json()["error"]["message"]
    own = {"template_id": flour, "components": [{"template_id": flour, "qty": 1}]}
    assert (
        client.post(f"/connections/{cid}/catalog/recipes", json=own, headers=idem()).status_code
        == 422
    )


def test_import_validates_first_then_creates_once(env):
    client, cid, url, db = env
    taken = "999000111222" + str(ean13_check_digit("999000111222"))
    assert (
        client.post(
            f"/connections/{cid}/catalog/products",
            json=prod(name="Existing", barcode=taken),
            headers=idem(),
        ).status_code
        == 201
    )
    good = "700000000001" + str(ean13_check_digit("700000000001"))
    rows = [
        {"name": "رز", "price": "25,5", "barcode": good, "category": "بقالة"},
        {"name": "زيت", "price": "abc"},
        {"name": "عدس", "price": "30", "barcode": taken},  # already in Odoo
        {"name": "فول", "price": "12", "barcode": good},  # repeated in the file
        {"name": "ملح", "price": "5", "auto_barcode": "internal"},
        {"name": "", "price": "5"},
    ]
    v = client.post(f"/connections/{cid}/catalog/import/validate", json={"rows": rows})
    assert v.status_code == 200, v.text
    vj = v.json()
    assert [r["ok"] for r in vj["rows"]] == [True, False, False, False, True, False]
    assert any("already exists in Odoo" in e for e in vj["rows"][2]["errors"])
    assert count(url, db, "رز") == 0  # validation created nothing
    imp = vj["import_id"]
    c1 = client.post(
        f"/connections/{cid}/catalog/import/commit", params={"import_id": imp}, json={"rows": rows}
    ).json()
    assert (c1["created"], c1["skipped"]) == (2, 4) or c1["created"] == 2
    assert count(url, db, "رز") == 1 and count(url, db, "ملح") == 1
    c2 = client.post(
        f"/connections/{cid}/catalog/import/commit", params={"import_id": imp}, json={"rows": rows}
    ).json()
    assert c2["created"] == 0 and c2["replayed"] == 2
    assert count(url, db, "رز") == 1 and count(url, db, "ملح") == 1  # re-sending never duplicates
    assert (
        client.post(
            f"/connections/{cid}/catalog/import/validate",
            json={"rows": [{"name": "x", "price": 1}] * 101},
        ).status_code
        == 422
    )


def test_other_tenant_cannot_touch_the_catalogue(env):
    client, cid, url, db = env
    other = TestClient(create_app())
    make_owner(other, f"{uuid.uuid4().hex[:8]}@example.com", business="Other")
    assert other.get(f"/connections/{cid}/catalog/products").status_code == 404
    assert (
        other.post(f"/connections/{cid}/catalog/products", json=prod(), headers=idem()).status_code
        == 404
    )
