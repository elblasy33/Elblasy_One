"""Expenses and the money overview, on Odoo's own accounting documents.

An expense is a vendor bill on an expense account (the *document*), optionally followed by a payment
(the *cash movement*). Nothing here assumes an expense is paid: an unpaid expense stays a payable
until a payment is recorded. No journal entry is ever written directly. Taxes are not applied to
platform expenses (the amount is the full amount payable); that is stated in the response."""

import re
from datetime import date as _date

from odoo import api, fields, models
from odoo.exceptions import UserError

from .bridge import wire

KEY_RE = re.compile(r"^[a-f0-9]{32}$")
# Operating expenses only: cost of goods sold ("expense_direct_cost") is a different figure and stays out.
EXPENSE_TYPES = ("expense",)
TOL = 0.005
MISC_PARTNER = "partner_misc_expenses"


def _num(v, field, minimum=0.0, maximum=1e9):
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise UserError(f"{field} must be a number.") from None
    if n != n or n < minimum or n > maximum:
        raise UserError(f"{field} is out of range.")
    return n


def _day(v, field):
    try:
        return _date.fromisoformat(str(v)[:10])
    except ValueError:
        raise UserError(f"{field} must be a date (YYYY-MM-DD).") from None


class ElblasyBridgeMoney(models.AbstractModel):
    _inherit = "elblasy.bridge"

    @api.model
    def _need_accounting(self):
        if not self.env.user.has_group("account.group_account_invoice"):
            raise UserError("The Odoo service user needs the Accounting (invoicing) rights.")

    @api.model
    def _expense_account_domain(self):
        return [("account_type", "in", EXPENSE_TYPES)]

    @api.model
    def expense_accounts(self):
        self._require_internal_user()
        self._need_accounting()
        accts = self.env["account.account"].search(self._expense_account_domain(), order="code")
        return wire({"items": [{"id": a.id, "code": a.code, "name": a.name} for a in accts]})

    @api.model
    def _bill_view(self, b):
        line = b.invoice_line_ids.filtered(lambda l: l.display_type in (False, "product"))[:1]
        return {
            "id": b.id,
            "name": b.name or None,
            "state": b.state,
            "date": str(b.invoice_date) if b.invoice_date else None,
            "partner_id": b.partner_id.id,
            "partner": b.partner_id.name,
            "ref": b.ref or None,
            "description": line.name if line else None,
            "account_id": line.account_id.id if line else None,
            "account": line.account_id.display_name if line else None,
            "amount_total": b.amount_total,
            "amount_residual": b.amount_residual,
            "payment_state": b.payment_state,
            "managed": bool(
                self.env["ir.model.data"].sudo().search_count(
                    [("module", "=", "elblasy_one"), ("model", "=", "account.move"), ("res_id", "=", b.id)]
                )
            ),
        }

    @api.model
    def expense_get(self, bill_id):
        self._require_internal_user()
        self._need_accounting()
        b = self.env["account.move"].browse(int(bill_id or 0)).exists()
        if not b or b.move_type != "in_invoice":
            return wire({"found": False})
        return wire({"found": True, "expense": self._bill_view(b)})

    @api.model
    def expense_create(self, op_id, key, spec):
        """Record an expense as a posted vendor bill; pay it at once only if asked to."""
        self._require_internal_user()
        self._need_accounting()
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid operation key.")
        existing = self._managed(f"exp_{key}")
        if existing:
            return wire({"outcome": "already_exists", "refs": {"expense": self._bill_view(existing)}})
        account = self.env["account.account"].search(self._expense_account_domain() + [("id", "=", int(spec.get("account_id") or 0))], limit=1)
        if not account:
            raise UserError("The category's account is not an expense account of this company.")
        amount = _num(spec.get("amount"), "amount", minimum=0.01)
        day = _day(spec.get("date") or fields.Date.context_today(self), "date")
        description = (spec.get("description") or "").strip()
        if not description or len(description) > 300:
            raise UserError("A description (up to 300 characters) is required.")
        partner = self.env["res.partner"].browse(int(spec.get("partner_id") or 0)).exists() if spec.get("partner_id") else None
        if spec.get("partner_id") and not partner:
            raise UserError("Payee not found.")
        if not partner:
            partner = self._managed(MISC_PARTNER)
            if not partner:
                partner = self.env["res.partner"].create({"name": "Miscellaneous expenses", "supplier_rank": 1, "is_company": True})
                self._tag(MISC_PARTNER, partner)
        pay = spec.get("pay_now")
        journal = None
        if pay:
            if pay.get("journal_type") not in ("cash", "bank"):
                raise UserError("Pay from the cash or the bank journal.")
            journal = self.env["account.journal"].search([("type", "=", pay["journal_type"])], limit=1)
            if not journal:
                raise UserError(f"No {pay['journal_type']} journal exists yet.")
        bill = self.env["account.move"].create({
            "move_type": "in_invoice", "partner_id": partner.id, "invoice_date": day,
            "ref": (spec.get("ref") or "")[:100] or False,
            "invoice_line_ids": [(0, 0, {"name": description, "account_id": account.id, "quantity": 1,
                                          "price_unit": amount, "tax_ids": [(6, 0, [])]})],
        })  # fmt: skip
        bill.action_post()
        bill = self.env["account.move"].browse(bill.id)
        if bill.state != "posted":
            raise UserError(f"The expense could not be posted (state: {bill.state}).")
        self._tag(f"exp_{key}", bill)
        if journal:
            wiz = self.env["account.payment.register"].with_context(active_model="account.move", active_ids=bill.ids).create(
                {"amount": bill.amount_residual, "journal_id": journal.id, "payment_date": day}
            )
            wiz._create_payments()
            bill = self.env["account.move"].browse(bill.id)
        return wire({"outcome": "created", "refs": {"expense": self._bill_view(bill), "taxes_applied": False}})

    @api.model
    def _expense_bills(self, d_from, d_to):
        """Vendor bills that carry non-product expense lines, in a date range (accrual date)."""
        lines = self.env["account.move.line"].search([
            ("move_id.move_type", "=", "in_invoice"), ("move_id.state", "=", "posted"),
            ("account_id.account_type", "in", EXPENSE_TYPES), ("product_id", "=", False),
            ("date", ">=", d_from), ("date", "<=", d_to),
        ])  # fmt: skip
        return lines.mapped("move_id"), lines

    @api.model
    def expense_list(self, limit, offset, date_from, date_to):
        self._require_internal_user()
        self._need_accounting()
        d_from = _day(date_from or "2000-01-01", "from")
        d_to = _day(date_to or "2999-12-31", "to")
        bills, _ = self._expense_bills(d_from, d_to)
        bills = bills.sorted(key=lambda b: (b.invoice_date or b.date, b.id), reverse=True)
        limit = max(1, min(int(limit or 25), 100))
        off = max(0, int(offset or 0))
        return wire({"total": len(bills), "items": [self._bill_view(b) for b in bills[off: off + limit]]})

    @api.model
    def expense_summary(self, date_from, date_to):
        """Incurred (bill totals) vs paid vs still owed: three different numbers, never merged."""
        self._require_internal_user()
        self._need_accounting()
        d_from, d_to = _day(date_from, "from"), _day(date_to, "to")
        bills, lines = self._expense_bills(d_from, d_to)
        cur = self.env.company.currency_id
        by_cat = {}
        for l in lines:
            k = l.account_id.display_name
            by_cat[k] = cur.round(by_cat.get(k, 0.0) + l.balance)
        incurred = cur.round(sum(b.amount_total for b in bills))
        owed = cur.round(sum(b.amount_residual for b in bills))
        return wire({
            "from": str(d_from), "to": str(d_to), "count": len(bills), "incurred": incurred,
            "paid": cur.round(incurred - owed), "still_owed": owed, "by_category": by_cat, "currency": cur.name,
            "definition": "Posted vendor bills on non-product expense accounts dated in the period (tax not applied)",
        })  # fmt: skip

    @api.model
    def _journal_cash_accounts(self, j):
        """Liquidity account plus the journal's outstanding-payment accounts: Odoo books a payment to the
        latter until it is reconciled with a statement, but a shop's drawer has already changed."""
        accts = j.default_account_id
        P = self.env["account.payment"]
        if "outstanding_account_id" in P._fields:  # where this journal's payments were actually booked
            accts |= P.search([("journal_id", "=", j.id)]).mapped("outstanding_account_id")
        for fn in ("_get_journal_inbound_outstanding_payment_accounts", "_get_journal_outbound_outstanding_payment_accounts"):
            if hasattr(j, fn):
                accts |= getattr(j, fn)()
        return accts

    @api.model
    def _journal_balance(self, j):
        accts = self._journal_cash_accounts(j)
        if not accts:
            return 0.0
        groups = self.env["account.move.line"].read_group(
            [("account_id", "in", accts.ids), ("journal_id", "=", j.id), ("parent_state", "=", "posted")], ["balance:sum"], []
        )
        return (groups[0]["balance"] if groups else 0.0) or 0.0

    @api.model
    def money_overview(self):
        """Book balances of cash and bank journals, and what is owed to suppliers."""
        self._require_internal_user()
        self._need_accounting()
        cur = self.env.company.currency_id
        accounts = []
        for j in self.env["account.journal"].search([("type", "in", ("cash", "bank"))]):
            accounts.append({"journal_id": j.id, "name": j.name, "type": j.type, "balance": cur.round(self._journal_balance(j))})
        bills = self.env["account.move"].search([("move_type", "in", ("in_invoice", "in_refund")), ("state", "=", "posted"), ("payment_state", "not in", ("paid", "reversed"))])
        owed = {}
        for b in bills:
            sign = 1 if b.move_type == "in_invoice" else -1
            owed[b.partner_id.name] = owed.get(b.partner_id.name, 0.0) + sign * b.amount_residual
        top = sorted(owed.items(), key=lambda kv: -kv[1])[:5]
        return wire({
            "currency": cur.name, "accounts": accounts,
            "payables": {"total": cur.round(sum(owed.values())), "top": [{"name": n, "owed": cur.round(v)} for n, v in top if v > 0]},
            "definition": {"balance": "Posted balance of the journal's cash/bank account plus its unreconciled payments (book balance, not a bank statement)",
                           "payables": "Open posted vendor bills minus open credit notes"},
        })  # fmt: skip

    @api.model
    def money_ledger(self, journal_type, limit):
        """Recent movements on cash or bank journals (what came in and went out)."""
        self._require_internal_user()
        self._need_accounting()
        if journal_type not in ("cash", "bank"):
            raise UserError("journal_type must be cash or bank.")
        journals = self.env["account.journal"].search([("type", "=", journal_type)])
        accts = self.env["account.account"]
        for j in journals:
            accts |= self._journal_cash_accounts(j)
        limit = max(1, min(int(limit or 30), 100))
        rows = self.env["account.move.line"].search([("account_id", "in", accts.ids), ("journal_id", "in", journals.ids), ("parent_state", "=", "posted")], order="date desc, id desc", limit=limit)
        return wire({"items": [{
            "id": l.id, "date": str(l.date), "name": l.move_id.name, "label": l.name or l.move_id.ref or None,
            "partner": l.partner_id.name or None, "amount": l.balance, "journal": l.journal_id.name,
        } for l in rows]})  # fmt: skip
