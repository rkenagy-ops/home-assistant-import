"""Shared fixtures for LANBON tests."""

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.components.lanbon.const import DOMAIN
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry

HOST = "192.168.0.106"
PORT = 8765
TOKEN = "a" * 32
MAC = "DCDA0C3BC764"
CHILD_MAC = "AABBCCDDEEFF"

INFO_ROOT: dict[str, Any] = {
    "proto": 1,
    "mac": MAC.lower(),
    "name": "4gang Switch",
    "type_name": "4gang Switch",
    "sw_type": 224,
    "mesh_level": 1,
    "is_root": True,
    "port": PORT,
}

DEVICES: dict[str, Any] = {
    "host": {
        "mac": MAC,
        "name": "4gang Switch",
        "kind": "switch",
        "is_root": True,
    },
    "devices": [
        {
            "mac": MAC,
            "name": "4gang Switch",
            "kind": "switch",
            "is_host": True,
            "available": True,
            "switches": [True, False],
            "channel_names": ["Living", "Kitchen", "  "],
        },
        {
            "mac": CHILD_MAC,
            "name": "Child Switch",
            "kind": "cover_switch",
            "is_host": False,
            "available": True,
            "switches": [False],
            "channel_names": ["Child"],
        },
        {
            "mac": "112233445566",
            "name": "Ignored",
            "kind": "light",
            "is_host": False,
            "available": True,
            "switches": "bad",
        },
        {
            "mac": "778899001122",
            "name": "No switches",
            "kind": "switch",
            "is_host": False,
            "available": True,
        },
    ],
}


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=MAC,
        title="4gang Switch",
        data={
            CONF_HOST: HOST,
            CONF_PORT: PORT,
            CONF_TOKEN: TOKEN,
            "mac": MAC,
            "sw_type": 224,
            "type_name": "4gang Switch",
        },
    )


@pytest.fixture
def mock_api() -> Generator[AsyncMock]:
    """Mock aiolanbon client methods used during setup and control."""
    with (
        patch(
            "homeassistant.components.lanbon.config_flow.LanbonClient.get_info",
            new_callable=AsyncMock,
            return_value=INFO_ROOT,
        ),
        patch(
            "homeassistant.components.lanbon.LanbonClient.get_info",
            new_callable=AsyncMock,
            return_value=INFO_ROOT,
        ),
        patch(
            "homeassistant.components.lanbon.LanbonClient.get_devices",
            new_callable=AsyncMock,
            return_value=DEVICES,
        ) as mock_devices,
        patch(
            "homeassistant.components.lanbon.LanbonClient.command",
            new_callable=AsyncMock,
            return_value={"ok": True},
        ) as mock_command,
        patch(
            "homeassistant.components.lanbon.LanbonClient.ws_listen",
            new_callable=AsyncMock,
        ) as mock_ws,
    ):
        mock = AsyncMock()
        mock.get_devices = mock_devices
        mock.command = mock_command
        mock.ws_listen = mock_ws
        # Keep old names for existing test assertions that used async_* prefix.
        mock.async_get_devices = mock_devices
        mock.async_command = mock_command
        mock.async_start_ws = mock_ws
        mock.async_stop_ws = AsyncMock()
        yield mock


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AsyncMock,
) -> MockConfigEntry:
    """Set up the LANBON integration."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
