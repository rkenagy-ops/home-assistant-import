"""The OpenRGB integration."""

import logging
from typing import Any

from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry

from .const import DOMAIN, UID_SEPARATOR
from .coordinator import OpenRGBConfigEntry, OpenRGBCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.SELECT]

# Keys used to embed the connection path as a trailing part, which made a device
# look new whenever it reconnected on a different path
_LEGACY_KEY_PARTS = 6


def _stable_key(legacy_key: str) -> str | None:
    """Convert a legacy connection path key to the serial based form.

    Legacy keys are ``entry_id||TYPE||vendor||description||serial||location``.
    Keys that are not in that shape, such as the SDK server device and the
    profile select entity, are left alone. Returns None when nothing changes.
    """
    parts = legacy_key.split(UID_SEPARATOR)
    if len(parts) != _LEGACY_KEY_PARTS:
        return None

    entry_id, device_type, vendor, description, serial, location = parts

    # "none" is what the legacy key builder wrote for a value the device did not
    # report, so it means absent rather than being a usable discriminator
    serial = serial.strip()
    if serial == "none":
        serial = ""
    if location == "none":
        location = ""

    new_key = UID_SEPARATOR.join(
        (entry_id, device_type, vendor, description, serial or location or "none")
    )
    return new_key if new_key != legacy_key else None


async def _async_migrate_device_keys(
    hass: HomeAssistant, entry: OpenRGBConfigEntry
) -> None:
    """Rewrite registered identifiers that still embed the connection path.

    Without this, every device reporting a serial would be registered again the
    first time the new key is generated, orphaning the existing entity along
    with anything referencing it.
    """
    entity_registry = er.async_get(hass)

    @callback
    def _migrate_entity(entity_entry: er.RegistryEntry) -> dict[str, Any] | None:
        new_key = _stable_key(entity_entry.unique_id)
        if new_key is None:
            return None
        if entity_registry.async_get_entity_id(
            entity_entry.domain, entity_entry.platform, new_key
        ):
            # A previous duplicate already occupies the stable identifier
            _LOGGER.debug(
                "Not migrating %s, the stable identifier is already in use",
                entity_entry.entity_id,
            )
            return None
        return {"new_unique_id": new_key}

    await er.async_migrate_entries(hass, entry.entry_id, _migrate_entity)

    # Device identifiers have no equivalent helper, but they carry the area and
    # any user assigned name, so they are migrated too
    device_registry = dr.async_get(hass)
    for device_entry in dr.async_entries_for_config_entry(
        device_registry, entry.entry_id
    ):
        for domain, identifier in device_entry.identifiers:
            if domain != DOMAIN:
                continue
            new_key = _stable_key(identifier)
            if new_key is None:
                continue
            if device_registry.async_get_device_by_identifier(
                (DOMAIN, new_key), entry.entry_id
            ):
                _LOGGER.debug(
                    "Not migrating device %s, the stable identifier is already in use",
                    device_entry.id,
                )
                continue
            device_registry.async_update_device(
                device_entry.id,
                new_identifiers=(device_entry.identifiers - {(domain, identifier)})
                | {(DOMAIN, new_key)},
            )


def _setup_server_device_registry(
    hass: HomeAssistant, entry: OpenRGBConfigEntry, coordinator: OpenRGBCoordinator
):
    """Set up device registry for the OpenRGB SDK server."""
    device_registry = dr.async_get(hass)

    # Create the parent OpenRGB SDK server device
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.data[CONF_NAME],
        model="OpenRGB SDK Server",
        manufacturer="OpenRGB",
        sw_version=coordinator.get_client_protocol_version(),
        entry_type=dr.DeviceEntryType.SERVICE,
    )


async def async_setup_entry(hass: HomeAssistant, entry: OpenRGBConfigEntry) -> bool:
    """Set up OpenRGB from a config entry."""
    await _async_migrate_device_keys(hass, entry)

    coordinator = OpenRGBCoordinator(hass, entry)

    await coordinator.async_config_entry_first_refresh()

    # The server device must be created first as other devices are children of it
    _setup_server_device_registry(hass, entry, coordinator)

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: OpenRGBConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: OpenRGBConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allows removal of device if it is no longer connected."""
    coordinator = entry.runtime_data

    for domain, identifier in device_entry.identifiers:
        if domain != DOMAIN:
            continue

        # Block removal of the OpenRGB SDK Server device
        if identifier == entry.entry_id:
            return False

        # Block removal of the OpenRGB device if it is still connected
        if identifier in coordinator.data:
            return False

    # Device is not connected or is not an OpenRGB device, allow removal
    return True
