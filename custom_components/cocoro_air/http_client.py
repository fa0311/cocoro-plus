"""Owned HTTP clients with Home Assistant's cached TLS configuration."""

import httpx
from homeassistant.core import HomeAssistant
from homeassistant.util.ssl import client_context


async def async_create_client(hass: HomeAssistant) -> httpx.AsyncClient:
    """Create an isolated, closeable session without blocking the event loop.

    HA's shared httpx client cannot be closed and shares cookies across entries.
    Creating a normal client in an executor gives us explicit entry ownership.
    """
    return await hass.async_add_executor_job(
        lambda: httpx.AsyncClient(verify=client_context())
    )
