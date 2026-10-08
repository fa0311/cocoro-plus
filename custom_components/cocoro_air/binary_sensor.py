"""Binary sensors for AIR water tanks and WASH operation status."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, Service
from .coordinator import CocoroCoordinator
from .entity import CocoroEntity

AIR_BINARY_SENSORS = (
    BinarySensorEntityDescription(
        key="water_tank",
        name="Water tank",
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
            CocoroBinarySensor(coordinator, description) for description in descriptions
        )
    async_add_entities(entities)


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
