# Albert Heijn koopzegels for Home Assistant

A Home Assistant custom integration (HACS-installable) that exposes the balance of your
Albert Heijn digital **koopzegels** as a sensor.

> [!WARNING]
> This rides the **unofficial** AH mobile-app API, which can change or break without
> notice. It is a personal-use project, polls gently (every 6 hours; the optional
> shopping list sync polls every 2 minutes), and is not affiliated with Albert Heijn.

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
| **Shopping list** (todo) | The AH shopping list ("Mijn lijst") as a todo entity — opt-in, see below |

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

## Shopping list ("Mijn lijst")

The AH shopping list can be exposed as a todo entity with full add/check/delete
support. It is **off by default**: enable *Sync shopping list* via the entry's
**Configure** button (no restart needed). While enabled, the list is polled every
2 minutes (configurable, min 60 s); items you add from HA land in the AH app as
free-text lines. Renaming items is not supported by the AH API.

Notes:

- The entity id follows your HA language: `todo.albert_heijn_shopping_list` on an
  English install, `todo.albert_heijn_boodschappenlijst` on a Dutch one. The
  examples below assume English — adjust to yours.
- This is the shopping list that sits next to the basket in the AH app, **not**
  the webshop basket itself.

### Two-way sync with the Home Assistant shopping list

