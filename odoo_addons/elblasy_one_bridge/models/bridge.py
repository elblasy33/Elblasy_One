"""Read-only discovery surface of the bridge (contract version 1).

Called by the platform backend over RPC as a dedicated service user authenticated by API key.
Only allowlisted methods exist here; there is no generic model access. Version-specific
logic must go into adapters, not into these methods.
"""

from odoo import api, models
from odoo.exceptions import AccessError

CONTRACT_VERSION = 1


def wire(value):
    """Odoo's XML-RPC cannot marshal None. Drop None-valued keys (absent == null for the platform)
    and convert tuples/sets to lists, recursively. Every public bridge result goes through this."""
    if isinstance(value, dict):
        return {k: wire(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple, set)):
        return [wire(v) for v in value if v is not None]
    return value

# Modules whose presence the platform cares about -> capability name.
TRACKED_MODULES = {
    "account": "accounting",
    "sale": "sales",
    "purchase": "purchase",
    "stock": "inventory",
    "point_of_sale": "pos",
    "stock_account": "inventory_valuation",
    "product_expiry": "expiry_tracking",
    "uom": "uom",
    "sale_stock": "sales_inventory",
    "purchase_stock": "purchase_inventory",
    "mrp": "manufacturing",
}


class ElblasyBridge(models.AbstractModel):
    _name = "elblasy.bridge"
    _description = "Elblasy One bridge (RPC facade)"

    @api.model
    def _require_internal_user(self):
        if not self.env.user.has_group("base.group_user"):
            raise AccessError("Elblasy bridge requires an internal user.")

    @api.model
    def ping(self):
        self._require_internal_user()
        return {"ok": True, "contract_version": CONTRACT_VERSION}

    @api.model
    def capabilities(self):
        """Versioned capability manifest. Read-only; derived from installed modules and
        the calling user's own access rights, never from the Odoo version alone."""
        self._require_internal_user()
        from odoo.release import version_info

        names = list(TRACKED_MODULES)
        installed = {
            m.name
            for m in self.env["ir.module.module"].sudo().search(
                [("name", "in", names), ("state", "=", "installed")]
            )
        }
        ent_mod = self.env["ir.module.module"].sudo().search([("name", "=", "web_enterprise")], limit=1)
        ent = ent_mod.state if ent_mod else None
        user = self.env.user
        companies = [
            {"id": c.id, "name": c.name, "currency": c.currency_id.name}
            for c in user.company_ids
        ]
        caps = {cap: mod in installed for mod, cap in TRACKED_MODULES.items()}
        warehouses = (
            self.env["stock.warehouse"].search_count([]) if "stock" in installed else None
        )
        return wire({
            "contract_version": CONTRACT_VERSION,
            "odoo": {
                "series": f"{version_info[0]}.{version_info[1]}",
                "edition": "enterprise" if ent == "installed" else "community",
                "enterprise_addons_available": ent in ("installed", "uninstalled", "to install"),
            },
            "database": self.env.cr.dbname,
            "current_company_id": self.env.company.id,
            "allowed_companies": companies,
            "modules": sorted(installed),
            "capabilities": caps,
            "multi_warehouse": (warehouses or 0) > 1 if warehouses is not None else None,
            "user": {"id": user.id, "login": user.login},
        })
