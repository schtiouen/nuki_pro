<p align="center">
  <img src="https://raw.githubusercontent.com/msdevio/nuki_pro/main/docs/nuki_logo_readme.png" alt="Nuki" width="220">
</p>

# Nuki Pro — Home Assistant integration for the Nuki Smart Lock (5th generation)

> Unofficial community integration, not affiliated with Nuki Home Solutions. The Nuki name and logo are trademarks of Nuki Home Solutions GmbH; they are only used to identify the supported devices and are not covered by the MIT license.

[Version française](README.fr.md)

Custom integration for the **Nuki Smart Lock Pro (5th generation)**, and more broadly the Nuki type 5 locks (Go, Pro, Ultra) and the 3.0/4.0 Pro.
It gives access to every feature of the lock **without a Bridge** (not compatible with the 5th generation) and **without a Thread border router**:

- **Nuki Web API** (token, required): state, settings, users, keypad codes, activity log with names;
- **Local MQTT** (optional, off by default): instant state and actions on your network, with automatic fallback to the Web API.

## Entities

| Type | Entities |
| --- | --- |
| Lock | Lock, unlock, open (unlatch); open, opening and jammed states; `changed_by` = last person |
| Sensors | Battery (%), Lock state, Mode, Door security, **Last user**, **Last unlock user**, **Last unlatch user**, **Last lock user**, Last action, Last action trigger, Last action time, Firmware, Nuki server state |
| Binary sensors | Locked, Battery critical, Charging, Night mode active, MQTT connection, Nuki server connection, Web API connection |
| Switches | Auto lock, Button enabled, LED enabled, Automatic updates, Slow speed in night mode, Pairing via button, Detached cylinder, Lift-up handle, Automatic battery type detection, **Access "name"** (one per app user) |
| Selects | Single button press, Double button press, Motor speed, Lock 'n' Go timeout, Unlatch duration, Bluetooth advertising mode, Battery type |
| Number | Auto lock timeout |
| Buttons | Lock 'n' Go, Lock 'n' Go with unlatch (disabled by default), Full lock, Refresh |
| Event | **Activity**: every lock action with the person, the trigger and the source (code, fingerprint), button or fob presses set to "no action", rejected codes and fingerprints |

### Accessories

Each paired accessory becomes its own device, linked to the lock ("connected via"):

| Device | Entities |
| --- | --- |
| **Door sensor** | Door open/closed, State (closed, open, calibrating, removed…), Battery critical, Tamper, **Events**: door opened, door closed, door left open, status mismatch, sensor jammed |
| **Keypad** (Keypad / Keypad 2) | Battery critical, Tamper and Mounting (Keypad 2 anti-theft), one **Access** switch per keypad code (number of fingerprints as an attribute) |
| **Fob** | Single, double and triple press actions, fob **Access** switch |

"Door security" (closed and locked, closed not locked, open) stays on the lock because it combines both. An accessory only shows up once paired; when added later, its entities are created without a restart.

Rarely used settings are created disabled: enable them from the device page.

The attributes of the "Last …" sensors give the action, the trigger, the source and the timestamp. Keypad codes are never exposed.

## Requirements

