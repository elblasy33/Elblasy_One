# Purchasing (suppliers, purchase orders, receiving, vendor bills, supplier payments)

Everything moves through Odoo's own documents: `purchase.order` -> `stock.picking` (receipt) -> `account.move` (vendor bill)
-> `account.payment`. The platform stores only operation tracking.

## Quantities and money are never mixed
Ordered / received / billed / remaining per line; on hand / available (free) / incoming / forecast per product (`GET .../orders/{id}`
returns both). Ordering does not change on-hand stock; receiving does; billing follows receiving (Odoo's "control on received
quantities"): a partial receipt is billed for what arrived only.

## Operations (tracked, idempotent by `Idempotency-Key`, verified by a fresh read)
| Operation | Permission | Verified by |
|---|---|---|
| `POST /suppliers` | purchasing.manage | supplier read-back |
| `POST /orders` (confirmed) | purchasing.manage | order state/partner/lines |
| `POST /orders/{id}/receive` (full or partial, lot numbers for tracked goods) | purchasing.manage | received += requested **and** on-hand stock += requested |
| `POST /orders/{id}/bill` | payments.create | bill posted, quantities billed = quantities received-and-unbilled |
| `POST /bills/{id}/pay` (cash or bank, partial allowed) | payments.create | residual decreased by exactly the amount |
| `GET /suppliers/{id}/statement` | payments.create | open bills, payments, balance |

## Guarantees (live tests on Odoo CE 18 and 19)
Over-receiving, billing nothing, paying more than owed, duplicate product lines, non-suppliers, tracked goods without a lot number
are refused with clear messages and change nothing. A lost response on *receiving* (Odoo applied it, the answer never arrived)
followed by a retry leaves stock at 6, not 12. The operation stores the pre-state of the first attempt and verifies the retry against
it. Roles: the stock clerk orders and receives but sees no prices/balances and cannot bill or pay; the accountant bills, pays and
reads balances but cannot buy or receive; the cashier has no access. Costs and balances are removed server-side.

## Not yet built
Purchase returns / supplier credit notes, editing or cancelling orders, supplier price lists, receiving into several locations,
expiry dates (the lot number is stored; the expiry date is written only when the product-expiry app is installed), supplier
payments from the register's cash drawer (the payment uses the cash *journal*; it does not alter a POS session's counted cash).
