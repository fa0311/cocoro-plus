# COCORO AIR & WASH

A Home Assistant custom integration for SHARP air cleaners and washing machines registered with COCORO MEMBERS. AIR and WASH share this integration; the existing `cocoro_air` domain and installation directory are retained.

## Supported features

| Appliance | Entities |
| --- | --- |
| Air cleaner / humidifying air cleaner | Power switch, humidity-mode on/off, temperature, humidity, PM2.5, cleaned air volume, odor level, dust level, cleanliness level, water tank |
| Washing machine | Operation state, remaining time in minutes, running, reservation, fault |

Washer monitoring includes washing, rinsing, spinning, drying, standby/pause, completion, drying-time calculation, and supported cleaning stages. Unknown operation codes and unknown durations remain `unknown`. Washing-machine start/stop, course selection, and reservation changes are not exposed.

AIR humidity-mode control switches the humidification setting; it does not set a target humidity or indicate whether water is currently evaporating. Humidifier entities are only created for appliances reporting controllable humidification. PM2.5 and dust entities are only created when the appliance reports the corresponding sensor. AIR level sensors use the official application's thresholds (odor 0–3, dust and cleanliness 0–4). PM2.5 measurement flags and unavailable measurements are excluded from numeric readings. Measurements that the official app suppresses while stopped remain `unknown`.

Updates are shared by all entities of an appliance and run every 30 seconds. Cloud/network failures make that appliance's entities `unavailable`; polling resumes automatically. Expired sessions are renewed once, and a persistent authentication failure starts Home Assistant's reauthentication flow. State changes can take a few seconds to appear because commands are delivered through the cloud.

## Installation

Add this repository as an **Integration** in [HACS custom repositories](https://www.hacs.dev/docs/faq/custom_repositories/), install it, and restart Home Assistant. Alternatively, copy `custom_components/cocoro_air` into your Home Assistant configuration's `custom_components` directory.

Home Assistant 2024.2 or newer is required. Compatibility was checked with 2024.2.4 and 2026.10.0.

## Configuration

1. Register your appliances using the official [COCORO AIR](https://cocoroplusapp.jp.sharp/air) or [COCORO WASH](https://cocoroplusapp.jp.sharp/wash) app. Complete any initial agreements or account verification there.
2. Open **Settings → Devices & services → Add integration → COCORO AIR & WASH**.
3. Enter your COCORO MEMBERS email and password.
4. Select the discovered appliances. Device IDs and model names are detected automatically.

Use **Configure** on an existing integration entry to rediscover appliances and change the selected set. At least one appliance must remain selected. Deselected appliances stop updating; their registry entries are retained so entity IDs can be reused when selected again.

Existing single-appliance AIR entries migrate automatically, preserving the credentials, device identity, and entity unique IDs. You can add a washer to an existing AIR entry through **Configure**. A proper `binary_sensor` is now provided for the water tank; an existing `sensor` water-tank entity is retained as a compatibility alias for automations.

Email/password are stored in Home Assistant's configuration entry, as in the previous version. Each account and service has an isolated HTTP session. Integration logs exclude credentials, authentication URLs, and raw cloud responses.

## Verified appliances

- KILS50 (existing AIR support)
- KISX70 / KI-SX70 (AIR discovery, monitoring, power and humidity-mode control)
- ES-12X1 (WASH discovery and monitoring)

Other air cleaners and washers may work when they expose the same properties. Appliances such as air conditioners are excluded from discovery. This integration uses the web application's undocumented cloud APIs; changes to those APIs may require an update.

## Implementation

Authentication, discovery, and response validation are shared. Service-specific modules decode AIR's `k1/k2/k3` properties and WASH's ECHONET properties. Each appliance has a `DataUpdateCoordinator`, and entities read its snapshot rather than fetching independently. Setup/unload closes owned HTTP clients and cancels polling.

Both services use `https://cocoroplusapp.jp.sharp`, with separate `/v1/cocoro-air/` and `/v1/cocoro-wash/` APIs and OAuth callbacks. The response's embedded status is checked even when HTTP status is 200.
