"""Scale labels from the shop's existing scales, whatever their format.

A label is an EAN-13: a prefix, the item's number in the scale (PLU), then the weight or the price, then a check
digit. Odoo reads such labels through its barcode nomenclature (`barcode.rule`, types "weight" and "price"). A shop
that already prints labels in its own format describes that format once; Elblasy One writes the matching rule, and
each weighed product gets the barcode its scale label points to. Nothing on the scales has to change."""

import re

from odoo import api, models
from odoo.exceptions import UserError

from .bridge import wire

KEY_RE = re.compile(r"^[a-f0-9]{32}$")
FMT = re.compile(r"^(\d{1,3})(\.+)\{(N+)(D*)\}$")


def ean13_check(d12):
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(d12))
    return str((10 - s % 10) % 10)


class ElblasyBridgeScale(models.AbstractModel):
    _inherit = "elblasy.bridge"

    @api.model
    def _nomenclature(self):
        nom = self.env.company.nomenclature_id if "nomenclature_id" in self.env.company._fields else False
        if not nom:
            raise UserError("This Odoo has no barcode nomenclature.")
        return nom

    @api.model
    def _rule_view(self, r):
        m = FMT.match(r.pattern or "")
        fmt = {"prefix": m.group(1), "plu_digits": len(m.group(2)), "int_digits": len(m.group(3)), "dec_digits": len(m.group(4))} if m else None
        return {"id": r.id, "name": r.name, "type": r.type, "pattern": r.pattern, "sequence": r.sequence, "format": fmt,
                "managed": bool(self.env["ir.model.data"].sudo().search_count([("model", "=", "barcode.rule"), ("res_id", "=", r.id), ("module", "=", "elblasy_one")]))}  # fmt: skip

    @api.model
    def scale_rules(self):
        self._require_internal_user()
        nom = self._nomenclature()
        rules = nom.rule_ids.filtered(lambda r: r.type in ("weight", "price")).sorted(lambda r: (r.sequence, r.id))
        return wire({"nomenclature": nom.name, "items": [self._rule_view(r) for r in rules]})

    @api.model
    def scale_rule_upsert(self, op_id, key, spec):
        """Describe a label format: prefix + PLU digits + weight/price digits (+ decimals) = 12 digits, then the
        check digit. Placed before Odoo's default rules so labels with this prefix are read this way."""
        self._require_internal_user()
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid operation key.")
        existing = self._managed(f"scale_{key}")
        if existing:
            return wire({"outcome": "already_exists", "refs": {"rule": self._rule_view(existing)}})
        prefix = str(spec.get("prefix") or "")
        kind = spec.get("kind")
        plu, n, d = (int(spec.get(k) or 0) for k in ("plu_digits", "int_digits", "dec_digits"))
        if not re.fullmatch(r"\d{1,3}", prefix):
            raise UserError("The prefix is 1 to 3 digits.")
        if kind not in ("weight", "price"):
            raise UserError("A label carries a weight or a price.")
        if plu < 1 or n < 1 or d < 0 or len(prefix) + plu + n + d != 12:
            raise UserError(f"Prefix, item number and value must make 12 digits (now {len(prefix) + plu + n + d}).")
        pattern = prefix + "." * plu + "{" + "N" * n + "D" * d + "}"
        nom = self._nomenclature()
        same = nom.rule_ids.filtered(lambda r: r.pattern == pattern and r.type == kind)
        if same:
            return wire({"outcome": "already_exists", "refs": {"rule": self._rule_view(same[:1])}})
        rule = self.env["barcode.rule"].create({
            "name": f"Scale {prefix} ({kind})", "barcode_nomenclature_id": nom.id, "type": kind,
            "encoding": "ean13", "pattern": pattern, "sequence": 5,
        })  # fmt: skip
        self._tag(f"scale_{key}", rule)
        return wire({"outcome": "created", "refs": {"rule": self._rule_view(rule)}})

    @api.model
    def _scale_barcode(self, rule, plu):
        """The barcode a weighed product must carry for labels of this rule to find it: the label with a zero value."""
        m = FMT.match(rule.pattern or "")
        if not m:
            raise UserError("This rule's format cannot be used for product codes.")
        digits = len(m.group(2))
        plu = str(plu or "").strip()
        if not plu.isdigit() or len(plu) > digits:
            raise UserError(f"The scale item number must be up to {digits} digits.")
        d12 = m.group(1) + plu.zfill(digits) + "0" * (len(m.group(3)) + len(m.group(4)))
        return d12 + ean13_check(d12)

    @api.model
    def scale_code_for(self, rule_id, plu):
        self._require_internal_user()
        rule = self.env["barcode.rule"].browse(int(rule_id or 0)).exists()
        if not rule:
            raise UserError("Scale rule not found.")
        return wire({"barcode": self._scale_barcode(rule, plu)})

    @api.model
    def scale_parse(self, code):
        """What Odoo reads from a label: test a real label from the shop's scale before relying on it."""
        self._require_internal_user()
        code = (code or "").strip()
        if not re.fullmatch(r"\d{8,14}", code):
            return wire({"type": "invalid"})
        parsed = self._nomenclature().parse_barcode(code) or {}
        out = {"type": parsed.get("type", "error"), "value": parsed.get("value"), "base_code": parsed.get("base_code")}
        if out["base_code"]:
            p = self.env["product.product"].search([("barcode", "=", out["base_code"])], limit=1)
            out["product"] = p.display_name if p else None
        return wire(out)
