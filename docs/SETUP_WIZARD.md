# Setup wizard & plans (Stages 1-2 + approval; execution is the next increment)

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

## Not yet built
Executor + post-execution verification (Stage 3-4), catalogue import (products/barcodes/scale codes),
expense/vendor-bill flows, the Next.js UI.
