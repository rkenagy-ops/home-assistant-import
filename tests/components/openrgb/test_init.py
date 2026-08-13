"""Tests for the OpenRGB integration init."""

import copy
import socket
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from openrgb.utils import ControllerParsingError, OpenRGBDisconnected, SDKVersionError
import pytest

from homeassistant.components.openrgb import async_remove_config_entry_device
from homeassistant.components.openrgb.const import DOMAIN, SCAN_INTERVAL, UID_SEPARATOR
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from tests.common import MockConfigEntry, async_fire_time_changed


async def test_entry_setup_unload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_openrgb_client: MagicMock,
) -> None:
    """Test entry setup and unload."""
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data is not None

    await hass.config_entries.async_unload(mock_config_entry.entry_id)

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    assert mock_openrgb_client.disconnect.called


@pytest.mark.usefixtures("mock_openrgb_client")
async def test_remove_config_entry_device_server(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that server device cannot be removed."""
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)  # pylint: disable=home-assistant-tests-registry-fixtures
    server_device = device_registry.async_get_device_by_identifier(
        (DOMAIN, mock_config_entry.entry_id), mock_config_entry.entry_id
    )

    assert server_device is not None

    # Try to remove server device - should be blocked
    result = await async_remove_config_entry_device(
        hass, mock_config_entry, server_device
    )

    assert result is False


@pytest.mark.usefixtures("mock_openrgb_client")
async def test_remove_config_entry_device_still_connected(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that connected devices cannot be removed."""
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)  # pylint: disable=home-assistant-tests-registry-fixtures

    # Get a device that's in coordinator.data (still connected)
    devices = dr.async_entries_for_config_entry(
        device_registry, mock_config_entry.entry_id
    )
    rgb_device = next(
        (d for d in devices if d.identifiers != {(DOMAIN, mock_config_entry.entry_id)}),
        None,
    )

    # pylint: disable-next=home-assistant-test-non-deterministic
    if rgb_device:
        # Try to remove device that's still connected - should be blocked
        result = await async_remove_config_entry_device(
            hass, mock_config_entry, rgb_device
        )
        assert result is False


@pytest.mark.usefixtures("mock_openrgb_client")
async def test_remove_config_entry_device_disconnected(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test that disconnected devices can be removed."""
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Create a device that's not in coordinator.data (disconnected)
    entry_id = mock_config_entry.entry_id
    server_device = device_registry.async_get_device_by_identifier(
        (DOMAIN, entry_id), entry_id
    )
    disconnected_device = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={
            (
                DOMAIN,
                UID_SEPARATOR.join(
                    [
                        entry_id,
                        "KEYBOARD",
                        "Old Vendor",
                        "Old Device",
                        "OLD123",
                        "Old Location",
                    ]
                ),
            )
        },
        name="Old Disconnected Device",
        via_device_id=server_device.id,
    )

    # Try to remove disconnected device - should succeed
    result = await async_remove_config_entry_device(
        hass, mock_config_entry, disconnected_device
    )

    assert result is True


@pytest.mark.usefixtures("mock_openrgb_client")
async def test_remove_config_entry_device_with_multiple_identifiers(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test device removal with multiple domain identifiers."""
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entry_id = mock_config_entry.entry_id
    server_device = device_registry.async_get_device_by_identifier(
        (DOMAIN, entry_id), entry_id
    )

    # Create a device with identifiers from multiple domains
    device_with_multiple_identifiers = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={
            ("other_domain", "some_other_id"),  # This should be skipped
            (
                DOMAIN,
                UID_SEPARATOR.join(
                    [
                        entry_id,
                        "DEVICE",
                        "Vendor",
                        "Name",
                        "SERIAL123",
                        "Location",
                    ]
                ),
            ),  # This is a disconnected OpenRGB device
        },
        name="Multi-Domain Device",
        via_device_id=server_device.id,
    )

    # Try to remove device - should succeed because the OpenRGB
    # identifier is disconnected
    result = await async_remove_config_entry_device(
        hass, mock_config_entry, device_with_multiple_identifiers
    )

    assert result is True


