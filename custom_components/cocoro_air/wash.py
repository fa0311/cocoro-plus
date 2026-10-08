"""WASH monitoring decoded from the official OperationCheck web UI."""

from __future__ import annotations

from typing import Any

from .air import hex_value
from .api import CocoroClient, CocoroResponseError, Device

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
    0x61: "idle",
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
    elif reserved is True and state in ("idle",):
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

    async def async_get_course(self, course_id: str) -> dict:
        """Fetch the same device-specific course detail used by the official page."""
        body = await self.session.async_request(
            "sensors",
            "sensors_post_021",
            method="POST",
            json={
                "deviceToken": self.device.device_id,
                "properties": [
                    {
                        "apg": "0x02",
                        "apc": ["0x00", "0x01", "0x02", "0x04", "0x07", "0x08", "0x09"],
                        "code": {"0x00": {"0x00": "0x10"}, "0x01": {"0x00": course_id}},
                    }
                ],
            },
        )
        return body["data"][0]

    async def async_send_course(
        self, course_id: str, slot: int = 1, drying: bool = False
    ) -> dict:
        """Download a course; starting it requires the appliance's physical button."""
        course = await self.async_get_course(course_id)
        body = await self.session.async_request(
            "sensors",
            "sensors_021",
            params={
                "device_id": self.device.device_id,
                "event_key": "echonet_property",
                "epc": "0xF0+0xF1",
            },
        )
        properties = {key: value for row in body["data"] for key, value in row.items()}
        capabilities = _bytes(properties["0xF0"])
        slots = capabilities[26] if capabilities[11] & 0x20 else 1
        if not 1 <= slot <= slots:
            raise ValueError("Download slot does not exist on this appliance")
        commands = course_commands(course, properties["0xF1"], slot, drying)
        try:
            await self.session.async_request(
                "sync/epc",
                "sync_epc_032",
                method="POST",
                json={
                    "deviceToken": self.device.device_id,
                    "event_key": "echonet_control",
                    "data": commands,
                },
            )
        except CocoroResponseError as err:
            # ES-12X1 applies the download despite this specific response. The
            # official UI accepts it; require the registered course to match.
            if err.status != 400 or err.info != "xdt is invalid":
                raise
            expected = int(commands[1]["edt"][8:10], 16)
            registered = await self.async_registered_course(capabilities, slot)
            if (
                registered is None
                or registered[0] != expected
                or int(registered[1]["0x01"], 16) != int(course_id, 16)
            ):
                raise
        return {"accepted": True, "course": course["0x02"], "slot": slot}

    async def async_registered_course(self, capabilities: bytes, slot: int):
        """Read a download slot using the official DownloadFavorite lookup."""
        body = await self.session.async_request(
            "sensors",
            "sensors_021",
            params={
                "device_id": self.device.device_id,
                "event_key": "echonet_property",
                "epc": "0xF1+0xFA",
            },
        )
        properties = {key: value for row in body["data"] for key, value in row.items()}
        short_id = (
            _bytes(properties["0xFA"])[12 + 2 * slot]
            if capabilities[11] & 0x20
            else _bytes(properties["0xF1"])[0]
        )
        if short_id == 0:
            return None
        body = await self.session.async_request(
            "sensors",
            "sensors_post_021",
            method="POST",
            json={
                "deviceToken": self.device.device_id,
                "properties": [
                    {
                        "apg": "0x02",
                        "apc": ["0x00", "0x01", "0x02", "0x09"],
                        "code": {
                            "0x00": {"0x00": "0x11"},
                            "0x01": {"0x00": f"0x{short_id:08x}"},
                        },
                    }
                ],
            },
        )
        return short_id, body["data"][0]


def course_commands(
    course: dict, current_f1: str, slot: int, drying: bool
) -> list[dict]:
    """Match NaviCourseDetailSend's EPC payload, preserving unrelated F1 bits."""
    if course["0x07"] != "0x01":
        raise ValueError("This course cannot be downloaded to the appliance")
    variants = {row["0x00"]: row["0x10"] for row in course["0x08"]}
    kind = "0x01" if drying else "0x00"
    if kind not in variants:
        raise ValueError("This course does not support the selected drying option")
    values = variants[kind]
    f1 = (
        current_f1[:8]
        + values["0x01"][2:].upper()
        + f"{slot - 1:02x}"
        + current_f1[14:18]
    )
    commands = [{"epc": "0xD0", "edt": values["0x00"]}, {"epc": "0xF1", "edt": f1}]
    # E4 is omitted by the official application when the washing-time field is zero.
    fields = {
        "0xE4": "0x02",
        "0xE5": "0x03",
        "0xE6": "0x04",
        "0xE7": "0x05",
        "0xE8": "0x06",
        "0xE9": "0x07",
    }
    commands.extend(
        {"epc": epc, "edt": values[key]}
        for epc, key in fields.items()
        if epc != "0xE4" or variants.get("0x00", values)["0x02"] != "0x00"
    )
    return commands