1. **Nuki Web API token**: on [web.nuki.io](https://web.nuki.io), menu **API**, generate a token with the permissions to view and manage smart locks, operate them, manage authorizations and configuration, and view the activity log. Nuki Web must be enabled for the lock in the Nuki app.
2. **MQTT (optional)**: in the Nuki app, lock settings, *Features & Configuration* > *Smart Home* > *MQTT*:
   - broker address (Mosquitto), username and password (32 characters at most); Nuki requires port 1883 without TLS, on the local network;
   - **turn off "Auto discovery"**, otherwise the lock creates duplicate entities in the MQTT integration;
   - keep **"Allow locking"** on for local actions.

## Installation

### With HACS (recommended)

1. HACS > ⋮ menu > **Custom repositories**: URL `https://github.com/msdevio/nuki_pro`, type **Integration**.
2. Search for **Nuki Pro** in HACS, download it, then restart Home Assistant.

HACS then reports new versions (GitHub releases).

### Manually

Copy the `custom_components/nuki_pro` folder into the `custom_components` folder of your Home Assistant configuration (Samba, SSH or Studio Code Server add-on), to get `/config/custom_components/nuki_pro/`. Restart Home Assistant.

### Adding the lock

**Settings > Devices & services > Add integration > Nuki Pro**, paste the token, then choose whether to use MQTT. When the lock's MQTT is on, Home Assistant also offers the lock under "Discovered".

If you used another Nuki integration before, remove it and revoke its token on web.nuki.io.

### Options

| Option | Default | Effect |
| --- | --- | --- |
| Web API polling interval | Empty = automatic: 30 s, or 300 s while MQTT is online | 15 to 3600 s (Nuki limit: 1000 requests per hour) |
| Channel for lock actions | Automatic | MQTT when online, else Web API; or force one of them |
| One switch per user or code | Yes | Turn it off if you have many codes |

## Languages

The interface is available in **English**, **French**, **German**, **Spanish**, **Dutch** and **Italian**. Forms, states, actions and error messages follow each user's language; entity and device names are created in the system language when the integration is added. Other languages fall back to English. New translations are welcome in `custom_components/nuki_pro/translations/` (`tests/test_translations.py` checks that every file has the same keys and placeholders as `en.json`).

## Actions (services)

All of them target the lock entity.

```yaml
# Full lock (double turn)
action: nuki_pro.lock_action
target:
  entity_id: lock.front_door
data:
  action: full_lock          # unlock, lock, unlatch, lock_n_go, lock_n_go_unlatch, full_lock
  transport: web             # optional: auto, mqtt, web

# Keypad code valid on Mondays and Fridays from 9:00 to 12:30
action: nuki_pro.create_keypad_code
target:
  entity_id: lock.front_door
data:
  name: Delivery
  code: "456789"             # 6 digits from 1 to 9, not starting with 12
  allowed_weekdays: [mon, fri]
  allowed_from_time: "09:00"
  allowed_until_time: "12:30"

# Disable an access (name or id)
action: nuki_pro.update_authorization
target:
  entity_id: lock.front_door
data:
  authorization: Delivery
  enabled: false

# Delete an access
action: nuki_pro.delete_authorization
target:
  entity_id: lock.front_door
data:
  authorization: Delivery
```

`nuki_pro.get_authorizations` and `nuki_pro.get_logs` (`limit` from 1 to 50) return a response usable in scripts (`response_variable`).

## Automations

The **Activity** entity fires on every action. Example: a notification when someone opens the door with a keypad code.

```yaml
triggers:
  - trigger: state
    entity_id: event.front_door_activity
conditions:
  - condition: template
    value_template: >
      {{ trigger.to_state.attributes.event_type in ['unlock', 'unlatch']
         and trigger.to_state.attributes.source == 'keypad_code' }}
actions:
  - action: notify.notify
    data:
      message: "Door opened by {{ trigger.to_state.attributes.user }}"
```

Event types of the **Activity** entity: `unlock`, `lock`, `unlatch`, `lock_n_go`, `lock_n_go_unlatch`, `full_lock`, `button_no_action`, `fob_no_action`, `wrong_code`, `wrong_fingerprint`.

Event types of the door sensor **Events** entity: `door_opened`, `door_closed`, `door_ajar_warning` (door left open), `door_status_mismatch`, `door_sensor_jammed`.

Tip: in the Nuki app, set a button (or fob) action to "no action". With MQTT, each press then fires `button_no_action` (or `fob_no_action`) with a `presses` attribute, usable as an automation button.

Entity ids depend on the lock name and on the Home Assistant language: check them on the device page.

## How it works

- With MQTT, the state arrives instantly and its values win; the Web API is polled every 5 minutes for settings, users and the log, and right after each activity to get the person's name.
- Without MQTT, the Web API is polled every 30 s: state, settings and log (2 requests per cycle, about 250 per hour for a limit of 1000); users are read again every 15 minutes and after each change.
- When MQTT goes down (lock offline, broker stopped), the Web API takes over at 30 s, without making the entities unavailable. An MQTT action without an answer is resent through the Web API; it cannot run late (10 s expiry on MQTT 5, QoS 0 on MQTT 3.1.1).
- If the token is revoked while MQTT works, the lock stays usable locally and Home Assistant asks for a new token.
- Setting changes show up at once, then are confirmed by the next read.
- Users changed in the Nuki app reach Nuki Web only once a day: the **Refresh** button requests a sync.

## Troubleshooting

- **Diagnostics**: device page > ⋮ > *Download diagnostics* (token, codes, names and GPS position are redacted).
- **Debug logs**:

  ```yaml
  logger:
    logs:
      custom_components.nuki_pro: debug
  ```

- **"Nothing received on this topic"**: check MQTT in the Nuki app and the `nuki/<NUKI_ID>` topic with MQTT Explorer, or untick MQTT.
- **MQTT connection flapping**: known issue of firmware 5.9.4 over Wi-Fi; the integration falls back to the Web API meanwhile.

## Development

```bash
uv venv -p 3.14 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/python -m pytest tests/
```

36 tests cover the Web API only mode, the MQTT mode, the accessories, the config flow, the diagnostics, the brand images and the translations (Home Assistant 2026.10.4). They also run in GitHub Actions, with the hassfest and HACS validations.

Sources: [Web API specification](https://api.nuki.io/static/swagger/swagger.json), [MQTT API specification v1.6](https://developer.nuki.io/t/about-the-mqtt-category/14233), [Nuki documentation](https://docs.nuki.io/guide/).

## License

Code under the [MIT](LICENSE) license © 2026 msaid_dev. The Nuki logo (`brand/` folder) remains the property of Nuki Home Solutions GmbH.
