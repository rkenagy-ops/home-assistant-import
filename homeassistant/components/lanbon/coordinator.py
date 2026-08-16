"""LANBON DataUpdateCoordinator."""

from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any, override

from aiolanbon import LanbonAuthError, LanbonClient, LanbonError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

if TYPE_CHECKING:
    from . import LanbonConfigEntry

_LOGGER = logging.getLogger(__name__)


class LanbonCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for LANBON device state."""

    config_entry: LanbonConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: LanbonConfigEntry,
        client: LanbonClient,
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
        """Handle a WebSocket state push from the event loop."""
        if data.get("type") == "state" or "devices" in data:
            self.async_set_updated_data(data)
