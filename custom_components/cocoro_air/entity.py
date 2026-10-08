"""Entity identity and device registry information."""

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, Service
from .coordinator import CocoroCoordinator


class CocoroEntity(CoordinatorEntity[CocoroCoordinator]):
    """Read from a shared coordinator; retain original AIR unique IDs."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CocoroCoordinator, key: str) -> None:
        super().__init__(coordinator)
        device = coordinator.device
        unique_id = f"{device.device_id}_{key}"
        registry = er.async_get(coordinator.hass)
        if any(
            entity.platform == DOMAIN and entity.unique_id == f"{DOMAIN}_{unique_id}"
            for entity in registry.entities.values()
        ):
            unique_id = f"{DOMAIN}_{unique_id}"
        self._attr_unique_id = unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            name=device.name,
            manufacturer="Sharp",
            model=device.model_name,
            suggested_area=device.place or None,
        )


class CocoroAirEntity(CocoroEntity):
    """AIR extensions use the same registry identity as the shared platforms."""

    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        self._key = key
        self._attr_translation_key = key


def coordinators(hass, entry):
    return (
        c
        for c in hass.data[DOMAIN][entry.entry_id].coordinators
        if c.device.service == Service.AIR
    )
