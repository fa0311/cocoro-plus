"""Air-cleaner power control."""

from __future__ import annotations

from typing import cast

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .air import AirDevice
from .api import CocoroError
from .const import DOMAIN, Service
from .coordinator import CocoroCoordinator
from .entity import CocoroEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        CocoroAirPower(coordinator)
        for coordinator in hass.data[DOMAIN][entry.entry_id].coordinators
        if coordinator.device.service == Service.AIR
    )


class CocoroAirPower(CocoroEntity, SwitchEntity):
    """Switch the complete air cleaner on/off independently of humidification."""

    _attr_translation_key = "power"
    _attr_icon = "mdi:air-purifier"

    def __init__(self, coordinator: CocoroCoordinator) -> None:
        super().__init__(coordinator, "power")

    @property
    def is_on(self) -> bool | None:
        return (self.coordinator.data or {}).get("power")

    async def _async_set_power(self, enabled: bool) -> None:
        api = cast(AirDevice, self.coordinator.api)
        try:
            await api.async_set_power(enabled)
        except CocoroError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set_power(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set_power(False)
