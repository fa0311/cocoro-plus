"""Shared authentication and discovery for the COCORO web APIs."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Any

import httpx

from .const import AUTH_HOST, BASE_URL, OBJECT_IDS, REQUEST_TIMEOUT, USER_AGENT, Service


class CocoroError(Exception):
    """A cloud request failed."""


class AuthenticationError(CocoroError):
    """Authentication failed or requires interactive verification."""


class CocoroResponseError(CocoroError):
    """An embedded API status failed; retain details without logging its body."""

    def __init__(self, status: int, info: str | None) -> None:
        super().__init__(f"COCORO service returned status {status}")
        self.status = status
        self.info = info


@dataclass(frozen=True)
class Device:
    """Appliance capabilities and location needed by device and weather features."""

    service: Service
    device_id: str
    model_name: str
    name: str
    place: str = ""
    has_humidifier: bool = False
    has_pm25: bool = True
    has_dust: bool = True
    spec: dict[str, Any] = field(default_factory=dict)
    zip_code: str = ""

    @property
    def key(self) -> str:
        """Stable selection key across services."""
        return f"{self.service}:{self.device_id}"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Device:
        return cls(**{**data, "service": Service(data["service"])})


class _LoginForm(HTMLParser):
    """Handle different attribute order, quoting, and HTML entities."""

    state: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "input" and values.get("name") == "state":
            self.state = values.get("value")


def _state(response: httpx.Response) -> str:
    form = _LoginForm()
    form.feed(response.text)
    if not form.state:
        raise AuthenticationError("Login form is unavailable")
    return form.state


class CocoroClient:
    """A service session with a caller-owned, isolated HTTP client.

    Never closes the caller's client or logs credentials, tokens, redirect
    queries, or response bodies. AIR and WASH have separate OAuth callbacks.
    """

    def __init__(
        self, client: httpx.AsyncClient, email: str, password: str, service: Service
    ) -> None:
        self.client = client
        self.email = email
        self._password = password
        self.service = service
        self._authenticated = False
        self._login_lock = asyncio.Lock()
        self._generation = 0

    async def async_login(self, *, generation: int | None = None) -> None:
        """Complete the COCORO MEMBERS login for this service."""
        async with self._login_lock:
            if generation is not None and self._generation != generation:
                return
            self._authenticated = False
            try:
                response = await self.client.get(
                    f"{BASE_URL}/v1/cocoro-{self.service}/login",
                    timeout=REQUEST_TIMEOUT,
                    headers={"User-Agent": USER_AGENT},
                )
                response.raise_for_status()
                redirect = httpx.URL(response.json()["redirectUrl"])
                response = await self.client.get(
                    redirect,
                    follow_redirects=True,
                    timeout=REQUEST_TIMEOUT,
                    headers={"User-Agent": USER_AGENT},
                )
                if (
                    response.url.host == AUTH_HOST
                    and response.url.path == "/u/login/identifier"
                ):
                    response = await self.client.post(
                        response.url,
                        data={
                            "state": _state(response),
                            "username": self.email,
                            "captcha": "",
                            "js-available": "true",
                            "webauthn-available": "false",
                            "is-brave": "false",
                            "webauthn-platform-available": "false",
                            "action": "default",
                        },
                        follow_redirects=True,
                        timeout=REQUEST_TIMEOUT,
                        headers={"User-Agent": USER_AGENT},
                    )
                if (
                    response.url.host == AUTH_HOST
                    and response.url.path == "/u/login/password"
                ):
                    response = await self.client.post(
                        response.url,
                        data={
                            "state": _state(response),
                            "username": self.email,
                            "password": self._password,
                            "action": "default",
                        },
                        follow_redirects=True,
                        timeout=REQUEST_TIMEOUT,
                        headers={"User-Agent": USER_AGENT},
                    )
                if (
                    response.status_code != 200
                    or response.url.host != httpx.URL(BASE_URL).host
                    or response.url.path.rstrip("/") != f"/{self.service}"
                    or response.url.params.get("login") not in (None, "success")
                ):
                    raise AuthenticationError("Login did not complete")
            except httpx.HTTPStatusError as err:
                if err.response.status_code in (400, 401, 403):
                    raise AuthenticationError("Authentication was rejected") from None
                raise CocoroError("Authentication service is unavailable") from None
            except httpx.RequestError:
                raise CocoroError("Cannot reach authentication service") from None
            self._authenticated = True
            self._generation += 1

    async def async_request(
        self, path: str, envelope: str | None, *, method: str = "GET", **kwargs: Any
    ) -> dict[str, Any]:
        """Read the BFF status inside HTTP 200; reauthenticate at most once."""
        if not self._authenticated:
            await self.async_login(generation=self._generation)
        retried = False
        while True:
            generation = self._generation
            try:
                response = await self.client.request(
                    method,
                    f"{BASE_URL}/v1/cocoro-{self.service}/{path}",
                    timeout=REQUEST_TIMEOUT,
                    headers={"User-Agent": USER_AGENT},
                    **kwargs,
                )
                if response.status_code == 401:
                    status = response.status_code
                    result: dict[str, Any] = {}
                else:
                    response.raise_for_status()
                    envelopes = response.json()
                    result = (
                        envelopes[envelope]
                        if envelope is not None
                        else next(iter(envelopes.values()))
                    )
                    status = result["status"]
                if status == 401:
                    if retried:
                        raise AuthenticationError("Service authentication expired")
                    await self.async_login(generation=generation)
                    retried = True
                    continue
                if status == 404:
                    raise CocoroError("Device is unavailable or no longer registered")
                if status < 200 or status >= 300:
                    raise CocoroResponseError(status, result["body"].get("info"))
                return result["body"]
            except httpx.HTTPStatusError as err:
                if err.response.status_code == 404:
                    raise CocoroError("Device is unavailable") from None
                raise CocoroError(
                    f"COCORO HTTP status {err.response.status_code}"
                ) from None
            except httpx.RequestError:
                raise CocoroError("Cannot reach COCORO service") from None

    async def async_get_devices(self) -> list[Device]:
        """Discover only air cleaners and washers from their own services."""
        body = await self.async_request("devices/cocoro-home", "devices_cocorohome_003")
        raw_devices = [
            raw
            for raw in body["devices"]
            if raw["object_id"].lower() == OBJECT_IDS[self.service]
        ]
        devices = []
        air_infos = {}
        if self.service == Service.AIR and raw_devices:
            infos = await self.async_request("deviceinfos", "device_infos_003_010")
            air_infos = {item["device_id"]: item for item in infos["devices"]}
        for raw in raw_devices:
            device_id = raw["device_id"]
            if self.service == Service.AIR:
                info = air_infos[device_id]
            else:
                info = await self.async_request(
                    "deviceinfo", "deviceinfo_010", params={"device_id": device_id}
                )
            model = info["model_name"]
            spec = info.get("spec") or {}
            name = info.get("device_name") or f"COCORO {self.service.upper()} {model}"
            place = info.get("place") or ""
            devices.append(
                Device(
                    service=self.service,
                    device_id=device_id,
                    model_name=model,
                    name=name,
                    place=place,
                    has_pm25=self.service == Service.AIR
                    and spec.get("hasPM25Sensor", False),
                    has_dust=self.service == Service.AIR
                    and spec.get("hasDustSensor", False),
                    spec=spec if self.service == Service.AIR else {},
                    zip_code=info.get("zip_code") or "",
                    has_humidifier=(
                        self.service == Service.AIR
                        and spec.get("hasHumidFunc", False)
                        and not spec.get("cannotControlHumid", False)
                    ),
                )
            )
        return devices
