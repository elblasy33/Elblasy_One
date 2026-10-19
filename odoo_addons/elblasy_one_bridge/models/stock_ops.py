"""Stock visibility, minimum levels, counts/adjustments and opening balances.

Rules enforced here (not only in the UI):
- Stock changes only through Odoo's inventory-adjustment flow (`stock.quant` -> `action_apply_inventory`),
  always with a reason that travels with the stock move; never by editing quantities directly.
- Each adjustment is keyed: a retry after a lost response is recognised and not applied twice.
- Minimum-level rules are created with trigger 'manual' so Odoo never raises purchase orders by itself:
  suggestions are recommendations, not confirmed orders.
- Opening balances are only accepted for products that have never had stock movement."""

import re

from odoo import api, fields, models
from odoo.exceptions import UserError

from .bridge import wire
from .setup_ops import XMLID_MODULE

KEY_RE = re.compile(r"^[a-f0-9]{32}$")
REASONS = ("count_correction", "damaged", "expired", "lost", "found", "theft", "opening_balance")
MAX_LINES = 200
TOL = 0.0005


def _num(v, field, minimum=0.0, maximum=1e9):
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise UserError(f"{field} must be a number.") from None
    if n != n or n < minimum or n > maximum:
        raise UserError(f"{field} is out of range.")
    return n


