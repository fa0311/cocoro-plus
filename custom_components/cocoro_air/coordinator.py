"""One periodic refresh per appliance, shared by all its entities."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from inspect import signature
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .air import AirDevice
from .api import AuthenticationError, CocoroError
from .cloud import (
    decode_cost_records,
    decode_tariff,
    notification_payload,
    parse_supplies,
    parse_weather,
)
from .const import UPDATE_INTERVAL
from .protocol import build_command, supported_modes
from .wash import WashDevice

_LOGGER = logging.getLogger(__name__)


class CocoroCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Expose authentication/network failures through Home Assistant."""

    def __init__(
        self, hass: HomeAssistant, api: AirDevice | WashDevice, entry=None
    ) -> None:
        # config_entry was added after the minimum supported HA 2024.2.
        entry_args = (
            {"config_entry": entry}
            if "config_entry" in signature(DataUpdateCoordinator.__init__).parameters
            else {}
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"COCORO {api.device.service.upper()} {api.device.model_name}",
            update_interval=UPDATE_INTERVAL,
            always_update=False,
            **entry_args,
        )
        self.api = api
        self.device = api.device
        self.device_id = self.device.device_id

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.api.async_update()
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except CocoroError as err:
            raise UpdateFailed(str(err)) from err


class CocoroAirCoordinator(CocoroCoordinator):
    """AIR controls and slower cloud metadata, sharing the appliance refresh."""

    def __init__(self, hass, api, entry=None):
        super().__init__(hass, api, entry)
        self.device_name = self.device.name
        self.model_name = self.device.model_name
        self.spec = {**self.device.spec, "model_name": self.model_name}
        self._lock = asyncio.Lock()
        self._cloud_updated = 0
        self._cloud_data = {}

    async def async_api(self, method, *args):
        try:
            return await method(*args)
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed("Sharp session expired") from err
        except CocoroError as err:
            raise HomeAssistantError(str(err)) from err

    async def _async_update_data(self):
        async with self._lock:
            try:
                body = await self.async_api(self.api.async_update)
                data = body
                if time.monotonic() - self._cloud_updated >= 900:
                    cloud = {}
                    for key, method in [
                        ("supplies_raw", self.api.get_supplies),
                        ("pets", self.api.get_pets),
                        ("notifications", self.api.get_notifications),
                        ("tariff", self.api.get_tariff),
                    ]:
                        try:
                            result = await self.async_api(method, self.device_id)
                            cloud[key] = (
                                result.get("data", []) if key == "pets" else result
                            )
                        except ConfigEntryAuthFailed:
                            raise
                        except HomeAssistantError:
                            # Optional cloud information must not disable device controls.
                            _LOGGER.warning("Unable to refresh Cocoro Air %s", key)
                            cloud[key] = None
                    if self.device.zip_code:
                        try:
                            weather = await self.async_api(
                                self.api.get_weather, self.api.metadata
                            )
                            cloud.update(
                                parse_weather(
                                    weather, datetime.now(ZoneInfo("Asia/Tokyo")).hour
                                )
                            )
                        except ConfigEntryAuthFailed:
                            raise
                        except HomeAssistantError:
                            _LOGGER.warning("Unable to refresh Cocoro Air weather")
                    try:
                        now = datetime.now(ZoneInfo("Asia/Tokyo")).replace(
                            minute=0, second=0, microsecond=0
                        )
                        # The website sends JST wall-calendar values labeled as UTC.
                        stamp = (
                            now.replace(tzinfo=timezone.utc)
                            .isoformat(timespec="milliseconds")
                            .replace("+00:00", "Z")
                        )
                        previous_year = now.replace(
                            year=now.year - 1,
                            day=min(now.day, 28) if now.month == 2 else now.day,
                        )
                        start = (
                            previous_year.replace(tzinfo=timezone.utc)
                            .isoformat(timespec="milliseconds")
                            .replace("+00:00", "Z")
                        )
                        daily_properties = [
                            {
                                "apg": "0x01",
                                "apc": ["0x40"],
                                "code": {"0x40": {"0x00": "0x00", "0x01": "0x00"}},
                            }
                        ]
                        monthly_properties = [
                            {
                                "apg": "0x01",
                                "apc": ["0x40"],
                                "code": {"0x40": {"0x00": "0x01", "0x01": "0x00"}},
                            }
                        ]
                        daily = decode_cost_records(
                            await self.async_api(
                                self.api.history,
                                self.device_id,
                                daily_properties,
                                stamp,
                                stamp,
                            )
                        )
                        monthly = decode_cost_records(
                            await self.async_api(
                                self.api.history,
                                self.device_id,
                                monthly_properties,
                                start,
                                stamp,
                            )
                        )
                        cloud["cost_today"] = next(
                            (
                                row["cost"]
                                for row in daily
                                if row["time"][:10] == now.strftime("%Y-%m-%d")
                            ),
                            None,
                        )
                        cloud["cost_month"] = next(
                            (
                                row["cost"]
                                for row in monthly
                                if row["time"][:7] == now.strftime("%Y-%m")
                            ),
                            None,
                        )
                    except ConfigEntryAuthFailed:
                        raise
                    except HomeAssistantError:
                        _LOGGER.warning(
                            "Unable to refresh Cocoro Air electricity costs"
                        )
                    self._cloud_data = cloud
                    self._cloud_updated = time.monotonic()
                data.update(self._cloud_data)
                data["pets"] = data.get("pets") or []
                tariff_rows = (data.get("tariff") or {}).get("data") or []
                prices = decode_tariff(tariff_rows[0] if tariff_rows else {})
                data["electricity_rate"] = (
                    prices[datetime.now(ZoneInfo("Asia/Tokyo")).hour]
                    if prices
                    else None
                )
                supplies = data.get("supplies_raw")
                record = (supplies or {}).get("data", [{}])
                data["supplies"] = parse_supplies(
                    record[0] if record else {},
                    {**data, **data["properties"]},
                    self.spec,
                )
                return data
            except ConfigEntryAuthFailed:
                raise
            except HomeAssistantError as err:
                raise UpdateFailed(str(err)) from err

    @property
    def modes(self):
        return supported_modes(self.spec, (self.data or {}).get("pets"), self.data)

    async def async_control(self, action, value):
        if action == "mode" and value not in self.modes:
            raise HomeAssistantError("Mode is not supported by this device")
        async with self._lock:
            try:
                commands = build_command(action, value, self.data or {}, self.spec)
            except ValueError as err:
                raise HomeAssistantError(str(err)) from err
            await self.async_api(self.api.control, self.api.metadata, commands)
        await self.async_request_refresh()

    async def async_cloud_write(self, method, *args):
        async with self._lock:
            result = await self.async_api(method, *args)
            self._cloud_updated = 0
        await self.async_request_refresh()
        return result

    async def async_set_notifications(self, patch):
        async with self._lock:
            current = await self.async_api(self.api.get_notifications, self.device_id)
            payload = notification_payload(self.device_id, current, patch)
            result = await self.async_api(
                self.api.set_notifications, self.device_id, payload["data"]
            )
            self._cloud_updated = 0
        await self.async_request_refresh()
        return result
