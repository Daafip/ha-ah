# Plan — Albert Heijn `koopzegels` sensor (HACS custom integration)

**Goal:** a Home Assistant custom integration, installable via HACS, that exposes the
balance of your AH digital *koopzegels* as a sensor. Built to extend later (bonus box,
spending, deliveries), but Phase 1 ships exactly one sensor.

**Domain:** `albert_heijn` (rename to something unique like `ah_koopzegels` only if you
also run another AH integration in the same HA instance, to avoid a domain clash).

---

## 0. Context & constraints (read first)

- **Unofficial API.** AH has no public developer API. This rides the mobile-app API,
  which changes without notice. Treat breakage as expected, poll gently, and keep this a
  personal-use project.
- **Auth is REST, data is GraphQL.** The token endpoints (`mobile-auth/...`) still work.
  Account data has largely migrated to `POST https://api.ah.nl/graphql`. The old
  `mobile-services/v1/...` REST routes are being retired.
- **Field discovery needed.** The exact GraphQL query/field for koopzegels is *not* in
  the jabbink gist. Authoritative reference: `gwillem/appie-go`
  (`doc/graphql-schema-*.md`). Introspection on the live endpoint was recently disabled,
  so use the dumped schema or a mitmproxy capture (see Phase 1).
- **Prior art to copy structure from:**
  - `dpvdberg/ha-albertheijn` — config flow, token storage/refresh, coordinator pattern.
  - `jensderooij1/ahha` — receipt/spending sensors.

---

## 1. How AH access works

### Tokens (REST — confirmed)
All requests send: `Content-Type: application/json`, `User-Agent: Appie/8.x ...`,
`X-Application: AHWEBSHOP`, and (when authenticated) `Authorization: Bearer <access_token>`.

1. **Anonymous token** (not needed for koopzegels, but useful for unauthenticated calls):
   `POST https://api.ah.nl/mobile-auth/v1/auth/token/anonymous` → `{"clientId":"appie"}`
2. **User login** (one-time, manual):
   open `https://login.ah.nl/secure/oauth/authorize?client_id=appie&redirect_uri=appie://login-exit&response_type=code`
   in a browser, log in, and grab `CODE` from the `appie://login-exit?code=CODE` redirect.
3. **Exchange code → tokens:**
   `POST https://api.ah.nl/mobile-auth/v1/auth/token` → `{"clientId":"appie","code":"CODE"}`
   returns `access_token`, `refresh_token`, `expires_in` (~7199s).
4. **Refresh:**
   `POST https://api.ah.nl/mobile-auth/v1/auth/token/refresh` → `{"clientId":"appie","refreshToken":"..."}`

We persist the **refresh_token**, refresh proactively (token lives ~2h), and on refresh
failure trigger HA's reauth flow.

### Koopzegels data (GraphQL — to be confirmed in Phase 1)
`POST https://api.ah.nl/graphql` with the bearer token and a query selecting the
koopzegels/savings field. Final query string is filled in after discovery. Design the
client so the query lives in one constant and the response parsing is isolated.

---

## 2. Architecture

```
config_flow  ──(stores refresh_token)──►  ConfigEntry
                                              │
__init__.async_setup_entry  ──creates──►  AhApiClient  ──►  AhCoordinator (DataUpdateCoordinator)
                                                                   │ polls every ~6h
                                                                   ▼
                                                            KoopzegelsSensor
```

- `AhApiClient` — thin async wrapper over the AH endpoints (token + GraphQL). Owns token
  state, raises typed exceptions. Uses HA's shared aiohttp session
  (`homeassistant.helpers.aiohttp_client.async_get_clientsession`).
- `AhCoordinator` — calls the client, normalises into a small dataclass, handles auth
  failure by raising `ConfigEntryAuthFailed` (HA shows reauth).
- `KoopzegelsSensor` — `CoordinatorEntity` reading from coordinator data.

---

## 3. Repository structure

```
ha-albert-heijn/
├── custom_components/
│   └── albert_heijn/
│       ├── __init__.py          # async_setup_entry / async_unload_entry
│       ├── manifest.json
│       ├── const.py             # DOMAIN, endpoints, defaults
│       ├── api.py               # AhApiClient + exceptions
│       ├── coordinator.py       # AhCoordinator
│       ├── config_flow.py       # user + reauth flows
│       ├── sensor.py            # KoopzegelsSensor
│       ├── strings.json
│       └── translations/
│           ├── en.json
│           └── nl.json
├── tests/
│   ├── conftest.py
│   ├── const.py                 # shared test constants
│   ├── test_api.py
│   ├── test_config_flow.py
│   ├── test_coordinator.py
│   ├── test_sensor.py
│   ├── test_init.py
│   └── fixtures/
│       ├── token.json           # ANONYMISED
│       └── koopzegels.json      # ANONYMISED
├── .github/workflows/
│   ├── validate.yml             # hassfest + HACS validation
│   └── test.yml                 # pytest matrix
├── hacs.json
├── pixi.toml
├── pyproject.toml               # ruff + pytest config
├── requirements_test.txt        # fallback if not using pixi for CI
├── README.md
├── CHANGELOG.md
├── LICENSE
└── .gitignore
```