class ElblasyBridgeStock(models.AbstractModel):
    _inherit = "elblasy.bridge"

    @api.model
    def _need_stock(self):
        if not self.env.user.has_group("stock.group_stock_user"):
            raise UserError("The Odoo service user needs the Inventory user rights.")

    @api.model
    def _stock_location(self):
        wh = self.env["stock.warehouse"].search([("company_id", "=", self.env.company.id)], limit=1)
        if not wh:
            raise UserError("No warehouse exists.")
        return wh, wh.lot_stock_id

    # ---- idempotency marker (an XML id on the company: "this keyed operation was applied") ----
    @api.model
    def _marked(self, name):
        return bool(self.env["ir.model.data"].sudo().search_count([("module", "=", XMLID_MODULE), ("name", "=", name)]))

    @api.model
    def _mark(self, name):
        self.env["ir.model.data"].sudo().create(
            {"module": XMLID_MODULE, "name": name, "model": "res.company", "res_id": self.env.company.id, "noupdate": True}
        )

    @api.model
    def _key_ok(self, key):
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise UserError("Invalid operation key.")
        return key

    # ---- overview ----
    @api.model
    def _min_by_product(self, wh):
        out = {}
        for op in self.env["stock.warehouse.orderpoint"].search([("warehouse_id", "=", wh.id)]):
            out[op.product_id.id] = {"min": op.product_min_qty, "max": op.product_max_qty}
        return out

    @api.model
    def _value_of(self, product, loc):
        quants = self.env["stock.quant"].search([("product_id", "=", product.id), ("location_id", "child_of", loc.id)])
        if quants and "value" in quants._fields:
            return sum(quants.mapped("value"))
        return product.qty_available * product.standard_price

    @api.model
    def stock_overview(self, query, only_low, limit, offset, product_id=0):
        self._require_internal_user()
        self._need_stock()
        wh, loc = self._stock_location()
        limit = max(1, min(int(limit or 25), 100))
        domain = [("is_storable", "=", True)]
        if product_id:
            domain.append(("id", "=", int(product_id)))
        q = (query or "").strip()
        if q:
            domain += ["|", "|", "|", ("name", "ilike", q), ("barcode", "ilike", q), ("default_code", "ilike", q),
                       ("product_template_attribute_value_ids.name", "ilike", q)]  # fmt: skip
        mins = self._min_by_product(wh)
        P = self.env["product.product"]
        rows = []
        for p in P.search(domain, order="name, id"):
            lv = mins.get(p.id)
            low = bool(lv) and p.virtual_available < lv["min"] - TOL
            if only_low and not low:
                continue
            rows.append(
                {
                    "product_id": p.id, "name": p.display_name, "barcode": p.barcode or None,
                    "on_hand": p.qty_available, "free": p.free_qty, "incoming": p.incoming_qty,
                    "outgoing": p.outgoing_qty, "forecast": p.virtual_available,
                    "min": lv["min"] if lv else None, "max": lv["max"] if lv else None, "low": low,
                    "cost": p.standard_price, "value": self.env.company.currency_id.round(self._value_of(p, loc)),
                    "tracking": p.tracking if "tracking" in p._fields else "none",
                }
            )  # fmt: skip
        total = len(rows)
        return wire({"total": total, "items": rows[int(offset or 0): int(offset or 0) + limit]})

    @api.model
    def stock_set_minimum(self, op_id, key, spec):
        """Minimum (and an implied maximum) per product. Manual trigger: Odoo never orders by itself."""
        self._require_internal_user()
        self._need_stock()
        self._key_ok(key)
        p = self.env["product.product"].browse(int(spec.get("product_id") or 0)).exists()
        if not p or not p.is_storable:
            raise UserError("Product not found or not stocked.")
        mn = _num(spec.get("min_qty"), "minimum")
        mx = _num(spec.get("max_qty", max(mn * 2, mn + 1)), "maximum")
        if mx < mn:
            raise UserError("The maximum cannot be below the minimum.")
        wh, loc = self._stock_location()
        OP = self.env["stock.warehouse.orderpoint"]
        op = OP.search([("product_id", "=", p.id), ("warehouse_id", "=", wh.id)], limit=1)
        vals = {"product_min_qty": mn, "product_max_qty": mx, "trigger": "manual"}
        if op:
            op.write(vals)
            outcome = "updated"
        else:
            OP.create({**vals, "product_id": p.id, "warehouse_id": wh.id, "location_id": loc.id})
            outcome = "created"
        return wire({"outcome": outcome, "refs": {"product_id": p.id, "min": mn, "max": mx}})

    @api.model
    def stock_suggestions(self):
        """Reorder *recommendations* only: nothing here creates an order."""
        self._require_internal_user()
        self._need_stock()
        wh, _ = self._stock_location()
        out = []
        for op in self.env["stock.warehouse.orderpoint"].search([("warehouse_id", "=", wh.id)]):
            p = op.product_id
            if p.virtual_available < op.product_min_qty - TOL:
                need = op.product_max_qty - p.virtual_available
                out.append({
                    "product_id": p.id, "name": p.display_name, "forecast": p.virtual_available,
                    "on_hand": p.qty_available, "incoming": p.incoming_qty, "min": op.product_min_qty,
                    "max": op.product_max_qty, "suggested_qty": float(int(need) if need == int(need) else int(need) + 1),
                })  # fmt: skip
        out.sort(key=lambda r: r["forecast"] - r["min"])
        return wire({"items": out})

    # ---- count / adjustment ----
    @api.model
    def _plan_lines(self, lines, reason):
        if reason not in REASONS:
            raise UserError("Unknown reason.")
        if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
            raise UserError(f"A count needs 1-{MAX_LINES} lines.")
        wh, loc = self._stock_location()
        cur = self.env.company.currency_id
        planned, seen = [], set()
        for l in lines:
            p = self.env["product.product"].browse(int(l.get("product_id") or 0)).exists()
            if not p or not p.is_storable:
                raise UserError("A counted product was not found or is not stocked.")
            if p.id in seen:
                raise UserError(f"'{p.display_name}' appears twice.")
            seen.add(p.id)
            counted = _num(l.get("counted_qty"), "counted quantity", maximum=1e8)
            quants = self.env["stock.quant"].search([("product_id", "=", p.id), ("location_id", "=", loc.id)])
            current = sum(quants.mapped("quantity"))
            lot = (l.get("lot_name") or "").strip()
            if p.tracking != "none" and not lot:
                raise UserError(f"'{p.display_name}' is tracked: say which lot was counted.")
            if p.tracking != "none":
                lq = quants.filtered(lambda q, lot=lot: q.lot_id.name == lot)
                current = sum(lq.mapped("quantity"))
            diff = counted - current
            unit_cost = None
            if reason == "opening_balance" and l.get("unit_cost") is not None:
                unit_cost = _num(l["unit_cost"], "unit cost")
            cost = unit_cost if unit_cost is not None else p.standard_price
            planned.append({
                "product_id": p.id, "name": p.display_name, "current": current, "counted": counted,
                "diff": diff, "value_change": cur.round(diff * cost), "lot_name": lot or None,
                "unit_cost": unit_cost,
            })  # fmt: skip
        return planned, wh, loc

    @api.model
    def stock_preview(self, spec):
        """What a count would change, without changing anything."""
        self._require_internal_user()
        self._need_stock()
        planned, _, _ = self._plan_lines(spec.get("lines"), spec.get("reason") or "count_correction")
        return wire({"lines": planned, "value_change": sum(l["value_change"] for l in planned)})

    @api.model
    def stock_adjust(self, op_id, key, spec):
        self._require_internal_user()
        self._need_stock()
        key = self._key_ok(key)
        reason = spec.get("reason") or "count_correction"
        planned, wh, loc = self._plan_lines(spec.get("lines"), reason)
        marker = f"adj_{key}"
        if self._marked(marker):
            return wire({"outcome": "already_exists", "refs": {"lines": planned, "applied": True}})
        Quant = self.env["stock.quant"].with_context(inventory_name=f"Elblasy {reason}: {(spec.get('note') or '')[:80]}".strip())
        changed = []
        for l in planned:
            if abs(l["diff"]) <= TOL:
                continue
            p = self.env["product.product"].browse(l["product_id"])
            lot = False
            if l["lot_name"]:
                lot = self.env["stock.lot"].search([("name", "=", l["lot_name"]), ("product_id", "=", p.id)], limit=1) or \
                    self.env["stock.lot"].create({"name": l["lot_name"], "product_id": p.id, "company_id": self.env.company.id})
            if l.get("unit_cost") is not None and reason == "opening_balance":
                p.standard_price = l["unit_cost"]  # opening cost is set before the stock is posted, so it is valued correctly
            quant = Quant.with_context(inventory_mode=True).create(
                {"product_id": p.id, "location_id": loc.id, "inventory_quantity": l["counted"],
                 **({"lot_id": lot.id} if lot else {})}
            )  # fmt: skip
            quant.action_apply_inventory()
            changed.append(l)
        self._mark(marker)
        return wire({"outcome": "created", "refs": {"lines": planned, "changed": len(changed), "applied": True}})

    @api.model
    def stock_has_history(self, product_ids):
        """Products that already had stock movement (opening balances are not allowed for them)."""
        self._require_internal_user()
        self._need_stock()
        ids = [int(i) for i in (product_ids or [])][:500]
        moved = self.env["stock.move.line"].read_group([("product_id", "in", ids), ("state", "=", "done")], ["product_id"], ["product_id"])
        return wire({"with_history": [m["product_id"][0] for m in moved if m["product_id"]]})

    @api.model
    def stock_resolve_barcodes(self, codes):
        """Barcode -> product, for opening-balance files."""
        self._require_internal_user()
        self._need_stock()
        found = {}
        for p in self.env["product.product"].search([("barcode", "in", [str(c)[:64] for c in (codes or [])][:500]), ("is_storable", "=", True)]):
            found[p.barcode] = {"product_id": p.id, "name": p.display_name}
        return wire({"found": found})
