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
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, Service
from .coordinator import CocoroCoordinator
from .entity import CocoroAirEntity, CocoroEntity, coordinators
from .wash import STATE_OPTIONS

AIR_SENSORS = (
    SensorEntityDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="pm25",
        translation_key="pm25",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement="µg/m³",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="cleaned_air_volume",
        translation_key="cleaned_air_volume",
        icon="mdi:air-purifier",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="odor_level",
        translation_key="odor_level",
        icon="mdi:scent",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="dust_level",
        translation_key="dust_level",
        icon="mdi:blur",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="cleanliness_level",
        translation_key="cleanliness_level",
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
                        key="water_tank", translation_key="water_tank", icon="mdi:water"
                    ),
                )
            )
    async_add_entities(entities)
    await async_setup_air_entry(hass, entry, async_add_entities)


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

    @property
    def extra_state_attributes(self):
        key = self.entity_description.key
        if key in ("temperature", "humidity", "pm25"):
            return {
                "measurement_status": (self.coordinator.data or {}).get(key + "_status")
            }
        return None


class LegacyWaterTankSensor(CocoroSensor):
    """Keep old sensor.water_tank states while offering a proper binary sensor."""

    @property
    def native_value(self) -> str | None:
        value = (self.coordinator.data or {}).get("water_tank")
        return None if value is None else "on" if value else "off"


DESCRIPTIONS = {
    "temperature": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    "humidity": (SensorDeviceClass.HUMIDITY, "%"),
    "pm25": (SensorDeviceClass.PM25, "µg/m³"),
    "dust_level": (None, None),
    "odor_level": (None, None),
    "air_quality": (None, None),
    "brightness": (None, None),
    "operating_status": (None, None),
    "cost_today": (SensorDeviceClass.MONETARY, "JPY"),
    "cost_month": (SensorDeviceClass.MONETARY, "JPY"),
    "electricity_rate": (None, "JPY/kWh"),
    "outdoor_temperature": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    "outdoor_humidity": (SensorDeviceClass.HUMIDITY, "%"),
    "pollen": (None, None),
    "pm25_forecast": (None, None),
    "yellow_sand": (None, None),
    "laundry": (None, None),
    "weather_code": (None, None),
}


async def async_setup_air_entry(hass, entry, async_add_entities):
    entities = []
    for c in coordinators(hass, entry):
        keys = ["operating_status", "cost_today", "cost_month", "electricity_rate"]
        if er.async_get(hass).async_get_entity_id(
            "sensor", DOMAIN, f"{DOMAIN}_{c.device_id}_air_quality"
        ):
            keys.append("air_quality")
        if c.device.zip_code:
            keys.extend(
                [
                    "outdoor_temperature",
                    "outdoor_humidity",
                    "pollen",
                    "pm25_forecast",
                    "yellow_sand",
                    "laundry",
                    "weather_code",
                ]
            )
        if c.spec.get("hasLightSensor"):
            keys.append("brightness")
        entities.extend(CocoroAirSensor(c, key) for key in keys)
        seen = set()

        def add_supplies(coordinator=c, registered=seen):
            new = []
            for name, supply in (coordinator.data or {}).get("supplies", {}).items():
                fields = ["last_cleaned"]
                if supply.get("remaining") is not None:
                    fields.append("remaining")
                for field in fields:
                    key = (name, field)
                    if key not in registered:
                        registered.add(key)
                        new.append(CocoroAirSupplySensor(coordinator, name, field))
            if new:
                async_add_entities(new)

        add_supplies()
        entry.async_on_unload(c.async_add_listener(add_supplies))
    async_add_entities(entities)


class CocoroAirSensor(CocoroAirEntity, SensorEntity):
    def __init__(self, coordinator, key):
        # Names/unique IDs for Temperature and Humidity exactly match version 1.1.
        super().__init__(coordinator, key)
        self._attr_device_class, self._attr_native_unit_of_measurement = DESCRIPTIONS[
            key
        ]
        if self._attr_native_unit_of_measurement and key not in (
            "cost_today",
            "cost_month",
        ):
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        key = "current_mode" if self._key == "operating_status" else self._key
        return (self.coordinator.data or {}).get(key)

    @property
    def extra_state_attributes(self):
        if self._key in ("temperature", "humidity", "pm25"):
            return {
                "measurement_status": (self.coordinator.data or {}).get(
                    self._key + "_status"
                )
            }
        return None


class CocoroAirSupplySensor(CocoroAirEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, name, field):
        super().__init__(coordinator, name + "_" + field)
        self._supply_name = name
        self._field = field
        if field == "remaining":
            self._attr_native_unit_of_measurement = "%"
        else:
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        value = (
            (self.coordinator.data or {})
            .get("supplies", {})
            .get(self._supply_name, {})
            .get(self._field)
        )
        if self._field == "last_cleaned" and value:
            from homeassistant.util.dt import parse_datetime

            return parse_datetime(value)
        return value

    @property
    def extra_state_attributes(self):
        data = (
            (self.coordinator.data or {}).get("supplies", {}).get(self._supply_name, {})
        )
        return {
            "part_model": data.get("model"),
            "cleaning_interval_hours": data.get("cleaning_interval_hours"),
        }
