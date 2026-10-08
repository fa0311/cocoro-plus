"""Entity identity and device registry information."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CocoroCoordinator


class CocoroEntity(CoordinatorEntity[CocoroCoordinator]):
    """Read from a shared coordinator; retain original AIR unique IDs."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CocoroCoordinator, key: str) -> None:
        super().__init__(coordinator)
        device = coordinator.device
        self._attr_unique_id = f"{device.device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            name=device.name,
            manufacturer="Sharp",
            model=device.model_name,
            suggested_area=device.place or None,
        )
