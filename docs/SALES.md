# Sales on Odoo's native POS

The platform is a thin, safe front for Odoo's own POS engine (`pos.session`, `pos.order`, `pos.payment`).
It does not compute prices or taxes, keep its own stock/cash ledger, or write accounting entries.

## Money-moving operations (all tracked, idempotent, independently verified)
| Operation | Endpoint | Odoo-side effect | Verified by |
|---|---|---|---|
| Open register | `POST /sales/sessions` | session `opened` | `sales_get_session` state |
| Sale | `POST /sales/orders` | `pos.order` via `sync_from_ui` (the POS screen's own path) | read-back of state, total, paid, lines, payments |
| Refund (whole or by line quantity) | `POST /sales/orders/{id}/refund` | negative order via `sync_from_ui` -> returned-stock movement + accounting | read-back (negative total, paid) |
| Refund request (cashier) | `POST /sales/orders/{id}/refund-request` | nothing in Odoo until a manager approves (`/sales/refund-requests/{id}/approve`, never self-approved) | same as a refund |
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

## Keyboard-first till (the fast path)
A busy till is driven from the keyboard and the scanner, never the mouse. Odoo's own POS has no built-in shortcut
layer (third-party apps add one); here it is part of the screen.

- **One command line** (always focused; typing anywhere goes into it, Arabic-Indic digits accepted):
  scan or type, then Enter. `3*` before a scan sets the quantity (the supermarket habit: quantity, ×, scan);
  `3*6221...` in one go works too; `*5` changes the selected line; `%10` gives a discount and `@25` a price
  (each only with its permission, audited); Enter on an empty line opens payment.
- **Instant on the device:** when the shift opens, the till loads everything it sells once (`/sales/catalog`:
  id, name, barcode, item code, price). Exact barcode, then item code, then a ranked, Arabic-aware name search
  (أ/إ/آ, ة/ه, ى/ي and tashkeel ignored) answer without a network round trip; a results list follows ↑/↓ and
  Enter. Weighed-item labels and products added after the shift opened go to the server lookup, which now also
  matches the item code. Odoo still prices every sale (quote and checkout).
- **Keys:** F1 shortcuts · F2 command line · F3 customer · F4/F12 pay · F8 park order · F9 next parked order ·
  ↑/↓ lines · + / − quantity · Delete remove line · Esc clear/deselect. Payment: Enter confirms; Enter with no
  amount pays the exact amount. After the sale: Enter starts the next one, P prints.
- **Feedback:** a short high beep when an item is added, a low one when nothing matched (can be muted by setting
  `pos-sound` to `0`), and the added line flashes.
- **Dialogs** open with the cursor in their first field (the browser's default put it on the close button).

Measured: every till call to the API takes ~45 ms (it was ~750 ms before the Odoo login was cached).

## The register screen (compared with Odoo's POS)
Product grid with category tabs, image tiles (served through the session-protected `/sales/products/{id}/image`), live stock badge and
"show more"; barcode/search box (F2); a numpad on the selected line with quantity, discount % (needs `sales.discount`) and price
(needs `sales.price.override`, audited as `price_override`) modes; several open orders (park the current one and serve someone else,
kept in the browser per session, so a reload does not lose them); an order note; F4 to pay. What Odoo's own POS has that this does
not: cash in/out from the drawer, product combos, per-line notes, kitchen/printer routing, offline operation, loyalty and gift cards.

## Partial refunds and refund requests
`lines: [{line_id, qty}]` refunds chosen quantities (empty = everything still refundable); a line can be refunded in several steps but never
beyond what was sold. A cashier has no `sales.returns` permission: they *ask*, and a manager/owner approves or rejects from the register's
history tab (audit: `sales.refund.requested`, `sales.order.refund.approved`, `sales.refund.rejected`; alert `refund_requests_waiting`).
Credit sales (open invoice) cannot be refunded here; they need a credit note in Odoo.

## Tracked goods at the till
- **Lot/expiry goods** are taken first-expiry-first-out automatically and never from an expired lot; a sale line is split into one order line
  per lot (Odoo's POS books one lot per line), the total unchanged. Whole units only. Too little usable stock -> `lot_stock_short`.
- **Serial goods** need exactly one distinct, in-stock serial per unit (`serials_required`, `serial_not_in_stock`); refunds put the same
  serials back. Found by an integration test: without lots the order was *paid* but stock never moved, so this is enforced.

## Day boundaries
"Today" runs from local midnight to local midnight in the Odoo user's timezone (it used to be UTC; found when a test crossed midnight).

## Not yet built
Discount approval thresholds (a cashier cannot discount at all; a manager rings the sale), non-cash terminals, offline mode, receipt
localisation of payment-method names (Odoo's "Cash" is created in English), per-tenant receipt branding, hardware (printer/drawer).
Sales are executed as the Odoo service user; the cashier identity is recorded in the audit log and the order note, not as an Odoo user.