@pytest.mark.parametrize(
    ("exception", "expected_state"),
    [
        (ConnectionRefusedError, ConfigEntryState.SETUP_RETRY),
        (OpenRGBDisconnected, ConfigEntryState.SETUP_RETRY),
        (ControllerParsingError, ConfigEntryState.SETUP_RETRY),
        (TimeoutError, ConfigEntryState.SETUP_RETRY),
        (socket.gaierror, ConfigEntryState.SETUP_RETRY),
        (SDKVersionError, ConfigEntryState.SETUP_RETRY),
        (RuntimeError("Test error"), ConfigEntryState.SETUP_RETRY),
    ],
)
async def test_setup_entry_exceptions(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_openrgb_client: MagicMock,
    exception: Exception,
    expected_state: ConfigEntryState,
) -> None:
    """Test setup entry with various exceptions."""
    mock_config_entry.add_to_hass(hass)

    mock_openrgb_client.client_class_mock.side_effect = exception

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is expected_state


async def test_reconnection_on_update_failure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_openrgb_client: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that coordinator reconnects when update fails."""
    mock_config_entry.add_to_hass(hass)

    # Set up the integration
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Verify initial state
    state = hass.states.get("light.ene_dram")
    assert state
    assert state.state == STATE_ON

    # Reset mock call counts after initial setup
    mock_openrgb_client.update.reset_mock()
    mock_openrgb_client.connect.reset_mock()

    # Simulate the first update call failing, then second succeeding
    mock_openrgb_client.update.side_effect = [
        OpenRGBDisconnected(),
        None,  # Second call succeeds after reconnect
    ]

    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    # Verify that disconnect and connect were called (reconnection happened)
    mock_openrgb_client.disconnect.assert_called_once()
    mock_openrgb_client.connect.assert_called_once()

    # Verify that update was called twice (once failed, once after reconnect)
    assert mock_openrgb_client.update.call_count == 2

    # Verify that the light is still available after successful reconnect
    state = hass.states.get("light.ene_dram")
    assert state
    assert state.state == STATE_ON


async def test_reconnection_fails_second_attempt(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_openrgb_client: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that coordinator fails when reconnection also fails."""
    mock_config_entry.add_to_hass(hass)

    # Set up the integration
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Verify initial state
    state = hass.states.get("light.ene_dram")
    assert state
    assert state.state == STATE_ON

    # Reset mock call counts after initial setup
    mock_openrgb_client.update.reset_mock()
    mock_openrgb_client.connect.reset_mock()

    # Simulate the first update call failing, and reconnection also failing
    mock_openrgb_client.update.side_effect = [
        OpenRGBDisconnected(),
        None,  # Second call would succeed if reconnect worked
    ]

    # Simulate connect raising an exception to mimic failed reconnection
    mock_openrgb_client.connect.side_effect = ConnectionRefusedError()

    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    # Verify that the light became unavailable after failed reconnection
    state = hass.states.get("light.ene_dram")
    assert state
    assert state.state == STATE_UNAVAILABLE

    # Verify that disconnect and connect were called (reconnection was attempted)
    mock_openrgb_client.disconnect.assert_called_once()
    mock_openrgb_client.connect.assert_called_once()

    # Verify that update was only called in the first attempt
    mock_openrgb_client.update.assert_called_once()


