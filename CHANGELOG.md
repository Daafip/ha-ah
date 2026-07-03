# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: [SemVer](https://semver.org/).

## [Unreleased]

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
