"""Read-only business insights: a week of sales, best sellers, slow-moving stock and goods near expiry.

All figures are computed from Odoo's own POS orders, stock and lots; nothing is stored by the platform."""

import datetime

import pytz

from odoo import api, fields, models

from .bridge import wire

PAID = ("paid", "done", "invoiced")
SLOW_DAYS = 30
EXPIRY_DAYS = 30


class ElblasyBridgeInsights(models.AbstractModel):
    _inherit = "elblasy.bridge"

    @api.model
    def insights_snapshot(self, days):
        self._require_internal_user()
        env = self.env
        days = max(1, min(int(days or 7), 31))
        cur = env.company.currency_id
        tz = pytz.timezone(env.user.tz or "UTC")
        today = fields.Date.context_today(self)
        out = {"currency": cur.name, "days": days}

        def utc(d):
            local = tz.localize(datetime.datetime.combine(d, datetime.time.min))
            return fields.Datetime.to_string(local.astimezone(pytz.utc).replace(tzinfo=None))

        if "pos.order" in env:
            first = today - datetime.timedelta(days=days - 1)
            orders = env["pos.order"].search([("state", "in", PAID), ("date_order", ">=", utc(first)), ("date_order", "<", utc(today + datetime.timedelta(days=1)))])
            per_day = {first + datetime.timedelta(days=i): 0.0 for i in range(days)}
            for o in orders:
                local = pytz.utc.localize(o.date_order).astimezone(tz).date()
                if local in per_day:
                    per_day[local] += o.amount_total
            out["sales_by_day"] = [{"day": str(d), "net": cur.round(v)} for d, v in sorted(per_day.items())]
            qty, amount = {}, {}
            for ln in orders.lines:
                if ln.qty > 0:
                    qty[ln.product_id] = qty.get(ln.product_id, 0.0) + ln.qty
                    amount[ln.product_id] = amount.get(ln.product_id, 0.0) + ln.price_subtotal_incl
            top = sorted(qty, key=lambda p: -amount[p])[:5]
            out["top_products"] = [{"name": p.display_name, "qty": qty[p], "amount": cur.round(amount[p])} for p in top]
            if "stock.quant" in env:
                since = utc(today - datetime.timedelta(days=SLOW_DAYS))
                sold = {r["product_id"][0] for r in env["pos.order.line"].search_read([("order_id.date_order", ">=", since)], ["product_id"], limit=20000)}
                quants = env["stock.quant"].read_group([("location_id.usage", "=", "internal"), ("quantity", ">", 0)], ["quantity:sum", "value:sum"], ["product_id"])
                slow = []
                for q in quants:
                    pid = q["product_id"][0]
                    if pid not in sold:
                        slow.append({"product_id": pid, "name": q["product_id"][1], "qty": q["quantity"], "value": cur.round(q.get("value") or 0.0)})
                slow.sort(key=lambda r: -r["value"])
                out["slow_moving"] = {"days": SLOW_DAYS, "count": len(slow), "items": slow[:5]}
        if "stock.lot" in env and "expiration_date" in env["stock.lot"]._fields:
            limit = fields.Datetime.now() + datetime.timedelta(days=EXPIRY_DAYS)
            lots = env["stock.lot"].search([("expiration_date", "!=", False), ("expiration_date", "<=", limit)], order="expiration_date", limit=200)
            rows = []
            for lot in lots:
                have = sum(lot.quant_ids.filtered(lambda q: q.location_id.usage == "internal").mapped("quantity"))
                if have > 0:
                    rows.append({"product": lot.product_id.display_name, "lot": lot.name, "qty": have, "expires": fields.Datetime.to_string(lot.expiration_date)[:10], "expired": lot.expiration_date < fields.Datetime.now()})
            out["expiring"] = {"days": EXPIRY_DAYS, "count": len(rows), "items": rows[:8]}
        return wire(out)
