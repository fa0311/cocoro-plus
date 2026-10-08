"""COCORO AIR & WASH, retaining the original cocoro_air domain."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from inspect import signature

import httpx
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .air import AirDevice
from .api import AuthenticationError, CocoroClient, CocoroError, Device
from .const import CONF_DEVICES, DOMAIN, Service
from .coordinator import CocoroAirCoordinator, CocoroCoordinator
from .http_client import async_create_client
from .services import async_setup_services, async_unload_services
from .wash import WashDevice

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.HUMIDIFIER,
    Platform.SWITCH,
    Platform.FAN,
    Platform.NUMBER,
    Platform.BUTTON,
]


@dataclass
class CocoroRuntime:
    """Resources owned by one configuration entry."""

    clients: list[httpx.AsyncClient]
    coordinators: list[CocoroCoordinator]


@dataclass
class SharedSession:
    """A service cookie jar retained while any matching account entry uses it."""

    api: CocoroClient
    owners: set[str] = field(default_factory=set)


async def _async_acquire_session(hass, entry, service):
    lock = hass.data.setdefault(f"{DOMAIN}_sessions_lock", asyncio.Lock())
    async with lock:
        sessions = hass.data.setdefault(f"{DOMAIN}_sessions", {})
        key = (entry.data[CONF_EMAIL].casefold(), entry.data[CONF_PASSWORD], service)
        if key not in sessions:
            client = await async_create_client(hass)
            api = CocoroClient(
                client, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD], service
            )
            authenticated = False
            try:
                await api.async_login()
                authenticated = True
            finally:
                if not authenticated:
                    await client.aclose()
            sessions[key] = SharedSession(api)
        shared = sessions[key]
        shared.owners.add(entry.entry_id)
        return shared.api


async def _async_release_sessions(hass, entry_id, clients):
    lock = hass.data[f"{DOMAIN}_sessions_lock"]
    async with lock:
        sessions = hass.data[f"{DOMAIN}_sessions"]
        for key, shared in list(sessions.items()):
            if shared.api.client in clients:
                shared.owners.discard(entry_id)
                if not shared.owners:
                    await shared.api.client.aclose()
                    del sessions[key]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up all selected appliances with per-service cookie jars."""
    clients: list[httpx.AsyncClient] = []
    coordinators: list[CocoroCoordinator] = []
    setup_complete = False
    try:
        sessions: dict[Service, CocoroClient] = {}
        for saved in entry.data[CONF_DEVICES]:
            device = Device.from_dict(saved)
            if device.service not in sessions:
                session = sessions[device.service] = await _async_acquire_session(
                    hass, entry, device.service
                )
                clients.append(session.client)
            if device.service == Service.AIR and not device.spec:
                discovered = await sessions[device.service].async_get_devices()
                fresh = next(
                    (item for item in discovered if item.key == device.key), None
                )
                if fresh is None:
                    raise CocoroError("Selected AIR device is no longer registered")
                device = Device.from_dict({**fresh.as_dict(), "name": device.name})
            api = (AirDevice if device.service == Service.AIR else WashDevice)(
                sessions[device.service], device
            )
            coordinator = (
                CocoroAirCoordinator
                if device.service == Service.AIR
                else CocoroCoordinator
            )(hass, api, entry)
            coordinators.append(coordinator)
            # Authenticate once, but allow other appliances to load when one is offline.
            await coordinator.async_refresh()
            if isinstance(coordinator.last_exception, ConfigEntryAuthFailed):
                raise coordinator.last_exception
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = CocoroRuntime(
            clients, coordinators
        )
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        async_setup_services(hass)
        setup_complete = True
    except AuthenticationError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except CocoroError as err:
        raise ConfigEntryNotReady(str(err)) from err
    finally:
        if not setup_complete:
            for coordinator in coordinators:
                await coordinator.async_shutdown()
            await _async_release_sessions(hass, entry.entry_id, clients)
            hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    async def async_close_sessions() -> None:
        await _async_release_sessions(hass, entry.entry_id, clients)

    entry.async_on_unload(async_close_sessions)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload entities, stop polling, and close owned HTTP clients."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    runtime: CocoroRuntime = hass.data[DOMAIN].pop(entry.entry_id)
    for coordinator in runtime.coordinators:
        await coordinator.async_shutdown()
    await _async_release_sessions(hass, entry.entry_id, runtime.clients)
    async_unload_services(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Keep old single-device AIR entries and their entity/device identities."""
    if entry.version > 2:
        return False
    if entry.version == 1:
        data = dict(entry.data)
        if CONF_DEVICES in data:
            # hldh214 v1 stores selected AIR IDs, with options overriding data.
            from .config_flow import async_discover

            selected = set(entry.options.get(CONF_DEVICES, data[CONF_DEVICES]))
            try:
                discovered = await async_discover(hass, data, (Service.AIR,))
            except AuthenticationError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except CocoroError as err:
                raise ConfigEntryNotReady(str(err)) from err
            data[CONF_DEVICES] = [
                device.as_dict()
                for device in discovered
                if device.device_id in selected
            ]
            if selected - {device["device_id"] for device in data[CONF_DEVICES]}:
                raise ConfigEntryNotReady("Selected AIR device is no longer registered")
        else:
            device = Device(
                service=Service.AIR,
                device_id=data.pop("device_id"),
                model_name=data.pop("model_name"),
                name=f"Cocoro Air {entry.data['model_name']}",
                has_humidifier=True,
            )
            data[CONF_DEVICES] = [device.as_dict()]
        # HA 2024.2 predates updating the version through async_update_entry.
        if "version" in signature(hass.config_entries.async_update_entry).parameters:
            hass.config_entries.async_update_entry(entry, data=data, version=2)
        else:
            entry.version = 2
            hass.config_entries.async_update_entry(entry, data=data)
    return True
