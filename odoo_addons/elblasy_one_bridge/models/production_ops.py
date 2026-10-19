"""Production of made products (own recipes) on Odoo's native manufacturing orders.

A batch is a normal `mrp.production`: components are consumed and the finished product is added by
Odoo itself, so stock and cost stay correct. The order's `origin` carries the operation key, so a
retry after a lost response finds the order instead of producing twice. A batch is refused up front
when components are short, so nothing is half-produced."""

import re

from odoo import api, models
from odoo.exceptions import UserError

from .bridge import wire

KEY_RE = re.compile(r"^[a-f0-9]{32}$")
MAX_QTY = 1e6


class ElblasyBridgeProduction(models.AbstractModel):
    _inherit = "elblasy.bridge"

    @api.model
    def _need_mrp(self):
        if "mrp.bom" not in self.env:
            raise UserError("Manufacturing is not enabled on this Odoo.")

    @api.model
    def production_recipes(self):
        self._require_internal_user()
        self._need_mrp()
        out = []
        for bom in self.env["mrp.bom"].search([("type", "=", "normal"), ("product_id", "=", False)], order="id"):
            t = bom.product_tmpl_id
            comps, batches = [], None
            for ln in bom.bom_line_ids:
                per_unit = ln.product_qty / (bom.product_qty or 1.0)
                have = ln.product_id.qty_available
                comps.append({"template_id": ln.product_id.product_tmpl_id.id, "name": ln.product_id.display_name,
                              "per_unit": per_unit, "on_hand": have, "uom": ln.product_uom_id.name})  # fmt: skip
                can = have / per_unit if per_unit else 0.0
                batches = can if batches is None else min(batches, can)
            out.append({"template_id": t.id, "name": t.name, "yield": bom.product_qty, "uom": t.uom_id.name,
                        "on_hand": t.qty_available, "can_make": max(0.0, batches or 0.0), "components": comps})  # fmt: skip
        return wire({"items": out})

    @api.model
    def _mo_view(self, mo):
        return {
            "id": mo.id, "name": mo.name, "state": mo.state, "product_id": mo.product_id.id,
            "template_id": mo.product_tmpl_id.id, "product": mo.product_id.display_name,
            "qty": mo.product_qty, "qty_produced": mo.qty_produced, "date": str(mo.date_start or "")[:19] or None,
            "components": [
                {"name": m.product_id.display_name, "consumed": m.quantity if m.state == "done" else 0.0}
                for m in mo.move_raw_ids
            ],
        }  # fmt: skip

    @api.model
    def production_get(self, mo_id):
        self._require_internal_user()
        self._need_mrp()
        mo = self.env["mrp.production"].browse(int(mo_id)).exists()
        return wire({"found": bool(mo), **(self._mo_view(mo) if mo else {})})

    @api.model
    def production_history(self, limit):
        self._require_internal_user()
        self._need_mrp()
        mos = self.env["mrp.production"].search([("origin", "like", "Elblasy One")], limit=max(1, min(int(limit or 20), 100)), order="id desc")
        return wire({"items": [self._mo_view(m) for m in mos]})

    @api.model
    def production_produce(self, op_id, key, spec):
        self._require_internal_user()
        self._need_mrp()
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid production key.")
        origin = f"Elblasy One {key}"
        Mo = self.env["mrp.production"]
        existing = Mo.search([("origin", "=", origin)], limit=1)
        if existing:
            return wire({"outcome": "already_exists", "refs": {"order": self._mo_view(existing)}})
        try:
            qty = float(spec.get("qty"))
        except (TypeError, ValueError):
            raise UserError("Quantity must be a number.") from None
        if not 0 < qty <= MAX_QTY:
            raise UserError("Quantity is out of range.")
        t = self.env["product.template"].browse(int(spec.get("template_id") or 0)).exists()
        bom = self.env["mrp.bom"].search([("product_tmpl_id", "=", t.id), ("type", "=", "normal")], limit=1) if t else None
        if not bom:
            raise UserError("This product has no recipe.")
        factor = qty / (bom.product_qty or 1.0)
        short = []
        for ln in bom.bom_line_ids:
            need = ln.product_qty * factor
            if ln.product_id.qty_available + 1e-9 < need:
                short.append(f"{ln.product_id.display_name} (need {need:g}, have {ln.product_id.qty_available:g})")
        if short:
            raise UserError("Not enough components: " + "; ".join(short))
        mo = Mo.create({"product_id": t.product_variant_id.id, "product_qty": qty, "bom_id": bom.id,
                        "product_uom_id": t.uom_id.id, "origin": origin})  # fmt: skip
        mo.action_confirm()
        mo.action_assign()
        mo.qty_producing = qty
        if hasattr(mo, "_set_qty_producing"):
            mo._set_qty_producing()
        res = mo.with_context(skip_consumption=True, skip_backorder=True, mo_ids_to_backorder=[]).button_mark_done()
        if isinstance(res, dict) and res.get("res_model"):  # a confirmation wizard Odoo wants answered
            wiz = self.env[res["res_model"]].with_context(**(res.get("context") or {})).create({})
            wiz.process()
        if mo.state != "done":
            raise UserError("The production order could not be completed.")
        return wire({"outcome": "created", "refs": {"order": self._mo_view(mo)}})
