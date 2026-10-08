"""Air-cleaner power control."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, Service
from .coordinator import CocoroCoordinator
from .entity import CocoroAirEntity, CocoroEntity, coordinators

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        CocoroAirPower(coordinator)
        for coordinator in hass.data[DOMAIN][entry.entry_id].coordinators
        if coordinator.device.service == Service.AIR
    )
    await async_setup_air_entry(hass, entry, async_add_entities)


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
        await self.coordinator.async_control("power", enabled)

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set_power(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set_power(False)


async def async_setup_air_entry(hass, entry, async_add_entities):
    entities = []
    for c in coordinators(hass, entry):
        if (
            c.spec.get("hasHumidFunc")
            and not c.spec.get("cannotControlHumid")
            and er.async_get(hass).async_get_entity_id(
                "switch", DOMAIN, f"{DOMAIN}_{c.device_id}_humidification"
            )
        ):
            entities.append(CocoroAirSwitch(c, "humidification"))
        if c.spec.get("hasCloudService"):
            entities.append(CocoroAirSwitch(c, "cloud"))
        for key in ("air_cleaner", "temperature"):
            entities.append(CocoroAirSwitch(c, "notify_" + key))
        if c.spec.get("hasHumanSensor"):
            entities.append(CocoroAirSwitch(c, "notify_human"))
    async_add_entities(entities)


class CocoroAirSwitch(CocoroAirEntity, SwitchEntity):
    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        if key != "humidification":
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self):
        if self._key.startswith("notify_"):
            return ((self.coordinator.data or {}).get("notifications") or {}).get(
                self._key[7:]
            )
        return (self.coordinator.data or {}).get(
            {"cloud": "cloud_enabled", "humidification": "humidification_enabled"}[
                self._key
            ]
        )

    async def _set(self, enabled):
        c = self.coordinator
        if self._key.startswith("notify_"):
            await c.async_set_notifications({self._key[7:]: enabled})
        else:
            await c.async_control(self._key, enabled)

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)
