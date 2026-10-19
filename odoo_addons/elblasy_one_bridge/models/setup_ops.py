"""Allowlisted, idempotent configuration operations (the only writes the bridge offers).

Each operation is keyed by a stable `key`; the record it creates is tagged with the XML id
`elblasy_one.<key>`. Calling again with the same key finds that record instead of creating a
second one, so a retry after a timeout is always safe. Operations are additive: they create or
enable, and never rewrite or delete existing configuration."""

import logging
import re

from odoo import api, models
from odoo.exceptions import AccessError, UserError

from .readiness import PLANNABLE_MODULES

_logger = logging.getLogger(__name__)
XMLID_MODULE = "elblasy_one"
KEY_RE = re.compile(r"^[a-z0-9_]{3,64}$")

# feature -> (res.config.settings field, group needed to apply)
FEATURES = {
    "variants": "group_product_variant",
    "uom": "group_uom",
    "lots": "group_stock_production_lot",
}
JOURNAL_TYPES = ("cash", "bank")


class ElblasyBridgeSetup(models.AbstractModel):
    _inherit = "elblasy.bridge"

    # ---- helpers ----
    @api.model
    def _managed(self, key):
        """The record previously created under this key, or None."""
        data = self.env["ir.model.data"].sudo().search(
            [("module", "=", XMLID_MODULE), ("name", "=", key)], limit=1
        )
        if not data:
            return None
        rec = self.env[data.model].browse(data.res_id).exists()
        return rec or None

    @api.model
    def _tag(self, key, record):
        self.env["ir.model.data"].sudo().create(
            {"module": XMLID_MODULE, "name": key, "model": record._name, "res_id": record.id,
             "noupdate": True}
        )  # fmt: skip

    @api.model
    def _need(self, group, what):
        if not self.env.user.has_group(group):
            raise AccessError(f"The Odoo service user needs '{group}' to {what}.")

    # ---- public entry ----
    @api.model
    def apply_step(self, op_id, kind, key, params):
        """Apply one setup step. Returns {"outcome": created|already_exists|enabled, "refs": {...}}."""
        self._require_internal_user()
        if kind not in self._STEP_HANDLERS:
            raise UserError(f"Unsupported setup step kind: {kind}")
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid step key.")
        params = params or {}
        _logger.info("elblasy apply_step op=%s kind=%s key=%s user=%s",
                     op_id, kind, key, self.env.user.login)  # fmt: skip
        result = getattr(self, self._STEP_HANDLERS[kind])(key, params)
        _logger.info("elblasy apply_step op=%s -> %s", op_id, result.get("outcome"))
        return result

    _STEP_HANDLERS = {
        "install_module": "_step_install_module",
        "enable_feature": "_step_enable_feature",
        "ensure_journal": "_step_ensure_journal",
        "ensure_pos_payment_method": "_step_ensure_pos_payment_method",
        "ensure_pos_config": "_step_ensure_pos_config",
    }

    # ---- handlers ----
    @api.model
    def _step_install_module(self, key, p):
        self._need("base.group_system", "install apps")
        name = p.get("module")
        if name not in PLANNABLE_MODULES:
            raise UserError(f"Module not allowed: {name}")
        mod = self.env["ir.module.module"].sudo().search([("name", "=", name)], limit=1)
        if not mod:
            raise UserError(f"Module not available on this Odoo: {name}")
        if mod.state == "installed":
            return {"outcome": "already_exists", "refs": {"module": name}}
        if mod.state != "uninstalled":
            raise UserError(f"Module {name} is in state {mod.state}; refusing to install.")
        mod.button_immediate_install()
        return {"outcome": "created", "refs": {"module": name}}

    @api.model
    def _step_enable_feature(self, key, p):
        self._need("base.group_system", "change settings")
        feature = p.get("feature")
        field = FEATURES.get(feature)
        if not field:
            raise UserError(f"Feature not allowed: {feature}")
        settings = self.env["res.config.settings"]
        if field not in settings._fields:
            raise UserError(f"This Odoo has no setting '{field}'.")
        current = settings.default_get([field]).get(field)
        if current:
            return {"outcome": "already_exists", "refs": {"feature": feature}}
        settings.create({field: True}).execute()
        return {"outcome": "enabled", "refs": {"feature": feature}}

    @api.model
    def _step_ensure_journal(self, key, p):
        self._need("account.group_account_manager", "create journals")
        jtype = p.get("type")
        if jtype not in JOURNAL_TYPES:
            raise UserError(f"Journal type not allowed: {jtype}")
        existing = self._managed(key)
        if existing:
            return {"outcome": "already_exists", "refs": {"journal_id": existing.id}}
        J = self.env["account.journal"]
        unmanaged = J.search([("type", "=", jtype)], limit=1)
        if unmanaged:  # the business already has one: reuse, never add a second
            return {"outcome": "already_exists", "refs": {"journal_id": unmanaged.id, "unmanaged": True}}
        prefix = "CSH" if jtype == "cash" else "BNK"
        code = next(c for c in (f"{prefix}{i}" for i in range(1, 100)) if not J.search_count([("code", "=", c)]))
        name = (p.get("name") or jtype.title())[:64]
        j = J.create({"name": name, "type": jtype, "code": code})
        self._tag(key, j)
        return {"outcome": "created", "refs": {"journal_id": j.id, "code": code}}

    @api.model
    def _step_ensure_pos_payment_method(self, key, p):
        self._need("point_of_sale.group_pos_manager", "create POS payment methods")
        kind = p.get("kind")
        if kind not in ("cash", "bank"):
            raise UserError(f"Payment method kind not allowed: {kind}")
        existing = self._managed(key)
        if existing:
            return {"outcome": "already_exists", "refs": {"payment_method_id": existing.id}}
        PM = self.env["pos.payment.method"]
        is_cash = kind == "cash"
        unmanaged = PM.search([("is_cash_count", "=", is_cash)], limit=1)
        if unmanaged:
            return {"outcome": "already_exists",
                    "refs": {"payment_method_id": unmanaged.id, "unmanaged": True}}  # fmt: skip
        journal = self.env["account.journal"].search([("type", "=", "cash" if is_cash else "bank")], limit=1)
        if not journal:
            raise UserError(f"No {kind} journal exists yet; run the journal step first.")
        vals = {"name": "Cash" if is_cash else "Card / Wallet / Transfer",
                "is_cash_count": is_cash, "journal_id": journal.id}  # fmt: skip
        pm = PM.create(vals)
        self._tag(key, pm)
        return {"outcome": "created", "refs": {"payment_method_id": pm.id}}

    @api.model
    def _step_ensure_pos_config(self, key, p):
        self._need("point_of_sale.group_pos_manager", "create a point of sale")
        existing = self._managed(key)
        if existing:
            return {"outcome": "already_exists", "refs": {"pos_config_id": existing.id}}
        Cfg = self.env["pos.config"]
        if Cfg.search_count([]):
            return {"outcome": "already_exists", "refs": {"unmanaged": True}}
        methods = self.env["pos.payment.method"]
        for k in p.get("payment_method_keys", []):
            rec = self._managed(k)
            if rec:
                methods |= rec
        if not methods:
            methods = self.env["pos.payment.method"].search([])
        if not methods:
            raise UserError("No payment methods exist to attach to the point of sale.")
        cfg = Cfg.create({"name": (p.get("name") or "Main")[:64], "payment_method_ids": [(6, 0, methods.ids)]})
        self._tag(key, cfg)
        return {"outcome": "created", "refs": {"pos_config_id": cfg.id,
                                               "payment_method_ids": methods.ids}}  # fmt: skip
