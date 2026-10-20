"""Receipts and invoices attached to expenses: type is sniffed, size limited, content round-trips through Odoo."""

import base64

from tests.integration.test_money_live import category, expense, login
from tests.integration.test_sales_live import idem, shop  # noqa: F401
from tests.integration.test_setup_execution_live import fresh, rpc  # noqa: F401

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n" + b"x" * 200


def b64(raw):
    return base64.b64encode(raw).decode()


def test_documents_attach_verify_download_and_reject_bad_files(shop):  # noqa: F811
    client, cid, url, db, cfg, cash = shop
    cat = category(client, cid)
    bill = expense(client, cid, cat, 120, description="فاتورة كهرباء").json()["expense"]["id"]
    base = f"/connections/{cid}/money"

    h = idem()
    body = {"filename": "../../فاتورة.png", "data_base64": b64(PNG)}
    r = client.post(f"{base}/expenses/{bill}/documents", json=body, headers=h)
    assert r.status_code == 201, r.text
    att = r.json()["attachment"]
    assert att["size"] == len(PNG) and att["mimetype"] == "image/png" and "/" not in att["name"]
    assert (
        client.post(f"{base}/expenses/{bill}/documents", json=body, headers=h).json()["replayed"]
        is True
    )
    stored = rpc(url, db)(
        "ir.attachment",
        "search_read",
        [["res_model", "=", "account.move"], ["res_id", "=", bill]],
        fields=["name", "file_size"],
    )
    assert len(stored) == 1 and stored[0]["file_size"] == len(PNG)  # independent read

    assert (
        client.post(
            f"{base}/expenses/{bill}/documents",
            json={"filename": "a.pdf", "data_base64": b64(PDF)},
            headers=idem(),
        ).status_code
        == 201
    )
    listed = client.get(f"{base}/expenses/{bill}/documents").json()["items"]
    assert [d["mimetype"] for d in listed] == ["image/png", "application/pdf"]

    dl = client.get(f"{base}/documents/{att['id']}")
    assert dl.status_code == 200 and dl.content == PNG and dl.headers["content-type"] == "image/png"
    assert (
        dl.headers["content-disposition"].startswith("attachment")
        and dl.headers["x-content-type-options"] == "nosniff"
    )

    # a script renamed to .png, an oversized file, and bad base64 are refused and nothing is stored
    for bad in (b"<script>alert(1)</script>", b"\x00" * (3 * 1024 * 1024 + 1)):
        res = client.post(
            f"{base}/expenses/{bill}/documents",
            json={"filename": "x.png", "data_base64": b64(bad)},
            headers=idem(),
        )
        assert res.status_code == 422, res.text
    assert (
        client.post(
            f"{base}/expenses/{bill}/documents",
            json={"filename": "x.png", "data_base64": "!!!!"},
            headers=idem(),
        ).status_code
        == 422
    )
    assert len(client.get(f"{base}/expenses/{bill}/documents").json()["items"]) == 2
    assert client.get(f"{base}/documents/99999999").status_code == 404

    cashier = login(client, cid, "cashier")
    assert cashier.get(f"{base}/expenses/{bill}/documents").status_code == 403
    assert (
        cashier.post(f"{base}/expenses/{bill}/documents", json=body, headers=idem()).status_code
        == 403
    )
    assert any(
        a["action"] == "money.expense.document" for a in client.get("/audit").json()["items"]
    )
