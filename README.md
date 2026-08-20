# Veggie Prep

Django web app plus a local-first native Android app for tracking household
groceries and suggesting meals from what is already on hand.

## Layout

- `config/` — Django project (settings, WSGI/ASGI, root URLs)
  - `config/settings.py` — environment-driven production-shaped settings
  - `config/settings_test.py` — test settings (in-memory SQLite)
- `requirements.txt` — runtime dependencies
- `android/` — native Android app; pantry and meal history stay on the phone

## Android app

The Android app does not require an account or the Django backend. Its pantry
uses an on-device SQLite ledger, generated meals are stored locally, cloud
backup is disabled, and API keys are encrypted with Android Keystore.

The current Android feature set includes:

- an offline catalog of 450+ household foods with visual tiles, breads and
  flatbreads, eggs and proteins, global and Indian regional aliases, storage
  defaults, and suggested shelf life;
- editable pantry expiry dates, including the ability to clear an unknown date;
- a dedicated Snacks section backed by the same local pantry inventory;
- expiry-first meal planning that excludes expired food and requires the
  earliest-expiring safe item in every saved suggestion;
- deterministic reconciliation of model quantities against real pantry lots;
- a consolidated shopping list for ingredients a meal still needs; and
- atomic **Cook & deduct** confirmation that rechecks and consumes the matched
  pantry quantities before marking a meal cooked.

See the live Android 16 emulator walkthrough in the
[Android screenshot gallery](docs/screenshots/android/README.md).

Meal generation is selectable in the app's **AI Choice** screen:

- **Gemini Nano** through Android's on-device ML Kit Prompt API, when supported
  by the phone.
- **Imported on-device model** in `.litertlm` format, including compatible
  Gemma models. The app tries GPU acceleration and falls back to CPU.
- **OpenAI-compatible API**, including a local vLLM/DGX address, Tailscale IP,
  or an HTTPS provider. Public hosts must use HTTPS; plain HTTP is accepted
  only for private LAN, `.local`, loopback, and Tailscale addresses.

No model file or API key is committed. Large on-device models are imported by
the user and copied to the app's private storage.

Build the development APK with Android Studio or:

```bash
cd android
./gradlew testDebugUnitTest lintDebug assembleDebug connectedDebugAndroidTest
```

The project targets Android 16 (API 36), has a minimum of Android 8 (API 26),
and supports release signing exclusively through the
`VEGGIE_PREP_KEYSTORE*` environment variables in `android/app/build.gradle.kts`.

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
