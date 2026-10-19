"""Read-only fact collection for the readiness engine. Never writes. Judgement lives in the
platform API (so rules are testable and versioned there); this only reports observed facts.

Every section is guarded: an access/model error yields {"unavailable": "<reason>"} so the
engine can report "unable to verify" instead of guessing."""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)
FOOTPRINT_MODULES_LIMIT = 50
CORE_AUTHORS = {"odoosa", "odoo"}


def _section(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - reported as unavailable, never silent
        _logger.info("readiness section failed: %s", type(exc).__name__)
        return {"unavailable": type(exc).__name__}


class ElblasyBridgeReadiness(models.AbstractModel):
    _inherit = "elblasy.bridge"

    @api.model
    def readiness_snapshot(self):
        self._require_internal_user()
        env = self.env
        installed = {
            m.name
            for m in env["ir.module.module"].sudo().search([("state", "=", "installed")])
        }

        def has(*mods):
            return all(m in installed for m in mods)

        def user_groups():
            return {
                "account_manager": env.user.has_group("account.group_account_manager")
                if has("account")
                else None,
                "stock_manager": env.user.has_group("stock.group_stock_manager")
                if has("stock")
                else None,
                "pos_manager": env.user.has_group("point_of_sale.group_pos_manager")
                if has("point_of_sale")
                else None,
                "system": env.user.has_group("base.group_system"),
            }

        def company():
            c = env.company
            return {
                "id": c.id,
                "name": c.name,
                "currency": c.currency_id.name,
                "country": c.country_id.code or None,
                "multi_company": env["res.company"].sudo().search_count([]) > 1,
            }

        def accounting():
            if not has("account"):
                return {"installed": False}
            c = env.company
            J = env["account.journal"]
            T = env["account.tax"]
            return {
                "installed": True,
                "chart_template": c.chart_template or None,
                "account_count": env["account.account"].search_count([]),
                "journals": {
                    t: J.search_count([("type", "=", t)])
                    for t in ("sale", "purchase", "cash", "bank", "general")
                },
                "taxes": {
                    "sale": T.search_count([("type_tax_use", "=", "sale")]),
                    "purchase": T.search_count([("type_tax_use", "=", "purchase")]),
                },
                "default_sale_tax": bool(c.account_sale_tax_id),
                "default_purchase_tax": bool(c.account_purchase_tax_id),
                "anglo_saxon": bool(c.anglo_saxon_accounting),
            }

        def inventory():
            if not has("stock"):
                return {"installed": False}
            Cat = env["product.category"]
            cats = Cat.search([])
            valuation = {}
            for cat in cats:
                key = f"{cat.property_cost_method or 'unset'}/{cat.property_valuation or 'unset'}"
                valuation[key] = valuation.get(key, 0) + 1
            P = env["product.template"]
            Quant = env["stock.quant"]
            return {
                "installed": True,
                "warehouses": [
                    {"code": w.code, "reception_steps": w.reception_steps,
                     "delivery_steps": w.delivery_steps}
                    for w in env["stock.warehouse"].search([])
                ],
                "internal_locations": env["stock.location"].search_count(
                    [("usage", "=", "internal")]
                ),
                "category_valuation": valuation,
                "feature_lots": env.user.has_group("stock.group_production_lot"),
                "feature_uom": env.user.has_group("uom.group_uom"),
                "feature_multi_locations": env.user.has_group("stock.group_stock_multi_locations"),
                "products": P.search_count([]),
                "products_tracked": P.search_count([("tracking", "!=", "none")]),
                "pending_pickings": env["stock.picking"].search_count(
                    [("state", "in", ("confirmed", "waiting", "assigned"))]
                ),
                "negative_quants": Quant.search_count(
                    [("location_id.usage", "=", "internal"), ("quantity", "<", 0)]
                ),
            }  # fmt: skip

        def pos():
            if not has("point_of_sale"):
                return {"installed": False}
            methods = env["pos.payment.method"].search([])
            return {
                "installed": True,
                "configs": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "payment_methods": len(c.payment_method_ids),
                        "has_cash_method": any(m.is_cash_count for m in c.payment_method_ids),
                        "has_open_session": bool(c.has_active_session),
                        "has_journal": bool(c.journal_id),
                    }
                    for c in env["pos.config"].search([])
                ],
                "payment_methods": [
                    {"name": m.name, "type": m.type, "is_cash_count": bool(m.is_cash_count)}
                    for m in methods
                ],
                "open_sessions": env["pos.session"].search_count([("state", "!=", "closed")]),
            }  # fmt: skip

        def footprint():
            """Evidence of real activity and customization (drives environment classification)."""
            out = {
                "posted_moves": env["account.move"].search_count([("state", "=", "posted")])
                if has("account")
                else 0,
                "sale_orders": env["sale.order"].search_count([]) if has("sale") else 0,
                "pos_orders": env["pos.order"].search_count([]) if has("point_of_sale") else 0,
                "done_stock_moves": env["stock.move"].search_count([("state", "=", "done")])
                if has("stock")
                else 0,
                "products": env["product.template"].search_count([]),
            }
            # Core authors differ across versions ("Odoo S.A." in 18, "odoo" for some in 19), so
            # compare normalised exact names; "Odoo Community Association" must NOT match.
            def is_core(author):
                return (author or "").lower().replace(".", "").replace(" ", "") in CORE_AUTHORS

            custom = [
                m
                for m in env["ir.module.module"].sudo().search([("state", "=", "installed")])
                if not is_core(m.author)
            ]
            names = sorted(m.name for m in custom if not m.name.startswith("elblasy_"))
            out["non_standard_modules"] = names[:FOOTPRINT_MODULES_LIMIT]
            out["non_standard_module_count"] = len(names)
            return out

        return {
            "snapshot_version": 1,
            "read_only": True,
            "company": _section(company),
            "user_groups": _section(user_groups),
            "accounting": _section(accounting),
            "inventory": _section(inventory),
            "pos": _section(pos),
            "footprint": _section(footprint),
        }
