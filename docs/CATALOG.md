# Catalogue (products, scale barcodes, recipes, import)

Products are created **in Odoo** through allowlisted bridge operations; the platform stores no product data,
only operation tracking and barcode counters. Opening stock is a separate workflow (not built yet).

## Guarantees
- **Idempotent**: every write needs an `Idempotency-Key`. Same key + same payload -> same product (replay);
  same key + different payload -> 409 `idempotency_conflict`. The key is also turned into a stable Odoo XML id
  (`elblasy_one.prod_<hash>`), so retrying after a lost response returns the existing product (live-tested:
  Odoo applies, response lost, retry -> exactly one product).
- **Verified**: after creation the product is read back from Odoo (`catalog_get`); name/price/barcode must match or the
  operation is `needs_review` (never reported as success).
- **Safe errors**: Odoo rejection -> 422 `product_rejected` with Odoo's message; unknown outcome -> 502 `outcome_unknown`.
- **Honest prerequisites**: variants, lot tracking and recipes are refused with a clear message if the Odoo feature is not enabled
  (the setup plan enables them) instead of creating unusable data.
- **Cost privacy**: product cost is stripped server-side unless the role has `products.cost.view`.
- Bridge results never contain `None` (Odoo's XML-RPC cannot marshal it); `wire()` strips it centrally.

## Weighing scale
Odoo's default nomenclature has the weight rule `21.....{NNDDD}` (verified on CE 18 and 19). A weighed product (UoM kg, `to_weight`)
is stored with barcode `21` + 5-digit code + `00000` + EAN-13 check digit. A scale prints the weight in digits 8-12; Odoo
zeroes them and recomputes the check digit to find the product. The live test feeds a printed 1.250 kg barcode to Odoo's own
`barcode.nomenclature.parse_barcode` and checks type=weight, value=1.25. Automatic codes: scale 00001-99999 per connection;
in-store codes use prefix `20` (never matches Odoo's 21/22/23 rules). Counters are per-connection rows (`barcode_sequences`);
collisions with existing Odoo barcodes skip to the next value.

## Endpoints (`/connections/{id}/catalog/...`)
`POST products` (products.manage), `GET products?q=&limit=&offset=` (products.view), `POST recipes`,
`POST import/validate`, `POST import/commit?import_id=` (<=100 rows; row-level errors; barcodes already in Odoo flagged;
commit is replay-safe per `import_id`+row).

## Roles
owner/manager: all. inventory_operator: manage+view. cashier/accountant: view (accountant also sees cost).

## Editing, archiving, categories
`PATCH /catalog/products/{template_id}` changes only the fields sent (name, price, cost, sku, barcode, category, in_pos, active); costs need
the cost-visibility permission; barcodes are checked against every product (also archived ones). **Archiving is refused while the product still
has stock**, so stock can never be hidden; `GET products?archived=true` lists archived products and `active:true` restores one.
`GET /catalog/categories` feeds the category picker. Tracking can be none, lot (first-expiry-first-out at the till) or serial.

## Limits / TODO
Recipes cannot be edited and only support single-variant products; no per-variant barcodes yet; units of measure are fixed to piece/kg
(no management screen); import is synchronous (100 rows); categories are matched by exact name; taxes use Odoo's company defaults.
