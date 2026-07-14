# Getting a real logo + HACS default-store listing

Two separate external submissions, in this order (brands is a prerequisite for HACS default).

## 1. Brand icon — home-assistant/brands

HA and HACS show integration logos from the
[home-assistant/brands](https://github.com/home-assistant/brands) repo, keyed by domain.
Until this is done, the integration shows a generic puzzle-piece icon; `hacs.json` has
no icon field. The entity icons inside HA are already covered by `icons.json`.

Steps:

1. ✅ Assets are prepared in [`docs/brands/custom_integrations/albert_heijn/`](brands/custom_integrations/albert_heijn/):
   `icon.png` (256×256) and `icon@2x.png` (512×512), derived from the official App Store
   artwork of the Albert Heijn app (nominative use of the brand mark for an integration
   that talks to their service is the accepted practice in the brands repo).
2. ✅ The same icons are shipped in-repo at `custom_components/albert_heijn/brand/`
   — the fallback location the `hacs/action` brands check accepts, so CI passes
   without (or ahead of) a brands-repo listing.
3. Fork `home-assistant/brands`, copy the `docs/brands/custom_integrations/albert_heijn/`
   folder into the fork's `custom_integrations/`, and open a PR; their CI validates
   dimensions and naming. Still needed for the icon to actually *show* in the HA/HACS
   UI, and a hard requirement for the default store. (Note: the extra `logo.png` in
   the in-repo brand folder is 600×600 — brands-repo CI wants logos ≤256 px high, so
   submit only `icon.png`/`icon@2x.png` or resize the logo first.)

## 2. HACS default store — hacs/default

Currently installable as a custom repository. Default-store listing removes the
add-repository step for other users. Requirements
([HACS docs](https://www.hacs.xyz/docs/publish/include/)) and our status:

| Requirement | Status |
| --- | --- |
| Public repo, issues enabled, description set | ✅ |
| GitHub repo **topics** set | ❌ the `hacs/action` topics check fails on this — see below |
| `hacs.json` with `name` | ✅ |
| `manifest.json` with domain/name/version/codeowners/docs/issue tracker | ✅ |
| README describing the integration | ✅ |
| GitHub releases | ✅ (v0.1.0+) |
| `hacs/action` validation in CI | ✅ (`validate.yml`) |
| Brands: in-repo fallback for the CI check | ✅ `custom_components/albert_heijn/brand/icon.png` |
| Added to home-assistant/brands | ❌ step 1 above; hard requirement for default store |

Topics can only be set on GitHub itself: repo page → **About** (gear icon) →
*Topics* → add e.g. `home-assistant`, `hacs`, `home-assistant-integration`,
`custom-component`, `albert-heijn`. Any non-empty topic list satisfies the check.

Steps once brands is merged:

1. Fork `hacs/default`, add `Daafip/ha-ah` to the `integration` list (alphabetical).
2. Open the PR using their template; automated checks run the same validation as our CI.

## Worth knowing before submitting

The integration rides an unofficial API. That is allowed in HACS (plenty of precedents),
but a default-store listing invites a wider audience and therefore more breakage reports
when AH changes something. Staying custom-repository-only is a legitimate choice for a
personal-use project — the plan explicitly framed default submission as optional.
