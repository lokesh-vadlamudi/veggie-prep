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
failure taxonomy). Deferred: cook-confirmation flow for suggestions,
DRF/API exposure, and provider key/ops configuration.
