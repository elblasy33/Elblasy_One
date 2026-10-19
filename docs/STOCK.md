# Stock: levels, minimums, suggestions, counts, approvals, opening balances

Stock changes only through Odoo's inventory-adjustment flow (`stock.quant` -> `action_apply_inventory`). Each change carries a
**reason code** (count_correction, damaged, expired, lost, found, theft, opening_balance) and the requester/approver on the Odoo
stock move itself.

## Visibility (quantities are never interchangeable)
`GET /stock/overview` returns per product: on hand, free (available to sell), incoming, outgoing, forecast, minimum/maximum, and -
only for roles with `products.cost.view` - cost and inventory value (value comes from Odoo's own `stock.quant.value`).

## Minimums and suggestions are recommendations
`PUT /stock/products/{id}/minimum` creates an Odoo reorder rule with `trigger = manual`, so **Odoo never raises purchase orders by
itself** (tested: zero orders after a rule is set and the product is below minimum). `GET /stock/suggestions` lists products whose
forecast fell below the minimum; the UI turns them into a *draft* purchase order that the user completes (supplier) and confirms.

## Counts / adjustments
`POST /stock/adjustments` (Idempotency-Key): preview from Odoo -> if the actor is not owner/manager and |value change| exceeds
`ELBLASY_STOCK_ADJUST_APPROVAL_VALUE` (default 500) the request is stored as `awaiting_approval` (HTTP 202) and **nothing moves**.
Owner/manager approves (`/approve`) or rejects (`/reject`); nobody can approve their own request; an approved request is applied by
the same keyed operation. Direct adjustments are verified: on-hand must equal before + planned difference. A lost response followed
by a retry is recognised by a keyed marker in Odoo and not applied twice (tested). The pre-state of the first attempt is stored so the
retry is verified against it (not against the already-changed state).

## Opening balances: a separate, validated, owner/manager step
`POST /stock/opening/validate` posts nothing; rows must resolve by barcode to a stocked product, quantities/costs must be valid, and a
product that **already had stock movement is refused** (use a count). `POST /stock/opening/commit?import_id=` is limited to
`inventory.approve` (owner/manager), posts in batches of 50 as tracked operations, sets the opening unit cost before posting so stock is
valued correctly (tested: 40 x 12.5 = 500), and re-sending the same `import_id` replays finished batches (never posts twice).

## Not yet built
Multi-location/warehouse transfers, per-lot adjustments from the UI beyond lot-number entry, expiry reporting, automatic purchase
orders (deliberately excluded), valuation reports by category, per-tenant configuration of the approval threshold.
