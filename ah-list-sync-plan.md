# Plan: Two-way sync between Home Assistant shopping list and Albert Heijn "Mijn lijst"

Implementation plan for the `Daafip/ha-ah` repo (HACS custom integration `albert_heijn`).

## Goal

Expose the Albert Heijn shopping list ("Mijn lijst" in the AH app) as a Home Assistant
`todo` entity with full CRUD support, so it can be two-way synced with HA's built-in
shopping list (`todo.shopping_list`):

- Item added in HA → appears as a **free-text item** in the AH list (no product link needed).
- Item deleted or checked off in the AH app → marked **completed** in HA.
- Item checked off in HA → **checked** in the AH app.

Note: the webshop *basket* is NOT the target. The basket mutations require real
`productId`s; free-text notes are a feature of the AH shopping list, which sits next to
the basket in the app. This satisfies the original intent ("just a text note").

## Constraints & repo conventions (follow these)

- Match existing code style: frozen dataclasses for API models, module-level
  `parse_*` functions, `AhApiError`/`AhAuthError`, `_LOGGER.debug` for requests.
- All queries/mutations as constants in `const.py`, response mapping in `api.py`.
- Tooling: `uv sync --locked`, `uv run pytest` (mocked API, no credentials),
  `uv run ruff check .`, `uv run pre-commit run --all-files`. All must pass.
- Tests mock aiohttp responses like the existing suite; add fixtures for every new
  endpoint, including error shapes.
- Update `README.md` (new entity + sync automation example) and `CHANGELOG.md`.
- Keep the polite-polling philosophy: the new list coordinator is separate from the
  6h koopzegels coordinator, default 120 s, configurable via options flow
  (min 60 s). Do not touch the 6h default of the existing coordinator.

## Known API surface (verified against gwillem/appie-go, schema dump Jan 2026)

Base host `https://api.ah.nl`, same Bearer token as existing GraphQL calls.
REST calls additionally need header `X-Application: AHWEBSHOP`.
GraphQL mutations need `x-apollo-operation-type: mutation` (queries stay `query`).

1. **List all shopping lists (REST v3)**
   `GET /mobile-services/lists/v3/lists?productId=1`
   Quirk: `productId` is required but ignored; returns all lists.
   Response items: `{id, description, itemCount, ...}`. The first list is the default
   "Mijn lijst".

2. **Read list items (GraphQL)**
   ```graphql
   query FavoriteListV2($ids: [String!]!) {
     favoriteListV2(ids: $ids) {
       id
       description
       totalSize
       items { id productId quantity }
     }
   }
   ```
   List id must be uppercased in `ids`.
   ⚠️ The `items` selection above is the *known-working minimum*. We also need the
   item's free-text label and checked state. **First implementation step: introspect
   the item type** (see "Step 0") and add the real field names — expected candidates:
   `description`, `strikeThrough` and/or `checked`. Do not guess in committed code.

3. **Add item incl. free text (REST v2)**
   `PATCH /mobile-services/shoppinglist/v2/items`
   ```json
   {"items": [{
     "description": "luiers",
     "quantity": 1,
     "type": "SHOPPABLE",
     "originCode": "PRD",
     "strikeThrough": false
   }]}
   ```
   Omitting `productId` makes it a free-text note. `originCode` and `type` are
   mandatory (generic error otherwise).

4. **Check / uncheck item (REST v3)**
   `PATCH /mobile-services/lists/v3/lists/items/{itemId}` with `{"checked": true}`.

5. **Delete items (GraphQL mutation)**
   ```graphql
   mutation DeleteProductsFromFavoriteList($favoriteListId: String!, $itemIds: [String!]!) {
     favoriteListProductsDeleteV2(id: $favoriteListId, itemIds: $itemIds) {
       status
       errorMessage
     }
   }
   ```
   Success ⇔ `status == "SUCCESS"`.

## Step 0 — schema discovery script (do this before wiring HA code)

Add `scripts/discover_list.py`, modeled on `scripts/discover_koopzegels.py`
(one-time login code, nothing stored):

