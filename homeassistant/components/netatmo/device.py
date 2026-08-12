"""Device registry helpers for the Netatmo integration."""

from collections.abc import Iterable
from typing import TYPE_CHECKING

import pyatmo

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import CONF_URL_CONTROL, DOMAIN, MANUFACTURER

if TYPE_CHECKING:
    from .coordinator import NetatmoConfigEntry


@callback
def async_disabled_netatmo_ids(
    hass: HomeAssistant, entry: NetatmoConfigEntry
) -> list[str]:
    """Return the Netatmo ids of every disabled device.

    A superset of the disabled home ids. Module ids never match a home id, so
    passing them through to pyatmo's denylist is harmless and avoids having to
    know which devices are homes before the topology has been fetched.
    """
    return [
        identifier[1]
        for device in dr.async_entries_for_config_entry(
            dr.async_get(hass), entry.entry_id
        )
        if device.disabled_by
        for identifier in device.identifiers
        if identifier[0] == DOMAIN
    ]


@callback
def async_register_parent_devices(
    hass: HomeAssistant, entry: NetatmoConfigEntry, account: pyatmo.AsyncAccount
) -> dict[str, str]:
    """Register a device per home and map Netatmo ids to device registry ids."""
    device_registry = dr.async_get(hass)
    parent_device_ids: dict[str, str] = {}

    for home_id, home_name in account.all_home_names.items():
        device_entry = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, home_id)},
            manufacturer=MANUFACTURER,
            model="Home",
            name=home_name,
            configuration_url=CONF_URL_CONTROL,
        )
        parent_device_ids[home_id] = device_entry.id

    return parent_device_ids


@callback
def async_sync_home_disabled_state(
    hass: HomeAssistant, entry: NetatmoConfigEntry, home_device_ids: Iterable[str]
) -> None:
    """Mirror each home device's disabled state onto its descendants.

    Devices disabled by the user are left alone in both directions, so toggling a
    home never undoes a manual choice.
    """
    device_registry = dr.async_get(hass)

    children: dict[str, list[dr.DeviceEntry]] = {}
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if device.via_device_id:
            children.setdefault(device.via_device_id, []).append(device)

    for home_device_id in home_device_ids:
        home_device = device_registry.async_get(home_device_id)
        assert home_device

        disabled = home_device.disabled_by is not None
        # Walk the whole subtree; a module can be a grandchild via its gateway
        stack = list(children.get(home_device_id, []))
        while stack:
            device = stack.pop()
            stack.extend(children.get(device.id, []))

            if disabled and device.disabled_by is None:
                device_registry.async_update_device(
                    device.id, disabled_by=dr.DeviceEntryDisabler.INTEGRATION
                )
            elif (
                not disabled
                and device.disabled_by is dr.DeviceEntryDisabler.INTEGRATION
            ):
                device_registry.async_update_device(device.id, disabled_by=None)
