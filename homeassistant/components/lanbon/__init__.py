"""LANBON integration setup."""

from dataclasses import dataclass

from aiolanbon import LanbonClient

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import LanbonCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [Platform.SWITCH]


@dataclass
class LanbonRuntimeData:
    """Runtime objects for one config entry."""

    client: LanbonClient
    coordinator: LanbonCoordinator


type LanbonConfigEntry = ConfigEntry[LanbonRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the LANBON component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LanbonConfigEntry) -> bool:
    """Set up LANBON from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    token = entry.data[CONF_TOKEN]
    client = LanbonClient(host, port, token, async_get_clientsession(hass))
    coordinator = LanbonCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = LanbonRuntimeData(client=client, coordinator=coordinator)

    host_mac = str(entry.data.get("mac") or "").upper()
    data = coordinator.data or {}
    host_info = data.get("host") or {}
    if not host_mac:
        host_mac = str(host_info.get("mac") or "").upper()

    registry = dr.async_get(hass)
    hub = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, host_mac)},
        manufacturer="LANBON",
        name=host_info.get("name") or f"LANBON {host_mac[-4:]}",
        model=str(host_info.get("kind") or "host"),
    )

    for dev in data.get("devices") or []:
        mac = str(dev.get("mac") or "").upper()
        if not mac or mac == host_mac:
            continue
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, mac)},
            manufacturer="LANBON",
            name=dev.get("name") or f"LANBON {mac[-4:]}",
            model=str(dev.get("kind") or "node"),
            via_device_id=hub.id,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_create_background_task(
        hass,
        client.ws_listen(coordinator.handle_ws),
        name="lanbon-ws",
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LanbonConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
