"""Retain the existing AIR humidity-mode entity."""

from __future__ import annotations

from homeassistant.components.humidifier import HumidifierDeviceClass, HumidifierEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, Service
from .coordinator import CocoroCoordinator
from .entity import CocoroEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Only air cleaners with controllable humidification get this entity."""
    async_add_entities(
        CocoroAirHumidifier(coordinator)
        for coordinator in hass.data[DOMAIN][entry.entry_id].coordinators
        if coordinator.device.service == Service.AIR
        and coordinator.device.has_humidifier
    )


class CocoroAirHumidifier(CocoroEntity, HumidifierEntity):
    """Humidity mode, with the original unique ID and on/off semantics."""

    _attr_translation_key = "humidity_mode"
    _attr_device_class = HumidifierDeviceClass.HUMIDIFIER

    def __init__(self, coordinator: CocoroCoordinator) -> None:
        super().__init__(coordinator, "humidity_mode")

    @property
    def is_on(self) -> bool | None:
        return (self.coordinator.data or {}).get("humidity_mode")

    @property
    def icon(self) -> str:
        return "mdi:air-humidifier" if self.is_on else "mdi:air-humidifier-off"

    async def _async_set_mode(self, enabled: bool) -> None:
        await self.coordinator.async_control("humidification", enabled)

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set_mode(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set_mode(False)