async def test_normal_update_without_errors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_openrgb_client: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test that normal updates work without triggering reconnection."""
    mock_config_entry.add_to_hass(hass)

    # Set up the integration
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Verify initial state
    state = hass.states.get("light.ene_dram")
    assert state
    assert state.state == STATE_ON

    # Reset mock call counts after initial setup
    mock_openrgb_client.update.reset_mock()
    mock_openrgb_client.connect.reset_mock()

    # Simulate successful update
    mock_openrgb_client.update.side_effect = None
    mock_openrgb_client.update.return_value = None

    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    # Verify that disconnect and connect were NOT called (no reconnection needed)
    mock_openrgb_client.disconnect.assert_not_called()
    mock_openrgb_client.connect.assert_not_called()

    # Verify that update was called only once
    mock_openrgb_client.update.assert_called_once()

    # Verify that the light is still available
    state = hass.states.get("light.ene_dram")
    assert state
    assert state.state == STATE_ON


def _light_unique_ids(
    entity_registry: er.EntityRegistry, entry: MockConfigEntry
) -> set[str]:
    """Return the unique ids of every light registered for the entry."""
    return {
        registry_entry.unique_id
        for registry_entry in er.async_entries_for_config_entry(
            entity_registry, entry.entry_id
        )
        if registry_entry.domain == Platform.LIGHT
    }


async def test_device_key_prefers_serial(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_openrgb_client: MagicMock,
    mock_openrgb_device: MagicMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test that a reported serial is used instead of the connection path."""
    device = copy.deepcopy(mock_openrgb_device)
    device.metadata.serial = "IO2105F28204577"
    device.metadata.location = "HID: /dev/hidraw14"
    mock_openrgb_client.devices = [device]

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _light_unique_ids(entity_registry, mock_config_entry) == {
        UID_SEPARATOR.join(
            [
                mock_config_entry.entry_id,
                "DRAM",
                "ENE",
                "ENE SMBus Device",
                "IO2105F28204577",
            ]
        )
    }