The automation below keeps `todo.shopping_list` (HA's built-in shopping list) and
the AH list in sync, loop-safely:

- added in HA → added to the AH list as free text;
- checked off in HA → checked in the AH app;
- checked off **or deleted** in the AH app → marked completed in HA (never
  resurrected).

Every run first reads both lists with `todo.get_items` and only writes when the
target actually differs (compare-before-write), so echo loops die out and the
5-minute fallback tick is idempotent. Items are matched case-insensitively on
their name; quotes and emoji in item names are fine because names are never
spliced into templates. Deletions are only pulled right after the AH entity
changed — on other runs a brand-new HA item would look "deleted" before it was
ever pushed.

```yaml
alias: "AH: boodschappenlijst twee-weg sync"
description: >-
  Two-way sync between todo.shopping_list and the Albert Heijn list.
  Compare-before-write keeps it idempotent and loop-safe.
triggers:
  - trigger: state
    entity_id: todo.shopping_list
    not_from: [unavailable, unknown]
    not_to: [unavailable, unknown]
    id: ha_changed
  - trigger: state
    entity_id: todo.albert_heijn_shopping_list
    not_from: [unavailable, unknown]
    not_to: [unavailable, unknown]
    id: ah_changed
  - trigger: time_pattern
    minutes: "/5"
    id: reconcile
conditions:
  - condition: template
    value_template: >-
      {{ states('todo.shopping_list') not in ['unavailable', 'unknown'] and
         states('todo.albert_heijn_shopping_list') not in ['unavailable', 'unknown'] }}
actions:
  - action: todo.get_items
    target:
      entity_id: todo.shopping_list
    data:
      status: [needs_action, completed]
    response_variable: ha_response
  - action: todo.get_items
    target:
      entity_id: todo.albert_heijn_shopping_list
    data:
      status: [needs_action, completed]
    response_variable: ah_response
  - variables:
      ha_all: "{{ ha_response['todo.shopping_list']['items'] }}"
      ah_all: "{{ ah_response['todo.albert_heijn_shopping_list']['items'] }}"
      ah_open_norm: >-
        {{ ah_all | selectattr('status', 'eq', 'needs_action')
                  | map(attribute='summary') | map('lower') | map('trim') | list }}
      ah_done_norm: >-
        {{ ah_all | selectattr('status', 'eq', 'completed')
                  | map(attribute='summary') | map('lower') | map('trim') | list }}
      # Open in HA and entirely unknown to AH -> add to AH (free text).
      to_add_to_ah: >-
        {% set ns = namespace(items=[]) %}
        {% for ha_item in ha_all if ha_item.status == 'needs_action'
           and (ha_item.summary | lower | trim) not in ah_open_norm + ah_done_norm %}
          {% set ns.items = ns.items + [ha_item.summary] %}
        {% endfor %}
        {{ ns.items }}
      # Completed in HA but still open in AH -> check in the app.
      to_check_in_ah: >-
        {% set ns = namespace(items=[]) %}
        {% for ha_item in ha_all if ha_item.status == 'completed' %}
          {% for ah_item in ah_all if ah_item.status == 'needs_action'
             and (ah_item.summary | lower | trim) == (ha_item.summary | lower | trim) %}
            {% set ns.items = ns.items + [ah_item.summary] %}
          {% endfor %}
        {% endfor %}
        {{ ns.items }}
      # Open in HA but checked in AH -> complete in HA. Safe on every run.
      to_complete_in_ha: >-
        {% set ns = namespace(items=[]) %}
        {% for ha_item in ha_all if ha_item.status == 'needs_action'
           and (ha_item.summary | lower | trim) in ah_done_norm %}
          {% set ns.items = ns.items + [ha_item.summary] %}
        {% endfor %}
        {{ ns.items }}
      # Open in HA and gone from AH -> deleted in the app -> complete in HA.
      # Only acted on right after an AH change (see the choose below).
      to_complete_in_ha_deleted: >-
        {% set ns = namespace(items=[]) %}
        {% for ha_item in ha_all if ha_item.status == 'needs_action'
           and (ha_item.summary | lower | trim) not in ah_open_norm + ah_done_norm %}
          {% set ns.items = ns.items + [ha_item.summary] %}
        {% endfor %}
        {{ ns.items }}
  - choose:
      # The HA list changed: push to AH.
      - conditions:
          - condition: trigger
            id: ha_changed
        sequence:
          - repeat:
              for_each: "{{ to_add_to_ah }}"
              sequence:
                - action: todo.add_item
                  target:
                    entity_id: todo.albert_heijn_shopping_list
                  data:
                    item: "{{ repeat.item }}"
          - repeat:
              for_each: "{{ to_check_in_ah }}"
              sequence:
                - action: todo.update_item
                  target:
                    entity_id: todo.albert_heijn_shopping_list
                  data:
                    item: "{{ repeat.item }}"
                    status: completed
      # The AH list changed (an app edit picked up by the poll): pull into HA.
      - conditions:
          - condition: trigger
            id: ah_changed
        sequence:
          - repeat:
              for_each: "{{ to_complete_in_ha + to_complete_in_ha_deleted }}"
              sequence:
                - action: todo.update_item
                  target:
                    entity_id: todo.shopping_list
                  data:
                    item: "{{ repeat.item }}"
                    status: completed
    # Fallback tick: reconcile checked state in both directions, which is safe
    # no matter which side changed. Additions wait for an HA state change,
    # deletions for an AH one.
    default:
      - repeat:
          for_each: "{{ to_check_in_ah }}"
          sequence:
            - action: todo.update_item
              target:
                entity_id: todo.albert_heijn_shopping_list
              data:
                item: "{{ repeat.item }}"
                status: completed
      - repeat:
          for_each: "{{ to_complete_in_ha }}"
          sequence:
            - action: todo.update_item
              target:
                entity_id: todo.shopping_list
              data:
                item: "{{ repeat.item }}"
                status: completed
mode: single
max_exceeded: silent
```

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
uv run python scripts/discover_list.py "appie://login-exit?code=..."   # shopping list schema
```

`discover_list.py` verifies the shopping list CRUD against the live API; add
`--roundtrip` to exercise add/check/uncheck/delete with a self-cleaning test item.

The AH GraphQL schema is unofficial; if it changes, the query lives in
[const.py](custom_components/albert_heijn/const.py) and the response mapping in
`parse_koopzegels` in [api.py](custom_components/albert_heijn/api.py).

## Roadmap

More sensors (bonus box, spending, next delivery) can reuse the same client and
coordinator — see [CHANGELOG.md](CHANGELOG.md) for what's released.
