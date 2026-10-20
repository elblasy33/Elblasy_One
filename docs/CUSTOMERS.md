# Customers, credit sales and receivables

Credit is a payment method of Odoo's own POS ("Customer account", set up by the reviewed plan when the owner says they sell on credit).
A sale that is partly or fully on credit needs a customer and becomes a *posted, open customer invoice* in Odoo; the paid part is an
ordinary payment. Collecting later is an inbound payment registered on that invoice.

- `POST/GET /customers`, `GET /customers/{id}/statement` (invoices, payments, balance, available credit), `PUT /customers/{id}/credit-limit`
  (needs `customers.credit.override`), `POST /customers/invoices/{id}/receive` (cash or bank).
- A credit limit is enforced at the sale (`credit_limit_exceeded`); an owner/manager may override it for one sale, which is audited.
- A credit sale cannot be refunded blindly: it needs a credit note in Odoo (refused with an explanation).
- Money overview and the Today page show total receivables and overdue invoices; alert `overdue_customer_invoices`.
- Verified: invoice state/residual and customer balance are re-read from Odoo after every credit sale and every collection.

Not yet built: credit notes from the platform, dunning/reminders, statements as PDF, interest, customer groups.
