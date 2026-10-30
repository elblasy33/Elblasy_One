# Kits, price lists, scale labels, promotions and loyalty

## Kits and recipes (`/catalog/recipes`)
A product can be composed of others in two ways: a **recipe** made in batches (production orders; ingredients go
out, the product comes in) or a **kit** sold as one item (Odoo `mrp.bom` type `phantom`; when it is sold at the till,
Odoo's own delivery takes its parts out of stock). Recipes can be edited (`replace: true`): the change applies from
now on; history stays. Every save is re-read from Odoo (`catalog_get_bom`) and compared. The screen shows the unit
cost from the components' costs and the margin against the sale price (only to users allowed to see costs).

## Features page (`/settings/features`)
Switches for units of measure, price lists, loyalty and promotions, production and kits, selling by weight, sizes and
colours, expiry, serial numbers and credit. Each switch is one answer of the business profile: switching it builds a
new plan that is reviewed and approved before Odoo changes. Switching off hides the feature in Elblasy One only; data
Odoo already holds for it is never deleted.

## Price lists (`/pricelists`, `/customers/{id}/pricelist`)
Odoo's `product.pricelist` keeps fixed prices per product, optionally from a quantity (wholesale breaks). A customer
can be given a list; the till's quote and checkout and sales orders then use Odoo's price engine with that list
(`specific_property_product_pricelist`). Rules created elsewhere in Odoo are shown and left untouched. Each change is
verified by asking Odoo's engine for the resulting price.

## Scale labels (`/scale/rules`, `/scale/parse`)
Shops with scales from an older system keep their labels. The owner describes the format once (prefix, digits of the
scale item number, weight or price, whole and decimal digits = 12 before the check digit); Elblasy One writes the
matching Odoo `barcode.rule` (types `weight` and `price`) ahead of the defaults. A weighed product is created with
its number on the scale (PLU) and gets the barcode its labels point to. Price labels give the quantity from the
unit price. A real label can be tested from the screen.

## Promotions and loyalty (`/loyalty/programs`)
Odoo Community's loyalty app keeps programmes, rewards, customer cards and history but applies them in its own POS
screen, which Elblasy One does not use, so Elblasy One applies them itself at quote and checkout, for programmes it
created: points (N per currency unit, value per point, minimum to redeem), buy X get Y (same item), a percentage off
chosen items or a category, and a percentage off the sale from an amount. Rewards are written as Odoo reward lines
(`is_reward_line`, `reward_id`), taxed like the goods they discount; points go to the customer's `loyalty.card` with a
`loyalty.history` line in the same transaction as the sale, so a retried sale never counts twice. The loyalty app's
own bookkeeping products (gift card, e-wallet top-up, reward discount lines) are kept off the till.

Limits: one points programme at a time; programmes created directly in Odoo are not applied by Elblasy One's till;
refunds return the money of reward lines but do not take back points; gift cards, e-wallets and coupon codes are not
supported yet.

## Not done yet: units of measure per product
The switch turns on Odoo's units of measure, but buying in one unit and selling in another (carton → piece) per
product is not built yet. Odoo 18 and 19 model units very differently (19 drops unit categories and the purchase
unit field), so it needs its own version adapter.
