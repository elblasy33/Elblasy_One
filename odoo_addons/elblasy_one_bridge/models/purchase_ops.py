"""Purchasing on Odoo's native documents: suppliers, purchase orders, receipts, vendor bills, payments.

Money and stock only ever move through Odoo's own workflows (purchase.order -> stock.picking ->
account.move -> account.payment). Every write is keyed (XML id `elblasy_one.<prefix>_<key>`) so a
retry after a lost response returns what already exists instead of doing it twice. Quantities are
kept apart on purpose: ordered / received / billed / on hand / incoming are different numbers."""

import re

from odoo import api, fields, models
from odoo.exceptions import UserError

from .bridge import wire

KEY_RE = re.compile(r"^[a-f0-9]{32}$")
MAX_LINES = 100
TOLERANCE = 0.005


def _num(v, field, minimum=0.0, maximum=1e9):
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise UserError(f"{field} must be a number.") from None
    if n != n or n < minimum or n > maximum:
        raise UserError(f"{field} is out of range.")
    return n


def _text(v, field, limit, required=True):
    v = (v or "").strip() if isinstance(v, str) else ""
    if required and not v:
        raise UserError(f"{field} is required.")
    if len(v) > limit:
        raise UserError(f"{field} is too long (max {limit}).")
    return v


