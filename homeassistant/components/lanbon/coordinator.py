"""LANBON DataUpdateCoordinator."""

from datetime import timedelta
import logging
from typing import Any, override

from aiolanbon import LanbonAuthError, LanbonClient, LanbonError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class LanbonCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for LANBON device state."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, client: LanbonClient
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )
        self.client = client

    @override
    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.get_devices()
        except LanbonAuthError as err:
            raise UpdateFailed(str(err)) from err
        except LanbonError as err:
            raise UpdateFailed(str(err)) from err

    def handle_ws(self, data: dict[str, Any]) -> None:
        """Handle a WebSocket state push."""
        if not isinstance(data, dict):
            return
        if data.get("type") == "state" or "devices" in data:
            self.hass.loop.call_soon_threadsafe(self.async_set_updated_data, data)
