# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: [SemVer](https://semver.org/).

## [Unreleased]

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
