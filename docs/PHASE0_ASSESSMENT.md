# Phase 0 Assessment — Elblasy One (2026-10-19)

## 1. Repository state
Empty directory, not a git repo (initialised during Phase 1). Nothing to preserve.

## 2. Environment
| Tool | Status |
|---|---|
| Node 26.7, npm 11 | present |
| pnpm 12.14, uv 0.13 | installed at user level during this session |
| Python 3.14 (project pins >=3.13) | present |
| Rust/cargo 1.88 | present (Tauri 2 needs system webkit2gtk libs — unverified) |
| Docker 29 + compose v5 | present |
| psql 18 client | present; no platform Postgres running yet |
| Odoo 18 (`:8018`), Odoo 19 (`:8019`) | **running in Docker locally** — usable as real integration targets |
| MCP odoo-local (`:8017`, db `sh_live_test`) | configured but connection refused; not used |

Live Odoo integration is therefore **unverified** so far; no Odoo instance has been contacted.

## 3. Reusable / missing
Reusable: local Odoo 18/19 containers, toolchain. Missing: everything else (web, desktop, bridge module, DB schema, CI, docs).

## 4. Target architecture
Modular monolith, per master prompt §5: Web/Desktop (same Next.js UI) -> FastAPI -> `elblasy_one_bridge` (Odoo addon, JSON-RPC controllers calling the ORM) -> Odoo.
The browser never talks to Odoo; Odoo credentials never leave the backend vault.
Bridge auth: a dedicated Odoo service user + API key per connection, stored Fernet-encrypted. Bridge re-checks permissions with Odoo ACLs and exposes only allowlisted operations (no generic model access).
Version differences live in `bridge/adapters/v18.py`, `v19.py`.

## 5. Monorepo
As proposed in the prompt; created: `apps/{web,desktop}`, `services/api`, `odoo_addons/elblasy_one_bridge`, `packages/*`, `tests/{integration,e2e}`, `infrastructure`, `docs/adr`.

## 6. Initial platform DB schema (PostgreSQL, Alembic) — design
- `tenants(id, name)`; `users(id, tenant_id, email, password_hash, role, active, mfa…)`
- `odoo_connections(id, tenant_id, name, base_url, odoo_version, status, company_id, secret_ciphertext, capability_manifest jsonb, manifest_fetched_at, last_health_ok_at, last_verified_at, compatibility_status)`
- `connection_user_grants(user_id, connection_id, company_ids)`
- `operations(id, tenant_id, connection_id, type, idempotency_key, request_fingerprint, actor_id, status, odoo_refs jsonb, safe_error, verification jsonb, created_at, updated_at)` with UNIQUE(tenant_id, connection_id, type, idempotency_key)
- `setup_plans(id, connection_id, template_id, template_version, mode, plan jsonb, status, approved_by, approved_at)`; `setup_plan_steps(plan_id, seq, op_id, status, odoo_ids)`
- `audit_events(id, ts, tenant_id, actor_id, action, target, before, after, approval_ref, outcome, correlation_id)` — append-only
- `approvals(id, operation_id, requested_by, decided_by, decision, reason)`
- `ui_preferences(user_id, key, value)`
No balances or stock quantities are stored.

## 7. Security risks (top)
SSRF via connection URL (guard implemented + tested); credential theft (vault implemented; key management for prod undecided); cross-tenant/company access; retry-induced duplicate sales/payments; frontend-only authorization; desktop client assumed trusted; bridge over-exposure of ORM; stack-trace leakage (handler implemented); DNS rebinding (guard returns validated IPs; the HTTP client must pin them — **not yet implemented**).

## 8. MVP backlog (priority order)
1. Auth + RBAC + tenants (JWT/session, argon2) 2. Alembic schema above 3. Connection CRUD + vault + health 4. Bridge skeleton: `/elblasy/v1/capabilities`, version, modules (read-only) 5. Readiness engine (read-only findings) 6. Setup plan generation + review UI 7. Web shell (Today/Sales/Inventory/Money/Settings, AR/EN RTL) 8. Products & stock read 9. Sales via Odoo native POS session/orders with operation tracking + verification 10. Setup execution (Phase 4) 11. Tauri shell.

## 9. Testing strategy
Pytest unit/API; integration suite parameterised over real Odoo 18 and 19 containers (docker compose in `infrastructure/docker`), using throwaway databases only; Playwright for e2e; mocked-Odoo tests never count toward integration claims.

## 10. Decisions needing your approval
1. **Auth model**: first-party email+password (argon2, JWT in httpOnly cookie) vs external IdP. *Assumed: first-party.*
2. **POS strategy**: drive Odoo's native `pos.order`/session through the bridge (recommended) vs `sale.order` + invoice + payment flow for non-POS sales. Needs a spike on 18/19.
3. **Multi-tenant model**: shared DB with `tenant_id` (assumed) vs DB per tenant.
4. **Secret key management in production**: env-supplied Fernet keys (current) vs KMS/Vault.
5. **Which Odoo edition** (Community vs Enterprise) is the target — the local containers look like Community.
6. May I use the local Odoo 18/19 containers (read-only discovery first, then throwaway DBs for write tests)? I won't touch existing databases without your go-ahead.

## 11. Risk register (short)
| Risk | Mitigation |
|---|---|
| POS semantics differ 18 vs 19 | adapters + per-version integration tests |
| Tauri build deps missing | verify in Phase 5 |
| Python 3.14 dep wheels | pinned >=3.13, tests pass on 3.14 |
| Scope explosion | phase gates, no phase skipped |

## Update — decisions & first live verification (2026-10-19)
User delegated all open decisions (defaults above adopted) and authorised use of the local Odoo containers as test targets.
- Test databases created (throwaway): `elblasy_t18` on Odoo 18.0 (:8018), `elblasy_t19` on Odoo 19.0 (:8019); both have web_enterprise, plus sale_management, purchase, stock_account, point_of_sale and `elblasy_one_bridge` installed. Pre-existing DBs (demo, man, test, test-blank, impa) were not touched.
- Verified live on both: `elblasy.bridge.ping` / `capabilities` (contract v1), version detection, wrong-credential rejection. See `services/api/tests/integration`.
- Findings: Odoo 19 deprecates /xmlrpc (removal in 22) -> swap transport to /json/2 before then. Both containers ship enterprise addons, so edition is detected by installed `web_enterprise`, not version string. Odoo 19 autoreloads on addon copy (resets in-flight RPC); Odoo 18 needed a container restart.
- Dev deploy of the addon = copy `odoo_addons/elblasy_one_bridge` into `/opt/odoo-18-one/addons` and `/opt/odoo-19/addons` (19 manifest version `19.0.*`).
