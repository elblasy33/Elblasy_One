"""Customers, their open invoices (receivables) and collecting payments.

A credit sale is a POS order paid with the 'Customer account' method: Odoo issues a posted invoice that stays open
for the credit part. That open invoice *is* the receivable; collecting is a normal inbound payment on it, so
partial payments, statements and overdue tracking come from Odoo's own documents."""

import re

from odoo import api, fields, models
from odoo.exceptions import UserError

from .bridge import wire

KEY_RE = re.compile(r"^[a-f0-9]{32}$")
TOL = 0.005


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


class ElblasyBridgeCustomers(models.AbstractModel):
    _inherit = "elblasy.bridge"

    @api.model
    def _customer_balance(self, partner):
        """What the customer owes: open posted invoices minus open credit notes."""
        moves = self.env["account.move"].search(
            [("partner_id", "=", partner.id), ("move_type", "in", ("out_invoice", "out_refund")),
             ("state", "=", "posted"), ("payment_state", "not in", ("paid", "reversed"))]
        )  # fmt: skip
        cur = self.env.company.currency_id
        return cur.round(sum(m.amount_residual if m.move_type == "out_invoice" else -m.amount_residual for m in moves))

    @api.model
    def _customer_view(self, p, with_balance=True):
        v = {"id": p.id, "name": p.name, "phone": p.phone or None, "email": p.email or None}
        limit = p.credit_limit if "credit_limit" in p._fields else 0.0
        v["credit_limit"] = limit or 0.0
        own = p.specific_property_product_pricelist if "specific_property_product_pricelist" in p._fields else False
        v["pricelist_id"], v["pricelist"] = (own.id, own.name) if own else (None, None)
        if with_balance:
            bal = self._customer_balance(p)
            v["receivable"] = bal
            v["available_credit"] = max(0.0, limit - bal) if limit else None
        return v

    @api.model
    def customers_upsert(self, op_id, key, spec):
        self._require_internal_user()
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid operation key.")
        existing = self._managed(f"cust_{key}")
        if existing:
            return wire({"outcome": "already_exists", "refs": {"customer": self._customer_view(existing)}})
        vals = {"name": _text(spec.get("name"), "name", 200), "customer_rank": 1}
        for f, limit in (("phone", 40), ("email", 120)):
            v = _text(spec.get(f), f, limit, required=False)
            if v:
                vals[f] = v
        if spec.get("credit_limit") is not None and "credit_limit" in self.env["res.partner"]._fields:
            vals["credit_limit"] = _num(spec["credit_limit"], "credit limit")
        p = self.env["res.partner"].create(vals)
        self._tag(f"cust_{key}", p)
        return wire({"outcome": "created", "refs": {"customer": self._customer_view(p)}})

    @api.model
    def customers_set_credit_limit(self, op_id, key, spec):
        self._require_internal_user()
        p = self.env["res.partner"].browse(int(spec.get("partner_id") or 0)).exists()
        if not p or "credit_limit" not in p._fields:
            raise UserError("Customer not found or credit limits are unavailable.")
        p.credit_limit = _num(spec.get("credit_limit"), "credit limit")
        return wire({"outcome": "updated", "refs": {"customer": self._customer_view(p)}})

    @api.model
    def customers_search(self, query, limit, offset, with_balance=True):
        self._require_internal_user()
        domain = [("customer_rank", ">", 0)]
        q = (query or "").strip()
        if q:
            domain += ["|", "|", ("name", "ilike", q), ("phone", "ilike", q), ("email", "ilike", q)]
        P = self.env["res.partner"]
        limit = max(1, min(int(limit or 25), 100))
        recs = P.search(domain, limit=limit, offset=max(0, int(offset or 0)), order="name")
        return wire({"total": P.search_count(domain), "items": [self._customer_view(p, with_balance) for p in recs]})

    @api.model
    def _invoice_view(self, b):
        return {
            "id": b.id, "name": b.name or None, "state": b.state, "move_type": b.move_type,
            "date": str(b.invoice_date) if b.invoice_date else None,
            "due": str(b.invoice_date_due) if b.invoice_date_due else None,
            "partner_id": b.partner_id.id, "partner": b.partner_id.name,
            "amount_total": b.amount_total, "amount_residual": b.amount_residual, "payment_state": b.payment_state,
        }

    @api.model
    def invoice_get(self, invoice_id):
        self._require_internal_user()
        b = self.env["account.move"].browse(int(invoice_id or 0)).exists()
        if not b or b.move_type not in ("out_invoice", "out_refund"):
            return wire({"found": False})
        return wire({"found": True, "invoice": self._invoice_view(b)})

    @api.model
    def customer_statement(self, partner_id):
        self._require_internal_user()
        p = self.env["res.partner"].browse(int(partner_id or 0)).exists()
        if not p:
            return wire({"found": False})
        invoices = self.env["account.move"].search(
            [("partner_id", "=", p.id), ("move_type", "in", ("out_invoice", "out_refund")), ("state", "=", "posted")],
            order="invoice_date desc, id desc", limit=100,
        )  # fmt: skip
        pay_domain = [("partner_id", "=", p.id), ("payment_type", "=", "inbound")]
        payments = self.env["account.payment"].search(pay_domain, order="date desc, id desc", limit=100)
        return wire({
            "found": True, "customer": self._customer_view(p),
            "invoices": [self._invoice_view(b) for b in invoices],
            "payments": [{"id": x.id, "name": x.name, "date": str(x.date), "amount": x.amount, "journal": x.journal_id.name} for x in payments],
        })  # fmt: skip

    @api.model
    def receivable_receive(self, op_id, key, spec):
        """Collect money from a customer against one open invoice (fully or partly)."""
        self._require_internal_user()
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid operation key.")
        existing = self._managed(f"rcv_{key}")
        if existing:
            return wire({"outcome": "already_exists", "refs": {"payment_id": existing.id}})
        inv = self.env["account.move"].browse(int(spec.get("invoice_id") or 0)).exists()
        if not inv or inv.move_type != "out_invoice" or inv.state != "posted":
            raise UserError("Only a posted customer invoice can be collected.")
        if inv.payment_state in ("paid", "in_payment") or inv.amount_residual <= TOL:
            raise UserError("This invoice is already paid.")
        amount = _num(spec.get("amount"), "payment amount", minimum=0.01)
        if amount > inv.amount_residual + TOL:
            raise UserError(f"The payment ({amount}) is more than what the customer owes on this invoice ({inv.amount_residual}).")
        jtype = spec.get("journal_type")
        if jtype not in ("cash", "bank"):
            raise UserError("Receive into the cash or the bank journal.")
        journal = self.env["account.journal"].search([("type", "=", jtype)], limit=1)
        if not journal:
            raise UserError(f"No {jtype} journal exists yet.")
        wiz = self.env["account.payment.register"].with_context(active_model="account.move", active_ids=inv.ids).create(
            {"amount": amount, "journal_id": journal.id, "payment_date": fields.Date.context_today(self)}
        )
        pay = wiz._create_payments()[:1]
        if not pay:
            raise UserError("Odoo did not create the payment.")
        self._tag(f"rcv_{key}", pay)
        inv = self.env["account.move"].browse(inv.id)
        return wire({"outcome": "created", "refs": {"payment_id": pay.id, "invoice": self._invoice_view(inv)}})

    @api.model
    def receivables_overview(self):
        self._require_internal_user()
        cur = self.env.company.currency_id
        today = fields.Date.context_today(self)
        invs = self.env["account.move"].search([("move_type", "in", ("out_invoice", "out_refund")), ("state", "=", "posted"), ("payment_state", "not in", ("paid", "reversed"))])
        by, overdue_n, overdue_amt = {}, 0, 0.0
        for b in invs:
            sign = 1 if b.move_type == "out_invoice" else -1
            by[b.partner_id.name] = by.get(b.partner_id.name, 0.0) + sign * b.amount_residual
            if b.move_type == "out_invoice" and b.invoice_date_due and b.invoice_date_due < today:
                overdue_n += 1
                overdue_amt += b.amount_residual
        top = sorted(by.items(), key=lambda kv: -kv[1])[:5]
        return wire({
            "currency": cur.name, "total": cur.round(sum(by.values())), "customers": len([1 for v in by.values() if v > TOL]),
            "top": [{"name": n, "owed": cur.round(v)} for n, v in top if v > TOL],
            "overdue": {"count": overdue_n, "amount": cur.round(overdue_amt)},
        })  # fmt: skip
