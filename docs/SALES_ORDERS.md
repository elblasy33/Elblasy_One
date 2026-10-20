# Manual sales orders (wholesale / on credit)

Outside the till, a shop sells to traders at their own prices and often on credit. That is Odoo's Sales app (`sale.order`), exposed under
**Sales orders** (permission `sales.orders`: owner and manager).

1. **Create**: pick the customer, add products, type the *unit price of each line* (defaults to the shelf price; discount % per line).
   Totals and tax are always Odoo's (`/sales-orders/quote`). Options: deliver now (stock leaves through a real delivery transfer; refused
   with `stock_short` if stock is short, and nothing is created) and invoice now (a posted customer invoice that stays open, with a
   credit period in days; the customer's credit limit is enforced, overridable by owner/manager and audited).
2. **Deliver** and **Invoice** can also be done later, separately (each verified by a fresh read: delivered quantities, stock, invoice
   posted and open for its full amount).
3. **Collect** with the receivables screens (customer statement), or cancel an order that has nothing delivered or invoiced.

Limits: tracked (lot/serial) goods must be delivered in Odoo; no partial deliveries or partial invoices from here yet; no quotation
(draft) stage, orders are confirmed on creation; no returns of delivered goods or credit notes from here.
