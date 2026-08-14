"""LANBON integration setup."""

from aiolanbon import LanbonClient

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PORT, CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .coordinator import LanbonCoordinator

PLATFORMS = [Platform.SWITCH]

type LanbonConfigEntry = ConfigEntry[LanbonCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: LanbonConfigEntry) -> bool:
    """Set up LANBON from a config entry."""
    client = LanbonClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_TOKEN],
        async_get_clientsession(hass),
    )
    coordinator = LanbonCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    host_mac = str(entry.data[CONF_MAC]).upper()
    data = coordinator.data
    host_info = data["host"]

    registry = dr.async_get(hass)
    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, host_mac)},
        connections={(dr.CONNECTION_NETWORK_MAC, host_mac)},
        manufacturer="LANBON",
        name=host_info.get("name") or f"LANBON {host_mac[-4:]}",
        model=str(host_info.get("kind") or "host"),
    )

    for dev in data["devices"]:
        mac = str(dev["mac"]).upper()
        if mac == host_mac:
            continue
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, mac)},
            connections={(dr.CONNECTION_NETWORK_MAC, mac)},
            manufacturer="LANBON",
            name=dev.get("name") or f"LANBON {mac[-4:]}",
            model=str(dev.get("kind") or "node"),
            via_device=(DOMAIN, host_mac),
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
