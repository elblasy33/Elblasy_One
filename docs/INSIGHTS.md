# Today's insights

`GET /sales/insights?days=7` (reports.view) reads live from Odoo: net sales per local day (refunds subtracted), best sellers, idle stock
(in stock, no till sale in 30 days, ranked by stock value) and lots expiring within 30 days. Shown on the Today page. Nothing is stored
by the platform. Limits: sales come from the POS only; idle-stock value uses Odoo's stock valuation; expiry needs the product-expiry app
(the expiry list is simply absent otherwise).
