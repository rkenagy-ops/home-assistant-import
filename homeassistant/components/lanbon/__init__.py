"""LANBON integration setup."""

from dataclasses import dataclass
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    Platform,
)
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.entity_platform import async_get_platforms
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, SERVICE_SET_CHANNEL_NAME
from .coordinator import LanbonApi, LanbonCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [Platform.SWITCH]

SERVICE_SET_CHANNEL_NAME_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_ids,
        vol.Required("name"): cv.string,
    }
)


@dataclass
class LanbonRuntimeData:
    """Runtime objects for one config entry."""

    api: LanbonApi
    coordinator: LanbonCoordinator


type LanbonConfigEntry = ConfigEntry[LanbonRuntimeData]


def _find_switch(hass: HomeAssistant, entity_id: str):
    """Return the LANBON switch entity for entity_id, if any."""
    for platform in async_get_platforms(hass, DOMAIN):
        if platform.domain != "switch":
            continue
        ent = platform.entities.get(entity_id)
        if ent is not None:
            return ent
    return None


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the LANBON component."""

    async def async_set_channel_name(call: ServiceCall) -> None:
        """Rename a LANBON switch channel on the panel."""
        name = str(call.data["name"]).strip()
        for entity_id in call.data[ATTR_ENTITY_ID]:
            ent = _find_switch(hass, entity_id)
            if ent is None:
                raise ServiceValidationError(
                    f"{entity_id} is not a loaded LANBON switch"
                )
            await ent.async_set_channel_name(name)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CHANNEL_NAME,
        async_set_channel_name,
        schema=SERVICE_SET_CHANNEL_NAME_SCHEMA,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LanbonConfigEntry) -> bool:
    """Set up LANBON from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, 8765)
    token = entry.data[CONF_TOKEN]
    api = LanbonApi(hass, host, port, token)
    coordinator = LanbonCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = LanbonRuntimeData(api=api, coordinator=coordinator)

    host_mac = (entry.data.get("mac") or "").upper()
    data = coordinator.data or {}
    host_info = data.get("host") or {}
    if not host_mac:
        host_mac = str(host_info.get("mac") or host).upper()

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
    await api.async_start_ws(coordinator.handle_ws)

    @callback
    def _on_entity_registry_updated(event) -> None:
        """Push HA UI rename to the panel via name_set."""
        if event.data.get("action") != "update":
            return
        changes = event.data.get("changes") or {}
        if "name" not in changes:
            return
        entity_id = event.data.get("entity_id")
        if not entity_id or not str(entity_id).startswith("switch."):
            return
        ereg = er.async_get(hass)
        entry_er = ereg.async_get(entity_id)
        if (
            entry_er is None
            or entry_er.config_entry_id != entry.entry_id
            or entry_er.name is None
        ):
            return
        ent = _find_switch(hass, entity_id)
        if ent is None:
            return
        if getattr(ent, "_suppress_registry_push", False):
            return
        new_name = str(entry_er.name).strip()
        if not new_name or new_name == ent.name:
            return

        async def _push() -> None:
            try:
                await ent.async_set_channel_name(new_name)
            except Exception:
                _LOGGER.exception("Failed to push rename for %s", entity_id)

        hass.async_create_task(_push())

    entry.async_on_unload(
        hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, _on_entity_registry_updated
        )
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LanbonConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False
    await entry.runtime_data.api.async_stop_ws()
    return True
