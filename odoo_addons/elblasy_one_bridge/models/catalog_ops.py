"""Catalogue operations: create products (incl. weighed, variant and tracked ones), search, and
manufacturing recipes (BoM). Additive and idempotent by a caller-supplied key (XML id
`elblasy_one.prod_<key>`), so a retry after a timeout returns the existing product instead of
creating a duplicate. Opening stock is deliberately NOT here: it is a separate, validated workflow."""

import re

from odoo import api, models
from odoo.exceptions import UserError

from .bridge import wire
from .setup_ops import XMLID_MODULE

KEY_RE = re.compile(r"^[a-z0-9_]{8,64}$")
MAX_ATTRS, MAX_VALUES, MAX_LINES = 3, 40, 100
SEARCH_LIMIT_MAX = 100


def _clean_text(v, field, limit):
    v = (v or "").strip() if isinstance(v, str) else ""
    if not v:
        raise UserError(f"{field} is required.")
    if len(v) > limit:
        raise UserError(f"{field} is too long (max {limit}).")
    return v


def _number(v, field, minimum=0.0):
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise UserError(f"{field} must be a number.") from None
    if n < minimum or n != n or n > 1e12:
        raise UserError(f"{field} is out of range.")
    return n


class ElblasyBridgeCatalog(models.AbstractModel):
    _inherit = "elblasy.bridge"

    # ---- helpers ----
    @api.model
    def _installed(self, name):
        return bool(
            self.env["ir.module.module"].sudo().search_count([("name", "=", name), ("state", "=", "installed")])
        )

    @api.model
    def _ensure_category(self, name):
        name = _clean_text(name, "category", 100)
        Cat = self.env["product.category"]
        cat = Cat.search([("name", "=", name)], limit=1)
        return cat or Cat.create({"name": name})

    @api.model
    def _ensure_attribute(self, name, values):
        name = _clean_text(name, "attribute name", 60)
        if not values or len(values) > MAX_VALUES:
            raise UserError(f"Attribute '{name}' needs 1-{MAX_VALUES} values.")
        Attr, Val = self.env["product.attribute"], self.env["product.attribute.value"]
        attr = Attr.search([("name", "=", name)], limit=1) or Attr.create(
            {"name": name, "create_variant": "always"}
        )
        out = Val
        for raw in values:
            v = _clean_text(raw, "attribute value", 60)
            rec = Val.search([("attribute_id", "=", attr.id), ("name", "=", v)], limit=1)
            out |= rec or Val.create({"attribute_id": attr.id, "name": v})
        return attr, out

    @api.model
    def _product_view(self, tmpl):
        return {
            "template_id": tmpl.id,
            "name": tmpl.name,
            "barcode": tmpl.barcode or None,
            "variant_ids": tmpl.product_variant_ids.ids,
            "variant_count": tmpl.product_variant_count,
        }

    # ---- create ----
    @api.model
    def catalog_upsert_product(self, op_id, key, spec):
        self._require_internal_user()
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid product key.")
        xml_name = f"prod_{key}"
        existing = self._managed(xml_name)
        if existing:
            return wire({"outcome": "already_exists", "refs": self._product_view(existing)})

        name = _clean_text(spec.get("name"), "name", 200)
        price = _number(spec.get("list_price", 0), "price")
        kind = spec.get("kind", "unit")
        if kind not in ("unit", "weight"):
            raise UserError("kind must be 'unit' or 'weight'.")
        tracking = spec.get("tracking", "none")
        if tracking not in ("none", "lot"):
            raise UserError("tracking must be 'none' or 'lot'.")
        if tracking == "lot" and not self.env.user.has_group("stock.group_production_lot"):
            raise UserError("Lot/expiry tracking is not enabled on this Odoo.")

        vals = {"name": name, "list_price": price, "type": "consu", "sale_ok": True, "purchase_ok": True}
        if "cost" in spec and spec["cost"] is not None:
            vals["standard_price"] = _number(spec["cost"], "cost")
        if self._installed("stock"):
            vals["is_storable"] = True
            vals["tracking"] = tracking
        if spec.get("sku"):
            vals["default_code"] = _clean_text(spec["sku"], "sku", 64)
        if spec.get("category"):
            vals["categ_id"] = self._ensure_category(spec["category"]).id
        if self._installed("point_of_sale"):
            vals["available_in_pos"] = bool(spec.get("pos", True))
            if kind == "weight":
                vals["to_weight"] = True
        if kind == "weight":
            kg = self.env.ref("uom.product_uom_kgm", raise_if_not_found=False)
            if not kg:
                raise UserError("Kilogram unit of measure not found.")
            vals["uom_id"] = kg.id
            if "uom_po_id" in self.env["product.template"]._fields:
                vals["uom_po_id"] = kg.id

        barcode = (spec.get("barcode") or "").strip()
        if barcode:
            if not re.fullmatch(r"[0-9A-Za-z\-]{3,64}", barcode):
                raise UserError("Barcode may contain only letters, digits and dashes (3-64).")
            clash = self.env["product.product"].with_context(active_test=False).search(
                [("barcode", "=", barcode)], limit=1
            )
            if clash:
                raise UserError(f"Barcode {barcode} is already used by '{clash.display_name}'.")
            vals["barcode"] = barcode

        variants = spec.get("variants")
        if variants:
            if not self.env.user.has_group("product.group_product_variant"):
                raise UserError("Sizes/colours (variants) are not enabled on this Odoo.")
            attrs = variants.get("attributes") or []
            if not 1 <= len(attrs) <= MAX_ATTRS:
                raise UserError(f"Variants need 1-{MAX_ATTRS} attributes.")
            total = 1
            lines = []
            for a in attrs:
                attr, vals_rec = self._ensure_attribute(a.get("name"), a.get("values"))
                total *= len(vals_rec)
                lines.append((0, 0, {"attribute_id": attr.id, "value_ids": [(6, 0, vals_rec.ids)]}))
            if total > MAX_LINES:
                raise UserError(f"Too many variants ({total}); the limit is {MAX_LINES}.")
            vals["attribute_line_ids"] = lines
            if barcode:
                raise UserError("Set barcodes per variant, not on the model, for products with variants.")

        tmpl = self.env["product.template"].create(vals)
        self._tag(xml_name, tmpl)
        return wire({"outcome": "created", "refs": self._product_view(tmpl)})

    # ---- read ----
    @api.model
    def catalog_search(self, query, limit, offset):
        self._require_internal_user()
        limit = max(1, min(int(limit or 25), SEARCH_LIMIT_MAX))
        offset = max(0, int(offset or 0))
        domain = [("type", "=", "consu")]
        q = (query or "").strip()
        if q:
            domain += ["|", "|", ("name", "ilike", q), ("barcode", "ilike", q), ("default_code", "ilike", q)]
        T = self.env["product.template"]
        total = T.search_count(domain)
        rows = []
        for t in T.search(domain, limit=limit, offset=offset, order="name"):
            rows.append(
                {
                    "template_id": t.id,
                    "name": t.name,
                    "sku": t.default_code or None,
                    "barcode": t.barcode or None,
                    "price": t.list_price,
                    "cost": t.standard_price,  # the platform strips this unless the user may see costs
                    "category": t.categ_id.name or None,
                    "uom": t.uom_id.name,
                    "on_hand": t.qty_available if t.is_storable else None,
                    "tracking": t.tracking if "tracking" in t._fields else "none",
                    "variant_count": t.product_variant_count,
                    "by_weight": bool(t.to_weight) if "to_weight" in t._fields else False,
                    "in_pos": bool(t.available_in_pos) if "available_in_pos" in t._fields else False,
                    "managed": bool(
                        self.env["ir.model.data"].sudo().search_count(
                            [("module", "=", XMLID_MODULE), ("model", "=", "product.template"), ("res_id", "=", t.id)]
                        )
                    ),
                }
            )
        return wire({"total": total, "items": rows})

    # ---- manufacturing recipe ----
    @api.model
    def catalog_set_bom(self, op_id, key, spec):
        self._require_internal_user()
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid recipe key.")
        if not self._installed("mrp"):
            raise UserError("Manufacturing is not enabled on this Odoo.")
        xml_name = f"bom_{key}"
        existing = self._managed(xml_name)
        if existing:
            return {"outcome": "already_exists", "refs": {"bom_id": existing.id}}
        T = self.env["product.template"]
        finished = T.browse(int(spec.get("template_id") or 0)).exists()
        if not finished:
            raise UserError("Finished product not found.")
        if finished.product_variant_count != 1:
            raise UserError("Recipes support products without variants only.")
        comps = spec.get("components") or []
        if not 1 <= len(comps) <= 50:
            raise UserError("A recipe needs 1-50 components.")
        qty = _number(spec.get("quantity", 1), "yield", minimum=0.0001)
        lines, seen = [], set()
        for c in comps:
            comp = T.browse(int(c.get("template_id") or 0)).exists()
            if not comp:
                raise UserError("Component product not found.")
            if comp.id == finished.id:
                raise UserError("A product cannot be its own component.")
            if comp.id in seen:
                raise UserError("Duplicate component.")
            if comp.product_variant_count != 1:
                raise UserError(f"Component '{comp.name}' has variants; not supported in recipes.")
            seen.add(comp.id)
            lines.append((0, 0, {"product_id": comp.product_variant_id.id,
                                  "product_qty": _number(c.get("qty"), "component quantity", 0.0001)}))  # fmt: skip
        if self.env["mrp.bom"].search_count([("product_tmpl_id", "=", finished.id)]):
            raise UserError("This product already has a recipe; editing recipes is not supported yet.")
        bom = self.env["mrp.bom"].create(
            {"product_tmpl_id": finished.id, "product_qty": qty, "type": "normal", "bom_line_ids": lines}
        )
        self._tag(xml_name, bom)
        return {"outcome": "created", "refs": {"bom_id": bom.id}}

    @api.model
    def catalog_get(self, template_id):
        """Read one product back (used for independent verification after creation)."""
        self._require_internal_user()
        t = self.env["product.template"].browse(int(template_id)).exists()
        if not t:
            return wire({"found": False})
        return wire(
            {
                "found": True,
                "template_id": t.id,
                "name": t.name,
                "barcode": t.barcode or None,
                "price": t.list_price,
                "variant_count": t.product_variant_count,
                "by_weight": bool(t.to_weight) if "to_weight" in t._fields else False,
                "uom": t.uom_id.name,
                "tracking": t.tracking if "tracking" in t._fields else "none",
            }
        )

    @api.model
    def catalog_barcodes_taken(self, barcodes):
        """Which of these barcodes already exist (including archived products)."""
        self._require_internal_user()
        codes = [str(b)[:64] for b in (barcodes or [])][:500]
        found = self.env["product.product"].with_context(active_test=False).search_read(
            [("barcode", "in", codes)], ["barcode"]
        )
        return wire({"taken": sorted({r["barcode"] for r in found})})
