"""Tests for LANBON setup and services."""

from unittest.mock import AsyncMock

import pytest

from homeassistant.components.lanbon.const import DOMAIN, SERVICE_SET_CHANNEL_NAME
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
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
    """Test setup creates devices/entities and unload stops the WebSocket."""
    entry = setup_integration
    assert entry.state is ConfigEntryState.LOADED
    mock_api.async_start_ws.assert_awaited()

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
    mock_api.async_stop_ws.assert_awaited()
    assert hass.services.has_service(DOMAIN, SERVICE_SET_CHANNEL_NAME)


async def test_service_remains_after_unload(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """Service stays registered so automations keep working after unload."""
    entry = setup_integration
    assert hass.services.has_service(DOMAIN, SERVICE_SET_CHANNEL_NAME)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.services.has_service(DOMAIN, SERVICE_SET_CHANNEL_NAME)


async def test_set_channel_name_service(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_api: AsyncMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test renaming a channel through the service."""
    living = _entity_id(entity_registry, f"{MAC}_0")
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_CHANNEL_NAME,
        {ATTR_ENTITY_ID: living, "name": "Hall"},
        blocking=True,
    )
    mock_api.async_command.assert_awaited()
    payload = mock_api.async_command.await_args.args[0]
    assert payload["op"] == "name_set"
    assert payload["mac"] == MAC
    assert payload["index"] == 0
    assert payload["name"] == "Hall"
    assert "Hall" in hass.states.get(living).name


async def test_set_channel_name_invalid_entity(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """Invalid targets raise a service validation error."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_CHANNEL_NAME,
            {ATTR_ENTITY_ID: "switch.not_lanbon", "name": "X"},
            blocking=True,
        )


async def test_command_failure_raises(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_api: AsyncMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Failed device commands surface as HomeAssistantError."""
    kitchen = _entity_id(entity_registry, f"{MAC}_1")
    mock_api.async_command.side_effect = HomeAssistantError("busy")
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


async def test_registry_rename_pushes_to_device(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_api: AsyncMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """UI registry renames are pushed to the panel for this entry only."""
    living = _entity_id(entity_registry, f"{MAC}_0")
    mock_api.async_command.reset_mock()
    entity_registry.async_update_entity(living, name="Renamed")
    await hass.async_block_till_done()
    mock_api.async_command.assert_awaited()
    payload = mock_api.async_command.await_args.args[0]
    assert payload["op"] == "name_set"
    assert payload["name"] == "Renamed"
