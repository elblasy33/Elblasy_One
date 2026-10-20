# Producing made products

For shops that make products from ingredients (a bakery counter, ready meals). A recipe is an Odoo bill of materials (`POST /catalog/recipes`);
a *batch* is a native manufacturing order, so Odoo itself consumes the components and adds the finished product with correct costing.

- `GET /production/recipes`: each recipe with its components, stock of each and `can_make` (how many units the current stock allows).
- `POST /production/batches {template_id, qty}`: refused up front when components are short ("Not enough components: ..."), so nothing is
  half-produced. Idempotent (the operation key is the order's origin), and verified by a fresh read of the order plus the finished product's
  stock (+qty) and every component's stock (-qty x per-unit).
- `GET /production/history`: the batches made through the platform.

Not yet built: editing recipes, multi-level recipes, production planning/scheduling, waste/yield variance, costing reports.
