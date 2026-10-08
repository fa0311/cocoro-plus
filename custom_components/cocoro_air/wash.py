"""WASH monitoring decoded from the official OperationCheck web UI."""

from __future__ import annotations

from typing import Any

from .air import hex_value
from .api import CocoroClient, Device

WASH_PROPERTIES = "0x88+0xE2+0xED+0x90+0xD0+0xF0+0xF4"
OPERATION_STATES = {
    0x41: "washing",
    0x42: "rinsing",
    0x43: "spinning",
    0x45: "finished",
    0x51: "finished",
    0x52: "drying",
    0x53: "finished",
    0x54: "finished",
    0x61: "paused",
    0xE0: "running",
    0xE1: "deodorizing",
    0xE2: "idle",
    0xE4: "calculating_drying_time",
    0xE5: "recalculating_drying_time",
    0xE6: "prewashing",
}
ACTIVE_STATES = {
    "washing",
    "rinsing",
    "spinning",
    "drying",
    "running",
    "deodorizing",
    "calculating_drying_time",
    "recalculating_drying_time",
    "prewashing",
    "tub_cleaning",
    "tub_drying",
    "water_path_cleaning",
}
STATE_OPTIONS = list(dict.fromkeys(OPERATION_STATES.values())) + [
    "reserved",
    "error",
    "tub_cleaning",
    "tub_drying",
    "water_path_cleaning",
]


def _bytes(value: Any) -> bytes | None:
    if value is None:
        return None
    return bytes.fromhex(value.removeprefix("0x").removeprefix("0X"))


def parse_duration(value: Any) -> int | None:
    """ED contains separate hour/minute bytes; 0xFFFF means unknown."""
    data = _bytes(value)
    if data is None or len(data) != 2 or data[0] == 255 or data[1] > 59:
        return None
    return data[0] * 60 + data[1]


def parse_wash_data(data: list[dict[str, Any]]) -> dict[str, Any]:
    """Decode established fields; do not guess unknown operation codes."""
    properties = {
        key.upper(): value
        for item in data
        for key, value in item.items()
        if key != "time"
    }
    stage = hex_value(properties.get("0XE2"))
    fault = {0x41: True, 0x42: False}.get(hex_value(properties.get("0X88")))
    reserved = {0x41: True, 0x42: False}.get(hex_value(properties.get("0X90")))
    course = _bytes(properties.get("0XF4"))
    course_code = course[15] if course is not None and len(course) > 15 else None
    capabilities = _bytes(properties.get("0XF0"))
    machine_type = (
        capabilities[10]
        if capabilities is not None and len(capabilities) > 10
        else None
    )
    mode = hex_value(properties.get("0XD0"))
    state = OPERATION_STATES.get(stage)
    if stage == 0xEF and course_code == 63:
        state = "water_path_cleaning"
    if state in ACTIVE_STATES and mode == 0x42:
        state = "tub_cleaning"
    elif stage == 0x52 and machine_type in (1, 2) and mode == 0xBF:
        state = "tub_drying"
    if fault is True:
        state = "error"
    elif reserved is True and state in ("idle", "paused"):
        state = "reserved"
    running = None if state is None else state in ACTIVE_STATES
    remaining = parse_duration(properties.get("0XED"))
    if state not in ACTIVE_STATES or stage in (0xE4, 0xE5):
        remaining = None
    return {
        "operation_state": state,
        "remaining_time": remaining,
        "running": running,
        "reserved": reserved,
        "fault": fault,
    }


class WashDevice:
    """Expose washer state through its WASH session."""

    def __init__(self, session: CocoroClient, device: Device) -> None:
        self.session = session
        self.device = device

    async def async_update(self) -> dict[str, Any]:
        body = await self.session.async_request(
            "sensors",
            "sensors_021",
            params={
                "device_id": self.device.device_id,
                "event_key": "echonet_property",
                "epc": WASH_PROPERTIES,
            },
        )
        data = body["data"]
        return parse_wash_data(data)
