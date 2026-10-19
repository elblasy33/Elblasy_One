"""Sales on Odoo's native POS engine: sessions, quotes, checkout, refunds, closing, read-backs.

Principles
- Prices and taxes are computed by Odoo (pricelist + tax engine), never by the platform. The caller
  sends the total it expects; if Odoo's total differs the sale is refused (price changed), so a
  cashier is never charged an amount they did not see.
- Checkout is idempotent by the caller's key (used as the POS order `uuid`): a retry returns the
  existing order, never a second one.
- Version differences live in small adapters (see `_change_sign`): Odoo 19 wants the change
  (`amount_return`) as a negative number, Odoo 18 as a positive one.
- Nothing here edits posted accounting: closing a session is Odoo's own validated flow."""

import re

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.release import version_info

from .bridge import wire

KEY_RE = re.compile(r"^[a-f0-9]{32}$")
MAX_LINES = 200
TOLERANCE = 0.005


def _num(v, field, minimum=0.0, maximum=1e9):
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise UserError(f"{field} must be a number.") from None
    if n != n or n < minimum or n > maximum:
        raise UserError(f"{field} is out of range.")
    return n


class ElblasyBridgeSales(models.AbstractModel):
    _inherit = "elblasy.bridge"

    # ---------- version adapters ----------
    @api.model
    def _change_sign(self):
        """Odoo 19 stores the change in `amount_return` as a negative number; 18 as positive."""
        return -1.0 if version_info[0] >= 19 else 1.0

    @api.model
    def _note_field(self):
        """Internal note field on pos.order: `general_note` (18) / `internal_note` (19)."""
        fields_ = self.env["pos.order"]._fields
        return next((f for f in ("internal_note", "general_note") if f in fields_), None)

    @api.model
    def _need_pos(self):
        if not self.env.user.has_group("point_of_sale.group_pos_user"):
            raise UserError("The Odoo service user needs the Point of Sale user rights.")

    @api.model
    def _config(self, config_id):
        cfg = self.env["pos.config"].browse(int(config_id or 0)).exists()
        if not cfg:
            raise UserError("Point of sale not found.")
        return cfg

    # ---------- views ----------
    @api.model
    def _session_view(self, s):
        return {
            "id": s.id,
            "name": s.name,
            "state": s.state,
            "config_id": s.config_id.id,
            "start_cash": s.cash_register_balance_start,
            "expected_cash": s.cash_register_balance_end,
            "counted_cash": s.cash_register_balance_end_real,
            "cash_difference": s.cash_register_difference,
            "opened_at": fields.Datetime.to_string(s.start_at) if s.start_at else None,
            "closed_at": fields.Datetime.to_string(s.stop_at) if s.stop_at else None,
            "order_count": len(s.order_ids),
        }

    @api.model
    def _order_view(self, o):
        return {
            "id": o.id,
            "name": o.name,
            "pos_reference": o.pos_reference,
            "uuid": o.uuid,
            "state": o.state,
            "session_id": o.session_id.id,
            "date_order": fields.Datetime.to_string(o.date_order),
            "amount_total": o.amount_total,
            "amount_tax": o.amount_tax,
            "amount_paid": o.amount_paid,
            "amount_return": abs(o.amount_return),
            "refund_of": o.lines.mapped("refunded_orderline_id.order_id")[:1].id or None,
            "partner_id": o.partner_id.id or None,
            "partner": o.partner_id.name or None,
            "invoice": (
                {
                    "id": o.account_move.id,
                    "name": o.account_move.name,
                    "state": o.account_move.state,
                    "payment_state": o.account_move.payment_state,
                    "amount_residual": o.account_move.amount_residual,
                }
                if o.account_move
                else None
            ),
            "credit_amount": sum(p.amount for p in o.payment_ids if p.payment_method_id.split_transactions),
            "lines": [
                {
                    "id": l.id,
                    "product_id": l.product_id.id,
                    "name": l.full_product_name or l.product_id.display_name,
                    "qty": l.qty,
                    "price_unit": l.price_unit,
                    "discount": l.discount,
                    "subtotal": l.price_subtotal,
                    "subtotal_incl": l.price_subtotal_incl,
                }
                for l in o.lines
            ],
            "payments": [
                {
                    "method_id": p.payment_method_id.id,
                    "method": p.payment_method_id.name,
                    "amount": p.amount,
                    "is_change": bool(p.is_change),
                    "is_credit": bool(p.payment_method_id.split_transactions),
                }
                for p in o.payment_ids
            ],
            "picking_states": [p.state for p in o.picking_ids],
        }

    # ---------- reads ----------
    @api.model
    def sales_state(self):
        self._require_internal_user()
        self._need_pos()
        company = self.env.company
        out = []
        for c in self.env["pos.config"].search([]):
            s = c.current_session_id
            out.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "session": self._session_view(s) if s else None,
                    "payment_methods": [
                        {"id": m.id, "name": m.name, "is_cash": bool(m.is_cash_count), "is_credit": bool(m.split_transactions)}
                        for m in c.payment_method_ids
                    ],
                }
            )
        stock_mode = getattr(company, "point_of_sale_update_stock_quantities", None)
        return wire(
            {
                "configs": out,
                "currency": company.currency_id.name,
                "currency_decimals": company.currency_id.decimal_places,
                "stock_updates": stock_mode,
            }
        )

    @api.model
    def _price_for(self, cfg, product, qty):
        pl = cfg.pricelist_id if "pricelist_id" in cfg._fields else False
        if pl and hasattr(pl, "_get_product_price"):
            return pl._get_product_price(product, qty)
        return product.lst_price

    @api.model
    def _quote_lines(self, cfg, lines, partner=None):
        if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
            raise UserError(f"A sale needs 1-{MAX_LINES} lines.")
        currency = cfg.currency_id
        fpos = cfg.default_fiscal_position_id if "default_fiscal_position_id" in cfg._fields else False
        quoted, total, tax_total = [], 0.0, 0.0
        for raw in lines:
            product = self.env["product.product"].browse(int(raw.get("product_id") or 0)).exists()
            if not product or not product.sale_ok or not product.available_in_pos:
                raise UserError("A product in the sale is not available for sale.")
            qty = _num(raw.get("qty"), "quantity", minimum=0.0001, maximum=1e6)
            disc = _num(raw.get("discount", 0), "discount", maximum=100.0)
            unit = self._price_for(cfg, product, qty)
            taxes = product.taxes_id.filtered(lambda t: t.company_id == cfg.company_id)
            if fpos:
                taxes = fpos.map_tax(taxes)
            net_unit = unit * (1 - disc / 100.0)
            res = taxes.compute_all(net_unit, currency, qty, product=product, partner=partner)
            incl, excl = res["total_included"], res["total_excluded"]
            quoted.append(
                {
                    "product_id": product.id,
                    "name": product.display_name,
                    "qty": qty,
                    "price_unit": unit,
                    "discount": disc,
                    "subtotal": excl,
                    "subtotal_incl": incl,
                    "tax_ids": taxes.ids,
                    "by_weight": bool(product.to_weight) if "to_weight" in product._fields else False,
                }
            )
            total += incl
            tax_total += incl - excl
        return quoted, currency.round(total), currency.round(tax_total)

    @api.model
    def sales_quote(self, spec):
        """Authoritative totals from Odoo's own pricelist/tax engine. Read-only."""
        self._require_internal_user()
        self._need_pos()
        cfg = self._config(spec.get("config_id"))
        quoted, total, tax = self._quote_lines(cfg, spec.get("lines"))
        return wire({"lines": quoted, "total": total, "tax": tax, "currency": cfg.currency_id.name})

    @api.model
    def sales_lookup(self, config_id, code):
        """Resolve a scanned barcode with Odoo's own nomenclature (handles weighed-item barcodes)."""
        self._require_internal_user()
        self._need_pos()
        cfg = self._config(config_id)
        code = (code or "").strip()
        if not re.fullmatch(r"[0-9A-Za-z\-]{3,64}", code):
            return wire({"found": False})
        nom = self.env.company.nomenclature_id if "nomenclature_id" in self.env.company._fields else False
        qty, lookup = 1.0, code
        if nom:
            parsed = nom.parse_barcode(code)
            if parsed.get("type") == "weight":
                qty, lookup = parsed["value"], parsed["base_code"]
        P = self.env["product.product"]
        product = P.search([("barcode", "=", lookup), ("available_in_pos", "=", True)], limit=1)
        if not product:  # a weighed barcode's base_code carries the zero-weight form
            product = P.search([("barcode", "=", code), ("available_in_pos", "=", True)], limit=1)
            qty = 1.0
        if not product:
            return wire({"found": False})
        return wire(
            {
                "found": True,
                "product_id": product.id,
                "name": product.display_name,
                "price": self._price_for(cfg, product, qty),
                "qty": qty,
                "by_weight": bool(product.to_weight) if "to_weight" in product._fields else False,
                "barcode": product.barcode or None,
            }
        )

    @api.model
    def sales_search(self, config_id, query, limit):
        """Sellable variants (a shoe in size 42 / black is one product here) for the register."""
        self._require_internal_user()
        self._need_pos()
        cfg = self._config(config_id)
        limit = max(1, min(int(limit or 24), 50))
        domain = [("available_in_pos", "=", True), ("sale_ok", "=", True)]
        q = (query or "").strip()
        if q:
            domain += ["|", "|", "|", ("name", "ilike", q), ("barcode", "ilike", q), ("default_code", "ilike", q),
                       ("product_template_attribute_value_ids.name", "ilike", q)]  # fmt: skip
        out = []
        for p in self.env["product.product"].search(domain, limit=limit, order="name, id"):
            out.append(
                {
                    "product_id": p.id,
                    "name": p.display_name,
                    "barcode": p.barcode or None,
                    "price": self._price_for(cfg, p, 1.0),
                    "on_hand": p.qty_available if p.is_storable else None,
                    "by_weight": bool(p.to_weight) if "to_weight" in p._fields else False,
                }
            )
        return wire({"items": out})

    @api.model
    def sales_get_order(self, order_id):
        self._require_internal_user()
        self._need_pos()
        o = self.env["pos.order"].browse(int(order_id)).exists()
        return wire({"found": True, "order": self._order_view(o)} if o else {"found": False})

    @api.model
    def sales_list_orders(self, session_id, limit, offset):
        self._require_internal_user()
        self._need_pos()
        domain = [("session_id", "=", int(session_id))] if session_id else []
        O = self.env["pos.order"]
        limit = max(1, min(int(limit or 25), 100))
        recs = O.search(domain, limit=limit, offset=max(0, int(offset or 0)), order="id desc")
        return wire({"total": O.search_count(domain), "items": [self._order_view(o) for o in recs]})

    @api.model
    def sales_get_session(self, session_id):
        self._require_internal_user()
        self._need_pos()
        s = self.env["pos.session"].browse(int(session_id)).exists()
        if not s:
            return wire({"found": False})
        view = self._session_view(s)
        view["move_state"] = s.move_id.state if s.move_id else None
        return wire({"found": True, "session": view})

    @api.model
    def sales_summary(self, day):
        """Paid POS orders for one calendar day (company timezone)."""
        self._require_internal_user()
        self._need_pos()
        d = fields.Date.from_string(day) if day else fields.Date.context_today(self)
        start = fields.Datetime.to_string(
            fields.Datetime.context_timestamp(self, fields.Datetime.from_string(f"{d} 00:00:00")).astimezone(__import__("datetime").timezone.utc).replace(tzinfo=None)
        )
        end = fields.Datetime.to_string(
            fields.Datetime.from_string(start) + __import__("datetime").timedelta(days=1)
        )
        orders = self.env["pos.order"].search(
            [("state", "in", ("paid", "done", "invoiced")), ("date_order", ">=", start), ("date_order", "<", end)]
        )
        cur = self.env.company.currency_id
        gross = cur.round(sum(o.amount_total for o in orders if o.amount_total > 0))
        refunds = cur.round(sum(o.amount_total for o in orders if o.amount_total < 0))
        by_method = {}
        for p in orders.payment_ids:
            key = p.payment_method_id.name
            by_method[key] = cur.round(by_method.get(key, 0.0) + p.amount)
        cash = cur.round(sum(p.amount for p in orders.payment_ids if p.payment_method_id.is_cash_count))
        return wire(
            {
                "day": str(d),
                "orders": len(orders.filtered(lambda o: o.amount_total > 0)),
                "gross_sales": gross,
                "refunds": refunds,
                "net_sales": cur.round(gross + refunds),
                "cash_collected": cash,
                "by_method": by_method,
                "currency": self.env.company.currency_id.name,
            }
        )

    # ---------- writes ----------
    @api.model
    def sales_open_session(self, op_id, key, spec):
        self._require_internal_user()
        self._need_pos()
        cfg = self._config(spec.get("config_id"))
        opening = _num(spec.get("opening_cash", 0), "opening cash")
        s = cfg.current_session_id
        if s and s.state == "opened":
            return wire({"outcome": "already_exists", "refs": {"session": self._session_view(s)}})
        if s and s.state in ("closing_control",):
            raise UserError("The current session is being closed.")
        if not s:
            s = self.env["pos.session"].create({"config_id": cfg.id})
        if s.state == "opening_control":
            s.set_opening_control(opening, spec.get("note") or "")
        s = self.env["pos.session"].browse(s.id)
        if s.state != "opened":
            raise UserError(f"The session could not be opened (state: {s.state}).")
        return wire({"outcome": "created", "refs": {"session": self._session_view(s)}})

    @api.model
    def sales_checkout(self, op_id, key, spec):
        self._require_internal_user()
        self._need_pos()
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid sale key.")
        Order = self.env["pos.order"]
        existing = Order.search([("uuid", "=", key)], limit=1)
        if existing:  # a retry after a lost response: return what was already created
            return wire({"outcome": "already_exists", "refs": {"order": self._order_view(existing)}})

        cfg = self._config(spec.get("config_id"))
        session = cfg.current_session_id
        if not session or session.state != "opened":
            raise UserError("No open session: open the cash register first.")
        partner = None
        if spec.get("partner_id"):
            partner = self.env["res.partner"].browse(int(spec["partner_id"])).exists()
            if not partner:
                raise UserError("Customer not found.")
        quoted, total, tax = self._quote_lines(cfg, spec.get("lines"), partner)
        expected = _num(spec.get("expected_total"), "expected total")
        if abs(expected - total) > TOLERANCE:
            raise UserError(f"PRICE_CHANGED: the total is now {total}, not {expected}. Refresh and retry.")
        if total <= 0:
            raise UserError("The total must be positive.")

        pays = spec.get("payments") or []
        if not 1 <= len(pays) <= 5:
            raise UserError("A sale needs 1-5 payments.")
        methods = cfg.payment_method_ids
        paid_cash = paid_other = credit_amt = 0.0
        pay_vals = []
        for p in pays:
            pm = methods.filtered(lambda m, pid=int(p.get("payment_method_id") or 0): m.id == pid)
            if not pm:
                raise UserError("Payment method is not available on this point of sale.")
            amt = _num(p.get("amount"), "payment amount", minimum=0.01)
            if pm.split_transactions:
                credit_amt += amt
            elif pm.is_cash_count:
                paid_cash += amt
            else:
                paid_other += amt
            pay_vals.append({"payment_method_id": pm.id, "amount": amt, "payment_date": fields.Datetime.now()})
        paid = paid_cash + paid_other + credit_amt
        if credit_amt > 0:
            if not partner:
                raise UserError("CUSTOMER_REQUIRED: choose the customer for a sale on credit.")
            if credit_amt > total + TOLERANCE:
                raise UserError("The credit amount cannot be more than the total.")
            limit = partner.credit_limit if "credit_limit" in partner._fields else 0.0
            if limit and limit > 0 and not spec.get("credit_override"):
                balance = self._customer_balance(partner)
                if balance + credit_amt > limit + TOLERANCE:
                    raise UserError(
                        f"CREDIT_LIMIT_EXCEEDED: the customer owes {balance}; adding {credit_amt} passes the limit {limit}."
                    )
        if paid + TOLERANCE < total:
            raise UserError(f"Payments ({paid}) do not cover the total ({total}).")
        change = round(paid - total, cfg.currency_id.decimal_places)
        if change > TOLERANCE and (paid_other > total + TOLERANCE or change > paid_cash + TOLERANCE):
            raise UserError("Change can only be given from cash, never from card/other payments.")

        now = fields.Datetime.now()
        order = {
            "uuid": key,
            "name": f"Elblasy {key[:8]}",
            "session_id": session.id,
            "config_id": cfg.id,
            "company_id": cfg.company_id.id,
            "user_id": self.env.uid,
            "state": "paid",
            "date_order": now,
            "amount_paid": paid,
            "amount_total": total,
            "amount_tax": tax,
            "amount_return": change * self._change_sign(),
            "partner_id": partner.id if partner else False,
            "to_invoice": credit_amt > 0,  # the credit part becomes an open invoice for the customer
            "sequence_number": 1,
            "lines": [
                [0, 0, {
                    "uuid": f"{key[:24]}{i:08x}",
                    "product_id": q["product_id"],
                    "qty": q["qty"],
                    "price_unit": q["price_unit"],
                    "discount": q["discount"],
                    "price_subtotal": q["subtotal"],
                    "price_subtotal_incl": q["subtotal_incl"],
                    "tax_ids": [[6, 0, q["tax_ids"]]],
                    "full_product_name": q["name"],
                }]
                for i, q in enumerate(quoted)
            ],
            "payment_ids": [[0, 0, v] for v in pay_vals],
        }
        note_field = self._note_field()
        if note_field and spec.get("note"):
            order[note_field] = str(spec["note"])[:200]
        if "pricelist_id" in cfg._fields and cfg.pricelist_id:
            order["pricelist_id"] = cfg.pricelist_id.id
        if "default_fiscal_position_id" in cfg._fields and cfg.default_fiscal_position_id:
            order["fiscal_position_id"] = cfg.default_fiscal_position_id.id
        Order.sync_from_ui([order])
        created = Order.search([("uuid", "=", key)], limit=1)
        if not created:
            raise UserError("Odoo did not create the order.")
        return wire({"outcome": "created", "refs": {"order": self._order_view(created)}})

    @api.model
    def sales_refund(self, op_id, key, spec):
        """Full refund of one paid order, paid back through the given method."""
        self._require_internal_user()
        self._need_pos()
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid refund key.")
        existing = self.env["pos.order"].search([("uuid", "=", f"{key[:24]}ffffffff")], limit=1)
        if existing:  # retry after a lost response
            return wire({"outcome": "already_exists", "refs": {"order": self._order_view(existing)}})
        orig = self.env["pos.order"].browse(int(spec.get("order_id") or 0)).exists()
        if not orig or orig.state not in ("paid", "done", "invoiced") or orig.amount_total <= 0:
            raise UserError("Only a paid sale can be refunded.")
        if orig.lines.mapped("refund_orderline_ids"):  # computed field `refunded_order_id` is not searchable
            raise UserError("This sale was already refunded.")
        if orig.account_move:
            raise UserError(
                "This sale has an invoice (a credit sale). Refunding it needs a credit note in Odoo; it cannot be refunded here."
            )
        session = orig.config_id.current_session_id
        if not session or session.state != "opened":
            raise UserError("Open the cash register to give a refund.")
        pm = orig.config_id.payment_method_ids.filtered(lambda m, pid=int(spec.get("payment_method_id") or 0): m.id == pid)
        if not pm:
            raise UserError("Payment method is not available on this point of sale.")
        # Same path the POS screen uses: negative lines pointing at the original lines + a negative
        # payment, processed by sync_from_ui. That is what creates the returned-stock movement and
        # the accounting exactly as for any POS order (the backend `refund()` shortcut does not).
        now = fields.Datetime.now()
        refund_uuid = f"{key[:24]}ffffffff"
        total = orig.amount_total
        order = {
            "uuid": refund_uuid,
            "name": f"Elblasy refund {key[:8]}",
            "session_id": session.id,
            "config_id": orig.config_id.id,
            "company_id": orig.company_id.id,
            "user_id": self.env.uid,
            "state": "paid",
            "date_order": now,
            "amount_paid": -total,
            "amount_total": -total,
            "amount_tax": -orig.amount_tax,
            "amount_return": 0.0,
            "partner_id": orig.partner_id.id or False,
            "to_invoice": False,
            "sequence_number": 1,
            "lines": [
                [0, 0, {
                    "uuid": f"{key[:24]}{i:08x}",
                    "product_id": l.product_id.id,
                    "qty": -l.qty,
                    "price_unit": l.price_unit,
                    "discount": l.discount,
                    "price_subtotal": -l.price_subtotal,
                    "price_subtotal_incl": -l.price_subtotal_incl,
                    "tax_ids": [[6, 0, l.tax_ids.ids]],
                    "full_product_name": l.full_product_name or l.product_id.display_name,
                    "refunded_orderline_id": l.id,
                }]
                for i, l in enumerate(orig.lines)
            ],
            "payment_ids": [[0, 0, {"payment_method_id": pm.id, "amount": -total, "payment_date": now}]],
        }
        if orig.pricelist_id:
            order["pricelist_id"] = orig.pricelist_id.id
        if orig.fiscal_position_id:
            order["fiscal_position_id"] = orig.fiscal_position_id.id
        self.env["pos.order"].sync_from_ui([order])
        refund = self.env["pos.order"].search([("uuid", "=", refund_uuid)], limit=1)
        if not refund or refund.state not in ("paid", "done", "invoiced"):
            raise UserError("The refund could not be completed.")
        return wire({"outcome": "created", "refs": {"order": self._order_view(refund)}})

    @api.model
    def sales_close_session(self, op_id, key, spec):
        self._require_internal_user()
        self._need_pos()
        s = self.env["pos.session"].browse(int(spec.get("session_id") or 0)).exists()
        if not s:
            raise UserError("Session not found.")
        if s.state == "closed":
            return wire({"outcome": "already_exists", "refs": {"session": self._session_view(s)}})
        counted = _num(spec.get("counted_cash", 0), "counted cash")
        if s.cash_journal_id:
            res = s.post_closing_cash_details(counted)
            if not res.get("successful"):
                raise UserError(res.get("message") or "The session cannot be closed yet.")
        res = s.close_session_from_ui()
        if not res.get("successful"):
            raise UserError(res.get("message") or "The session could not be closed.")
        s = self.env["pos.session"].browse(s.id)
        if s.state != "closed":
            raise UserError(f"The session did not close (state: {s.state}).")
        view = self._session_view(s)
        view["move_state"] = s.move_id.state if s.move_id else None
        return wire({"outcome": "created", "refs": {"session": view}})
