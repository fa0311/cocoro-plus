"""One periodic refresh per appliance, shared by all its entities."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .air import AirDevice
from .api import AuthenticationError, CocoroError
from .const import UPDATE_INTERVAL
from .wash import WashDevice

_LOGGER = logging.getLogger(__name__)


class CocoroCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Expose authentication/network failures through Home Assistant."""

    def __init__(self, hass: HomeAssistant, api: AirDevice | WashDevice) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"COCORO {api.device.service.upper()} {api.device.model_name}",
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )
        self.api = api
        self.device = api.device

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.api.async_update()
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except CocoroError as err:
            raise UpdateFailed(str(err)) from err
