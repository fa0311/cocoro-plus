# COCORO AIR & WASH

A Home Assistant custom integration for SHARP air cleaners and washing machines registered with COCORO MEMBERS. AIR and WASH share an account-based integration while using their own cloud APIs. The existing `cocoro_air` domain and installation directory are retained for compatibility.

## Supported features

| Appliance | Entities and controls |
| --- | --- |
| Air cleaner / humidifying air cleaner | Power, exact SHARP operating presets, humidification setting, temperature, humidity, PM2.5, cleaned air volume, odor/dust/cleanliness levels |
| AIR cloud features | Cloud service setting, notification switches and temperature thresholds, electricity rate and daily/monthly cost, outdoor weather and air forecasts, filter/supply life and maintenance dates, refresh button |
| AIR diagnostics | Water tank, actual humidification, empty water tank, plasma setting, child lock, light sensor, maintenance and unit errors, where supported |
| Washing machine | Operation state, remaining minutes, running, reservation and fault indicators; actions to read and download supported courses |

Entities and operating presets depend on the appliance's reported capabilities. Turn the AIR appliance on and wait for its reported running state before selecting a preset; the official API disables preset changes while stopped. Humidification control changes its enabled setting, rather than a target humidity. The separate humidifying indicator reports actual operation. Ordinal levels follow the official application: odor 0–3 and dust/cleanliness 0–4. Suppressed, measuring and out-of-range numeric measurements remain `unknown`; temperature, humidity and PM2.5 expose a `measurement_status` attribute for these cases.

Washer monitoring includes washing, rinsing, spinning, drying, standby, completion, drying-time calculation, reservation and supported cleaning stages. Unknown operation codes and durations remain `unknown`. A physical pause does not reliably change the cloud state: on the tested ES-12X1, it continued reporting drying during a pause. No separate pause indicator or remote start/stop is exposed.

Appliance state is polled every 30 seconds through a shared coordinator. AIR cloud metadata is refreshed every 15 minutes, or with the refresh button/read-cloud-information action. Commands use subsequently reported state without optimistic updates. Cloud delivery can take several seconds. Network/device failures make the affected appliance unavailable; failed optional AIR metadata requests leave appliance controls available. Authentication is renewed once on expiry; persistent authentication failures invoke Home Assistant reauthentication.

## Installation and configuration

Add this repository as an **Integration** in [HACS custom repositories](https://www.hacs.dev/docs/faq/custom_repositories/), install it, and restart Home Assistant. Alternatively, copy `custom_components/cocoro_air` into your configuration's `custom_components` directory.

Home Assistant 2024.2 or newer is required. Compatibility was verified with 2024.2.4 and 2026.10.0. HTTP dependencies are provided by Home Assistant.

1. Register appliances in the official [COCORO AIR](https://cocoroplusapp.jp.sharp/air) or [COCORO WASH](https://cocoroplusapp.jp.sharp/wash) application. Complete initial agreements or account verification there.
2. Open **Settings → Devices & services → Add integration → COCORO AIR & WASH**.
3. Enter your COCORO MEMBERS email and password.
4. Select the discovered appliances. IDs, models and capabilities are detected automatically.

Use **Configure** to rediscover appliances and change the selected set, including adding a washer to an existing AIR entry. At least one appliance must remain selected. Deselected appliances stop updating; their registry entries remain available for reuse. **Reconfigure** updates credentials while checking that the account owns the configured appliances.

Existing single-device entries and hldh214's selected-device entries migrate automatically. Device/entity identities, including the prefixed entity IDs used by hldh214, are retained. Existing water-tank sensor and humidification-switch entities remain as compatibility aliases; new installations use the appropriate binary-sensor and humidifier platforms.

Credentials are stored in Home Assistant configuration entries. Sessions are shared across entries for the same account and service, with separate AIR and WASH cookie jars. Unloading the last owner closes the session. Integration logs exclude credentials, authentication URLs and raw responses.

## Actions

Actions are available in **Developer tools → Actions** under `cocoro_air`. Select the Home Assistant device; it may be omitted when exactly one appliance supporting that action is configured.

| Action | Purpose |
| --- | --- |
| `get_cloud_info` | Read AIR capabilities, modes, supplies, pets, notifications and hourly tariff |
| `get_history` | Read AIR measurements or daily/monthly electricity-cost history |
| `get_weather` | Read outdoor weather, pollen, PM2.5, yellow-sand and laundry forecasts |
| `set_pet` / `delete_pet` | Manage AIR pet registrations and corresponding presets |
| `set_notifications` | Change supported notification preferences, preserving other fields |
| `set_electricity_tariff` | Set 24 hourly JPY/kWh prices |
| `maintain_supply` | Record cleaning or replacement and reset supported counters |
| `set_prefilter` | Enable or disable disposable-prefilter use |
| `get_wash_course` | Read the selected washer's course details and supported variants |
| `send_wash_course` | Download a supported course into an appliance slot |

Maintenance actions should reflect completed physical maintenance. Capabilities and the official application's restrictions determine which counters can be reset remotely. Read actions return response data for use in scripts and automations.

### Washer course download

Find a course in the official WASH catalogue and copy the `idCode` from its detail link. For example, `0x0003D5C3` identifies the fluffy-towel course on the tested ES-12X1. Course availability and variants are appliance-specific; check `get_wash_course` first.

```yaml
action: cocoro_air.send_wash_course
data:
  device_id: YOUR_HOME_ASSISTANT_DEVICE_ID
  course_id: "0x0003D5C3"
  slot: 1
  drying: false
```

The response contains `accepted`, the course name and slot. This downloads the configuration. To run it, select **Download Course** and press **Start** on the appliance. The slot is checked against the appliance's reported slot count, and unsupported course variants are rejected.

The ES-12X1 can apply a download while returning status 400 with `xdt is invalid`; the official application accepts this response. This integration accepts that specific case only after reading back the requested slot and matching both its internal course code and full catalogue ID. Other errors and mismatched registrations remain failures.

## Verification and implementation

Actual KI-SX70 monitoring, power, humidification, operating presets and AIR cloud reads were checked against the official application. ES-12X1 discovery, spinning/drying/washing state, remaining time, standby, course delivery and registered-course readback were checked with the real appliance. Numeric/ordinal boundaries and measurement flags were also checked against the official JavaScript and its UI using mock responses. KILS50 support from the original integration is retained.

The history from fa0311, yuyuvn and hldh214 is merged. Authentication and discovery are asynchronous and shared; service-specific modules decode AIR's `k1/k2/k3` and WASH's ECHONET properties. Both use `https://cocoroplusapp.jp.sharp`, with separate `/v1/cocoro-air/` and `/v1/cocoro-wash/` endpoints and OAuth callbacks. Embedded response statuses are checked even when HTTP status is 200.

Other compatible air cleaners and washers may work; unrelated appliance classes are excluded from discovery. The integration uses the official web application's undocumented cloud APIs, so vendor changes may require updates.
