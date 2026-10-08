"""Binary sensors for AIR water tanks and WASH operation status."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, Service
from .coordinator import CocoroCoordinator
from .entity import CocoroAirEntity, CocoroEntity, coordinators

AIR_BINARY_SENSORS = (
    BinarySensorEntityDescription(
        key="water_tank",
        translation_key="water_tank",
        device_class=BinarySensorDeviceClass.MOISTURE,
        icon="mdi:water",
    ),
)
WASH_BINARY_SENSORS = (
    BinarySensorEntityDescription(
        key="running",
        translation_key="running",
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    BinarySensorEntityDescription(
        key="reserved", translation_key="reserved", icon="mdi:calendar-clock"
    ),
    BinarySensorEntityDescription(
        key="fault",
        translation_key="fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
)
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Use the binary_sensor platform for boolean states."""
    entities = []
    for coordinator in hass.data[DOMAIN][entry.entry_id].coordinators:
        descriptions = (
            AIR_BINARY_SENSORS
            if coordinator.device.service == Service.AIR
            else WASH_BINARY_SENSORS
        )
        entities.extend(
            CocoroBinarySensor(coordinator, description)
            for description in descriptions
            if description.key != "water_tank"
            or coordinator.device.spec.get("hasHumidFunc")
        )
    async_add_entities(entities)
    await async_setup_air_entry(hass, entry, async_add_entities)


class CocoroBinarySensor(CocoroEntity, BinarySensorEntity):
    """A boolean property; absent values stay unknown."""

    def __init__(
        self, coordinator: CocoroCoordinator, description: BinarySensorEntityDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return (self.coordinator.data or {}).get(self.entity_description.key)


async def async_setup_air_entry(hass, entry, async_add_entities):
    entities = []
    for c in coordinators(hass, entry):
        keys = ["plasma_enabled", "care_error", "unit_date_error", "unit_out_error"]
        if c.spec.get("hasHumidFunc"):
            keys.extend(["humidifying", "water_empty"])
        if c.spec.get("hasChildLock") or c.spec.get("hasPetMode"):
            keys.append("child_lock")
        if c.spec.get("hasLightSensor"):
            keys.append("light_sensor_bright")
        entities.extend(CocoroAirBinarySensor(c, key) for key in keys)
        seen = set()

        def add_supplies(coordinator=c, registered=seen):
            new = []
            for name in (coordinator.data or {}).get("supplies", {}):
                if name not in registered:
                    registered.add(name)
                    new.append(CocoroAirBinarySensor(coordinator, "care_" + name))
            if new:
                async_add_entities(new)

        add_supplies()
        entry.async_on_unload(c.async_add_listener(add_supplies))
    async_add_entities(entities)


class CocoroAirBinarySensor(CocoroAirEntity, BinarySensorEntity):
    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        if key.startswith("care_") or key in (
            "water_empty",
            "unit_date_error",
            "unit_out_error",
        ):
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self):
        if self._key.startswith("care_") and self._key != "care_error":
            return (
                (self.coordinator.data or {})
                .get("supplies", {})
                .get(self._key[5:], {})
                .get("needs_cleaning")
            )
        return (self.coordinator.data or {}).get(self._key)
