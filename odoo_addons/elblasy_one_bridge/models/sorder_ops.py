"""Manual sales orders (Odoo's Sales app): wholesale or on-credit sales made outside the till.

A sales order is a normal `sale.order`: confirmed, then delivered (stock leaves through a real delivery
transfer) and invoiced (a posted customer invoice that stays open until the customer pays, collected through the
receivables screens). Prices are typed per line, because wholesale prices differ from the shelf price; totals and
taxes always come from Odoo."""

import datetime
import re

from odoo import api, fields, models
from odoo.exceptions import UserError

from .bridge import wire
from .customers_ops import _num, _text

KEY_RE = re.compile(r"^[a-f0-9]{32}$")
MAX_LINES = 100
TOL = 0.005


class ElblasyBridgeSalesOrders(models.AbstractModel):
    _inherit = "elblasy.bridge"

    @api.model
    def _need_sales_orders(self):
        if "sale.order" not in self.env:
            raise UserError("The Sales app is not installed on this Odoo.")

    @api.model
    def _so_lines(self, spec, partner):
        """Validated lines with Odoo-computed amounts. Price defaults to the product's sale price."""
        raw = spec.get("lines")
        if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_LINES:
            raise UserError(f"An order needs 1-{MAX_LINES} lines.")
        company = self.env.company
        cur = company.currency_id
        out, seen = [], set()
        for r in raw:
            prod = self.env["product.product"].browse(int(r.get("product_id") or 0)).exists()
            if not prod or not prod.sale_ok:
                raise UserError("A product in the order cannot be sold.")
            if prod.id in seen:
                raise UserError(f"'{prod.display_name}' appears twice; merge the lines.")
            seen.add(prod.id)
            qty = _num(r.get("qty"), "quantity", minimum=0.0001, maximum=1e7)
            if r.get("price_unit") is not None:
                price = _num(r["price_unit"], "price")
            else:  # the customer's price list (wholesale, quantity breaks), else the shelf price
                own = partner.specific_property_product_pricelist if partner and "specific_property_product_pricelist" in partner._fields else False
                price = own._get_product_price(prod, qty) if own else prod.lst_price
            disc = _num(r.get("discount", 0), "discount", maximum=100.0)
            taxes = prod.taxes_id.filtered(lambda t: t.company_id == company)
            res = taxes.compute_all(price * (1 - disc / 100.0), cur, qty, product=prod, partner=partner)
            out.append({"product": prod, "qty": qty, "price": price, "discount": disc,
                        "untaxed": res["total_excluded"], "total": res["total_included"]})  # fmt: skip
        return out

    @api.model
    def _so_view(self, so):
        deliveries = so.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing")
        return {
            "id": so.id, "name": so.name, "state": so.state, "partner_id": so.partner_id.id, "partner": so.partner_id.name,
            "date": fields.Datetime.to_string(so.date_order)[:10],
            "amount_untaxed": so.amount_untaxed, "amount_tax": so.amount_tax, "amount_total": so.amount_total,
            "invoice_status": so.invoice_status,
            "delivery_status": (
                "none" if not deliveries else "done" if all(p.state == "done" for p in deliveries if p.state != "cancel")
                else "waiting"
            ),
            "lines": [
                {"id": l.id, "product_id": l.product_id.id, "name": l.name, "qty": l.product_uom_qty, "delivered": l.qty_delivered,
                 "invoiced": l.qty_invoiced, "price_unit": l.price_unit, "discount": l.discount, "subtotal": l.price_subtotal,
                 "total": l.price_total, "tracking": l.product_id.tracking if "tracking" in l.product_id._fields else "none"}
                for l in so.order_line if not l.display_type
            ],  # fmt: skip
            "invoices": [self._invoice_view(b) for b in so.invoice_ids if b.state != "cancel"],
            "pickings": [{"id": p.id, "name": p.name, "state": p.state} for p in deliveries],
        }

    @api.model
    def sorder_products(self, query, limit):
        self._require_internal_user()
        self._need_sales_orders()
        domain = [("sale_ok", "=", True)]
        q = (query or "").strip()
        if q:
            domain += ["|", "|", ("name", "ilike", q), ("barcode", "ilike", q), ("default_code", "ilike", q)]
        prods = self.env["product.product"].search(domain, limit=max(1, min(int(limit or 10), 30)), order="name")
        return wire({"items": [{"product_id": p.id, "name": p.display_name, "price": p.lst_price,
                                "on_hand": p.qty_available if p.is_storable else None, "tracking": p.tracking if "tracking" in p._fields else "none"}
                               for p in prods]})  # fmt: skip

    @api.model
    def sorder_quote(self, spec):
        """Read-only: Odoo's totals for these lines (taxes included)."""
        self._require_internal_user()
        self._need_sales_orders()
        partner = self.env["res.partner"].browse(int(spec.get("partner_id") or 0)).exists() or self.env["res.partner"]
        lines = self._so_lines(spec, partner)
        cur = self.env.company.currency_id
        return wire({"untaxed": cur.round(sum(l["untaxed"] for l in lines)), "total": cur.round(sum(l["total"] for l in lines)),
                     "currency": cur.name})  # fmt: skip

    @api.model
    def sorder_get(self, order_id):
        self._require_internal_user()
        self._need_sales_orders()
        so = self.env["sale.order"].browse(int(order_id or 0)).exists()
        return wire({"found": True, "order": self._so_view(so)} if so else {"found": False})

    @api.model
    def sorder_list(self, limit, offset):
        self._require_internal_user()
        self._need_sales_orders()
        S = self.env["sale.order"]
        dom = [("state", "in", ("sale", "done", "cancel"))]
        recs = S.search(dom, limit=max(1, min(int(limit or 25), 100)), offset=max(0, int(offset or 0)), order="id desc")
        return wire({"total": S.search_count(dom), "items": [self._so_view(o) for o in recs]})

    # ---------- writes ----------
    @api.model
    def _so_deliver(self, so):
        """Validate every open delivery in full. Refuses (changing nothing) when stock is short."""
        pickings = so.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing" and p.state not in ("done", "cancel"))
        for ln in so.order_line.filtered(lambda l: l.product_id.is_storable and not l.display_type):
            need = ln.product_uom_qty - ln.qty_delivered
            if need > TOL and ln.product_id.qty_available + TOL < need:
                raise UserError(f"STOCK_SHORT: '{ln.product_id.display_name}': {ln.product_id.qty_available:g} in stock, {need:g} needed.")
            if need > TOL and ln.product_id.tracking != "none":
                raise UserError(f"TRACKED_DELIVERY: '{ln.product_id.display_name}' is tracked by lot/serial; deliver it in Odoo.")
        for pk in pickings:
            for m in pk.move_ids:
                m.quantity = m.product_uom_qty
                m.picked = True
            res = pk.with_context(skip_sms=True).button_validate()
            if isinstance(res, dict) and res.get("res_model") == "stock.backorder.confirmation":
                self.env["stock.backorder.confirmation"].with_context(**res.get("context", {})).create({"pick_ids": [(4, pk.id)]}).process_cancel_backorder()
            elif isinstance(res, dict):
                raise UserError("Odoo needs a manual step to finish this delivery; complete it in Odoo.")
            if pk.state != "done":
                raise UserError(f"The delivery did not complete (state: {pk.state}).")
        return pickings

    @api.model
    def _so_invoice(self, so, due_days):
        so.invalidate_recordset()
        if so.invoice_status != "to invoice":
            raise UserError("Nothing is left to invoice: deliver the goods first, or everything is already invoiced.")
        moves = so._create_invoices()
        today = fields.Date.context_today(self)
        for mv in moves:
            vals = {"invoice_date": today}
            if due_days is not None:
                vals.update({"invoice_payment_term_id": False, "invoice_date_due": today + datetime.timedelta(days=int(due_days))})
            mv.write(vals)
            mv.action_post()
            if mv.state != "posted":
                raise UserError(f"The invoice could not be posted (state: {mv.state}).")
        return moves

    @api.model
    def sorder_create(self, op_id, key, spec):
        self._require_internal_user()
        self._need_sales_orders()
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid operation key.")
        existing = self._managed(f"so_{key}")
        if existing:
            return wire({"outcome": "already_exists", "refs": {"order": self._so_view(existing)}})
        partner = self.env["res.partner"].browse(int(spec.get("partner_id") or 0)).exists()
        if not partner:
            raise UserError("CUSTOMER_REQUIRED: choose the customer for this order.")
        lines = self._so_lines(spec, partner)
        total = sum(l["total"] for l in lines)
        due_days = spec.get("due_days")
        if due_days is not None and not 0 <= int(due_days) <= 365:
            raise UserError("The credit period must be 0-365 days.")
        if spec.get("invoice_now"):
            limit = partner.credit_limit if "credit_limit" in partner._fields else 0.0
            if limit and limit > 0 and not spec.get("credit_override"):
                bal = self._customer_balance(partner)
                if bal + total > limit + TOL:
                    raise UserError(f"CREDIT_LIMIT_EXCEEDED: the customer owes {bal}; adding {total:.2f} passes the limit {limit}.")
        if spec.get("deliver_now"):  # check before creating anything
            for l in lines:
                p = l["product"]
                if p.is_storable and p.qty_available + TOL < l["qty"]:
                    raise UserError(f"STOCK_SHORT: '{p.display_name}': {p.qty_available:g} in stock, {l['qty']:g} needed.")
                if p.is_storable and p.tracking != "none":
                    raise UserError(f"TRACKED_DELIVERY: '{p.display_name}' is tracked by lot/serial; deliver it in Odoo.")
        note = _text(spec.get("note"), "note", 500, required=False)
        vals = {"partner_id": partner.id, "order_line": [(0, 0, {"product_id": l["product"].id, "product_uom_qty": l["qty"],
                                                              "price_unit": l["price"], "discount": l["discount"]}) for l in lines]}  # fmt: skip
        if note and "note" in self.env["sale.order"]._fields:
            vals["note"] = note
        so = self.env["sale.order"].create(vals)
        so.action_confirm()
        if so.state not in ("sale", "done"):
            raise UserError(f"The order was created but is waiting in Odoo (state: {so.state}).")
        self._tag(f"so_{key}", so)
        if spec.get("deliver_now"):
            self._so_deliver(so)
        if spec.get("invoice_now"):
            self._so_invoice(so, due_days)
        return wire({"outcome": "created", "refs": {"order": self._so_view(self.env["sale.order"].browse(so.id))}})

    @api.model
    def sorder_deliver(self, op_id, key, spec):
        self._require_internal_user()
        self._need_sales_orders()
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid operation key.")
        so = self.env["sale.order"].browse(int(spec.get("order_id") or 0)).exists()
        if not so or so.state not in ("sale", "done"):
            raise UserError("Only a confirmed order can be delivered.")
        if not so.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing" and p.state not in ("done", "cancel")):
            return wire({"outcome": "already_exists", "refs": {"order": self._so_view(so)}})
        self._so_deliver(so)
        return wire({"outcome": "created", "refs": {"order": self._so_view(self.env["sale.order"].browse(so.id))}})

    @api.model
    def sorder_invoice(self, op_id, key, spec):
        self._require_internal_user()
        self._need_sales_orders()
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid operation key.")
        existing = self._managed(f"soinv_{key}")
        if existing:
            return wire({"outcome": "already_exists", "refs": {"order": self._so_view(self.env["sale.order"].browse(spec.get("order_id")).exists()),
                                                              "invoice": self._invoice_view(existing)}})  # fmt: skip
        so = self.env["sale.order"].browse(int(spec.get("order_id") or 0)).exists()
        if not so or so.state not in ("sale", "done"):
            raise UserError("Only a confirmed order can be invoiced.")
        partner = so.partner_id
        due_days = spec.get("due_days")
        if due_days is not None and not 0 <= int(due_days) <= 365:
            raise UserError("The credit period must be 0-365 days.")
        pending = sum(l.price_total * (l.qty_to_invoice / l.product_uom_qty) for l in so.order_line if l.product_uom_qty and l.qty_to_invoice > 0)
        limit = partner.credit_limit if "credit_limit" in partner._fields else 0.0
        if limit and limit > 0 and not spec.get("credit_override"):
            bal = self._customer_balance(partner)
            if bal + pending > limit + TOL:
                raise UserError(f"CREDIT_LIMIT_EXCEEDED: the customer owes {bal}; adding {pending:.2f} passes the limit {limit}.")
        moves = self._so_invoice(so, due_days)
        self._tag(f"soinv_{key}", moves[:1])
        return wire({"outcome": "created", "refs": {"order": self._so_view(self.env["sale.order"].browse(so.id)), "invoice": self._invoice_view(moves[:1])}})

    @api.model
    def sorder_cancel(self, op_id, key, spec):
        self._require_internal_user()
        self._need_sales_orders()
        so = self.env["sale.order"].browse(int(spec.get("order_id") or 0)).exists()
        if not so:
            raise UserError("Order not found.")
        if so.state == "cancel":
            return wire({"outcome": "already_exists", "refs": {"order": self._so_view(so)}})
        if any(l.qty_delivered or l.qty_invoiced for l in so.order_line):
            raise UserError("Part of this order is already delivered or invoiced; it cannot be cancelled here.")
        so._action_cancel()
        so = self.env["sale.order"].browse(so.id)
        if so.state != "cancel":
            raise UserError("The order could not be cancelled.")
        return wire({"outcome": "updated", "refs": {"order": self._so_view(so)}})