### Key file contents (sketch)

`manifest.json`
```json
{
  "domain": "albert_heijn",
  "name": "Albert Heijn",
  "version": "0.1.0",
  "documentation": "https://github.com/<you>/ha-albert-heijn",
  "issue_tracker": "https://github.com/<you>/ha-albert-heijn/issues",
  "codeowners": ["@<you>"],
  "config_flow": true,
  "iot_class": "cloud_polling",
  "integration_type": "service",
  "requirements": []
}
```
- `version` **must** match the release git tag — HACS reads it from here.
- Prefer the stdlib + the shared aiohttp session, so `requirements` stays empty (nothing
  to install at runtime). Add a pinned dep only if you genuinely need one.

`hacs.json`
```json
{
  "name": "Albert Heijn",
  "render_readme": true,
  "homeassistant": "2024.12.0"
}
```
Installed as a **custom repository**, category *Integration*. (Default-store submission is
a later, optional goal — see Phase 4.)

---

## 4. Component design notes

**`config_flow.py`**
- `user` step: a single text field where you paste either the raw `CODE` or the full
  `appie://login-exit?code=...` URL. Validate by exchanging it for tokens immediately
  (it's single-use and short-lived). On success, store the `refresh_token` in the entry
  and set a stable `unique_id` (e.g. the AH member id from the token/profile) to prevent
  duplicate entries.
- `reauth` step: same field, re-runs the exchange and updates the stored token.
- Show the authorize URL in the step description so it's one click away.
- *Later option:* programmatic username/password login. Deprioritised — the login page
  has bot protection and changes; the paste-the-code flow is far more robust.

**`api.py`**
- Methods: `async_exchange_code(code)`, `async_refresh()`, `async_get_koopzegels()`.
- Token handling: refresh when `expires_at` is within a margin (e.g. 60s) before any data
  call.
- Exceptions: `AhAuthError` (401 / bad refresh → maps to `ConfigEntryAuthFailed`),
  `AhApiError` (5xx / GraphQL errors / timeouts → coordinator marks entity unavailable).
- Keep the GraphQL query string and the response→dataclass mapping in clearly marked
  spots so a schema change is a one-line edit.

**`coordinator.py`**
- `update_interval = timedelta(hours=6)` default (koopzegels only move when you shop;
  token refresh is independent of this). Expose as an options-flow setting later.
- `_async_update_data()` calls the client, returns a `KoopzegelsData` dataclass.

**`sensor.py`** — `KoopzegelsSensor`
- `state` = euro value of saved koopzegels (the headline number).
- `device_class = MONETARY`, `native_unit_of_measurement = "EUR"`,
  `state_class = TOTAL`.
- Attributes (depending on what the query returns): `stamp_count`,
  `full_books`, `stamps_until_next_book` (relative to the 490 threshold), `last_updated`.
- `unique_id` derived from member id + `_koopzegels`; attach to a `DeviceInfo` named
  "Albert Heijn" so future sensors group under one device.
- Returns unavailable cleanly when the coordinator has no data.

*(Finalise state vs. attributes once the discovery step shows the real fields — the build
is structured so this is a small change, not a rewrite.)*

---

## 5. Dev environment (Pixi)

`pixi.toml` (sketch)
```toml
[project]
name = "ha-albert-heijn"
channels = ["conda-forge"]
platforms = ["linux-64", "win-64", "osx-arm64"]

[dependencies]
python = "3.13.*"

[pypi-dependencies]
homeassistant = "*"
pytest-homeassistant-custom-component = "*"
aioresponses = "*"
pytest = "*"
pytest-cov = "*"
pytest-asyncio = "*"
ruff = "*"

[tasks]
test = "pytest -q --cov=custom_components/albert_heijn --cov-report=term-missing"
lint = "ruff check ."
format = "ruff format ."
```
Pin `homeassistant` and `pytest-homeassistant-custom-component` to matching versions —
the test helper tracks specific HA releases.

---

## 6. Testing strategy (local — this is the part you asked to nail down)

Foundation: **`pytest-homeassistant-custom-component`**, which provides the `hass`
fixture, `MockConfigEntry`, and the plumbing to load a custom component in tests. HTTP is
mocked with **`aioresponses`** (aiohttp) against **anonymised** JSON fixtures — never real
tokens, member ids, names, or transaction ids.

Run everything with `pixi run test`. Target ~90%+ on the integration package.

Planned tests:

- **`test_api.py`**
  - token exchange parses `access_token`/`refresh_token`/`expires_in`
  - refresh updates the stored token + expiry
  - koopzegels GraphQL response parses into the dataclass (fixture-driven)
  - `401` → `AhAuthError`; `500` / GraphQL `errors` / timeout → `AhApiError`
  - proactive refresh fires when the token is near expiry, not on every call

- **`test_config_flow.py`**
  - happy path: valid code → entry created, refresh_token stored, correct `unique_id`
  - accepts both raw `CODE` and full `appie://...` URL
  - invalid/expired code → form error, no entry
  - duplicate prevented (same `unique_id` → `abort` with `already_configured`)
  - reauth: updates token on an existing entry

- **`test_coordinator.py`**
  - successful update returns expected data
  - `AhAuthError` → `ConfigEntryAuthFailed` (reauth triggered)
  - `AhApiError` → `UpdateFailed`

- **`test_sensor.py`**
  - after a coordinator refresh, state + attributes match the fixture
  - api failure → entity `unavailable`
  - `unique_id` / `device_class` / `state_class` are correct

- **`test_init.py`**
  - `async_setup_entry` creates the coordinator and forwards to `sensor`
  - `async_unload_entry` cleans up

Manual smoke test before the first release: install via HACS custom repo into a dev HA,
add the integration with a real code, confirm the sensor populates. (Keep this manual —
don't put real credentials in the repo.)

---

## 7. CI (GitHub Actions)

- **`validate.yml`**
  - `home-assistant/actions/hassfest` (manifest correctness)
  - `hacs/action` with `category: integration` (HACS-readiness)
- **`test.yml`**
  - `pixi run test` (or pip + `requirements_test.txt`) on a small matrix of HA versions
  - `ruff check`
- Run on push + PR. Branch protection: green CI before merge.

---

## 8. Changelog & versioning

- **`CHANGELOG.md`** in *Keep a Changelog* format: an `## [Unreleased]` section at top,
  then dated `## [X.Y.Z]` sections, grouped by Added / Changed / Fixed / Removed.
- **SemVer.** While pre-1.0, breaking changes can land in minor bumps, but still note them.
- **Release ritual:** move Unreleased → a new version section, bump `manifest.json`
  `version` to match, tag `vX.Y.Z`, create a GitHub release. HACS surfaces the tag +
  release notes.
- Start manual. Automate later (release-please or towncrier) if it gets tedious.

Initial `CHANGELOG.md`:
```markdown
# Changelog
All notable changes to this project are documented here.
Format: Keep a Changelog. Versioning: SemVer.

## [Unreleased]

## [0.1.0] - YYYY-MM-DD
### Added
- Initial release: `koopzegels` balance sensor with config flow and token refresh.
```

---

## 9. Secrets & privacy (by design)

- Credentials/tokens live only in the HA config entry (encrypted at rest by HA); never in
  the repo, logs, or fixtures.
- Test fixtures are scrubbed: fake tokens, no real member id / name / transaction data.
- If you add a diagnostics download later, use HA's redaction
  (`homeassistant.components.diagnostics.async_redact_data`) for tokens and personal ids.
- Log at debug level without dumping tokens.

---

## 10. Phased roadmap

**Phase 0 — Scaffold**
- [x] Repo skeleton, `hacs.json`, `manifest.json`, empty integration that loads cleanly
- [x] `pixi.toml`, `pyproject.toml` (ruff), `LICENSE`, `README.md`, `CHANGELOG.md`
- [x] CI green (hassfest + HACS + an empty pytest)

**Phase 1 — Auth + discovery**
- [x] `AhApiClient` token methods (anonymous, code exchange, refresh) + tests
- [x] `config_flow` user step (paste code) + reauth + tests
- [x] **Discover the koopzegels GraphQL query** via `gwillem/appie-go` schema dump, or a
      one-off mitmproxy capture of the app's "Mijn koopzegels" screen
- [x] Throwaway script/test proving you can read your real balance

**Phase 2 — Koopzegels sensor (first release)**
- [x] `async_get_koopzegels()` + response mapping + tests
- [x] `AhCoordinator` (6h poll, auth-failure → reauth) + tests
- [x] `KoopzegelsSensor` (monetary, attributes) + tests
- [x] Manual smoke test in dev HA
- [x] Tag `v0.1.0`, write changelog, GitHub release

**Phase 3 — Hardening & polish**
- [x] `nl` + `en` translations, friendly config-flow text
- [x] Options flow (poll interval), redacted diagnostics, better error messages
- [x] `v0.2.0`

**Phase 4 — Optional expansion**
- [x] More sensors (spending, next delivery) reusing the client/coordinator — v0.3.0
      (bonus box skipped: no documented query shape in the schema dump)
- [x] Consider HACS default-repository submission — considered; checklist + prepared
      brand assets in `docs/hacs-default-submission.md` (external PRs remain)

---

## 11. Open decisions to make as you go

1. **State unit:** euro value (recommended headline) vs. raw stamp count — confirm after
   discovery, expose the other as an attribute.
2. **Domain name:** `albert_heijn` vs. a koopzegels-scoped domain (clash avoidance).
3. **Token strategy:** stick with persisted refresh_token + reauth (recommended) vs.
   attempt programmatic login later.
4. **Poll interval default:** 6h is a safe start; tune once you see how often the balance
   actually changes.

---

## 12. Phase 5 — expansion backlog (brainstorm 2026-07-04)

Everything below is confirmed to exist in the `appie-go` schema dump
(`graphql-schema-20260118.md`); exact field shapes still need the discovery-script
treatment before building, like koopzegels got.

### Confirmed endpoints and what they could become

| API surface | Data | Candidate HA surface |
| --- | --- | --- |
| `milesBalance`, `milesTransactions` | Air Miles balance (Int) | Sensor "Air Miles" |
| `groceryList` + `groceryList*` mutations | The AH shopping list | **`todo` entity, two-way sync** |
| `favoriteListV2` + `favoriteList*V2` mutations | Named favorite lists | Second `todo` entity / service |
| `basket` (`summary`, `items`) | Current webshop basket | Sensors: basket total (EUR), item count |
| `bonusPersonalPromotionBundles`, `bonusPromotions` | Personal bonus-box offers | Sensor: offers waiting; attributes list them |
| `bonusActivatePersonalPromotion` (mutation) | Activate an offer | Button "Activate all bonus box offers" |
| `order(id).delivery.trackAndTraceV2.etaBlock` | Live delivery ETA (start/end) | Sensor that tightens the poll on delivery day |
| `orderDeliverySlots` | Bookable slots | Sensor: next available slot |
| `orderFulfillments` (have it) | All upcoming deliveries | **`calendar` entity** with slot windows |
| `orderReport`, `orderReportTotal` | Online-order spending | Extend month-spending to online orders |
| `posReceiptDetails(id)` | Receipt line items | Event/attribute: last receipt products |
| `purchaseStampTransactions` | Koopzegels history | Attribute or event on balance change |
| `purchaseStampSavingGoal` + set/delete mutations | Saving goal (name, amount) | Sensor progress-to-goal; `number` to set it |
| `paymentsGetFullBookletsCount` | Full booklets (Int) | Cross-check for the koopzegels sensor |
| `settlementsTotal` | Refunds owed to you | Sensor "Open settlements" (EUR) |
| `subscriptionPremiumSavingsV2` | Premium savings (`totalSavedAmount`) | Sensor "Saved with Premium" |
| `subscriptionCurrent`, `subscriptionSummary` | Subscription state | Diagnostic sensor |
| `storesSearch`, `storesInformation`, `GetFavoriteStore` | Store opening hours | Binary sensor "favorite store open" + closes-at |
| `products` search | Product prices | Price-tracker sensors for configured product ids |

### Suggested order

1. **5a — Shopping list as `todo` entity.** The standout HA feature: AH list on a
   dashboard, voice-add via assist, check off while shopping. First write-path — needs
   the mutation treated carefully.
2. **5b — Deliveries `calendar` + live ETA sensor.** Calendar from `orderFulfillments`
   (data already fetched); on delivery day poll `trackAndTraceV2` more often.
3. **5c — Bonus box.** Offers-waiting sensor first; the activate-button mutation later.
4. **5d — Koopzegels extras.** Saving-goal progress + `number` entity, transactions.
5. **5e — Money sensors.** Premium savings, settlements, online-order spending,
   Air Miles. Cheap wins, same coordinator pattern.

### Design notes

- **Read-only first.** Mutations (`todo` sync, bonus activation, saving goal) write to a
  live account through an unofficial API — ship behind an options-flow toggle, default
  off, and never retry a mutation blindly.
- **Feature toggles.** One options-flow section per feature group so a broken endpoint
  can be switched off without a release; every fetch stays best-effort like receipts.
- **Poll budget.** Keep the single coordinator, but a delivery-day fast lane (ETA) may
  justify a second, short-lived coordinator only active around a planned slot.
- **Out of scope.** Recipes/cookbook, CMS content, B2B/company, customer-care
  conversations — not home-automation material.
