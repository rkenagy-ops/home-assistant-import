"""Tests for LANBON switch entities."""

from unittest.mock import AsyncMock

from homeassistant.components.lanbon.const import DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import CHILD_MAC, MAC

from tests.common import MockConfigEntry


def _entity_id(entity_registry: er.EntityRegistry, unique_id: str) -> str:
    entry = entity_registry.async_get_entity_id("switch", DOMAIN, unique_id)
    assert entry is not None
    return entry


async def test_switch_turn_on_off(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_api: AsyncMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test turning switches on and off."""
    living = _entity_id(entity_registry, f"{MAC}_0")
    child = _entity_id(entity_registry, f"{CHILD_MAC}_0")

    await hass.services.async_call(
        "switch",
        "turn_off",
        {ATTR_ENTITY_ID: living},
        blocking=True,
    )
    payload = mock_api.async_command.await_args.args[0]
    assert payload == {
        "mac": MAC,
        "op": "switch_set",
        "index": 0,
        "on": False,
    }

    await hass.services.async_call(
        "switch",
        "turn_on",
        {ATTR_ENTITY_ID: child},
        blocking=True,
    )
    payload = mock_api.async_command.await_args.args[0]
    assert payload == {
        "mac": CHILD_MAC,
        "op": "switch_set",
        "index": 0,
        "on": True,
    }


async def test_switch_unique_ids(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test switch unique IDs are stable."""
    living = entity_registry.async_get(_entity_id(entity_registry, f"{MAC}_0"))
    child = entity_registry.async_get(_entity_id(entity_registry, f"{CHILD_MAC}_0"))
    assert living is not None
    assert child is not None
    assert living.unique_id == f"{MAC}_0"
    assert child.unique_id == f"{CHILD_MAC}_0"


async def test_initial_states(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test initial switch states from the device snapshot."""
    living = _entity_id(entity_registry, f"{MAC}_0")
    kitchen = _entity_id(entity_registry, f"{MAC}_1")
    child = _entity_id(entity_registry, f"{CHILD_MAC}_0")
    assert hass.states.get(living).state == STATE_ON
    assert hass.states.get(kitchen).state == STATE_OFF
    assert hass.states.get(child).state == STATE_OFF


async def test_switch_unavailable_when_coordinator_fails(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Coordinator failure marks switches unavailable."""
    entry = setup_integration
    living = _entity_id(entity_registry, f"{MAC}_0")
    entry.runtime_data.coordinator.last_update_success = False
    entry.runtime_data.coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert hass.states.get(living).state == "unavailable"


async def test_registry_rename_ignores_other_domains(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_api: AsyncMock,
) -> None:
    """Registry updates for non-switch entities are ignored."""
    mock_api.async_command.reset_mock()
    hass.bus.async_fire(
        er.EVENT_ENTITY_REGISTRY_UPDATED,
        {"action": "create", "entity_id": "light.x", "changes": {}},
    )
    await hass.async_block_till_done()
    mock_api.async_command.assert_not_awaited()
