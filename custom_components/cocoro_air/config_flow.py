"""Account login, appliance discovery, selection, and reauthentication."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv

from .api import AuthenticationError, CocoroClient, CocoroError, Device
from .const import CONF_DEVICES, DOMAIN, Service
from .http_client import async_create_client

CREDENTIALS = vol.Schema(
    {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}
)


async def async_discover(
    hass: HomeAssistant, credentials: dict[str, Any], services=tuple(Service)
) -> list[Device]:
    """Use an isolated cookie jar per service and close temporary sessions."""
    devices = []
    for service in services:
        client = await async_create_client(hass)
        try:
            api = CocoroClient(
                client, credentials[CONF_EMAIL], credentials[CONF_PASSWORD], service
            )
            devices.extend(await api.async_get_devices())
        finally:
            await client.aclose()
    return devices


def _saved_devices(entry: config_entries.ConfigEntry) -> list[Device]:
    if CONF_DEVICES in entry.data:
        return [
            Device.from_dict(saved)
            if isinstance(saved, dict)
            else Device(Service.AIR, saved, "", "COCORO AIR")
            for saved in entry.data[CONF_DEVICES]
        ]
    return [
        Device(
            Service.AIR,
            entry.data["device_id"],
            entry.data["model_name"],
            entry.title,
            has_humidifier=True,
        )
    ]


def _available(
    hass: HomeAssistant, devices: list[Device], own_entry_id: str | None = None
) -> list[Device]:
    configured = {
        device.key
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.entry_id != own_entry_id
        for device in _saved_devices(entry)
    }
    return [device for device in devices if device.key not in configured]


def _selection(devices: list[Device], defaults: list[str]) -> vol.Schema:
    labels = {
        device.key: f"{device.name} ({device.model_name}, {device.service.upper()})"
        + (f" — {device.place}" if device.place else "")
        for device in devices
    }
    return vol.Schema(
        {vol.Required(CONF_DEVICES, default=defaults): cv.multi_select(labels)}
    )


def _error(err: CocoroError) -> dict[str, str]:
    return {
        "base": "invalid_auth"
        if isinstance(err, AuthenticationError)
        else "cannot_connect"
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one COCORO account with several appliances."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> OptionsFlow:
        return OptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors = {}
        if user_input is not None:
            try:
                self._credentials = dict(user_input)
                self._credentials[CONF_EMAIL] = user_input[CONF_EMAIL].strip()
                devices = await async_discover(self.hass, self._credentials)
                if not devices:
                    return self.async_abort(reason="no_devices_found")
                await self.async_set_unique_id(self._credentials[CONF_EMAIL].casefold())
                self._abort_if_unique_id_configured()
                self._devices = _available(self.hass, devices)
                if not self._devices:
                    return self.async_abort(reason="already_configured")
                return await self.async_step_device()
            except CocoroError as err:
                errors = _error(err)
        return self.async_show_form(
            step_id="user", data_schema=CREDENTIALS, errors=errors
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors = {}
        if user_input is not None:
            # Another flow may have configured an appliance since discovery.
            available = _available(self.hass, self._devices)
            selected = [
                device for device in available if device.key in user_input[CONF_DEVICES]
            ]
            if selected:
                return self.async_create_entry(
                    title="COCORO AIR & WASH",
                    data={
                        **self._credentials,
                        CONF_DEVICES: [device.as_dict() for device in selected],
                    },
                )
            errors["base"] = "select_device"
        return self.async_show_form(
            step_id="device",
            data_schema=_selection(
                self._devices, [device.key for device in self._devices]
            ),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None) -> FlowResult:
        """Update credentials; appliance selection is available through options."""
        return await self._async_step_credentials(user_input, "reconfigure")

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._async_step_credentials(user_input, "reauth_confirm")

    async def _async_step_credentials(self, user_input, step_id) -> FlowResult:
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None
        errors = {}
        if user_input is not None:
            try:
                saved = _saved_devices(entry)
                discovered = await async_discover(
                    self.hass,
                    user_input,
                    tuple(dict.fromkeys(device.service for device in saved)),
                )
                if not {device.key for device in saved} <= {
                    device.key for device in discovered
                }:
                    errors["base"] = "wrong_account"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data={**entry.data, **user_input},
                        reason="reconfigure_successful"
                        if step_id == "reconfigure"
                        else "reauth_successful",
                    )
            except CocoroError as err:
                errors = _error(err)
        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL, default=entry.data[CONF_EMAIL]): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)


class OptionsFlow(config_entries.OptionsFlow):
    """Rediscover appliances and change the selected set."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors = {}
        if not hasattr(self, "_devices"):
            try:
                self._devices = _available(
                    self.hass,
                    await async_discover(self.hass, dict(self._entry.data)),
                    self._entry.entry_id,
                )
            except CocoroError as err:
                return self.async_abort(
                    reason="invalid_auth"
                    if isinstance(err, AuthenticationError)
                    else "cannot_connect"
                )
            # An offline/disconnected appliance remains selectable until explicitly removed.
            known = {device.key for device in self._devices}
            self._devices.extend(
                device
                for device in _saved_devices(self._entry)
                if device.key not in known
            )
        if user_input is not None:
            selected = [
                device
                for device in _available(self.hass, self._devices, self._entry.entry_id)
                if device.key in user_input[CONF_DEVICES]
            ]
            if selected:
                # Keep migrated device names so existing entity IDs remain stable.
                old = {device.key: device for device in _saved_devices(self._entry)}
                selected = [
                    Device(**{**device.as_dict(), "name": old[device.key].name})
                    if device.key in old
                    else device
                    for device in selected
                ]
                self.hass.config_entries.async_update_entry(
                    self._entry,
                    data={
                        **self._entry.data,
                        CONF_DEVICES: [device.as_dict() for device in selected],
                    },
                )
                return self.async_create_entry(title="", data={})
            errors["base"] = "select_device"
        return self.async_show_form(
            step_id="init",
            data_schema=_selection(
                self._devices, [device.key for device in _saved_devices(self._entry)]
            ),
            errors=errors,
        )
