"""AIR-specific state decoding and humidification control."""

from __future__ import annotations

from typing import Any

from .api import CocoroClient, Device
from .protocol import parse_status


def hex_value(value: Any) -> int | None:
    """Decode an available hexadecimal property."""
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
        self.metadata = {
            "device_id": device.device_id,
            "model_name": device.model_name,
            "zip_code": device.zip_code,
            "spec": device.spec,
        }

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
        legacy = parse_air_data(data)
        parsed = parse_status(body, self.device.spec)
        legacy_keys = (
            "humidity_mode",
            "water_tank",
            "cleaned_air_volume",
            "cleanliness_level",
        )
        return {**parsed, **{key: legacy[key] for key in legacy_keys}}

    async def async_set_humidity_mode(self, enabled: bool) -> None:
        await self.control(
            self.metadata,
            [{"opc": "k3", "odt": {"s5": "00", "s7": "FF" if enabled else "00"}}],
        )

    async def async_set_power(self, enabled: bool) -> None:
        await self.control(
            self.metadata,
            [
                {"epc": "0x80", "edt": "0x30" if enabled else "0x31"},
                {"opc": "k3", "odt": {"s6": "FF" if enabled else "00"}},
            ],
        )

    async def request(self, method, path, **kwargs):
        return await self.session.async_request(path, None, method=method, **kwargs)

    async def get_notifications(self, device_id):
        return await self.request(
            "GET", "notify_setting/air-cleaner", params={"device_id": device_id}
        )

    async def set_notifications(self, device_id, data):
        return await self.request(
            "POST",
            "notify_setting/air-cleaner",
            json={"bff_device_id": device_id, "data": data},
        )

    async def read_properties(self, device_id, path, properties):
        return await self.request(
            "POST", path, json={"deviceToken": device_id, "properties": properties}
        )

    async def control(self, device, commands):
        additional_request = int(device.get("spec", {}).get("seriiesCode", 0)) >= 6
        return await self.request(
            "POST",
            "sync/air-cleaner",
            json={
                "deviceToken": device["device_id"],
                "model_name": device.get("model_name", ""),
                "additional_request": additional_request,
                "event_key": "echonet_control",
                "data": commands,
            },
        )

    async def control_properties(self, device_id, properties):
        return await self.read_properties(
            device_id, "devices/control/air-cleaner", properties
        )

    async def get_supplies(self, device_id):
        return await self.read_properties(
            device_id, "contents/supplies", [{"apg": "0x02", "apc": ["0x10"]}]
        )

    async def get_pets(self, device_id):
        return await self.read_properties(
            device_id, "contents/pets", [{"apg": "0x01", "apc": ["0x00"]}]
        )

    async def get_tariff(self, device_id):
        return await self.read_properties(
            device_id, "latest/air-cleaner", [{"apg": "0x01", "apc": ["0x50"]}]
        )

    async def get_weather(self, device, date=None):
        params = {"zipcode": device["zip_code"], "apc": "0x01+0x10+0x20+0x30"}
        if date is not None:
            params["date"] = date
        return await self.request("GET", "weathers", params=params)

    async def get_air_history(self, device_id, from_time, to_time, count=1000):
        return await self.history(
            device_id,
            [
                {
                    "apg": "0x01",
                    "apc": ["0x20"],
                    "epc_ext": [{"opc": "k1"}, {"opc": "k2"}, {"opc": "k3"}],
                }
            ],
            from_time,
            to_time,
            count=count,
        )

    async def history(
        self, device_id, properties, from_time, to_time, count=100, offset=0
    ):
        return await self.request(
            "POST",
            "history-conceal/air-cleaner",
            json={
                "deviceToken": device_id,
                "properties": properties,
                "from_time": from_time,
                "to_time": to_time,
                "count": count,
                "offset": offset,
            },
        )

    async def write_supplies(self, device_id, properties):
        return await self.read_properties(
            device_id, "contents/control/supplies", properties
        )

    async def write_pet(self, device_id, properties):
        return await self.read_properties(
            device_id, "contents/control/pets", properties
        )

    async def delete_pet(self, device_id, pet_id):
        return await self.request(
            "DELETE",
            "contents/control/pets",
            params={"device_id": device_id, "apc": "0x00", "adt": pet_id},
        )
