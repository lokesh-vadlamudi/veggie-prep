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

## Tests

```bash
.venv/bin/python manage.py test
```

Runs the full project test suite (SQLite in-memory, no PostgreSQL needed).

## Status

Foundation slice 1: project scaffold, DRF wiring, environment-based settings,
test tooling. Models (Household, Product, StockLot, InventoryEvent), the
inventory service layer, authentication flows, and the API surface are
deferred to later slices.