1. Exchange code → token (reuse `AhApiClient`).
2. `GET` the v3 lists, print them.
3. Run `favoriteListV2` with an *extended* selection set and print the raw JSON.
   Try adding `description`, `strikeThrough`, `checked`, `type` to `items` one at a
   time; GraphQL will error on unknown fields, so bisect until the real names are
   known. Alternatively run a targeted introspection query on the item type.
4. Add a free-text item via the v2 PATCH, re-read, check it off via the v3 PATCH,
   delete it via the mutation — a full round-trip smoke test.

Record the confirmed field names in a comment block at the top of `const.py`'s list
section. All committed queries must use only confirmed fields.

## Step 1 — API layer (`api.py`, `const.py`)

New constants in `const.py`:
- `REST_BASE_URL = "https://api.ah.nl"`
- `LISTS_URL`, `SHOPPINGLIST_ITEMS_URL`, `LIST_ITEM_CHECK_URL` (format string)
- `LIST_ITEMS_OPERATION` / `LIST_ITEMS_QUERY` (favoriteListV2, confirmed fields)
- `LIST_DELETE_OPERATION` / `LIST_DELETE_MUTATION`
- `REST_HEADERS = {**DEFAULT_HEADERS, "X-Application": "AHWEBSHOP"}`

New dataclass:
```python
@dataclass(frozen=True)
class AhListItem:
    item_id: str
    description: str
    checked: bool
    product_id: int | None = None
    quantity: int = 1
```

New `AhApiClient` methods (all raising `AhApiError`/`AhAuthError` consistently):
- `async_get_default_list_id() -> str` — v3 lists, first entry; cache on the client.
- `async_get_list_items(list_id) -> list[AhListItem]` — GraphQL + `parse_list_items`.
- `async_add_free_text_item(description, quantity=1) -> None` — v2 PATCH.
- `async_set_item_checked(item_id, checked) -> None` — v3 PATCH.
- `async_delete_items(list_id, item_ids) -> None` — mutation, assert SUCCESS.
- Internal helper `_async_rest(method, url, payload)` that mirrors `_async_graphql`:
  ensure token, merge `REST_HEADERS` + Authorization, map 401/403 → `AhAuthError`,
  timeout handling via the existing `_async_post` pattern (extend it to support
  PATCH/GET or add a generic `_async_request`).

Unit tests: parse function edge cases (missing fields, nulls), auth-error mapping,
free-text payload shape (assert no `productId` key when None).

## Step 2 — list coordinator (`coordinator.py` or new module)

- `AhListCoordinator(DataUpdateCoordinator[list[AhListItem]])`, own update interval
  from options (`CONF_LIST_SCAN_INTERVAL`, default 120 s).
- On each refresh: fetch items for the cached default list id; on `AhAuthError`
  raise `ConfigEntryAuthFailed` (same reauth path as the existing coordinator).
- Keep the previous snapshot on the coordinator (`self.previous_items`) so the todo
  entity and any diff logic can distinguish "deleted upstream" from "first load".
  Set `previous_items = None` on startup and skip diffing until the second refresh.

## Step 3 — `todo.py` platform

Add `Platform.TODO` to `PLATFORMS` in `__init__.py`.

`AhShoppingListTodoEntity(CoordinatorEntity, TodoListEntity)`:
- `supported_features = CREATE_TODO_ITEM | DELETE_TODO_ITEM | UPDATE_TODO_ITEM`
  (UPDATE covers status changes; renaming can raise `HomeAssistantError("not supported")`
  unless the API turns out to support it — check in Step 0).
- `todo_items`: map `AhListItem` → `TodoItem(uid=item_id, summary=description,
  status=COMPLETED if checked else NEEDS_ACTION)`.
- `async_create_todo_item`: `async_add_free_text_item(item.summary)`, then
  `await coordinator.async_request_refresh()`.
- `async_update_todo_item`: only handle status → `async_set_item_checked`, refresh.
- `async_delete_todo_items`: `async_delete_items(list_id, uids)`, refresh.
- Entity naming/device info consistent with existing sensors (same device, translation
  keys in `strings.json` + `translations/nl.json`: "Boodschappenlijst").

