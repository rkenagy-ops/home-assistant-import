"""Tests for the LANBON coordinator (library HTTP covered by aiolanbon)."""

from unittest.mock import AsyncMock, patch

from aiolanbon import LanbonAuthError, LanbonClient, LanbonConnectionError
import pytest

from homeassistant.components.lanbon.coordinator import LanbonCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed

from .conftest import DEVICES, HOST, PORT, TOKEN

from tests.common import MockConfigEntry


async def test_coordinator_update_failed(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test coordinator maps library failures to UpdateFailed."""
    mock_config_entry.add_to_hass(hass)
    client = LanbonClient(HOST, PORT, TOKEN, async_get_clientsession(hass))
    coordinator = LanbonCoordinator(hass, mock_config_entry, client)
    with (
        patch.object(client, "get_devices", side_effect=LanbonAuthError("bad")),
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_update_data()
    with (
        patch.object(client, "get_devices", side_effect=LanbonConnectionError("down")),
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_update_data()


async def test_coordinator_update_ok(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test coordinator returns device snapshot."""
    mock_config_entry.add_to_hass(hass)
    client = LanbonClient(HOST, PORT, TOKEN, async_get_clientsession(hass))
    coordinator = LanbonCoordinator(hass, mock_config_entry, client)
    with patch.object(client, "get_devices", new=AsyncMock(return_value=DEVICES)):
        assert await coordinator._async_update_data() == DEVICES


async def test_handle_ws_ignores_non_state(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test handle_ws ignores unrelated payloads."""
    mock_config_entry.add_to_hass(hass)
    client = LanbonClient(HOST, PORT, TOKEN, async_get_clientsession(hass))
    coordinator = LanbonCoordinator(hass, mock_config_entry, client)
    coordinator.handle_ws("nope")  # type: ignore[arg-type]
    coordinator.handle_ws({"type": "pong"})
