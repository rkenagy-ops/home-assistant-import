"""Tests for LANBON setup."""

from unittest.mock import AsyncMock

from aiolanbon import LanbonError
import pytest

from homeassistant.components.lanbon.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import CHILD_MAC, MAC

from tests.common import MockConfigEntry


def _entity_id(entity_registry: er.EntityRegistry, unique_id: str) -> str:
    entry = entity_registry.async_get_entity_id("switch", DOMAIN, unique_id)
    assert entry is not None
    return entry


async def test_setup_and_unload(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_api: AsyncMock,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test setup creates devices/entities and unload succeeds."""
    entry = setup_integration
    assert entry.state is ConfigEntryState.LOADED
    mock_api.ws_listen.assert_called()

    hub = device_registry.async_get_device({(DOMAIN, MAC)})
    child = device_registry.async_get_device({(DOMAIN, CHILD_MAC)})
    assert hub is not None
    assert child is not None
    assert child.via_device_id == hub.id

    living = _entity_id(entity_registry, f"{MAC}_0")
    kitchen = _entity_id(entity_registry, f"{MAC}_1")
    child_sw = _entity_id(entity_registry, f"{CHILD_MAC}_0")
    assert hass.states.get(living).state == STATE_ON
    assert hass.states.get(kitchen).state == STATE_OFF
    assert hass.states.get(child_sw).state == STATE_OFF

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_command_failure_raises(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_api: AsyncMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Failed device commands surface as HomeAssistantError."""
    kitchen = _entity_id(entity_registry, f"{MAC}_1")
    mock_api.command.side_effect = LanbonError("busy")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {ATTR_ENTITY_ID: kitchen},
            blocking=True,
        )


async def test_ws_state_push(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """WebSocket state pushes update coordinator-backed entities."""
    entry = setup_integration
    living = _entity_id(entity_registry, f"{MAC}_0")
    kitchen = _entity_id(entity_registry, f"{MAC}_1")
    coordinator = entry.runtime_data.coordinator
    coordinator.handle_ws(
        {
            "type": "state",
            "host": {"mac": MAC, "name": "4gang Switch", "kind": "switch"},
            "devices": [
                {
                    "mac": MAC,
                    "kind": "switch",
                    "is_host": True,
                    "available": True,
                    "switches": [False, True],
                    "channel_names": ["Living", "Kitchen"],
                }
            ],
        }
    )
    await hass.async_block_till_done()
    assert hass.states.get(living).state == STATE_OFF
    assert hass.states.get(kitchen).state == STATE_ON