async def test_device_key_ignores_padded_serial(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_openrgb_client: MagicMock,
    mock_openrgb_device: MagicMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test that a serial of only padding is treated as not reported.

    Some controllers answer a serial request with padding when the hardware
    cannot supply one, which must not be mistaken for a real serial.
    """
    device = copy.deepcopy(mock_openrgb_device)
    device.metadata.serial = "                      "
    device.metadata.location = "HID: /dev/hidraw14"
    mock_openrgb_client.devices = [device]

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _light_unique_ids(entity_registry, mock_config_entry) == {
        UID_SEPARATOR.join(
            [
                mock_config_entry.entry_id,
                "DRAM",
                "ENE",
                "ENE SMBus Device",
                "HID: /dev/hidraw14",
            ]
        )
    }


async def test_device_key_survives_changed_connection_path(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_openrgb_client: MagicMock,
    mock_openrgb_device: MagicMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test that unchanged hardware keeps its identity on a new path.

    Connection paths are reassigned when a device reconnects and on every
    reboot, which previously registered the device again as a duplicate.
    """
    device = copy.deepcopy(mock_openrgb_device)
    device.metadata.serial = "IO2105F28204577"
    device.metadata.location = "HID: /dev/hidraw14"
    mock_openrgb_client.devices = [device]

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    unique_ids_before = _light_unique_ids(entity_registry, mock_config_entry)
    assert len(unique_ids_before) == 1

    # Same hardware, reconnected on a different path
    device.metadata.location = "HID: /dev/hidraw31"

    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _light_unique_ids(entity_registry, mock_config_entry) == unique_ids_before


async def test_migrate_legacy_device_key(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_openrgb_client: MagicMock,
    mock_openrgb_device: MagicMock,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test that already registered keys drop the connection path."""
    device = copy.deepcopy(mock_openrgb_device)
    device.metadata.serial = "IO2105F28204577"
    device.metadata.location = "HID: /dev/hidraw31"
    mock_openrgb_client.devices = [device]

    mock_config_entry.add_to_hass(hass)

    # Registered by an earlier version, on a path that has since changed
    legacy_key = UID_SEPARATOR.join(
        [
            mock_config_entry.entry_id,
            "DRAM",
            "ENE",
            "ENE SMBus Device",
            "IO2105F28204577       ",
            "HID: /dev/hidraw14",
        ]
    )
    legacy_entity = entity_registry.async_get_or_create(
        Platform.LIGHT, DOMAIN, legacy_key, config_entry=mock_config_entry
    )
    device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, legacy_key)},
    )
    foreign_device = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={("other_domain", legacy_key)},
    )

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Identifiers owned by another integration are left untouched
    assert device_registry.async_get_device_by_identifier(
        ("other_domain", legacy_key), mock_config_entry.entry_id
    ) == device_registry.async_get(foreign_device.id)

    stable_key = UID_SEPARATOR.join(
        [
            mock_config_entry.entry_id,
            "DRAM",
            "ENE",
            "ENE SMBus Device",
            "IO2105F28204577",
        ]
    )

    # The existing entity was reused rather than replaced by a duplicate
    migrated = entity_registry.async_get(legacy_entity.entity_id)
    assert migrated
    assert migrated.unique_id == stable_key
    assert _light_unique_ids(entity_registry, mock_config_entry) == {stable_key}

    assert device_registry.async_get_device_by_identifier(
        (DOMAIN, stable_key), mock_config_entry.entry_id
    )
    assert not device_registry.async_get_device_by_identifier(
        (DOMAIN, legacy_key), mock_config_entry.entry_id
    )


@pytest.mark.parametrize(
    ("legacy_serial", "legacy_location", "expected_last_part"),
    [
        ("none", "I2C: PIIX4, address 0x70", "I2C: PIIX4, address 0x70"),
        # Neither value was reported, so there is nothing to fall back to
        ("none", "none", "none"),
    ],
)
async def test_migrate_legacy_device_key_without_serial(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_openrgb_client: MagicMock,
    entity_registry: er.EntityRegistry,
    legacy_serial: str,
    legacy_location: str,
    expected_last_part: str,
) -> None:
    """Test that a key for a device without a serial keeps its location."""
    mock_config_entry.add_to_hass(hass)

    legacy_key = UID_SEPARATOR.join(
        [
            mock_config_entry.entry_id,
            "DRAM",
            "ENE",
            "ENE SMBus Device",
            legacy_serial,
            legacy_location,
        ]
    )
    legacy_entity = entity_registry.async_get_or_create(
        Platform.LIGHT, DOMAIN, legacy_key, config_entry=mock_config_entry
    )

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    migrated = entity_registry.async_get(legacy_entity.entity_id)
    assert migrated
    assert migrated.unique_id == UID_SEPARATOR.join(
        [
            mock_config_entry.entry_id,
            "DRAM",
            "ENE",
            "ENE SMBus Device",
            expected_last_part,
        ]
    )


async def test_migrate_keeps_existing_duplicate(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_openrgb_client: MagicMock,
    mock_openrgb_device: MagicMock,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test that migration does not collide with an existing registration.

    A duplicate registered before the fix may already occupy the stable key, so
    the legacy entry has to be left alone instead of failing the migration.
    """
    device = copy.deepcopy(mock_openrgb_device)
    device.metadata.serial = "IO2105F28204577"
    mock_openrgb_client.devices = [device]

    mock_config_entry.add_to_hass(hass)

    stable_key = UID_SEPARATOR.join(
        [
            mock_config_entry.entry_id,
            "DRAM",
            "ENE",
            "ENE SMBus Device",
            "IO2105F28204577",
        ]
    )
    legacy_key = UID_SEPARATOR.join(
        [
            mock_config_entry.entry_id,
            "DRAM",
            "ENE",
            "ENE SMBus Device",
            "IO2105F28204577       ",
            "HID: /dev/hidraw14",
        ]
    )
    entity_registry.async_get_or_create(
        Platform.LIGHT, DOMAIN, stable_key, config_entry=mock_config_entry
    )
    legacy_entity = entity_registry.async_get_or_create(
        Platform.LIGHT, DOMAIN, legacy_key, config_entry=mock_config_entry
    )
    device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, stable_key)},
    )
    legacy_device = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, legacy_key)},
    )

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert device_registry.async_get_device_by_identifier(
        (DOMAIN, legacy_key), mock_config_entry.entry_id
    ) == device_registry.async_get(legacy_device.id)

    untouched = entity_registry.async_get(legacy_entity.entity_id)
    assert untouched
    assert untouched.unique_id == legacy_key
