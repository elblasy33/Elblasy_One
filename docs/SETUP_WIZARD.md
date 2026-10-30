# Setup wizard, plans and execution

## The business profile (no business type)
Nobody picks "grocery" or "shoe shop" from a list: no list could cover every small business, and a real shop
is often a mix (sweets by weight *and* sized clothes; a bakery that also delivers to traders). The wizard asks
how the business **works**, in five stages, and each answer switches on concrete capabilities:

| Stage | Questions (shown only when relevant) | Switches on |
|---|---|---|
| How you sell | what you sell (ready goods / things you make / services), how customers buy (till / orders for traders / delivery), busy-day volume, tills at once, tables, branches | services, sales orders, fast till; honest limits for tables, several tills, delivery tracking, branches |
| Your goods | by weight (+ scale prints a barcode label), sizes/colours, expiry, serial numbers, buy in one unit and sell in another, barcodes on products, recipes for what you make | weighing, scale labels, variants, expiry + lots, serials, units, internal barcodes, manufacturing |
| Customers and money | payment methods, known customers, credit and credit limits, retail vs wholesale prices, **VAT situation** | credit sales, credit limits, price lists, *prices include tax* (a real Odoo setting, allowed only before the first invoice) or *no sales tax* (products created without tax) |
| Buying and stock | follow stock, suppliers, buying on credit, reorder suggestions | supplier credit, reorder |
| People and devices | who works in the shop, scanner / receipt printer / drawer | (recorded for the next steps) |

A side panel shows, live, what the answers will set up and what this version cannot do yet (*limitations*, never
blocking). The review page lists every answer with an edit button per stage. The wizard starts from the last
profile, so it is also where the owner changes the business later: a changed profile builds a new plan that only
adds. Unanswered questions take sensible defaults; an unanswered VAT question is reported in the plan.

Answers that still carry `vertical` (the first questionnaire) are read with the legacy questions and templates, so
earlier plans and API clients keep working.

Flow: questionnaire (business language, conditional, AR/EN) -> `BusinessProfile` -> template + features
-> **dry-run plan** from a live read-only scan -> review/export -> hash-bound approvals.

- Verticals: grocery, bookstore, shoes, clothing, general. Add-ons derived from answers:
  manufacturing (`mrp`), expiry/lots (`product_expiry`), weighing scale (native Odoo weight rule
  `21.....{NNDDD}`; no module), variants (sizes/colours), multiple UoM, credit sales, supplier credit.
- **Additive only**: steps install/enable/create what is missing. Nothing existing is modified or
  deleted; differences are listed in `existing_notes` for human review.
- Step kinds (executor allowlist): install_module, enable_feature, ensure_journal,
  ensure_pos_payment_method, ensure_pos_config, load_chart_of_accounts. Each has a stable key
  (future XML id `elblasy_one.<key>`), risk, impact, recovery text, approval roles, dependencies.
- Chart of accounts is never loaded over posted entries; needs owner **and** accountant approval.
- Approval binds to `plan_hash`; a new plan supersedes older drafts/approvals. `snapshot_hash`
  lets the executor detect drift between planning and execution.
- Unsupported (reported, not worked around): >1 branch, weighed items combined with variants.
- Endpoints: `POST /setup/questionnaire`, `GET /setup/templates`,
  `POST|GET /connections/{id}/setup/plans[/{pid}[/export|/approve]]`.

## Execution (Stages 3-4)
`POST /connections/{id}/setup/plans/{pid}/execute` — requires `approved` status and every required
role's approval on the current `plan_hash`.
- **Drift guard**: first run replans from a fresh scan; if `snapshot_hash` differs from the reviewed
  one, execution is refused (409 `plan_drift`).
- **Per step**: tracked `Operation` (idempotency key `<plan>:<step>`) -> bridge `apply_step` (keyed
  by XML id `elblasy_one.<key>`, additive, allowlisted kinds/modules/features, Odoo-group checks)
  -> **independent verification**: fresh capabilities+snapshot, replan, step must now be `satisfied`.
  Only then is the step `succeeded` and its dependents allowed to run.
- **Outcome semantics**: Odoo refusal = `failed` (dependents `skipped`); timeout/connection loss =
  `needs_review` (unknown, never assumed failed); bridge says OK but Odoo disagrees = `needs_review`.
- **Recovery**: call execute again. Finished steps are skipped, the rest are idempotent, so nothing is
  duplicated. No automatic rollback; each step records recovery text (archive journal, uninstall app...).
- Reuse over duplication: an existing unmanaged cash/bank journal, payment method or POS is reused,
  never duplicated.
- **Not executable (manual)**: `load_chart_of_accounts` (financial, irreversible, not live-tested).
  Reported as `manual_required`; plan ends `needs_review` until the owner/accountant does it.
- Execution is synchronous (install of an app ~20-40 s). A background worker + progress polling is a TODO.

## Live-test evidence
`tests/integration/test_setup_execution_live.py` runs on throwaway copies (`duplicate_database`, ~4 s)
of the CE 18 and 19 template DBs: full grocery setup (mrp, product_expiry, lots, cash journal,
payment methods, POS) -> status `completed`, verified straight from Odoo via independent RPC;
re-plan shows nothing to apply; bridge rejects unlisted kinds/modules/features; an unprivileged
Odoo user cannot apply steps. Fake-Odoo tests cover timeouts, lost responses, rejection, false
success claims, drift and manual steps.

## Not yet built
Catalogue import (products/barcodes/scale codes), expense/vendor-bill flows, background worker,
the Next.js UI. Note: both CE test servers share one PostgreSQL, so each lists both `ce18`/`ce19`
(open only the matching one).

## Electronics and serial numbers
The `electronics` vertical (phones and appliances) tracks each item by serial/IMEI by default, plus colours/capacities. The question
`tracks_serials` appears for electronics and general trading; answering yes (or choosing electronics) adds the `serials` and `lots` features,
and the plan enables Odoo's "Lots & serial numbers" setting through the normal reviewed step. Products are then created with tracking
`serial`; receiving needs one serial per unit and the till needs one per unit sold.
