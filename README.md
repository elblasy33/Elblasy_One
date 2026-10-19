# Elblasy One

Simplified business-management platform on top of **Odoo Community** (18, 19). Odoo stays the
source of truth for accounting, stock and posted documents. See `docs/PHASE0_ASSESSMENT.md`.

```
Web / Desktop -> FastAPI (services/api) -> elblasy_one_bridge (Odoo addon) -> Odoo ORM
```
The browser never talks to Odoo; Odoo credentials live only encrypted in the platform DB.

## Run locally (API)
```bash
docker compose -f infrastructure/docker/compose.platform.yml up -d          # platform Postgres :5433
docker compose -f infrastructure/docker/compose.odoo-community.yml up -d    # Odoo CE 18 :8118, 19 :8119
cd services/api && cp .env.example .env   # fill ELBLASY_JWT_SECRET and ELBLASY_SECRET_KEYS
uv sync && uv run alembic upgrade head && uv run uvicorn elblasy_api.main:app --reload
```
### Prepare the Odoo CE test databases (one-time)
Create DBs `ce18` / `ce19` (master password `dev-master`, admin/admin, no demo) and install
`elblasy_one_bridge`, `sale_management`, `purchase`, `stock_account`, `point_of_sale`.
(Scripted setup is a TODO; see Known limitations.)

## Run the web app
```bash
cd services/api && uv run uvicorn elblasy_api.main:app --port 8000      # API
cd apps/web && pnpm install && ELBLASY_API_URL=http://localhost:8000 pnpm dev   # http://localhost:3000
```
The browser only talks to the Next.js origin; `/api/*` is proxied to the API (same-site session cookie, Odoo never reachable from the client).
Arabic (RTL) is the default; English via the language switch. Checks: `pnpm typecheck && pnpm lint`.
End-to-end (real browser + API + Postgres + Odoo CE 18 template copy): `cd apps/web && pnpm exec playwright test`.

## Tests
`cd services/api && uv run pytest` — uses a throwaway Postgres DB built by the Alembic migrations;
`tests/integration` talks to the real Odoo CE containers and skips when they are unreachable.
Lint/types: `uv run ruff check . && uv run mypy src`.

## Known limitations
- Rate limiter is in-process (single worker). Move to a shared store before scaling out.
- DNS-rebinding: URLs are validated at use, but the HTTP call does not yet pin the validated IP.
- Odoo transport uses /xmlrpc (deprecated in 19, removed in 22) — swap to /json/2.
- Test-DB provisioning for Odoo is manual (see above).
- Web UI covers sign-up, connection, setup wizard, plan review/execution, Today. Sales/Inventory/Money screens are honest placeholders. No desktop app yet.
- UI strings from the API (plan impact/notes) are localised client-side by key; unknown keys fall back to English.
