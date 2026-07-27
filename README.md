# Albert Heijn koopzegels for Home Assistant

A Home Assistant custom integration (HACS-installable) that exposes the balance of your
Albert Heijn digital **koopzegels** as a sensor.

> [!WARNING]
> This rides the **unofficial** AH mobile-app API, which can change or break without
> notice. It is a personal-use project, polls gently (every 6 hours; the optional
> shopping list pushes only when you ask it to), and is not affiliated with Albert Heijn.

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
| **Sync shopping list** (button) | Pushes your Home Assistant to-do list to the AH app — opt-in, see below |

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

### Getting the login code with less copy-pasting

Two optional helpers make step 3 above less fiddly. Neither is required — manually
copying the address from the browser's error page always works.

- **Linux desktop:** `scripts/install-appie-catcher.sh` registers `appie://` links
  with a small script that appends the code to a file (default `~/appie-code.txt`)
  instead of failing to open. Log in, then `tail -1 ~/appie-code.txt` for the code.
  `scripts/uninstall-appie-catcher.sh` removes it again.
- **Any device, including mobile:** `scripts/appie-code-helper.html` is a static,
  offline page — open it locally in any browser, paste whatever text you can get
  hold of that contains the failed redirect (or just the code), and it extracts a
  clean, copyable code. It can't catch the redirect itself: `appie://...` is a
  custom URL scheme, so nothing hosted (this page included) gets a chance to run
  before the OS looks for a registered app and gives up — this only cleans up
  whatever text you already have. If your phone's browser doesn't surface that
  text anywhere (no error page, nothing in the address bar), remote-debugging it
  from a computer over USB (`chrome://inspect` for Android Chrome, Safari's
  *Develop* menu for iOS) shows the failed request's `Location` header in the
  Network tab regardless of what the screen displays.

## Shopping list ("Mijn lijst")

The AH shopping list can be filled from Home Assistant (free text only — no product
matching, no quantity sync). It is **off by default**: enable *Sync shopping list*
via the entry's **Configure** button (no restart needed).

There are two ways to use it, chosen via the **Configure** dialog's *"Existing to-do
list to push to Albert Heijn"* field:

1. **Push an existing to-do list (recommended)** — pick e.g. the built-in
   `todo.shopping_list`. No extra entity is created and nothing runs in the
   background: you press the **Sync shopping list** button (or call the
   `albert_heijn.sync_shopping_list` action) and the list is pushed to the app in
   one batched write. This is what the rest of this section describes.
2. **A dedicated entity** — leave the field empty and a separate
   `todo.albert_heijn_*` entity is created, mirroring the AH list one-to-one
   (add/check/delete all round-trip to AH immediately, and the AH side is polled
   every 2 minutes). Use this if you want to wire it up yourself, or if you don't
   want the integration touching an existing list at all.

Renaming items is not supported by the AH API in either mode.

Notes:

- With the dedicated entity, the entity id follows your HA language:
  `todo.albert_heijn_shopping_list` on an English install,
  `todo.albert_heijn_boodschappenlijst` on a Dutch one.
- This is the shopping list that sits next to the basket in the AH app, **not**
  the webshop basket itself.

### What a push does

The push is **one-way and manual**: Home Assistant writes to the AH app, never the
other way around, and only when you ask for it. Per item on the source list:

| On your HA list | On the AH list | What happens |
| --- | --- | --- |
| open | absent | added as free text |
| open | present (checked or not) | left alone |
| completed | open | checked off in the app |
| completed | absent or already checked | nothing |
| — | present | left alone (you added it in the app) |

Matching is case- and whitespace-insensitive, so it survives however HA normalises
what you typed. Nothing is ever written back into Home Assistant: an item you check
off in the app stays open on your HA list until you clear it there yourself.

Two earlier behaviours are gone on purpose. The sync no longer runs itself on every
list change and every poll (that turned one long list into a storm of requests that
kept re-reading each other's half-finished work), and it no longer pulls AH changes
back into HA. In this mode the AH list is only read at the moment you push.

### The action

```yaml
action: albert_heijn.sync_shopping_list
data:
  entity_id: todo.shopping_list   # optional, defaults to the configured list
```

Both fields are optional: `entity_id` pushes a different to-do list than the
configured one, and `config_entry_id` picks the account when you have more than one
Albert Heijn entry set up to sync. Ask for a response to see what changed:

```yaml
action: albert_heijn.sync_shopping_list
response_variable: pushed
# pushed = {source_entity_id: ..., added: [...], checked: [...], unchanged: 2}
```

Add the **Sync shopping list** button to a dashboard for a one-tap version:

```yaml
type: button
entity: button.albert_heijn_sync_shopping_list
name: Naar AH-lijst
icon: mdi:cart-arrow-right
```

Or push automatically at a moment that suits you — e.g. when you leave home, so the
app is up to date by the time you reach the store:

```yaml
alias: "AH: lijst pushen bij vertrek"
triggers:
  - trigger: zone
    entity_id: person.me
    zone: zone.home
    event: leave
actions:
  - action: albert_heijn.sync_shopping_list
mode: single
```

### Alternative: automation for the dedicated entity

With the dedicated-entity mode there is no button and no action — that entity *is*
the AH list, so writing to it writes to the app. The automation below does the same
one-way push from `todo.shopping_list`, on demand:

```yaml
alias: "AH: boodschappenlijst pushen"
description: One-way push from todo.shopping_list to the Albert Heijn entity.
triggers: []   # run it by hand, or add your own trigger
actions:
  - action: todo.get_items
    target:
      entity_id: todo.shopping_list
    data:
      status: [needs_action]
    response_variable: ha_response
  - action: todo.get_items
    target:
      entity_id: todo.albert_heijn_shopping_list
    data:
      status: [needs_action, completed]
    response_variable: ah_response
  - variables:
      ah_known: >-
        {{ ah_response['todo.albert_heijn_shopping_list']['items']
           | map(attribute='summary') | map('lower') | map('trim') | list }}
      to_add: >-
        {% set ns = namespace(items=[]) %}
        {% for item in ha_response['todo.shopping_list']['items']
           if (item.summary | lower | trim) not in ah_known %}
          {% set ns.items = ns.items + [item.summary] %}
        {% endfor %}
        {{ ns.items }}
  - repeat:
      for_each: "{{ to_add }}"
      sequence:
        - action: todo.add_item
          target:
            entity_id: todo.albert_heijn_shopping_list
          data:
            item: "{{ repeat.item }}"
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
