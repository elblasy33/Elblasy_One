# Readiness engine (read-only)

`GET /connections/{id}/readiness` (permission `config.manage`) = bridge `readiness_snapshot` (facts)
+ `elblasy_api.readiness.engine` (judgement, ruleset v1.0). Nothing is written to Odoo; each scan is
audited (`readiness.scan`). A live test compares write dates/counts of key models before/after.

- **Facts vs judgement**: the addon only reports observed state; rules live in the API so they are
  unit-tested and versioned. Sections that cannot be read become `unable_to_verify` (never guessed).
- **Finding fields**: id, severity, subsystem, classification, description, evidence, confidence,
  recommended_action, auto_remediation_safe, required_permission, verification.
- **Classifications**: confirmed_issue, missing_configuration, valid_alternative, review_required,
  unable_to_verify. A difference from a template is never `confirmed_issue` unless it breaks a workflow
  (e.g. POS without payment methods, tracked products with lots disabled, negative stock).
- **Environment**: new_installation | existing_clean | existing_with_transactions |
  existing_customized | incompatible. "Customized" = installed modules whose author is not Odoo
  (normalised exact match; OCA is *not* core).
- `auto_remediation_safe` is false for every rule today; remediation arrives with Phase 4.

## Known limits
No rule yet covers: per-category account mappings, payment-terminal/printer hardware, multi-step
receipt flows beyond a review note, fiscal localisation specifics. Rules are generic, not
grocery-specific; template-specific checks come with the setup templates.