class ElblasyBridgePurchase(models.AbstractModel):
    _inherit = "elblasy.bridge"

    @api.model
    def _need_purchase(self):
        if not self.env.user.has_group("purchase.group_purchase_user"):
            raise UserError("The Odoo service user needs the Purchase user rights.")

    @api.model
    def _key(self, key):
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid operation key.")
        return key

    # ---------------- views ----------------
    @api.model
    def _po_view(self, po):
        return {
            "id": po.id,
            "name": po.name,
            "state": po.state,
            "partner_id": po.partner_id.id,
            "partner": po.partner_id.name,
            "date_order": fields.Datetime.to_string(po.date_order),
            "amount_untaxed": po.amount_untaxed,
            "amount_tax": po.amount_tax,
            "amount_total": po.amount_total,
            "invoice_status": po.invoice_status,
            "receipt_status": po.receipt_status if "receipt_status" in po._fields else None,
            "lines": [
                {
                    "id": l.id,
                    "product_id": l.product_id.id,
                    "name": l.name,
                    "ordered": l.product_qty,
                    "received": l.qty_received,
                    "billed": l.qty_invoiced,
                    "price_unit": l.price_unit,
                    "subtotal": l.price_subtotal,
                    "tracking": l.product_id.tracking if "tracking" in l.product_id._fields else "none",
                }
                for l in po.order_line
                if not l.display_type
            ],
            "pickings": [{"id": p.id, "name": p.name, "state": p.state} for p in po.picking_ids],
            "bills": [self._bill_brief(b) for b in po.invoice_ids],
        }

    @api.model
    def _bill_brief(self, b):
        return {
            "id": b.id,
            "name": b.name or None,
            "state": b.state,
            "payment_state": b.payment_state,
            "amount_total": b.amount_total,
            "amount_residual": b.amount_residual,
            "invoice_date": str(b.invoice_date) if b.invoice_date else None,
            "move_type": b.move_type,
        }

    # ---------------- suppliers ----------------
    @api.model
    def _supplier_balance(self, partner):
        """What we owe this supplier: open posted vendor bills minus open credit notes."""
        moves = self.env["account.move"].search(
            [("partner_id", "=", partner.id), ("move_type", "in", ("in_invoice", "in_refund")),
             ("state", "=", "posted"), ("payment_state", "not in", ("paid", "reversed"))]
        )  # fmt: skip
        cur = self.env.company.currency_id
        return cur.round(sum(m.amount_residual if m.move_type == "in_invoice" else -m.amount_residual for m in moves))

    @api.model
    def suppliers_upsert(self, op_id, key, spec):
        self._require_internal_user()
        self._need_purchase()
        key = self._key(key)
        existing = self._managed(f"partner_{key}")
        if existing:
            return wire({"outcome": "already_exists", "refs": {"supplier": self._supplier_view(existing)}})
        vals = {
            "name": _text(spec.get("name"), "name", 200),
            "supplier_rank": 1,
            "is_company": True,
        }
        for f, limit in (("phone", 40), ("email", 120), ("vat", 40), ("street", 200)):
            v = _text(spec.get(f), f, limit, required=False)
            if v:
                vals[f] = v
        p = self.env["res.partner"].create(vals)
        self._tag(f"partner_{key}", p)
        return wire({"outcome": "created", "refs": {"supplier": self._supplier_view(p)}})

    @api.model
    def _supplier_view(self, p):
        return {"id": p.id, "name": p.name, "phone": p.phone or None, "email": p.email or None,
                "balance": self._supplier_balance(p)}  # fmt: skip

    @api.model
    def suppliers_search(self, query, limit, offset):
        self._require_internal_user()
        self._need_purchase()
        domain = [("supplier_rank", ">", 0)]
        q = (query or "").strip()
        if q:
            domain += ["|", "|", ("name", "ilike", q), ("phone", "ilike", q), ("email", "ilike", q)]
        P = self.env["res.partner"]
        limit = max(1, min(int(limit or 25), 100))
        recs = P.search(domain, limit=limit, offset=max(0, int(offset or 0)), order="name")
        return wire({"total": P.search_count(domain), "items": [self._supplier_view(p) for p in recs]})

    @api.model
    def supplier_statement(self, partner_id):
        self._require_internal_user()
        self._need_purchase()
        p = self.env["res.partner"].browse(int(partner_id or 0)).exists()
        if not p or not p.supplier_rank:
            return wire({"found": False})
        bills = self.env["account.move"].search(
            [("partner_id", "=", p.id), ("move_type", "in", ("in_invoice", "in_refund")), ("state", "=", "posted")],
            order="invoice_date desc, id desc", limit=100,
        )  # fmt: skip
        payments = self.env["account.payment"].search(
            [("partner_id", "=", p.id), ("payment_type", "=", "outbound"), ("state", "in", ("paid", "in_process", "posted"))]
            if "state" in self.env["account.payment"]._fields
            else [("partner_id", "=", p.id), ("payment_type", "=", "outbound")],
            order="date desc, id desc", limit=100,
        )  # fmt: skip
        return wire(
            {
                "found": True,
                "supplier": self._supplier_view(p),
                "bills": [self._bill_brief(b) for b in bills],
                "payments": [
                    {"id": x.id, "name": x.name, "date": str(x.date), "amount": x.amount,
                     "journal": x.journal_id.name, "state": x.state}
                    for x in payments
                ],
            }
        )

    # ---------------- stock levels (kept apart: on hand / reserved / incoming / forecast) ----------------
    @api.model
    def stock_levels(self, product_ids):
        self._require_internal_user()
        ids = [int(i) for i in (product_ids or [])][:500]
        out = {}
        for p in self.env["product.product"].browse(ids).exists():
            out[str(p.id)] = {
                "on_hand": p.qty_available,
                "free": p.free_qty,
                "incoming": p.incoming_qty,
                "outgoing": p.outgoing_qty,
                "forecast": p.virtual_available,
            }
        return wire({"levels": out})

    @api.model
    def purchase_products(self, query, limit):
        """Purchasable variants for building an order (a shoe in size 42 is one product here)."""
        self._require_internal_user()
        self._need_purchase()
        limit = max(1, min(int(limit or 20), 50))
        domain = [("purchase_ok", "=", True)]
        q = (query or "").strip()
        if q:
            domain += ["|", "|", "|", ("name", "ilike", q), ("barcode", "ilike", q), ("default_code", "ilike", q),
                       ("product_template_attribute_value_ids.name", "ilike", q)]  # fmt: skip
        out = []
        for p in self.env["product.product"].search(domain, limit=limit, order="name, id"):
            out.append({
                "product_id": p.id, "name": p.display_name, "barcode": p.barcode or None,
                "cost": p.standard_price, "on_hand": p.qty_available if p.is_storable else None,
                "tracking": p.tracking if "tracking" in p._fields else "none",
            })  # fmt: skip
        return wire({"items": out})

    # ---------------- purchase orders ----------------
    @api.model
    def purchase_create_order(self, op_id, key, spec):
        self._require_internal_user()
        self._need_purchase()
        key = self._key(key)
        existing = self._managed(f"po_{key}")
        if existing:
            return wire({"outcome": "already_exists", "refs": {"order": self._po_view(existing)}})
        partner = self.env["res.partner"].browse(int(spec.get("partner_id") or 0)).exists()
        if not partner or not partner.supplier_rank:
            raise UserError("Supplier not found.")
        lines = spec.get("lines") or []
        if not 1 <= len(lines) <= MAX_LINES:
            raise UserError(f"An order needs 1-{MAX_LINES} lines.")
        vals_lines, seen = [], set()
        for l in lines:
            prod = self.env["product.product"].browse(int(l.get("product_id") or 0)).exists()
            if not prod or not prod.purchase_ok:
                raise UserError("A product in the order cannot be purchased.")
            if prod.id in seen:
                raise UserError(f"'{prod.display_name}' appears twice; merge the lines.")
            seen.add(prod.id)
            qty = _num(l.get("qty"), "quantity", minimum=0.0001, maximum=1e7)
            price = _num(l.get("price_unit"), "price", maximum=1e9) if l.get("price_unit") is not None else prod.standard_price
            vals_lines.append((0, 0, {"product_id": prod.id, "product_qty": qty, "price_unit": price, "name": prod.display_name}))
        order_vals = {"partner_id": partner.id, "order_line": vals_lines}
        note = _text(spec.get("note"), "note", 500, required=False)
        note_field = next((f for f in ("notes", "note") if f in self.env["purchase.order"]._fields), None)
        if note and note_field:
            order_vals[note_field] = note  # `notes` (18) / `note` (19)
        po = self.env["purchase.order"].create(order_vals)
        po.button_confirm()
        po = self.env["purchase.order"].browse(po.id)
        if po.state not in ("purchase", "done"):
            raise UserError(f"The order was created but is waiting for approval in Odoo (state: {po.state}).")
        self._tag(f"po_{key}", po)
        return wire({"outcome": "created", "refs": {"order": self._po_view(po)}})

    @api.model
    def purchase_get(self, order_id):
        self._require_internal_user()
        self._need_purchase()
        po = self.env["purchase.order"].browse(int(order_id or 0)).exists()
        return wire({"found": True, "order": self._po_view(po)} if po else {"found": False})

    @api.model
    def purchase_list(self, limit, offset):
        self._require_internal_user()
        self._need_purchase()
        O = self.env["purchase.order"]
        limit = max(1, min(int(limit or 25), 100))
        recs = O.search([], limit=limit, offset=max(0, int(offset or 0)), order="id desc")
        return wire({"total": O.search_count([]), "items": [self._po_view(o) for o in recs]})

    # ---------------- receiving goods ----------------
    @api.model
    def purchase_receive(self, op_id, key, spec):
        """Receive goods against a confirmed order. `lines` = [{line_id, qty, lot_name?, expiry?}]; a
        partial receipt leaves a backorder for the rest. Receiving more than ordered is refused."""
        self._require_internal_user()
        self._need_purchase()
        key = self._key(key)
        existing = self._managed(f"rcpt_{key}")
        if existing:
            return wire({"outcome": "already_exists", "refs": {"order": self._po_view(existing.purchase_id) if "purchase_id" in existing._fields and existing.purchase_id else {"id": existing.id}}})
        po = self.env["purchase.order"].browse(int(spec.get("order_id") or 0)).exists()
        if not po or po.state not in ("purchase", "done"):
            raise UserError("Only a confirmed order can be received.")
        wanted = {int(l["line_id"]): l for l in (spec.get("lines") or [])}
        if not wanted:
            raise UserError("Say how much of which line arrived.")
        pickings = po.picking_ids.filtered(lambda p: p.state not in ("done", "cancel") and p.picking_type_code == "incoming")
        if not pickings:
            raise UserError("Nothing is waiting to be received on this order.")
        # every requested line must belong to the order and not exceed what is still expected
        by_line = {l.id: l for l in po.order_line}
        for lid, l in wanted.items():
            pol = by_line.get(lid)
            if not pol:
                raise UserError("A line does not belong to this order.")
            qty = _num(l.get("qty"), "received quantity", minimum=0.0001, maximum=1e7)
            remaining = pol.product_qty - pol.qty_received
            if qty > remaining + TOLERANCE:
                raise UserError(f"'{pol.product_id.display_name}': {qty} exceeds the {remaining} still expected.")
            if pol.product_id.tracking != "none" and not _text(l.get("lot_name"), "lot number", 80, required=False):
                raise UserError(f"'{pol.product_id.display_name}' is tracked: enter the lot number.")
        done_picking = None
        for pk in pickings:
            moves = pk.move_ids.filtered(lambda m: m.purchase_line_id.id in wanted)
            if not moves:
                continue
            for m in pk.move_ids:  # nothing is received unless it was asked for
                m.quantity = 0
                m.picked = False
            for m in moves:
                req = wanted[m.purchase_line_id.id]
                qty = _num(req["qty"], "received quantity", minimum=0.0001)
                lot = _text(req.get("lot_name"), "lot number", 80, required=False)
                if lot:
                    m.move_line_ids.unlink()
                    self.env["stock.move.line"].create({
                        "move_id": m.id, "picking_id": pk.id, "product_id": m.product_id.id,
                        "location_id": m.location_id.id, "location_dest_id": m.location_dest_id.id,
                        "quantity": qty, "lot_name": lot, "product_uom_id": m.product_uom.id,
                    })  # fmt: skip
                else:
                    m.quantity = qty
                m.picked = True
            res = pk.with_context(skip_sms=True).button_validate()
            if isinstance(res, dict) and res.get("res_model") == "stock.backorder.confirmation":
                wiz = self.env["stock.backorder.confirmation"].with_context(**res.get("context", {})).create({"pick_ids": [(4, pk.id)]})
                wiz.process()
            elif isinstance(res, dict) and res.get("res_model") == "stock.immediate.transfer":
                self.env["stock.immediate.transfer"].with_context(**res.get("context", {})).create({"pick_ids": [(4, pk.id)]}).process()
            elif isinstance(res, dict):
                raise UserError("Odoo needs a manual step to finish this receipt; complete it in Odoo.")
            if pk.state != "done":
                raise UserError(f"The receipt did not complete (state: {pk.state}).")
            done_picking = done_picking or pk
        if not done_picking:
            raise UserError("The lines do not match any pending receipt.")
        for lid, req in wanted.items():
            if req.get("expiry") and "expiration_date" in self.env["stock.lot"]._fields:
                lot = self.env["stock.lot"].search([("name", "=", req.get("lot_name")), ("product_id", "=", by_line[lid].product_id.id)], limit=1)
                if lot:
                    lot.expiration_date = req["expiry"]
        self._tag(f"rcpt_{key}", done_picking)
        return wire({"outcome": "created", "refs": {"order": self._po_view(self.env["purchase.order"].browse(po.id)), "picking": done_picking.name}})

    # ---------------- returning goods to the supplier ----------------
    @api.model
    def purchase_return(self, op_id, key, spec):
        """Send received goods back to the supplier. `lines` = [{line_id, qty}]. The stock leaves through
        a real return transfer; when the order was already billed, a posted vendor credit note for the
        returned value reduces what is owed. Returning more than was received is refused."""
        self._require_internal_user()
        self._need_purchase()
        key = self._key(key)
        existing = self._managed(f"ret_{key}")
        if existing:
            po = existing.purchase_id if "purchase_id" in existing._fields and existing.purchase_id else None
            return wire({"outcome": "already_exists", "refs": {"order": self._po_view(po) if po else {"id": existing.id}}})
        po = self.env["purchase.order"].browse(int(spec.get("order_id") or 0)).exists()
        if not po or po.state not in ("purchase", "done"):
            raise UserError("Only a confirmed order can have goods returned.")
        wanted = {}
        for item in spec.get("lines") or []:
            lid = int(item.get("line_id") or 0)
            wanted[lid] = wanted.get(lid, 0.0) + _num(item.get("qty"), "returned quantity", minimum=0.0001, maximum=1e7)
        if not wanted:
            raise UserError("Say how much of which line goes back.")
        by_line = {l.id: l for l in po.order_line}
        for lid, qty in wanted.items():
            pol = by_line.get(lid)
            if not pol:
                raise UserError("A line does not belong to this order.")
            if qty > pol.qty_received + TOLERANCE:
                raise UserError(f"'{pol.product_id.display_name}': only {pol.qty_received:g} received, cannot return {qty:g}.")
        left = dict(wanted)
        first_return = None
        for pk in po.picking_ids.filtered(lambda p: p.state == "done" and p.picking_type_code == "incoming").sorted("id"):
            take = {}
            for m in pk.move_ids.filtered(lambda m: m.state == "done" and m.purchase_line_id.id in left):
                give = min(left[m.purchase_line_id.id], m.quantity)
                if give > TOLERANCE:
                    take[m.id] = give
                    left[m.purchase_line_id.id] -= give
            if not take:
                continue
            wiz = self.env["stock.return.picking"].with_context(active_id=pk.id, active_model="stock.picking").create({})
            for ln in wiz.product_return_moves:
                ln.quantity = take.get(ln.move_id.id, 0.0)
            wiz.product_return_moves.filtered(lambda r: not r.quantity).unlink()
            res = wiz.action_create_returns() if hasattr(wiz, "action_create_returns") else wiz.create_returns()
            rp = self.env["stock.picking"].browse(res["res_id"])
            for m in rp.move_ids:
                m.quantity = m.product_uom_qty
                m.picked = True
            out = rp.with_context(skip_sms=True).button_validate()
            if isinstance(out, dict) and out.get("res_model") == "stock.backorder.confirmation":
                self.env["stock.backorder.confirmation"].with_context(**out.get("context", {})).create({"pick_ids": [(4, rp.id)]}).process_cancel_backorder()
            elif isinstance(out, dict):
                raise UserError("Odoo needs a manual step to finish this return; complete it in Odoo.")
            if rp.state != "done":
                raise UserError(f"The return did not complete (state: {rp.state}).")
            first_return = first_return or rp
        if not first_return or any(v > TOLERANCE for v in left.values()):
            raise UserError("The returned goods could not be matched to received transfers.")
        credit = None
        billed = po.invoice_ids.filtered(lambda b: b.move_type == "in_invoice" and b.state == "posted")
        if billed:
            note_lines = []
            for lid, qty in wanted.items():
                pol = by_line[lid]
                note_lines.append((0, 0, {"product_id": pol.product_id.id, "quantity": qty, "price_unit": pol.price_unit,
                                          "purchase_line_id": pol.id, "tax_ids": [(6, 0, pol.tax_ids.ids if "tax_ids" in pol._fields else pol.taxes_id.ids)]}))  # fmt: skip
            credit = self.env["account.move"].create({
                "move_type": "in_refund", "partner_id": po.partner_id.id, "invoice_date": fields.Date.context_today(self),
                "ref": f"Return {first_return.name}", "invoice_origin": po.name, "invoice_line_ids": note_lines,
            })  # fmt: skip
            credit.action_post()
        self._tag(f"ret_{key}", first_return)
        refs = {"order": self._po_view(self.env["purchase.order"].browse(po.id)), "picking": first_return.name}
        if credit:
            refs["credit_note"] = self._bill_brief(credit)
        return wire({"outcome": "created", "refs": refs})

    # ---------------- vendor bills ----------------
    @api.model
    def purchase_create_bill(self, op_id, key, spec):
        """Bill what was received (Odoo's 'control on received quantities'), post it."""
        self._require_internal_user()
        self._need_purchase()
        key = self._key(key)
        existing = self._managed(f"bill_{key}")
        if existing:
            return wire({"outcome": "already_exists", "refs": {"bill": self._bill_brief(existing)}})
        po = self.env["purchase.order"].browse(int(spec.get("order_id") or 0)).exists()
        if not po or po.state not in ("purchase", "done"):
            raise UserError("Only a confirmed order can be billed.")
        if po.invoice_status != "to invoice":
            raise UserError("Nothing is left to bill: receive the goods first, or everything received is already billed.")
        action = po.action_create_invoice()
        bill = self.env["account.move"].browse(action.get("res_id") or 0)
        if not bill and action.get("domain"):
            bill = self.env["account.move"].search(action["domain"], order="id desc", limit=1)
        if not bill:
            bill = po.invoice_ids.filtered(lambda b: b.state == "draft")[:1]
        if not bill:
            raise UserError("Odoo did not create a bill.")
        bill.write({"invoice_date": fields.Date.context_today(self)})
        bill.action_post()
        bill = self.env["account.move"].browse(bill.id)
        if bill.state != "posted":
            raise UserError(f"The bill could not be posted (state: {bill.state}).")
        self._tag(f"bill_{key}", bill)
        view = self._bill_brief(bill)
        view["lines"] = [{"product_id": l.product_id.id, "qty": l.quantity, "price_unit": l.price_unit, "total": l.price_total}
                         for l in bill.invoice_line_ids if l.display_type in (False, "product")]  # fmt: skip
        return wire({"outcome": "created", "refs": {"bill": view, "order_id": po.id}})

    @api.model
    def purchase_get_bill(self, bill_id):
        self._require_internal_user()
        self._need_purchase()
        b = self.env["account.move"].browse(int(bill_id or 0)).exists()
        if not b or b.move_type not in ("in_invoice", "in_refund"):
            return wire({"found": False})
        view = self._bill_brief(b)
        view["partner_id"] = b.partner_id.id
        view["lines"] = [{"product_id": l.product_id.id, "qty": l.quantity, "price_unit": l.price_unit, "total": l.price_total}
                         for l in b.invoice_line_ids if l.display_type in (False, "product")]  # fmt: skip
        return wire({"found": True, "bill": view})

    # ---------------- paying a supplier ----------------
    @api.model
    def purchase_pay_bill(self, op_id, key, spec):
        """Pay a posted vendor bill (fully or partially) from the cash or bank journal."""
        self._require_internal_user()
        self._need_purchase()
        key = self._key(key)
        existing = self._managed(f"pay_{key}")
        if existing:
            return wire({"outcome": "already_exists", "refs": {"payment_id": existing.id, "bill": self._bill_brief(existing.reconciled_bill_ids[:1]) if existing.reconciled_bill_ids else None}})
        bill = self.env["account.move"].browse(int(spec.get("bill_id") or 0)).exists()
        if not bill or bill.move_type != "in_invoice" or bill.state != "posted":
            raise UserError("Only a posted vendor bill can be paid.")
        if bill.payment_state in ("paid", "in_payment") or bill.amount_residual <= TOLERANCE:
            raise UserError("This bill is already paid.")
        amount = _num(spec.get("amount"), "payment amount", minimum=0.01)
        if amount > bill.amount_residual + TOLERANCE:
            raise UserError(f"The payment ({amount}) is more than what is still owed ({bill.amount_residual}).")
        jtype = spec.get("journal_type")
        if jtype not in ("cash", "bank"):
            raise UserError("Pay from the cash or the bank journal.")
        journal = self.env["account.journal"].search([("type", "=", jtype)], limit=1)
        if not journal:
            raise UserError(f"No {jtype} journal exists yet.")
        wiz = self.env["account.payment.register"].with_context(active_model="account.move", active_ids=bill.ids).create(
            {"amount": amount, "journal_id": journal.id, "payment_date": fields.Date.context_today(self)}
        )
        payments = wiz._create_payments()
        pay = payments[:1]
        if not pay:
            raise UserError("Odoo did not create the payment.")
        self._tag(f"pay_{key}", pay)
        bill = self.env["account.move"].browse(bill.id)
        return wire({"outcome": "created", "refs": {"payment_id": pay.id, "bill": self._bill_brief(bill)}})
