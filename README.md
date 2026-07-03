# Albert Heijn koopzegels for Home Assistant

A Home Assistant custom integration (HACS-installable) that exposes the balance of your
Albert Heijn digital **koopzegels** as a sensor.

> [!WARNING]
> This rides the **unofficial** AH mobile-app API, which can change or break without
> notice. It is a personal-use project, polls gently (every 6 hours), and is not
> affiliated with Albert Heijn.

## Sensor

`sensor.albert_heijn_koopzegels` — the euro payout value of your saved koopzegels
(device class *monetary*), with attributes:

| Attribute | Meaning |
| --- | --- |
| `stamp_count` | Total stamps saved |
| `full_booklets` | Completed booklets |
| `booklet_stamps` | Stamps in the current booklet |
| `stamps_until_next_booklet` | Stamps left to fill the current booklet (target 490) |
| `invested` / `interest` | Euro paid in and bonus earned |

## Installation

1. In HACS: *Custom repositories* → add `https://github.com/Daafip/ha-ah` as
   category **Integration**, then install **Albert Heijn** and restart HA.
2. *Settings → Devices & services → Add integration → Albert Heijn*.
3. Follow the login step:
   - Open the AH login link shown in the dialog and log in.
   - The browser ends on an `appie://login-exit?code=...` address it cannot open.
     Copy that address (or just the `code` value).
   - Paste it in the dialog. The code is single-use and expires in minutes.

Only the (rotating) refresh token is stored, inside the HA config entry. When it stops
working, HA prompts to re-authenticate with a fresh code.

The poll interval (default 6 h) is configurable via the entry's **Configure** button.
A redacted diagnostics download is available from the device page for bug reports.

## Development

Uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync --locked          # create the environment
uv run pytest             # run the test suite (mocked API, no credentials)
uv run ruff check .       # lint
uv run pre-commit run --all-files
```

To verify against the real API with your own account (one-time code, nothing stored):

```bash
uv run python scripts/discover_koopzegels.py "appie://login-exit?code=..."
```

The AH GraphQL schema is unofficial; if it changes, the query lives in
[const.py](custom_components/albert_heijn/const.py) and the response mapping in
`parse_koopzegels` in [api.py](custom_components/albert_heijn/api.py).

## Roadmap

More sensors (bonus box, spending, next delivery) can reuse the same client and
coordinator — see [CHANGELOG.md](CHANGELOG.md) for what's released.
