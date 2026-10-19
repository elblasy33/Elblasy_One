# Setup wizard, plans and execution

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
