# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: [SemVer](https://semver.org/).

## [Unreleased]

## [0.6.0] - 2026-07-21

### Added

- Options flow: pick an **existing todo list** (e.g. the built-in
  `todo.shopping_list`) to sync directly, instead of always creating a
  dedicated `todo.albert_heijn_*` entity. Leave the field empty to keep the
  previous (dedicated-entity) behavior. Switching between the two — or to a
  different target entity — reloads the entry, same as toggling the sync
  itself.
- New `AhListSyncManager` implements the sync directly against the chosen
  entity via the `todo` services (`get_items`/`add_item`/`update_item`): HA-side
  changes push additions and check-offs to the AH list; AH poll updates pull
  checked-off-or-deleted items into completions on the HA side. This is the
  same logic the README's manual automation used, now built in.
- Diagnostics report the configured sync target entity.

### Changed

- The options-flow entity selector excludes the integration's own dedicated
  todo entity (when one exists) to avoid pointing the sync at itself.

## [0.5.0] - 2026-07-14

### Added

- **Shopping list** ("Mijn lijst") as a todo entity with add/check/delete support.
  Opt-in via a new *Sync shopping list* toggle in the entry's Configure dialog
  (default off: existing installs get no new polling or entities on upgrade).
  Enabling/disabling takes effect without a restart.
- Items added from HA land in the AH app as free-text lines; checking an item in
  either place can be mirrored to the other. Renaming is not supported by the API.
- Separate poll interval for the list (default 120 s, min 60 s), configurable in
  the same dialog. The 6 h koopzegels interval is untouched.
- README: loop-safe two-way sync automation between `todo.shopping_list` and the
  AH list (compare-before-write, no resurrection of deleted items).
- Verification script `scripts/discover_list.py`: exercises the full
  add/check/uncheck/delete cycle against a real account with a self-cleaning
  test item.
- Diagnostics include the list items (descriptions unredacted on purpose — they
  are what needs debugging; account identifiers stay redacted).

### Notes

- All four list operations were live-verified on 2026-07-14. The shopping list
  turned out to be a REST-only resource (`shoppinglist/v2/items`): GraphQL's
  `favoriteListV2` cannot see free-text items, everything is a PATCH merge
  keyed on the item description, and quantity 0 deletes. Details in the
  shopping list section of `const.py`.

## [0.4.0] - 2026-07-04

### Added

- **Deliveries calendar**: all delivery slots as a calendar entity (past and planned).
- Five new best-effort sensors: **Air Miles**, **Premium savings**, **Open settlements**,
  **Saving goal** (with progress attributes), and **Basket** (total + item count).
  All endpoints verified against the live API on 2026-07-04; anything that doesn't apply
  to your account shows as *unknown* without affecting the other sensors.
- Monetary sensors display with 2-decimal precision (the API can return sub-cent values).
- Optional endpoints are now fetched concurrently, keeping the poll cycle fast.
- README examples: Lovelace card, balance-change notification, and a store-zone
  automation with a persistent notification that clears on leaving.

## [0.3.1] - 2026-07-04

### Added

- Entity icons via `icons.json` (postage stamp, receipt, cash, delivery truck).
- Checklist for the brand-logo and HACS default-store submissions
  (`docs/hacs-default-submission.md`).

## [0.3.0] - 2026-07-04

### Added

- Three new sensors reusing the same client/coordinator: **Last receipt** (total of the
  most recent in-store receipt), **Spent this month** (sum of this calendar month's
  receipts), and **Next delivery** (timestamp of the next planned delivery slot).
- Receipt and delivery endpoints degrade gracefully: if they fail, the sensors show
  *unknown* while koopzegels keeps working.
- Discovery script now also exercises the receipts and deliveries endpoints.

### Changed

- Coordinator data is now an aggregate (`AhData`); diagnostics include all fetched data
  with transaction and order ids redacted.

### Not included

- Bonus box sensor: the unofficial schema dump documents no usable query shape for it.

## [0.2.0] - 2026-07-03

### Added

- Options flow: configurable poll interval (1–24 h, default 6 h), applied without
  reloading the integration.
- Redacted diagnostics download (tokens and member id are scrubbed).
- Options-flow translations (English + Dutch) and debug logging around token refresh
  and GraphQL calls.

## [0.1.0] - 2026-07-03

### Added

- Initial release: `koopzegels` balance sensor with config flow (paste-the-code login),
  proactive token refresh, reauth flow, and English + Dutch translations.
