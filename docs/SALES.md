# Sales on Odoo's native POS

The platform is a thin, safe front for Odoo's own POS engine (`pos.session`, `pos.order`, `pos.payment`).
It does not compute prices or taxes, keep its own stock/cash ledger, or write accounting entries.

## Money-moving operations (all tracked, idempotent, independently verified)
| Operation | Endpoint | Odoo-side effect | Verified by |
|---|---|---|---|
| Open register | `POST /sales/sessions` | session `opened` | `sales_get_session` state |
| Sale | `POST /sales/orders` | `pos.order` via `sync_from_ui` (the POS screen's own path) | read-back of state, total, paid, lines, payments |
| Refund (full) | `POST /sales/orders/{id}/refund` | negative order via `sync_from_ui` -> returned-stock movement + accounting | read-back (negative total, paid) |
| Close register | `POST /sales/sessions/{id}/close` | counted cash -> Odoo's closing flow -> posted journal entry | session `closed` and `move_id` posted |

Reads: `GET /sales/state`, `/sales/products` (variant-level search), `/sales/lookup` (barcode via Odoo's nomenclature, incl. weighed
labels), `POST /sales/quote` (Odoo's pricelist + tax engine), `/sales/orders`, `/sales/summary`.

## Guarantees (each covered by a live test on Odoo CE 18 and 19)
- **No duplicate sale**: the client's `Idempotency-Key` becomes the POS order `uuid`. Retry -> same order. Same key with a different
  cart -> 409. A *lost response* (Odoo recorded it, answer never arrived) -> `outcome_unknown`; retry returns the existing order; stock
  falls once.
- **No surprise price**: the sale carries `expected_total`; if Odoo's total differs the sale is refused (`price_changed`), and the UI
  hides any total that does not match the current cart while a new quote loads.
- **Change only from cash**; payments must cover the total; discounts need `sales.discount`; refunds need `sales.returns`;
  the cashier's e-mail is stored in the Odoo order's internal note.
- **Stock follows the sale**: with the company setting `point_of_sale_update_stock_quantities = real` stock is deducted (picking `done`)
  at each sale and restored by a refund (tested). If the setting is `closing`, the setup plan proposes an explicit, approved step
  ("Update stock at every sale"); nothing changes silently. The sale response reports `stock_updated`.
- **Cash reconciliation**: closing with a counted amount different from Odoo's expected cash reports `has_difference`, is audited, and
  Odoo posts the difference per its own accounting configuration.

## Version adapters (bridge `sales_ops.py`)
Odoo 19 stores change (`amount_return`) as a negative number, Odoo 18 as positive; the internal-note field is `internal_note` (19) /
`general_note` (18); session numbering differs. All isolated in small helpers.

## Not yet built
Partial refunds, credit sales / customer accounts, non-cash terminals, discounts approval thresholds, offline mode, receipt
localisation of payment-method names (Odoo's "Cash" is created in English), per-tenant receipt branding, hardware (printer/drawer).
Sales are executed as the Odoo service user; the cashier identity is recorded in the audit log and the order note, not as an Odoo user.
