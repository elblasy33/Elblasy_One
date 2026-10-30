"""Price lists: retail and wholesale prices, quantity breaks, and a list per customer.

Odoo's own `product.pricelist` keeps the prices; the till and sales orders read them through Odoo's price engine.
Elblasy One manages simple "fixed price for this product from this quantity" rules, which is what small shops use;
other rule kinds already in Odoo are shown and left untouched."""

import re

from odoo import api, models
from odoo.exceptions import UserError

from .bridge import wire
from .customers_ops import _num, _text

KEY_RE = re.compile(r"^[a-f0-9]{32}$")


class ElblasyBridgePricelists(models.AbstractModel):
    _inherit = "elblasy.bridge"

    @api.model
    def _pl_view(self, pl, with_items=False):
        v = {"id": pl.id, "name": pl.name, "currency": pl.currency_id.name, "items": len(pl.item_ids),
             "customers": self.env["res.partner"].search_count([("specific_property_product_pricelist", "=", pl.id)])
             if "specific_property_product_pricelist" in self.env["res.partner"]._fields else 0}  # fmt: skip
        if with_items:
            rows = []
            for it in pl.item_ids.sorted(lambda i: (i.product_tmpl_id.name or "", i.min_quantity)):
                simple = it.compute_price == "fixed" and it.applied_on in ("1_product", "0_product_variant")
                tmpl = it.product_tmpl_id or it.product_id.product_tmpl_id
                rows.append({"id": it.id, "template_id": tmpl.id or None, "product": tmpl.name or None, "min_qty": it.min_quantity,
                             "price": it.fixed_price if simple else None, "list_price": tmpl.list_price if tmpl else None,
                             "managed": simple, "rule": None if simple else (it.name or it.compute_price)})  # fmt: skip
            v["rules"] = rows
        return v

    @api.model
    def pricelists_list(self):
        self._require_internal_user()
        if not self.env.user.has_group("product.group_product_pricelist"):
            return wire({"enabled": False, "items": []})
        return wire({"enabled": True, "items": [self._pl_view(p) for p in self.env["product.pricelist"].search([], order="sequence, id")]})

    @api.model
    def pricelist_get(self, pricelist_id):
        self._require_internal_user()
        pl = self.env["product.pricelist"].browse(int(pricelist_id or 0)).exists()
        return wire({"found": True, "pricelist": self._pl_view(pl, True)} if pl else {"found": False})

    @api.model
    def pricelist_create(self, op_id, key, spec):
        self._require_internal_user()
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid operation key.")
        existing = self._managed(f"pl_{key}")
        if existing:
            return wire({"outcome": "already_exists", "refs": {"pricelist": self._pl_view(existing)}})
        if not self.env.user.has_group("product.group_product_pricelist"):
            raise UserError("Price lists are not enabled on this Odoo; switch them on under Features first.")
        name = _text(spec.get("name"), "name", 80)
        if self.env["product.pricelist"].search_count([("name", "=", name)]):
            raise UserError(f"A price list named '{name}' already exists.")
        pl = self.env["product.pricelist"].create({"name": name})
        self._tag(f"pl_{key}", pl)
        return wire({"outcome": "created", "refs": {"pricelist": self._pl_view(pl)}})

    @api.model
    def pricelist_set_price(self, op_id, key, spec):
        """Fixed price for one product from a minimum quantity (setting it again replaces it; price None removes it)."""
        self._require_internal_user()
        pl = self.env["product.pricelist"].browse(int(spec.get("pricelist_id") or 0)).exists()
        tmpl = self.env["product.template"].browse(int(spec.get("template_id") or 0)).exists()
        if not pl or not tmpl:
            raise UserError("Price list or product not found.")
        min_qty = _num(spec.get("min_qty", 0), "minimum quantity", maximum=1e7)
        Item = self.env["product.pricelist.item"]
        current = Item.search([("pricelist_id", "=", pl.id), ("applied_on", "=", "1_product"), ("product_tmpl_id", "=", tmpl.id),
                               ("min_quantity", "=", min_qty), ("compute_price", "=", "fixed")], limit=1)  # fmt: skip
        if spec.get("price") is None:
            current.unlink()
            return wire({"outcome": "updated", "refs": {"pricelist": self._pl_view(pl, True)}})
        price = _num(spec.get("price"), "price")
        if current:
            current.write({"fixed_price": price})
        else:
            Item.create({"pricelist_id": pl.id, "applied_on": "1_product", "product_tmpl_id": tmpl.id,
                         "min_quantity": min_qty, "compute_price": "fixed", "fixed_price": price})  # fmt: skip
        return wire({"outcome": "updated", "refs": {"pricelist": self._pl_view(pl, True)}})

    @api.model
    def customer_set_pricelist(self, op_id, key, spec):
        self._require_internal_user()
        partner = self.env["res.partner"].browse(int(spec.get("partner_id") or 0)).exists()
        if not partner:
            raise UserError("Customer not found.")
        pid = int(spec.get("pricelist_id") or 0)
        pl = self.env["product.pricelist"].browse(pid).exists() if pid else self.env["product.pricelist"]
        if pid and not pl:
            raise UserError("Price list not found.")
        partner.write({"specific_property_product_pricelist": pl.id or False})
        return wire({"outcome": "updated", "refs": {"partner_id": partner.id, "pricelist_id": pl.id or None}})

    @api.model
    def price_check(self, pricelist_id, template_id, qty):
        """What Odoo's own engine charges for this product at this quantity on this list (verification)."""
        self._require_internal_user()
        pl = self.env["product.pricelist"].browse(int(pricelist_id or 0)).exists()
        tmpl = self.env["product.template"].browse(int(template_id or 0)).exists()
        if not pl or not tmpl:
            return wire({"found": False})
        return wire({"found": True, "price": pl._get_product_price(tmpl.product_variant_id, float(qty or 1))})
