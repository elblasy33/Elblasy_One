"""Read-only operational facts for the alerts centre. The platform decides which are alerts and who may see them."""

from datetime import timedelta

from odoo import api, fields, models

from .bridge import wire

STALE_SESSION_HOURS = 24


class ElblasyBridgeAlerts(models.AbstractModel):
    _inherit = "elblasy.bridge"

    @api.model
    def alerts_snapshot(self):
        self._require_internal_user()
        env = self.env
        today = fields.Date.context_today(self)
        out = {"currency": env.company.currency_id.name}
        try:
            overdue = env["account.move"].search(
                [("move_type", "=", "in_invoice"), ("state", "=", "posted"), ("payment_state", "not in", ("paid", "reversed", "in_payment")),
                 ("invoice_date_due", "<", today)]
            )  # fmt: skip
            out["overdue_bills"] = {"count": len(overdue), "amount": env.company.currency_id.round(sum(overdue.mapped("amount_residual")))}
        except Exception:  # noqa: BLE001
            out["overdue_bills"] = None
        try:
            if "pos.session" in env:
                limit = fields.Datetime.now() - timedelta(hours=STALE_SESSION_HOURS)
                stale = env["pos.session"].search([("state", "in", ("opened", "opening_control")), ("start_at", "<", limit)])
                out["stale_sessions"] = {"count": len(stale), "names": stale.mapped("name")[:5]}
        except Exception:  # noqa: BLE001
            out["stale_sessions"] = None
        try:
            if "stock.quant" in env:
                neg = env["stock.quant"].search_count([("location_id.usage", "=", "internal"), ("quantity", "<", 0)])
                out["negative_stock"] = {"count": neg}
        except Exception:  # noqa: BLE001
            out["negative_stock"] = None
        try:
            if "stock.picking" in env:
                late = env["stock.picking"].search_count(
                    [("picking_type_code", "=", "incoming"), ("state", "in", ("assigned", "confirmed", "waiting")),
                     ("scheduled_date", "<", fields.Datetime.now() - timedelta(days=3))]
                )  # fmt: skip
                out["late_receipts"] = {"count": late}
        except Exception:  # noqa: BLE001
            out["late_receipts"] = None
        return wire(out)
