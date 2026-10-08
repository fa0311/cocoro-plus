"""Sensor entities for AIR and WASH appliances."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, Service
from .coordinator import CocoroCoordinator
from .entity import CocoroEntity
from .wash import STATE_OPTIONS

AIR_SENSORS = (
    SensorEntityDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="humidity",
        name="Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="pm25",
        name="PM2.5",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement="µg/m³",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="cleaned_air_volume",
        name="Cleaned air volume",
        icon="mdi:air-purifier",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="odor_level",
        name="Odor level",
        icon="mdi:scent",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="dust_level",
        name="Dust level",
        icon="mdi:blur",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="cleanliness_level",
        name="Cleanliness level",
        icon="mdi:air-filter",
        state_class=SensorStateClass.MEASUREMENT,
    ),
)
WASH_SENSORS = (
    SensorEntityDescription(
        key="operation_state",
        translation_key="operation_state",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_OPTIONS,
        icon="mdi:washing-machine",
    ),
    SensorEntityDescription(
        key="remaining_time",
        translation_key="remaining_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-outline",
    ),
)
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create appropriate sensors for each selected appliance."""
    entities = []
    registry = er.async_get(hass)
    for coordinator in hass.data[DOMAIN][entry.entry_id].coordinators:
        descriptions = (
            AIR_SENSORS if coordinator.device.service == Service.AIR else WASH_SENSORS
        )
        entities.extend(
            CocoroSensor(coordinator, description)
            for description in descriptions
            if not (description.key == "pm25" and not coordinator.device.has_pm25)
            and not (
                description.key == "dust_level" and not coordinator.device.has_dust
            )
        )
        if coordinator.device.service == Service.AIR and registry.async_get_entity_id(
            "sensor", DOMAIN, f"{coordinator.device.device_id}_water_tank"
        ):
            # Older versions registered a BinarySensorEntity on the sensor platform.
            # Retain that entity ID as a compatibility alias for existing automations.
            entities.append(
                LegacyWaterTankSensor(
                    coordinator,
                    SensorEntityDescription(
                        key="water_tank", name="Water tank", icon="mdi:water"
                    ),
                )
            )
    async_add_entities(entities)


class CocoroSensor(CocoroEntity, SensorEntity):
    """An entity updated by the appliance coordinator."""

    def __init__(
        self, coordinator: CocoroCoordinator, description: SensorEntityDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return (self.coordinator.data or {}).get(self.entity_description.key)


class LegacyWaterTankSensor(CocoroSensor):
    """Keep old sensor.water_tank states while offering a proper binary sensor."""

    @property
    def native_value(self) -> str | None:
        value = (self.coordinator.data or {}).get("water_tank")
        return None if value is None else "on" if value else "off"
