import re
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from elblasy_api import audit, operations
from elblasy_api.catalog_barcode import internal_barcode, is_valid_ean13, scale_barcode
from elblasy_api.config import Settings, get_settings
from elblasy_api.db import get_session
from elblasy_api.deps import api_error, get_vault, require
from elblasy_api.models import BarcodeSequence, OdooConnection, User
from elblasy_api.odoo.client import BridgeClient, OdooError, OdooRejectedError, OdooUncertainError
from elblasy_api.routers.connections import _client, _owned
from elblasy_api.security.rbac import P_COST_VISIBLE, P_PRODUCTS, P_PRODUCTS_VIEW, has_permission
from elblasy_api.security.vault import SecretVault
from elblasy_api.setup.planner import shop_features

router = APIRouter(prefix="/connections/{cid}/catalog", tags=["catalog"])
IDEM = Annotated[
    str, Header(alias="Idempotency-Key", min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
]
BARCODE_RE = re.compile(r"^[0-9A-Za-z\-]{3,64}$")
MAX_IMPORT_ROWS = 100


class VariantAttr(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    values: list[str] = Field(min_length=1, max_length=40)


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    price: float = Field(ge=0, le=1e9)
    cost: float | None = Field(default=None, ge=0, le=1e9)
    kind: Literal["unit", "weight", "service"] = "unit"
    barcode: str | None = None
    auto_barcode: Literal["none", "internal", "scale"] = "none"
    category: str | None = Field(default=None, max_length=100)
    sku: str | None = Field(default=None, max_length=64)
    tracking: Literal["none", "lot", "serial"] = "none"
    pos: bool = True
    variants: list[VariantAttr] | None = Field(default=None, max_length=3)

    @field_validator("name", "category", "sku")
    @classmethod
    def strip(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def rules(self) -> "ProductIn":
        if self.barcode:
            self.barcode = self.barcode.strip()
            if not BARCODE_RE.match(self.barcode):
                raise ValueError("barcode may contain letters, digits and dashes only (3-64)")
        if self.barcode and self.auto_barcode != "none":
            raise ValueError("give a barcode or ask for an automatic one, not both")
        if self.auto_barcode == "scale" and self.kind != "weight":
            raise ValueError("scale barcodes are only for products sold by weight")
        if self.variants and (self.barcode or self.auto_barcode != "none"):
            raise ValueError(
                "products with sizes/colours get barcodes per variant, not on the model"
            )
        if self.variants and self.kind == "weight":
            raise ValueError("weighed products cannot have variants")
        return self


class RecipeLine(BaseModel):
    template_id: int = Field(gt=0)
    qty: float = Field(gt=0, le=1e9)


class RecipeIn(BaseModel):
    template_id: int = Field(gt=0)
    quantity: float = Field(default=1, gt=0, le=1e9)
    components: list[RecipeLine] = Field(min_length=1, max_length=50)
    # manufacture: made in batches (production orders); kit: sold as one item, components leave stock at the sale
    kind: Literal["manufacture", "kit"] = "manufacture"
    replace: bool = False  # change an existing recipe (future use only; history stays)


def _conn(
    db: Session, user: User, cid: uuid.UUID, s: Settings, vault: SecretVault
) -> tuple[OdooConnection, BridgeClient]:
    c = _owned(db, user, cid)
    if c.status != "active" or c.secret_ciphertext is None:
        raise api_error(409, "connection_revoked", "Connection is revoked")
    return c, _client(c.base_url, c.db_name, c.login, vault.decrypt(c.secret_ciphertext), s)


def _take(db: Session, cid: uuid.UUID, kind: str) -> int:
    """Next value of a per-connection counter, race-safe (row lock; PK guards first insert)."""
    for _ in range(3):
        row = db.scalar(
            select(BarcodeSequence)
            .where(BarcodeSequence.connection_id == cid, BarcodeSequence.kind == kind)
            .with_for_update()
        )
        if row is None:
            db.add(BarcodeSequence(connection_id=cid, kind=kind, next_value=1))
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                continue
            continue
        v = row.next_value
        row.next_value = v + 1
        db.commit()
        return v
    raise api_error(503, "sequence_busy", "Could not allocate a barcode, try again")


def _make_barcode(
    db: Session, cid: uuid.UUID, kind: str, client: BridgeClient | None = None
) -> str:
    """Next automatic barcode that Odoo does not already use. Numbers are per connection, so a second
    connection (or a re-connect) to the same Odoo would otherwise walk into codes already taken: each
    candidate is checked against Odoo (one fast read) and taken ones are skipped, keeping codes sequential."""
    for _ in range(200):
        try:
            n = _take(db, cid, kind)
            code = scale_barcode(n) if kind == "scale" else internal_barcode(n)
        except ValueError as exc:
            raise api_error(
                409, "barcode_space_exhausted", "No more automatic barcodes available"
            ) from exc
        if client is None:
            return code
        try:
            if code not in client.call_bridge("catalog_barcodes_taken", [code]).get("taken", []):
                return code
        except OdooError:
            return code  # Odoo still refuses a duplicate on create; the caller then retries
    raise api_error(409, "barcode_space_exhausted", "No free automatic barcode found")


def _spec(p: ProductIn, barcode: str | None) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "name": p.name, "list_price": p.price, "kind": p.kind, "tracking": p.tracking, "pos": p.pos,
    }  # fmt: skip
    for k, v in (
        ("cost", p.cost),
        ("category", p.category or None),
        ("sku", p.sku or None),
        ("barcode", barcode),
    ):
        if v is not None:
            spec[k] = v
    if p.variants:
        spec["variants"] = {"attributes": [a.model_dump() for a in p.variants]}
    return spec


def create_product(
    db: Session, request: Request | None, user: User, c: OdooConnection, client: BridgeClient,
    p: ProductIn, idem: str,
) -> tuple[dict[str, Any], bool]:  # fmt: skip
    """Tracked, idempotent creation + independent read-back. Returns (product, replayed)."""
    op, replayed = operations.begin(
        db, tenant_id=user.tenant_id, connection_id=c.id, actor_id=user.id,
        op_type="catalog.product.create", idem=idem, payload=p.model_dump(),
    )  # fmt: skip
    if replayed:
        return {**(op.odoo_refs or {}), "replayed": True}, True
    planned = (op.odoo_refs or {}).get("planned_barcode")
    barcode = p.barcode or planned
    if not barcode and p.auto_barcode != "none":
        barcode = _make_barcode(db, c.id, p.auto_barcode, client)
    # persist the chosen barcode before calling Odoo so a retry reuses it
    op.odoo_refs = {"planned_barcode": barcode} if barcode else None
    db.commit()
    key = operations.odoo_key(user.tenant_id, c.id, idem)
    attempts = 5 if p.auto_barcode != "none" and not planned else 1
    res: dict[str, Any] | None = None
    for attempt in range(attempts):
        try:
            res = client.call_bridge(
                "catalog_upsert_product",
                str(op.id),
                key,
                {
                    **_spec(p, barcode),
                    **(
                        {"no_tax": True}
                        if "no_sales_tax" in shop_features(db, user.tenant_id, c.id)
                        else {}
                    ),
                },
                timeout=60,
            )
            break
        except OdooUncertainError as exc:
            operations.fail(db, op, "needs_review", str(exc))
            raise api_error(
                502,
                "outcome_unknown",
                "The product may have been created. Retry with the same Idempotency-Key.",
            ) from exc
        except OdooRejectedError as exc:
            if "already used" in str(exc) and p.auto_barcode != "none" and attempt < attempts - 1:
                barcode = _make_barcode(
                    db, c.id, p.auto_barcode, client
                )  # collision: next free one
                op.odoo_refs = {"planned_barcode": barcode}
                db.commit()
                continue
            operations.fail(db, op, "failed", str(exc))
            raise api_error(
                422, "product_rejected", str(exc).removeprefix("Odoo rejected the call: ")
            ) from exc
        except OdooError as exc:
            operations.fail(db, op, "needs_review", str(exc))
            raise api_error(502, "odoo_unavailable", str(exc)) from exc
    assert res is not None  # noqa: S101
    refs = res["refs"]
    # independent verification: read the product back from Odoo and compare
    try:
        got = client.call_bridge("catalog_get", refs["template_id"])
    except OdooError as exc:
        operations.fail(db, op, "needs_review", str(exc))
        raise api_error(
            502,
            "verification_unavailable",
            "Created, but could not verify. Retry with the same key.",
        ) from exc
    ok = (
        got.get("found") is True and got.get("name") == p.name
        and abs(float(got.get("price", -1)) - p.price) < 0.005
        and (barcode is None or got.get("barcode") == barcode)
    )  # fmt: skip
    if not ok:
        operations.fail(db, op, "needs_review", "Odoo does not show the product as requested")
        raise api_error(502, "verification_failed", "Odoo does not show the product as requested")
    product = {
        **refs,
        "price": p.price,
        "kind": p.kind,
        "outcome": res["outcome"],
        "replayed": False,
    }
    operations.succeed(db, op, product, {"verified": True, "method": "catalog_get readback"})
    if request is not None:
        audit.record(db, request, action="catalog.product.create", outcome="success", actor=user,
                     target_type="product", target_id=refs["template_id"],
                     after={"name": p.name, "barcode": barcode})  # fmt: skip
        db.commit()
    return product, False


@router.post("/products", status_code=201)
def post_product(
    cid: uuid.UUID, body: ProductIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_PRODUCTS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    product, _ = create_product(db, request, user, c, client, body, idem)
    return product


@router.get("/products")
def list_products(
    cid: uuid.UUID, q: str = Query("", max_length=100), limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100_000), archived: bool = False,
    user: User = Depends(require(P_PRODUCTS_VIEW)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    try:
        res = client.call_bridge("catalog_search", q, limit, offset, archived)
    except OdooError as exc:
        raise api_error(502, "odoo_unavailable", str(exc)) from exc
    if not has_permission(user.role, P_COST_VISIBLE):  # enforced here, not in the UI
        for it in res.get("items", []):
            it.pop("cost", None)
    return res


@router.get("/categories")
def list_categories(
    cid: uuid.UUID, user: User = Depends(require(P_PRODUCTS_VIEW)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    try:
        return client.call_bridge("catalog_categories")
    except OdooError as exc:
        raise api_error(502, "odoo_unavailable", str(exc)) from exc


class ProductPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    price: float | None = Field(default=None, ge=0, le=1e9)
    cost: float | None = Field(default=None, ge=0, le=1e9)
    sku: str | None = Field(default=None, max_length=64)
    barcode: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=100)
    in_pos: bool | None = None
    active: bool | None = None


@router.patch("/products/{template_id}")
def patch_product(
    cid: uuid.UUID, template_id: int, body: ProductPatch, idem: IDEM, request: Request,
    user: User = Depends(require(P_PRODUCTS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    changes = body.model_dump(exclude_unset=True)
    if "cost" in changes and not has_permission(user.role, P_COST_VISIBLE):
        raise api_error(403, "forbidden", "You may not change costs")
    if not changes:
        raise api_error(422, "nothing_to_change", "Nothing to change")
    spec = {"template_id": template_id, **changes}

    def verify(res: dict[str, Any], _before: Any) -> dict[str, Any]:
        try:
            got = client.call_bridge("catalog_get", template_id)
        except OdooError as exc:
            raise api_error(
                502, "verification_unavailable", "Saved, but could not verify. Retry."
            ) from exc
        want = {
            "name": "name",
            "price": "price",
            "cost": "cost",
            "sku": "sku",
            "category": "category",
            "in_pos": "in_pos",
            "active": "active",
        }
        for field, key in want.items():
            if field not in changes or changes[field] is None:
                continue
            a, b = got.get(key), changes[field]
            same = (
                abs(float(a or 0) - float(b)) < 0.005
                if isinstance(b, float | int) and not isinstance(b, bool)
                else a == b
            )
            if not same:
                raise api_error(502, "verification_failed", f"Odoo does not show the new {field}")
        if "barcode" in changes and (got.get("barcode") or None) != (
            (changes["barcode"] or "").strip() or None
        ):
            raise api_error(502, "verification_failed", "Odoo does not show the new barcode")
        return {
            "template_id": template_id,
            "outcome": res["outcome"],
            "replayed": False,
            "name": got.get("name"),
            "active": got.get("active"),
        }

    return operations.run_write(
        db, request, user=user, conn=c, client=client, op_type="catalog.product.update", idem=idem,
        payload=spec, method="catalog_update_product", spec=spec, verify=verify, what="product",
        audit_action="catalog.product.archive" if changes.get("active") is False else "catalog.product.update",
        target_type="product", target_id=lambda o: o["template_id"],
        audit_after=lambda o: {k: v for k, v in changes.items() if k != "cost"}, rejected_code="product_rejected",
    )  # fmt: skip


@router.get("/recipes/{template_id}")
def get_recipe(
    cid: uuid.UUID, template_id: int, user: User = Depends(require(P_PRODUCTS_VIEW)),
    db: Session = Depends(get_session), s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    _, client = _conn(db, user, cid, s, vault)
    try:
        got = client.call_bridge("catalog_get_bom", template_id)
    except OdooError as exc:
        raise api_error(502, "odoo_unavailable", str(exc)) from exc
    if not has_permission(user.role, P_COST_VISIBLE):  # costs only for those who may see them
        got.pop("unit_cost", None)
        got.pop("margin", None)
        for c in got.get("components", []):
            c.pop("cost", None)
    return got


@router.post("/recipes", status_code=201)
def post_recipe(
    cid: uuid.UUID, body: RecipeIn, idem: IDEM, request: Request,
    user: User = Depends(require(P_PRODUCTS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    c, client = _conn(db, user, cid, s, vault)
    op, replayed = operations.begin(
        db, tenant_id=user.tenant_id, connection_id=c.id, actor_id=user.id,
        op_type="catalog.recipe.create", idem=idem, payload=body.model_dump(),
    )  # fmt: skip
    if replayed:
        return {**(op.odoo_refs or {}), "replayed": True}
    key = operations.odoo_key(user.tenant_id, c.id, idem)
    try:
        res = client.call_bridge("catalog_set_bom", str(op.id), key, body.model_dump(), timeout=60)
    except OdooUncertainError as exc:
        operations.fail(db, op, "needs_review", str(exc))
        raise api_error(
            502,
            "outcome_unknown",
            "The recipe may have been created. Retry with the same Idempotency-Key.",
        ) from exc
    except OdooRejectedError as exc:
        operations.fail(db, op, "failed", str(exc))
        raise api_error(
            422, "recipe_rejected", str(exc).removeprefix("Odoo rejected the call: ")
        ) from exc
    except OdooError as exc:
        operations.fail(db, op, "needs_review", str(exc))
        raise api_error(502, "odoo_unavailable", str(exc)) from exc
    # independent check: read the recipe back from Odoo and compare with what was asked
    try:
        got = client.call_bridge("catalog_get_bom", body.template_id)
    except OdooError as exc:
        operations.fail(db, op, "needs_review", str(exc))
        raise api_error(
            502, "verification_unavailable", "Saved, but could not verify. Retry with the same key."
        ) from exc
    want = sorted((ln.template_id, round(ln.qty, 6)) for ln in body.components)
    have = sorted((c["template_id"], round(c["qty"], 6)) for c in got.get("components", []))
    if (
        not got.get("found")
        or got["kind"] != body.kind
        or abs(got["quantity"] - body.quantity) > 1e-6
        or want != have
    ):
        operations.fail(db, op, "needs_review", "Odoo does not show the recipe as requested")
        raise api_error(502, "verification_failed", "Odoo does not show the recipe as requested")
    out = {**res["refs"], "outcome": res["outcome"], "replayed": False, "recipe": got}
    operations.succeed(db, op, out, {"verified": True, "method": "catalog_get_bom readback"})
    audit.record(db, request, action="catalog.recipe.update" if res["outcome"] == "updated" else "catalog.recipe.create",
                 outcome="success", actor=user, target_type="bom", target_id=out["bom_id"],
                 after={"kind": body.kind, "components": len(body.components)})  # fmt: skip
    db.commit()
    return out


# ---------------- bulk import: validate first, then create ----------------
class ImportRows(BaseModel):
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_IMPORT_ROWS)


def _row_errors(row: dict[str, Any], seen: set[str]) -> tuple[ProductIn | None, list[str]]:
    errs: list[str] = []
    try:
        price = float(str(row.get("price", "")).replace(",", "."))
    except ValueError:
        price = -1
        errs.append("price must be a number")
    cost_raw = row.get("cost")
    cost: float | None = None
    if cost_raw not in (None, ""):
        try:
            cost = float(str(cost_raw).replace(",", "."))
        except ValueError:
            errs.append("cost must be a number")
    barcode = str(row.get("barcode") or "").strip() or None
    if barcode:
        if barcode in seen:
            errs.append("barcode repeated in this file")
        seen.add(barcode)
        if barcode.isdigit() and len(barcode) == 13 and not is_valid_ean13(barcode):
            errs.append("barcode has a wrong EAN-13 check digit")
    kind = str(row.get("kind") or "unit").strip().lower()
    if kind not in ("unit", "weight"):
        errs.append("kind must be 'unit' or 'weight'")
        kind = "unit"
    auto = "none"
    if not barcode and str(row.get("auto_barcode") or "").strip().lower() in ("internal", "scale"):
        auto = str(row["auto_barcode"]).strip().lower()
    if errs:
        return None, errs
    try:
        p = ProductIn(name=str(row.get("name") or ""), price=price, cost=cost, kind=kind,  # type: ignore[arg-type]
                      barcode=barcode, auto_barcode=auto,  # type: ignore[arg-type]
                      category=(str(row.get("category") or "").strip() or None),
                      sku=(str(row.get("sku") or "").strip() or None))  # fmt: skip
    except ValidationError as exc:
        return None, [
            f"{'.'.join(map(str, e['loc']))}: {str(e['msg']).removeprefix('Value error, ')}"
            for e in exc.errors()
        ]
    return p, []


@router.post("/import/validate")
def import_validate(
    cid: uuid.UUID, body: ImportRows,
    user: User = Depends(require(P_PRODUCTS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    """Nothing is created. Row-level problems are reported, including barcodes already in Odoo."""
    _, client = _conn(db, user, cid, s, vault)
    seen: set[str] = set()
    parsed = [_row_errors(r, seen) for r in body.rows]
    codes = [p.barcode for p, _ in parsed if p and p.barcode]
    taken: set[str] = set()
    if codes:
        try:
            taken = set(client.call_bridge("catalog_barcodes_taken", codes).get("taken", []))
        except OdooError as exc:
            raise api_error(502, "odoo_unavailable", str(exc)) from exc
    results = []
    for i, (p, errs) in enumerate(parsed):
        if p and p.barcode in taken:
            errs = [*errs, "barcode already exists in Odoo"]
        results.append({"row": i + 1, "ok": not errs, "errors": errs})
    return {
        "import_id": uuid.uuid4().hex,
        "valid": sum(r["ok"] for r in results),
        "invalid": sum(not r["ok"] for r in results),
        "rows": results,
    }


@router.post("/import/commit")
def import_commit(
    cid: uuid.UUID, body: ImportRows, request: Request,
    import_id: str = Query(pattern=r"^[0-9a-f]{32}$"),
    user: User = Depends(require(P_PRODUCTS)), db: Session = Depends(get_session),
    s: Settings = Depends(get_settings), vault: SecretVault = Depends(get_vault),
) -> dict[str, Any]:  # fmt: skip
    """Creates the valid rows one tracked operation each (key = import_id + row). Re-sending the same
    import_id is safe: finished rows are replayed, not duplicated. Invalid rows are skipped and reported."""
    c, client = _conn(db, user, cid, s, vault)
    seen: set[str] = set()
    out = []
    for i, row in enumerate(body.rows):
        p, errs = _row_errors(row, seen)
        if p is None:
            out.append({"row": i + 1, "status": "skipped", "errors": errs})
            continue
        try:
            prod, replayed = create_product(
                db, request, user, c, client, p, f"imp-{import_id}-{i:04d}"
            )
            out.append(
                {
                    "row": i + 1,
                    "status": "replayed" if replayed else "created",
                    "template_id": prod.get("template_id"),
                }
            )
        except Exception as exc:  # noqa: BLE001 - one bad row must not abort the batch
            detail = getattr(exc, "detail", None)
            msg = detail.get("message") if isinstance(detail, dict) else "error"
            out.append({"row": i + 1, "status": "failed", "errors": [msg]})
    return {"import_id": import_id, "created": sum(r["status"] == "created" for r in out),
            "replayed": sum(r["status"] == "replayed" for r in out),
            "skipped": sum(r["status"] == "skipped" for r in out),
            "failed": sum(r["status"] == "failed" for r in out), "rows": out}  # fmt: skip
