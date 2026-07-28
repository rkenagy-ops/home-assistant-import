"""Switch entities for LANBON Mesh panels."""

from typing import Any, override

from aiolanbon import LanbonClient, LanbonError

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import LanbonConfigEntry
from .const import DOMAIN
from .coordinator import LanbonCoordinator


def _channel_name(dev: dict[str, Any] | None, index: int) -> str | None:
    if not dev:
        return None
    names = dev.get("channel_names") or []
    if isinstance(names, list) and index < len(names) and names[index]:
        text = str(names[index]).strip()
        return text or None
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LanbonConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up LANBON switch entities from a config entry."""
    coordinator = entry.runtime_data.coordinator
    client = entry.runtime_data.client
    registry = dr.async_get(hass)

    host = (coordinator.data or {}).get("host") or {}
    hub_mac = str(host.get("mac") or "").upper()
    hub = registry.async_get_device({(DOMAIN, hub_mac)}) if hub_mac else None
    hub_id = hub.id if hub else None

    entities: list[LanbonSwitch] = []
    for dev in (coordinator.data or {}).get("devices") or []:
        kind = dev.get("kind")
        switches = dev.get("switches")
        if not isinstance(switches, list):
            continue
        if kind not in ("switch", "cover_switch"):
            continue
        mac = str(dev.get("mac") or "").upper()
        is_host = bool(dev.get("is_host"))
        for idx, _val in enumerate(switches):
            entities.append(
                LanbonSwitch(
                    coordinator,
                    client=client,
                    mac=mac,
                    index=idx,
                    channel_name=_channel_name(dev, idx),
                    is_host=is_host,
                    via_device_id=None if is_host else hub_id,
                )
            )
    async_add_entities(entities)


class LanbonSwitch(CoordinatorEntity[LanbonCoordinator], SwitchEntity):
    """Representation of a LANBON switch channel."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: LanbonCoordinator,
        *,
        client: LanbonClient,
        mac: str,
        index: int,
        channel_name: str | None,
        is_host: bool,
        via_device_id: str | None,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._client = client
        self._mac = mac
        self._index = index
        self._attr_unique_id = f"{mac}_{index}"
        self._attr_name = channel_name or f"Switch {index + 1}"
        device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            manufacturer="LANBON",
            name="LANBON Host" if is_host else f"LANBON {mac[-4:]}",
        )
        if via_device_id is not None:
            device_info["via_device_id"] = via_device_id
        self._attr_device_info = device_info

    def _dev(self) -> dict[str, Any] | None:
        for d in (self.coordinator.data or {}).get("devices") or []:
            if str(d.get("mac") or "").upper() == self._mac:
                return d
        return None

    def _apply_channel_name(self, name: str | None) -> None:
        """Update entity name from device-provided channel_names."""
        new_name = name or f"Switch {self._index + 1}"
        if new_name != self._attr_name:
            self._attr_name = new_name

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        # Refresh the device-provided default name; never overwrite a
        # user registry override (RegistryEntry.name).
        self._apply_channel_name(_channel_name(self._dev(), self._index))
        super()._handle_coordinator_update()

    async def _async_command(self, payload: dict[str, Any]) -> None:
        try:
            await self._client.command(payload)
        except LanbonError as err:
            raise HomeAssistantError(str(err)) from err

    @property
    @override
    def available(self) -> bool:
        """Return True if entity is available."""
        if not super().available:
            return False
        dev = self._dev()
        return bool(dev and dev.get("available", True))

    @property
    @override
    def is_on(self) -> bool | None:
        """Return True if the switch is on."""
        dev = self._dev()
        if not dev:
            return None
        switches = dev.get("switches") or []
        if self._index >= len(switches):
            return None
        return bool(switches[self._index])

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._async_command(
            {"mac": self._mac, "op": "switch_set", "index": self._index, "on": True}
        )
        await self.coordinator.async_request_refresh()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._async_command(
            {"mac": self._mac, "op": "switch_set", "index": self._index, "on": False}
        )
        await self.coordinator.async_request_refresh()
