"""Loyalty points and promotions, applied at Elblasy One's till.

Odoo Community keeps the programmes, rewards, customer cards and point history (`loyalty` app), but applies them
inside its own POS screen, which Elblasy One does not use. So the rules are applied here, on the server, at quote
and at checkout, from the programmes Elblasy One created (tagged), and the result is written back the Odoo way:
reward lines on the POS order (`is_reward_line`, `reward_id`) and points on the customer's `loyalty.card` with a
`loyalty.history` entry, all in the same transaction as the sale, so a retried sale never counts points twice.

Supported shapes (what small shops use):
- points: N points per currency unit spent by a known customer; each point is worth V when redeemed (minimum M).
- buy X get Y: of one product, every X+Y units, Y are free.
- product discount: P% off chosen products or a category.
- order discount: P% off the whole sale from a minimum amount.
"""

import math
import re

from odoo import api, fields, models
from odoo.exceptions import UserError

from .bridge import wire
from .customers_ops import _num, _text

KEY_RE = re.compile(r"^[a-f0-9]{32}$")
KINDS = ("points", "bxgy", "product_discount", "order_discount")


class ElblasyBridgeLoyalty(models.AbstractModel):
    _inherit = "elblasy.bridge"

    # ---------- programmes ----------
    @api.model
    def _need_loyalty(self):
        if "loyalty.program" not in self.env:
            raise UserError("Loyalty is not installed on this Odoo; switch it on under Features first.")

    @api.model
    def _managed_programs(self, active_only=True):
        if "loyalty.program" not in self.env:
            return self.env["res.partner"].browse()  # empty recordset of any model
        ids = self.env["ir.model.data"].sudo().search([("module", "=", "elblasy_one"), ("model", "=", "loyalty.program")]).mapped("res_id")
        P = self.env["loyalty.program"].with_context(active_test=active_only)
        progs = P.browse(ids).exists()
        today = fields.Date.context_today(self)
        if active_only:
            progs = progs.filtered(lambda p: p.active and (not p.date_from or p.date_from <= today) and (not p.date_to or p.date_to >= today))
        return progs

    @api.model
    def _kind(self, prog):
        if prog.program_type == "loyalty":
            return "points"
        if prog.program_type == "buy_x_get_y":
            return "bxgy"
        reward = prog.reward_ids[:1]
        return "order_discount" if reward.discount_applicability == "order" else "product_discount"

    @api.model
    def _program_view(self, prog):
        rule, reward = prog.rule_ids[:1], prog.reward_ids[:1]
        kind = self._kind(prog)
        v = {"id": prog.id, "name": prog.name, "kind": kind, "active": prog.active,
             "date_from": str(prog.date_from) if prog.date_from else None, "date_to": str(prog.date_to) if prog.date_to else None}  # fmt: skip
        if kind == "points":
            v.update({"points_per_unit": rule.reward_point_amount, "point_value": reward.discount, "min_redeem": reward.required_points,
                      "members": self.env["loyalty.card"].search_count([("program_id", "=", prog.id), ("partner_id", "!=", False)])})  # fmt: skip
        elif kind == "bxgy":
            p = reward.reward_product_id
            v.update({"buy": rule.minimum_qty, "free": reward.reward_product_qty, "product_id": p.id, "product": p.display_name})
        elif kind == "product_discount":
            v.update({"percent": reward.discount, "products": [{"id": x.id, "name": x.display_name} for x in reward.discount_product_ids],
                      "category": reward.discount_product_category_id.name or None})  # fmt: skip
        else:
            v.update({"percent": reward.discount, "minimum_amount": rule.minimum_amount})
        return v

    @api.model
    def loyalty_programs(self):
        self._require_internal_user()
        if "loyalty.program" not in self.env:
            return wire({"installed": False, "items": []})
        return wire({"installed": True, "items": [self._program_view(p) for p in self._managed_programs(active_only=False)]})

    @api.model
    def loyalty_program_create(self, op_id, key, spec):
        self._require_internal_user()
        self._need_loyalty()
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid operation key.")
        existing = self._managed(f"lp_{key}")
        if existing:
            return wire({"outcome": "already_exists", "refs": {"program": self._program_view(existing)}})
        kind = spec.get("kind")
        if kind not in KINDS:
            raise UserError("Unknown programme kind.")
        name = _text(spec.get("name"), "name", 120)
        P = self.env["product.product"]
        vals = {"name": name, "trigger": "auto", "applies_on": "current", "date_from": spec.get("date_from") or False,
                "date_to": spec.get("date_to") or False}  # fmt: skip
        if "pos_ok" in self.env["loyalty.program"]._fields:
            vals["pos_ok"] = True
        if kind == "points":
            if self._managed_programs().filtered(lambda p: p.program_type == "loyalty"):
                raise UserError("A points programme is already running; change it instead of adding another.")
            vals.update({"program_type": "loyalty", "applies_on": "both",
                         "rule_ids": [(0, 0, {"reward_point_mode": "money", "reward_point_amount": _num(spec.get("points_per_unit"), "points per unit", 0.0001, 1000)})],
                         "reward_ids": [(0, 0, {"reward_type": "discount", "discount_mode": "per_point", "discount_applicability": "order",
                                                "discount": _num(spec.get("point_value"), "point value", 0.0001, 1e6),
                                                "required_points": _num(spec.get("min_redeem", 1), "minimum points", 1, 1e9)})]})  # fmt: skip
        elif kind == "bxgy":
            prod = P.browse(int(spec.get("product_id") or 0)).exists()
            if not prod:
                raise UserError("Product not found.")
            buy, free = int(_num(spec.get("buy"), "buy", 1, 1000)), int(_num(spec.get("free"), "free", 1, 1000))
            vals.update({"program_type": "buy_x_get_y",
                         "rule_ids": [(0, 0, {"product_ids": [(6, 0, [prod.id])], "minimum_qty": buy, "reward_point_mode": "unit", "reward_point_amount": 1})],
                         "reward_ids": [(0, 0, {"reward_type": "product", "reward_product_id": prod.id, "reward_product_qty": free, "required_points": buy})]})  # fmt: skip
        elif kind == "product_discount":
            ids = [int(x) for x in spec.get("product_ids") or []]
            prods = P.browse(ids).exists()
            cat = self.env["product.category"].browse(int(spec.get("category_id") or 0)).exists()
            if not prods and not cat:
                raise UserError("Choose the products or the category on offer.")
            pct = _num(spec.get("percent"), "percent", 0.01, 100)
            vals.update({"program_type": "promotion",
                         "rule_ids": [(0, 0, {"product_ids": [(6, 0, prods.ids)], "product_category_id": cat.id or False, "minimum_qty": 1, "reward_point_mode": "order"})],
                         "reward_ids": [(0, 0, {"reward_type": "discount", "discount_mode": "percent", "discount": pct, "discount_applicability": "specific",
                                                "discount_product_ids": [(6, 0, prods.ids)], "discount_product_category_id": cat.id or False, "required_points": 1})]})  # fmt: skip
        else:
            pct = _num(spec.get("percent"), "percent", 0.01, 100)
            vals.update({"program_type": "promotion",
                         "rule_ids": [(0, 0, {"minimum_amount": _num(spec.get("minimum_amount", 0), "minimum amount"), "minimum_qty": 0, "reward_point_mode": "order"})],
                         "reward_ids": [(0, 0, {"reward_type": "discount", "discount_mode": "percent", "discount": pct, "discount_applicability": "order", "required_points": 1})]})  # fmt: skip
        prog = self.env["loyalty.program"].create(vals)
        self._tag(f"lp_{key}", prog)
        return wire({"outcome": "created", "refs": {"program": self._program_view(prog)}})

    @api.model
    def loyalty_program_set_active(self, op_id, key, spec):
        self._require_internal_user()
        self._need_loyalty()
        prog = self._managed_programs(active_only=False).filtered(lambda p: p.id == int(spec.get("program_id") or 0))
        if not prog:
            raise UserError("Programme not found.")
        prog.write({"active": bool(spec.get("active"))})
        return wire({"outcome": "updated", "refs": {"program": self._program_view(prog)}})

    @api.model
    def loyalty_points_of(self, partner_id):
        self._require_internal_user()
        prog = self._managed_programs().filtered(lambda p: p.program_type == "loyalty")[:1]
        partner = self.env["res.partner"].browse(int(partner_id or 0)).exists()
        if not prog or not partner:
            return wire({"program": None})
        card = self.env["loyalty.card"].search([("program_id", "=", prog.id), ("partner_id", "=", partner.id)], limit=1)
        reward = prog.reward_ids[:1]
        return wire({"program": prog.name, "points": card.points if card else 0.0, "point_value": reward.discount, "min_redeem": reward.required_points})

    @api.model
    def _till_hidden_products(self):
        """Products the loyalty app creates for its own bookkeeping (gift card, e-wallet top-up, reward discount
        lines): never offered at the till as goods."""
        ids = set(self.env["ir.model.data"].sudo().search([("module", "in", ("loyalty", "pos_loyalty")), ("model", "=", "product.product")]).mapped("res_id"))
        tmpl = self.env["ir.model.data"].sudo().search([("module", "in", ("loyalty", "pos_loyalty")), ("model", "=", "product.template")]).mapped("res_id")
        if tmpl:
            ids |= set(self.env["product.product"].with_context(active_test=False).search([("product_tmpl_id", "in", tmpl)]).ids)
        if "loyalty.reward" in self.env:
            ids |= set(self.env["loyalty.reward"].with_context(active_test=False).search([]).mapped("discount_line_product_id").ids)
        return list(ids)

    # ---------- the engine ----------
    @api.model
    def _loyalty_rewards(self, quoted, partner, redeem_points):
        """Rewards for these quoted lines. Each reward carries its amounts with and without tax and the tax set it
        belongs to, so the discount is taxed exactly like the goods it discounts."""
        progs = self._managed_programs()
        if not progs:
            return [], None
        cur = self.env.company.currency_id
        rewards = []

        def share(lines, frac, prog, reward, label, points_cost=0.0):
            by_tax = {}
            for q in lines:
                k = tuple(sorted(q["tax_ids"]))
                ex, inc = by_tax.get(k, (0.0, 0.0))
                by_tax[k] = (ex + q["subtotal"] * frac(q), inc + q["subtotal_incl"] * frac(q))
            for k, (ex, inc) in by_tax.items():
                if inc > 0.0001:
                    rewards.append({"program_id": prog.id, "reward_id": reward.id, "label": label, "tax_ids": list(k),
                                    "excl": -cur.round(ex), "incl": -cur.round(inc), "points_cost": points_cost})  # fmt: skip
                    points_cost = 0.0  # counted once

        for prog in progs.filtered(lambda p: p.program_type == "buy_x_get_y"):
            rule, reward = prog.rule_ids[:1], prog.reward_ids[:1]
            x, y, pid = rule.minimum_qty, reward.reward_product_qty, reward.reward_product_id.id
            for q in quoted:
                if q["product_id"] == pid and x > 0 and y > 0:
                    free = math.floor(q["qty"] / (x + y)) * y
                    if free:
                        share([q], lambda line, f=free: f / line["qty"], prog, reward, f"{prog.name} (+{free:g})")
        for prog in progs.filtered(lambda p: p.program_type == "promotion"):
            rule, reward = prog.rule_ids[:1], prog.reward_ids[:1]
            pct = reward.discount / 100.0
            if reward.discount_applicability == "specific":
                cat = reward.discount_product_category_id
                prods = set(reward.discount_product_ids.ids)
                hit = [q for q in quoted if q["product_id"] in prods or (cat and self.env["product.product"].browse(q["product_id"]).categ_id.id in self.env["product.category"].search([("id", "child_of", cat.id)]).ids)]
                if hit:
                    share(hit, lambda line: pct, prog, reward, f"{prog.name} ({reward.discount:g}%)")
        so_far = sum(q["subtotal_incl"] for q in quoted) + sum(r["incl"] for r in rewards)
        for prog in progs.filtered(lambda p: p.program_type == "promotion" and p.reward_ids[:1].discount_applicability == "order"):
            rule, reward = prog.rule_ids[:1], prog.reward_ids[:1]
            total_incl = sum(q["subtotal_incl"] for q in quoted)
            if so_far + 0.0001 >= (rule.minimum_amount or 0.0) and so_far > 0 and total_incl > 0:
                value = reward.discount / 100.0 * so_far  # on what remains after the other offers
                share(quoted, lambda line, v=value, t=total_incl: v / t, prog, reward, f"{prog.name} ({reward.discount:g}%)")
                so_far -= value

        points = None
        prog = progs.filtered(lambda p: p.program_type == "loyalty")[:1]
        if prog and partner:
            rule, reward = prog.rule_ids[:1], prog.reward_ids[:1]
            card = self.env["loyalty.card"].search([("program_id", "=", prog.id), ("partner_id", "=", partner.id)], limit=1)
            balance = card.points if card else 0.0
            used = 0.0
            if redeem_points:
                redeem = float(redeem_points)
                if redeem < reward.required_points:
                    raise UserError(f"POINTS_MINIMUM: at least {reward.required_points:g} points can be redeemed.")
                if redeem > balance + 1e-9:
                    raise UserError(f"POINTS_SHORT: the customer has {balance:g} points.")
                value = min(redeem * reward.discount, max(0.0, so_far))
                used = math.ceil(value / reward.discount) if reward.discount else 0.0
                total_incl = sum(q["subtotal_incl"] for q in quoted)
                if total_incl > 0 and value > 0:
                    share(quoted, lambda line: value / total_incl, prog, reward, f"{prog.name} (−{used:g})", points_cost=used)
                    so_far -= value
            earned = math.floor(max(0.0, so_far) * rule.reward_point_amount)
            points = {"program_id": prog.id, "program": prog.name, "balance": balance, "earned": earned, "used": used,
                      "after": balance - used + earned, "point_value": reward.discount, "min_redeem": reward.required_points}  # fmt: skip
        return rewards, points

    @api.model
    def _loyalty_settle(self, order, points):
        """Write the points Odoo's way after the sale: card balance and a history line, same transaction."""
        if not points or "loyalty.card" not in self.env or not order.partner_id:
            return
        Card = self.env["loyalty.card"]
        card = Card.search([("program_id", "=", points["program_id"]), ("partner_id", "=", order.partner_id.id)], limit=1)
        if not card:
            card = Card.create({"program_id": points["program_id"], "partner_id": order.partner_id.id, "points": 0})
        card.points = card.points - points["used"] + points["earned"]
        if "loyalty.history" in self.env:
            self.env["loyalty.history"].create({"card_id": card.id, "description": order.name, "issued": points["earned"],
                                                "used": points["used"], "order_model": "pos.order", "order_id": order.id})  # fmt: skip
