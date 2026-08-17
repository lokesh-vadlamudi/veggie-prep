# Veggie Prep

Django + Django REST Framework backend for tracking household groceries and
suggesting meals from what is already on hand. The API is designed to be
consumed by future Android/iOS clients.

## Layout

- `config/` — Django project (settings, WSGI/ASGI, root URLs)
  - `config/settings.py` — environment-driven production-shaped settings
  - `config/settings_test.py` — test settings (in-memory SQLite)
- `requirements.txt` — runtime dependencies

## Setup

Requires Python 3.10+ (developed against 3.12).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Copy `.env.example` to `.env` (or export the variables in your shell) and
point it at a PostgreSQL instance:

```bash
export DJANGO_SECRET_KEY=...
export DB_NAME=veggie_prep
export DB_USER=veggie_prep
export DB_PASSWORD=...
export DB_HOST=localhost
export DB_PORT=5432
```

No secrets are stored in the repository. When `DJANGO_DEBUG=false`,
`DJANGO_SECRET_KEY` is mandatory; when `DJANGO_DEBUG=true`, an insecure
fallback key is used for local development.

## Database

Production settings use PostgreSQL (`django.db.backends.postgresql`) via
`psycopg` (v3). All connection parameters come from `DB_*` environment
variables with local defaults suitable for a `veggie_prep` database on
`localhost:5432`.

### SQLite test override

The test suite never requires PostgreSQL: running `manage.py test`
automatically selects `config.settings_test`, which replaces the database
with in-memory SQLite. You can also run any management command against test
settings explicitly:

```bash
DJANGO_SETTINGS_MODULE=config.settings_test .venv/bin/python manage.py check
```

## AI meal suggestions

The "Suggest meals" page asks a configured provider (any OpenAI-compatible
chat-completions endpoint, e.g. a local vLLM server) to plan one meal from
your household's positive-balance stock, prioritizing lots that expire within
two days. Suggestions are read-only: they never change inventory, and each
one stores a bounded, structured record of the provider's proposal plus a
deterministic reconciliation against your lots (owned vs. missing quantity,
which expiring lots are rescued). No prompt/response text and no credentials
are stored.

Configuration is server-side only (see `.env.example`); nothing about the
provider is stored in the database and no secret ever reaches the UI:

| Variable       | Required | Meaning                                                       |
| -------------- | :------: | ------------------------------------------------------------- |
| `AI_BASE_URL`  | yes*     | Provider base URL; empty/missing disables the feature.        |
| `AI_MODEL`     | yes*     | Model identifier to request.                                  |
| `AI_API_KEY`   | no       | Sent as `Authorization: Bearer` when your endpoint needs one. |
| `AI_TIMEOUT`   | no       | Socket timeout in seconds (default 30, capped at 120).        |

\* required only when the feature is enabled.

The provider must reply with a single JSON object (title, servings,
time_minutes, steps, optional substitutions/safety_note, rationale, and an
ingredients list using the app's units — `count, each, g, kg, ml, l`).
Responses are size-capped, and malformed JSON, schema violations, unsupported
units, or invalid quantities produce a recoverable error on the form with no
partial suggestion and no inventory change.

## API (v1)

Versioned inventory API under `/api/v1/`, session-authenticated with CSRF
enforced (same cookies as the web app — POST the `X-CSRFToken` header from
the `csrftoken` cookie, as a browser does).

All lots belong to the requester's household; lots in other households or
with unknown UUIDs return a stable `404` envelope. Quantities are exact
three-decimal strings on the wire (input accepts finite decimals with at
most 3 places; booleans, non-finite values, and imprecise values are
rejected with `400`).

| Method & path | Purpose |
| --- | --- |
| `GET /api/v1/inventory/lots/` | Paginated lots. Filters: `location`, `expiry_group`, `include_empty=true\|false` (default hides zero-balance lots), `page`, `page_size`. |
| `POST /api/v1/inventory/lots/` | Add stock: `product_name`, `quantity`, `unit`, optional `location`, `purchased_at`, `expires_on`, `note`. `201` with `Location`. |
| `GET /api/v1/inventory/lots/<uuid>/` | Lot detail with ledger-derived `balance`. |
| `GET /api/v1/inventory/lots/<uuid>/events/` | Paginated ledger history (`quantity` absolute, `signed_quantity` ledger-signed). |
| `POST /api/v1/inventory/lots/<uuid>/consume/` | `quantity` (positive), optional `note`. `409 insufficient_stock` on over-consume. |
| `POST /api/v1/inventory/lots/<uuid>/discard/` | `quantity` (positive), optional `note`. |
| `POST /api/v1/inventory/lots/<uuid>/correct/` | `observed_balance` (≥ 0), required `reason`. `409 no_op_correction` when unchanged. |
| `GET /api/v1/meals/` | Paginated household meal history, newest first (`-created_at, -id`). Optional exact `status` filter: `suggested`, `cooked`, `rejected`. |
| `GET /api/v1/meals/<uuid>/` | Full immutable detail: proposal fields plus ordered ingredients with safe allocation entries only (`lot_id`, exact 3dp `quantity`, `unit`, per-lot `rescued`, `expires_on`). Malformed allocation entries are omitted; foreign-household lots are never exposed. |
| `POST /api/v1/meals/generate/` | Generate one suggestion: `servings` (1–50), `max_minutes` (5–600), optional `dietary_exclusions` (list, ≤ 20), `preference`, `include_expired`. Calls the provider exactly once. `201` with `Location`; `503 ai_unavailable` on config/network/HTTP failure; `422 invalid_provider_output` on malformed/oversized provider output. Zero writes on any failure. |
| `POST /api/v1/meals/<uuid>/cook/` | No body. Revalidates the snapshot against live balances and atomically consumes the allocated lots, records the cook, and marks the suggestion `cooked` (200 with refreshed status and `cooked_at`). `409 already_cooked` on duplicate; `409 cook_conflict` on rejected/stale/insufficient/malformed allocations with full rollback; foreign/unknown UUIDs are `404`. |

Errors are a stable envelope: `{"error": {"code": ..., "message": ..., "fields": {...}}}` with codes `not_authenticated`, `csrf_failed`, `not_found`, `validation_error`, `insufficient_stock`, `no_op_correction`, `service_error`, `method_not_allowed`, `parse_error`, `unsupported_media_type`, `ai_unavailable`, `invalid_provider_output`, `already_cooked`, `cook_conflict`, `internal_error`. All writes go through the transactional service layer only.

## Tests

```bash
.venv/bin/python manage.py test
```

Runs the full project test suite (SQLite in-memory, no PostgreSQL needed; no
network calls — the provider is always faked in tests).

## Status

Implemented: models (Household, Product, StockLot, InventoryEvent,
MealSuggestion, MealIngredient), the transactional inventory service layer,
authenticated web workflow (dashboard, add/consume/discard/correct,
auth/logout), and AI meal suggestion generation with deterministic
reconciliation (form, result, history; household-scoped 404s; provider
failure taxonomy), the versioned DRF inventory API
(`inventory/api/`, `/api/v1/inventory/lots/...`), and the versioned meal API
(`GET /api/v1/meals/`, `GET /api/v1/meals/<uuid>/`,
`POST /api/v1/meals/generate/`, `POST /api/v1/meals/<uuid>/cook/` with
exactly-once cook confirmation and full rollback on conflict). Deferred:
provider key/ops configuration.
