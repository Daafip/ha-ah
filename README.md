# Albert Heijn koopzegels for Home Assistant

A Home Assistant custom integration (HACS-installable) that exposes the balance of your
Albert Heijn digital **koopzegels** as a sensor.

> [!WARNING]
> This rides the **unofficial** AH mobile-app API, which can change or break without
> notice. It is a personal-use project, polls gently (every 6 hours), and is not
> affiliated with Albert Heijn.

## Sensors

| Entity | Meaning |
| --- | --- |
| **Koopzegels** | Euro payout value of your saved koopzegels |
| **Last receipt** | Total of your most recent in-store receipt |
| **Spent this month** | Sum of this calendar month's in-store receipts |
| **Next delivery** | Timestamp of the next planned delivery slot |
| **Deliveries** (calendar) | All delivery slots as calendar events |
| **Air Miles** | Air Miles balance (if linked) |
| **Premium savings** | Total saved through the Premium subscription |
| **Open settlements** | Refunds owed to you |
| **Saving goal** | Koopzegels saving goal, with progress attributes |
| **Basket** | Current webshop basket total and item count |

The koopzegels sensor carries attributes for the stamp counts:

| Attribute | Meaning |
| --- | --- |
| `stamp_count` | Total stamps saved |
| `full_booklets` | Completed booklets |
| `booklet_stamps` | Stamps in the current booklet |
| `stamps_until_next_booklet` | Stamps left to fill the current booklet (target 490) |
| `invested` / `interest` | Euro paid in and bonus earned |

The receipt and delivery sensors are best-effort: when those endpoints fail or don't
apply to your account, they show *unknown* while koopzegels keeps working.

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

## Examples

Entity ids below assume an English-language HA install; check yours under
*Settings → Devices & services → Albert Heijn* (a Dutch install generates ids from the
Dutch names, e.g. `sensor.albert_heijn_uitgegeven_deze_maand`).

### Lovelace card

An overview card plus a booklet progress line:

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Albert Heijn
    entities:
      - sensor.albert_heijn_koopzegels
      - sensor.albert_heijn_last_receipt
      - sensor.albert_heijn_spent_this_month
      - sensor.albert_heijn_next_delivery
  - type: markdown
    content: >-
      {% set k = 'sensor.albert_heijn_koopzegels' %}
      **Boekje:** {{ state_attr(k, 'booklet_stamps') }}/{{ state_attr(k, 'full_booklet_target') }}
      zegels — nog {{ state_attr(k, 'stamps_until_next_booklet') }} tot een vol boekje
      ({{ state_attr(k, 'full_booklets') }} vol).
```

### Simple automation — ping when the balance changes

Fires after you've shopped and the next poll picks up the new balance:

```yaml
alias: "AH: koopzegels bijgewerkt"
triggers:
  - trigger: state
    entity_id: sensor.albert_heijn_koopzegels
    not_from: [unavailable, unknown]
    not_to: [unavailable, unknown]
actions:
  - action: notify.notify  # or notify.mobile_app_<your_phone>
    data:
      title: "Koopzegels"
      message: >-
        Saldo is nu € {{ states('sensor.albert_heijn_koopzegels') }} — nog
        {{ state_attr('sensor.albert_heijn_koopzegels', 'stamps_until_next_booklet') }}
        zegels tot een vol boekje.
mode: single
```

### Complex automation — store-zone notification

Define a zone per AH store you visit (*Settings → Areas, labels & zones → Zones*, or YAML):

```yaml
# configuration.yaml
zone:
  - name: AH Centrum
    latitude: 52.37403
    longitude: 4.88969
    radius: 75
    icon: mdi:cart
  - name: AH XL
    latitude: 52.35870
    longitude: 4.90800
    radius: 100
    icon: mdi:cart
```

While you're inside one of those zones, a persistent notification shows your koopzegels
status; it disappears again when you leave. The fixed `notification_id` is what makes the
dismiss target exactly the notification that enter created:

```yaml
alias: "AH: koopzegels-herinnering in de winkel"
description: Persistent notification while at an AH store, removed on leaving.
triggers:
  - trigger: zone
    entity_id: person.john_doe
    zone: zone.ah_xl
    event: enter
    id: enter
  - trigger: zone
    entity_id: person.john_doe
    zone: zone.ah_2
    event: enter
    id: enter
  - trigger: zone
    entity_id: person.john_doe
    zone: zone.ah_3
    event: enter
    id: enter
conditions: []
actions:
  - choose:
      - conditions:
          - condition: trigger
            id: enter
          - condition: template
            value_template: >-
              {{ state_attr('sensor.albert_heijn_koopzegels', 'full_booklets') >
              0 }}
        sequence:
          - action: notify.mobile_app_<phone>
            data:
              title: 🛒 Albert Heijn
              message: >
                {% set k = 'sensor.albert_heijn_koopzegels' %} Koopzegelsaldo: €
                {{ states(k) }}
                {{ state_attr(k, 'full_booklets')}} boekje(s) zijn vol. 

                Boekje: {{ state_attr(k, 'booklet_stamps') }}/{{ state_attr(k,
                'full_booklet_target') }} zegels (nog {{ state_attr(k,
                'stamps_until_next_booklet') }} tot volgende volle boekje).
            enabled: true
mode: restart

```
To get it on your phone instead of the HA dashboard, swap both sequences for
`notify.mobile_app_<phone>` 


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
