"""AIR-specific state decoding and humidification control."""

from __future__ import annotations

from typing import Any

from .api import CocoroClient, Device


def hex_value(value: Any) -> int | None:
    """Preserve unavailable/malformed fields as unknown."""
    return int(value, 16) if value is not None else None


def parse_air_data(data: list[dict[str, Any]]) -> dict[str, Any]:
    """Decode the original k1/k2/k3 properties without retaining stale fields."""
    groups = {
        key: value
        for item in data
        for key, value in item.items()
        if key in ("k1", "k2", "k3")
    }

    def value(group: str, field: str) -> int | None:
        fields = groups.get(group)
        return hex_value(fields.get(field)) if fields is not None else None

    def flag(group: str, field: str) -> bool | None:
        return {0: False, 255: True}.get(value(group, field))

    temperature, humidity = value("k1", "s1"), value("k1", "s2")
    mode = value("k3", "s1")
    stopped = mode is not None and (mode & 0xF0 == 0 or mode == 0x1E)
    pm25 = value("k1", "s7")
    # Hn.pm25Value: the top bit marks measurement in progress, lower 10 bits
    # contain the concentration. Out-of-range readings are not exact values.
    pm25 = pm25 & 0x03FF if pm25 is not None and not pm25 & 0x8000 else None
    if pm25 is not None and pm25 >= 500:
        pm25 = None

    def level(field: str, thresholds: tuple[int, ...]) -> int | None:
        number = value("k2", field)
        if number is None or stopped:
            return None
        return sum(number >= threshold for threshold in thresholds)

    properties = {key.lower(): value for item in data for key, value in item.items()}
    return {
        "power": {0x30: True, 0x31: False}.get(hex_value(properties.get("0x80"))),
        "temperature": temperature
        if temperature is not None and 0 <= temperature <= 50 and not stopped
        else None,
        "humidity": humidity
        if humidity is not None and 0 <= humidity <= 100 and not stopped
        else None,
        "cleaned_air_volume": value("k1", "s6"),
        "pm25": pm25 if not stopped else None,
        # Official Cn/wn/Dn thresholds; rounding differs at the boundaries.
        "odor_level": level("s1", (17, 51, 76)),
        "dust_level": level("s2", (16, 36, 56, 76)),
        "cleanliness_level": level("s4", (1, 26, 51, 76)),
        "water_tank": flag("k2", "s6"),
        "humidity_mode": flag("k3", "s7"),
    }


class AirDevice:
    """An air cleaner backed by an AIR session."""

    def __init__(self, session: CocoroClient, device: Device) -> None:
        self.session = session
        self.device = device

    async def async_update(self) -> dict[str, Any]:
        body = await self.session.async_request(
            "sensors-conceal/air-cleaner",
            "sensors_aircleaner_021",
            params={
                "device_id": self.device.device_id,
                "event_key": "echonet_property",
                "opc": "k1+k2+k3",
                "epc": "0x80+0x86",
            },
        )
        data = body["data"]
        return parse_air_data(data)

    async def async_set_humidity_mode(self, enabled: bool) -> None:
        await self.session.async_request(
            "sync/air-cleaner",
            "sync_aircleaner_032",
            method="POST",
            json={
                "additional_request": False,
                "deviceToken": self.device.device_id,
                "event_key": "echonet_control",
                "data": [
                    {"opc": "k3", "odt": {"s5": "00", "s7": "FF" if enabled else "00"}}
                ],
                "model_name": self.device.model_name,
            },
        )

    async def async_set_power(self, enabled: bool) -> None:
        """Send the same paired EPC/k3 command as PurifierStatusScreen."""
        await self.session.async_request(
            "sync/air-cleaner",
            "sync_aircleaner_032",
            method="POST",
            json={
                "additional_request": False,
                "deviceToken": self.device.device_id,
                "event_key": "echonet_control",
                "data": [
                    {"epc": "0x80", "edt": "0x30" if enabled else "0x31"},
                    {"opc": "k3", "odt": {"s6": "FF" if enabled else "00"}},
                ],
                "model_name": self.device.model_name,
            },
        )
