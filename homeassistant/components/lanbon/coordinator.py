"""LANBON API client and DataUpdateCoordinator."""

import asyncio
from contextlib import suppress
from datetime import timedelta
import json
import logging
from typing import Any, override

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=8)


class LanbonApi:
    """HTTP/WebSocket client for the LANBON Mesh root local API."""

    def __init__(self, hass: HomeAssistant, host: str, port: int, token: str) -> None:
        """Initialize the API client."""
        self.hass = hass
        self.host = host
        self.port = port or DEFAULT_PORT
        self.token = token
        self._session = async_get_clientsession(hass)
        self._ws_task: asyncio.Task | None = None
        self._listeners: list = []

    @property
    def base(self) -> str:
        """Return the HTTP base URL."""
        return f"http://{self.host}:{self.port}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def async_get_info(self) -> dict[str, Any]:
        """Fetch host info."""
        async with self._session.get(
            f"{self.base}/api/v1/info", headers=self._headers(), timeout=_TIMEOUT
        ) as resp:
            if resp.status == 401:
                raise PermissionError("invalid token")
            resp.raise_for_status()
            return await resp.json(content_type=None)

    async def async_get_devices(self) -> dict[str, Any]:
        """Fetch host and child device snapshot."""
        async with self._session.get(
            f"{self.base}/api/v1/devices", headers=self._headers(), timeout=_TIMEOUT
        ) as resp:
            if resp.status == 401:
                raise PermissionError("invalid token")
            resp.raise_for_status()
            return await resp.json(content_type=None)

    async def async_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a command to the Mesh root."""
        async with self._session.post(
            f"{self.base}/api/v1/command",
            headers={**self._headers(), "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=_TIMEOUT,
        ) as resp:
            if resp.status == 401:
                raise PermissionError("invalid token")
            resp.raise_for_status()
            data = await resp.json(content_type=None)
            if isinstance(data, dict) and data.get("ok") is False:
                raise HomeAssistantError(str(data.get("err") or "command failed"))
            return data

    def add_listener(self, cb) -> None:
        """Register a WebSocket message listener."""
        self._listeners.append(cb)

    async def async_start_ws(self, on_message) -> None:
        """Start the WebSocket listener loop."""
        self.add_listener(on_message)
        if self._ws_task and not self._ws_task.done():
            return
        self._ws_task = self.hass.async_create_task(self._ws_loop())

    async def async_stop_ws(self) -> None:
        """Stop the WebSocket listener loop."""
        if self._ws_task:
            self._ws_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._ws_task
            self._ws_task = None

    async def _ws_loop(self) -> None:
        url = f"ws://{self.host}:{self.port}/api/v1/ws?token={self.token}"
        while True:
            try:
                async with self._session.ws_connect(url, heartbeat=30) as ws:
                    _LOGGER.debug("LANBON WS connected %s:%s", self.host, self.port)
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                            except json.JSONDecodeError:
                                continue
                            for cb in list(self._listeners):
                                cb(data)
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("LANBON WS error: %s", err)
            await asyncio.sleep(5)


class LanbonCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for LANBON device state."""

    def __init__(self, hass: HomeAssistant, api: LanbonApi) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )
        self.api = api

    @override
    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.api.async_get_devices()
        except PermissionError as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            raise UpdateFailed(str(err)) from err

    def handle_ws(self, data: dict[str, Any]) -> None:
        """Handle a WebSocket state push."""
        if not isinstance(data, dict):
            return
        if data.get("type") == "state" or "devices" in data:
            self.hass.loop.call_soon_threadsafe(self.async_set_updated_data, data)
