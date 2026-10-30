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
        if kind not in ("unit", "weight", "service"):
            raise UserError("kind must be 'unit', 'weight' or 'service'.")
        tracking = spec.get("tracking", "none")
        if tracking not in ("none", "lot", "serial"):
            raise UserError("tracking must be 'none', 'lot' or 'serial'.")
        if tracking != "none" and not self.env.user.has_group("stock.group_production_lot"):
            raise UserError("Lot/expiry tracking is not enabled on this Odoo.")

        vals = {"name": name, "list_price": price, "type": "consu", "sale_ok": True, "purchase_ok": True}
        if "cost" in spec and spec["cost"] is not None:
            vals["standard_price"] = _number(spec["cost"], "cost")
        if kind == "service":  # sold, never stocked
            vals["type"] = "service"
            if tracking != "none":
                raise UserError("A service cannot be tracked by lot or serial.")
        elif self._installed("stock"):
            vals["is_storable"] = True
            vals["tracking"] = tracking
        if spec.get("no_tax"):  # the owner said the business is not VAT-registered
            vals["taxes_id"] = [(6, 0, [])]
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
        if vals.get("standard_price") and tmpl.product_variant_count > 1:
            # Odoo applies the template cost only when there is a single variant; give every variant it.
            tmpl.product_variant_ids.write({"standard_price": vals["standard_price"]})
        self._tag(xml_name, tmpl)
        return wire({"outcome": "created", "refs": self._product_view(tmpl)})

    # ---- read ----
    @api.model
    def catalog_search(self, query, limit, offset, archived=False):
        self._require_internal_user()
        limit = max(1, min(int(limit or 25), SEARCH_LIMIT_MAX))
        offset = max(0, int(offset or 0))
        domain = [("type", "in", ("consu", "service"))]
        q = (query or "").strip()
        if q:
            domain += ["|", "|", ("name", "ilike", q), ("barcode", "ilike", q), ("default_code", "ilike", q)]
        T = self.env["product.template"]
        if archived:
            T = T.with_context(active_test=False)
            domain += [("active", "=", False)]
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
                    "active": bool(t.active),
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
        """A recipe (made in batches: manufacturing orders) or a kit (sold as one item; its components leave
        stock at the sale). With `replace`, an existing recipe's lines are changed for future use; history stays."""
        self._require_internal_user()
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid recipe key.")
        if not self._installed("mrp"):
            raise UserError("Manufacturing is not enabled on this Odoo.")
        xml_name = f"bom_{key}"
        existing = self._managed(xml_name)
        if existing:
            return {"outcome": "already_exists", "refs": {"bom_id": existing.id}}
        kind = spec.get("kind", "manufacture")
        if kind not in ("manufacture", "kit"):
            raise UserError("kind must be 'manufacture' or 'kit'.")
        bom_type = "phantom" if kind == "kit" else "normal"
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
        Bom = self.env["mrp.bom"]
        current = Bom.search([("product_tmpl_id", "=", finished.id)], limit=1)
        if current and not spec.get("replace"):
            raise UserError("This product already has a recipe; edit it instead.")
        if current:
            current.write({"bom_line_ids": [(5, 0, 0)] + lines, "product_qty": qty, "type": bom_type})
            bom, outcome = current, "updated"
        else:
            bom = Bom.create({"product_tmpl_id": finished.id, "product_qty": qty, "type": bom_type, "bom_line_ids": lines})
            outcome = "created"
        self._tag(xml_name, bom)
        return {"outcome": outcome, "refs": {"bom_id": bom.id}}

    @api.model
    def catalog_get_bom(self, template_id):
        """A product's recipe or kit, with what one unit costs from its components."""
        self._require_internal_user()
        if "mrp.bom" not in self.env:
            return wire({"found": False})
        t = self.env["product.template"].browse(int(template_id or 0)).exists()
        bom = self.env["mrp.bom"].search([("product_tmpl_id", "=", t.id)], limit=1) if t else None
        if not bom:  # no composition yet: the sale price still lets the screen show cost and margin while building
            return wire({"found": False, **({"price": t.list_price} if t else {})})
        cur = self.env.company.currency_id
        comps = []
        for ln in bom.bom_line_ids:
            p = ln.product_id
            comps.append({"template_id": p.product_tmpl_id.id, "name": p.display_name, "qty": ln.product_qty,
                          "uom": ln.product_uom_id.name, "cost": p.standard_price,
                          "on_hand": p.qty_available if p.is_storable else None})  # fmt: skip
        unit_cost = cur.round(sum(c["qty"] * c["cost"] for c in comps) / (bom.product_qty or 1.0))
        return wire({
            "found": True, "bom_id": bom.id, "kind": "kit" if bom.type == "phantom" else "manufacture",
            "quantity": bom.product_qty, "components": comps, "unit_cost": unit_cost, "price": t.list_price,
            "margin": cur.round(t.list_price - unit_cost),
        })  # fmt: skip

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
                "active": bool(t.active),
                "sku": t.default_code or None,
                "category": t.categ_id.name or None,
                "cost": t.standard_price,
                "in_pos": bool(t.available_in_pos) if "available_in_pos" in t._fields else False,
                "on_hand": t.qty_available if t.is_storable else None,
            }
        )

    @api.model
    def catalog_categories(self):
        self._require_internal_user()
        rows = self.env["product.category"].search_read([], ["complete_name"], order="complete_name", limit=500)
        return wire({"items": [r["complete_name"] for r in rows]})

    @api.model
    def catalog_update_product(self, op_id, key, spec):
        """Set fields of an existing product to the given values (naturally idempotent). Only fields
        named in `spec` change; archiving is refused while stock remains, so stock never hides."""
        self._require_internal_user()
        t = self.env["product.template"].with_context(active_test=False).browse(int(spec.get("template_id") or 0)).exists()
        if not t:
            raise UserError("Product not found.")
        vals = {}
        if "name" in spec:
            vals["name"] = _clean_text(spec["name"], "name", 200)
        if "price" in spec:
            vals["list_price"] = _number(spec["price"], "price")
        if "cost" in spec and spec["cost"] is not None:
            vals["standard_price"] = _number(spec["cost"], "cost")
        if "sku" in spec:
            vals["default_code"] = _clean_text(spec["sku"], "sku", 64) if spec["sku"] else False
        if spec.get("category"):
            vals["categ_id"] = self._ensure_category(spec["category"]).id
        if "in_pos" in spec and self._installed("point_of_sale"):
            vals["available_in_pos"] = bool(spec["in_pos"])
        if "barcode" in spec:
            barcode = (spec["barcode"] or "").strip()
            if barcode:
                if not re.fullmatch(r"[0-9A-Za-z\-]{3,64}", barcode):
                    raise UserError("Barcode may contain only letters, digits and dashes (3-64).")
                if t.product_variant_count > 1:
                    raise UserError("Set barcodes per variant for products with variants.")
                clash = self.env["product.product"].with_context(active_test=False).search(
                    [("barcode", "=", barcode), ("product_tmpl_id", "!=", t.id)], limit=1
                )
                if clash:
                    raise UserError(f"Barcode {barcode} is already used by '{clash.display_name}'.")
            vals["barcode"] = barcode or False
        if "active" in spec:
            want = bool(spec["active"])
            if not want and t.active and t.is_storable and abs(t.qty_available) > 1e-9:
                raise UserError("This product still has stock; bring it to zero before archiving it.")
            vals["active"] = want
        if not vals:
            raise UserError("Nothing to change.")
        t.write(vals)
        if vals.get("standard_price") is not None and t.product_variant_count > 1:
            t.product_variant_ids.write({"standard_price": vals["standard_price"]})
        return wire({"outcome": "updated", "refs": self._product_view(t)})

    @api.model
    def catalog_barcodes_taken(self, barcodes):
        """Which of these barcodes already exist (including archived products)."""
        self._require_internal_user()
        codes = [str(b)[:64] for b in (barcodes or [])][:500]
        found = self.env["product.product"].with_context(active_test=False).search_read(
            [("barcode", "in", codes)], ["barcode"]
        )
        return wire({"taken": sorted({r["barcode"] for r in found})})
