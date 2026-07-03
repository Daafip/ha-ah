# Design decisions — Albert Heijn koopzegels integration

Record of the choices made while implementing [the plan](../albert-heijn-koopzegels-plan.md),
including where and why the implementation deviates from it. Written at `v0.1.0` (2026-07-03).

## Tooling: uv instead of pixi

The plan (§5) sketched a pixi dev environment, but the repo was instantiated from HKV's
**uv** package template, with uv-based CI workflows and a lockfile already in place.
Rewriting that to pixi would have replaced working infrastructure for no functional gain,
so the dev environment is uv (`uv sync`, `uv run pytest`). The plan's `requirements_test.txt`
fallback was dropped for the same reason — CI installs from `uv.lock`.

## GraphQL discovery: schema dump, confirmed live

The exact koopzegels query was the plan's big unknown (§0, Phase 1). Instead of a mitmproxy
capture, the fields were taken from the `gwillem/appie-go` schema dump
(`doc/graphql-schema-20260118.md`):

- Query root: `purchaseStampBalance` → `points { totalPoints currentBookletPoints fullBooklets }`,
  `money { invested interest payout }` (each a `Money { amount }`),
  `constants { fullBookletTarget { points } }`
- `member { id }` for a stable account identifier

Both queries were **verified against the live API on 2026-07-03** with a real account via
`scripts/discover_koopzegels.py`. Everything schema-dependent lives in two marked places —
the query constants in `const.py` and `parse_koopzegels()` in `api.py` — so a schema change
is a one-file fix (per the plan's design requirement).

## State unit: euro payout value (open decision 1)

The sensor state is `money.payout.amount` — what the balance is actually worth, including
the booklet bonus — because that is the headline number in the app. Raw stamp count,
booklet progress, invested amount, and interest are attributes. `device_class = monetary`,
`state_class = total`, unit `EUR`.

The booklet target (490) is read from `constants.fullBookletTarget.points` when present and
falls back to a constant, so `stamps_until_next_booklet` keeps working if AH ever changes
the target.

## Domain name: `albert_heijn` (open decision 2)

Kept the plan's default. No other AH integration runs in the target HA instance, so there
is no clash to avoid, and the generic name leaves room for later sensors (bonus box,
spending, deliveries) under one domain.

## Auth: paste-the-code + persisted refresh token (open decision 3)

- **Login** is the manual authorize-URL flow: the user logs in at `login.ah.nl` and pastes
  the resulting `appie://login-exit?code=...` redirect (raw code also accepted — the flow
  parses either). Programmatic username/password login was rejected per the plan: the login
  page has bot protection and changes frequently.
- **Only the refresh token is stored**, in the config entry (encrypted at rest by HA).
  AH rotates the refresh token on every refresh, so the client fires a callback on rotation
  and `__init__.py` persists the new token back into the entry — otherwise a restart after
  ~2 h would need reauth.
- Access tokens live ~2 h; the client refreshes proactively when within 60 s of expiry,
  guarded by an `asyncio.Lock` so concurrent calls don't double-refresh.
- On auth failure the coordinator raises `ConfigEntryAuthFailed`, which triggers HA's
  standard reauth flow. Reauth verifies the member id matches the existing entry and aborts
  with `wrong_account` if someone logs in with a different account.

## Unique ID: AH member id via GraphQL

The plan suggested deriving the unique id "from the token/profile". The access token is not
a self-describing JWT, so the config flow does an extra `member { id }` GraphQL call after
the code exchange. That id (e.g. `59810852`) is the config-entry `unique_id` (duplicate
prevention) and prefixes the sensor's `unique_id` (`<member_id>_koopzegels`), and identifies
the `DeviceInfo` so future sensors group under one "Albert Heijn" device.

## Poll interval: fixed 6 h (open decision 4)

Koopzegels only change when you shop, and the API is unofficial — poll gently. 6 h fixed
for v0.1.0; an options-flow setting is planned for v0.2.0 (plan Phase 3). Token refresh is
independent of the poll (it happens lazily before any data call).

## Error model

Two exception types in `api.py`, mapped once in the coordinator:

| API situation | Exception | Coordinator behaviour |
|---|---|---|
| 400/401/403 on token endpoints, 401/403 on GraphQL | `AhAuthError` | `ConfigEntryAuthFailed` → reauth flow |
| 5xx, timeouts, connection errors, GraphQL `errors`, unparsable payloads | `AhApiError` | `UpdateFailed` → entity unavailable, retry next cycle |

`AhAuthError` subclasses `AhApiError`, so callers that don't care about the distinction can
catch one type.

## HTTP details

- HA's shared aiohttp session (`async_get_clientsession`); `requirements: []` in the
  manifest — nothing to install at runtime.
- Headers mimic the mobile app (`User-Agent: Appie/…`, `X-Application: AHWEBSHOP`, and the
  `x-apollo-operation-name`/`-type` headers on GraphQL calls, per the appie-go docs).
  `Content-Type` is left to aiohttp's `json=` parameter to avoid duplicate-header issues.
- 30 s timeout on every request via `asyncio.timeout`.

## Testing

`pytest-homeassistant-custom-component` + `aioresponses`, as planned (§6). 33 tests, 95%
coverage on the integration package. Choices within that:

- API-client tests mock HTTP with `aioresponses` against **anonymised fixtures**
  (`tests/fixtures/`); flow/init/sensor tests patch `AhApiClient` with `AsyncMock` instead —
  they test HA wiring, not HTTP.
- Tests locate the entity through the entity registry by `unique_id` rather than hardcoding
  an entity id, so they don't depend on translation loading.
- The proactive-refresh test exploits `aioresponses`' single-use mocks: if the client
  refreshed more than once, the second refresh finds no mock and the test fails.
- The real-API smoke test stays manual (`scripts/discover_koopzegels.py`) — no credentials
  in the repo or CI, per the plan's privacy rules (§9).

## CI

Kept the template's uv-based `tests.yaml` and `pre-commit.yml`; added `validate.yml` with
hassfest + HACS validation (plan §7). The template's Quarto-docs and PyPI-publish workflows
were removed — this is not a PyPI package and has no rendered docs site.

## Not done yet (deliberately)

- Options flow for the poll interval, redacted diagnostics, friendlier errors → v0.2.0
  (plan Phase 3).
- More sensors (bonus box, spending, next delivery) → Phase 4; the client/coordinator/device
  are structured for it.
- HACS default-store submission — custom-repository install only for now.
- `.env` / `.env.template` (username/password) are unused: programmatic login was rejected.
  `.env` is gitignored so credentials can never be committed.