Tests: use `pytest-homeassistant-custom-component` patterns already in the repo;
verify entity state, item mapping, and that service calls hit the right client
methods (mock `AhApiClient`).

## Step 4 — options flow

Extend the existing options flow (the entry's **Configure** button) with two new
options; keep the existing poll-interval option untouched:

1. `CONF_LIST_ENABLED` — **boolean toggle "Boodschappenlijst synchroniseren"**,
   default **off** (opt-in: existing users get no new polling or entities on
   upgrade). Use a `BooleanSelector` so it renders as a switch in the UI.
2. `CONF_LIST_SCAN_INTERVAL` — list scan interval (seconds, min 60, default 120).
   Only relevant when the toggle is on; fine to always show it.

Behavior of the toggle:
- **Off:** the `AhListCoordinator` is not created and performs zero API calls; the
  todo entity is not set up. `todo.py`'s `async_setup_entry` returns early when
  disabled (or `__init__.py` skips forwarding `Platform.TODO`).
- **Changing the option** must take effect without a HA restart: register an
  update listener (`entry.add_update_listener`) that calls
  `hass.config_entries.async_reload(entry.entry_id)` — the standard pattern.
  Turning it off removes the entity; the entity registry keeps its customizations
  for when it's re-enabled.
- Add translation strings for both options in `strings.json` and
  `translations/nl.json`.

Tests: options flow round-trip for both fields, reload-on-change, and that no list
endpoints are called when the toggle is off (assert mock call counts).

## Step 5 — sync automation (documentation, not code)

Add a README section with a loop-safe two-way sync between `todo.shopping_list`
and the new `todo.albert_heijn_boodschappenlijst`. Design rules:

- Compare-before-write: every action first calls `todo.get_items` on both entities
  and diffs by lowercased summary; only write when the target actually differs.
  This makes the automation idempotent and kills echo loops.
- HA → AH: item exists in HA with `needs_action` and no matching AH item → `todo.add_item`
  on the AH entity.
- AH → HA: matching item is checked or absent on the AH side while `needs_action`
  in HA → `todo.update_item` with `status: completed` on `todo.shopping_list`.
- HA checked → AH checked: mirror with `todo.update_item` on the AH entity.
- Trigger: state change of either entity (item count) + a fallback time_pattern
  (e.g. `/5` minutes) to catch missed edges; `mode: single` with `max_exceeded: silent`.

Provide the full YAML in the README, written so item names with quotes/emoji don't
break the templates (use `| lower | trim` on both sides of comparisons).

## Step 6 — quality gates

- `uv run pytest`, `uv run ruff check .`, `uv run pre-commit run --all-files` all green.
- Diagnostics: extend the redaction list so list item descriptions are NOT redacted
  (needed for debugging) but any account identifiers remain redacted.
- CHANGELOG entry under a new minor version (new platform ⇒ 0.5.0).
- README: new entity table row, install note unchanged, sync automation section,
  warning that this rides the unofficial API and list polling is per-2-minutes.

## Explicit non-goals

- No basket mutations, no product matching/search, no quantity sync (free text only).
- No push/websocket; deletion detection on the AH side is polling-based by design.
- Do not sync item renames in v1.

## Acceptance criteria

1. Adding "testitem-claude" to `todo.albert_heijn_*` in HA makes it appear as a
   free-text line in the AH app within one poll cycle, and vice-versa flows per Step 5.
2. Deleting or checking that item in the AH app marks it completed in HA within one
   poll interval, without resurrecting it.
3. Restarting HA does not mass-complete or duplicate items (first-refresh guard).
4. Auth expiry during any list call triggers the existing reauth flow, not a crash.
5. With the sync toggle **off** (the default), zero list-related API calls are made
   and no todo entity exists; flipping the toggle in Configure adds/removes the
   entity without an HA restart.
6. Full test suite and linters pass; no real credentials required for CI.
