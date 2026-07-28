"""Config flow for LANBON."""

import logging
from typing import Any, override

from aiolanbon import LanbonAuthError, LanbonClient, LanbonConnectionError
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import DEFAULT_PORT, DOMAIN, SUPPORTED_PROTO

_LOGGER = logging.getLogger(__name__)


async def _validate(
    hass: HomeAssistant, host: str, port: int, token: str
) -> dict[str, Any]:
    """Validate connectivity and authentication to the Mesh root API."""
    client = LanbonClient(host, port, token, async_get_clientsession(hass))
    return await client.get_info()


class LanbonConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LANBON."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._host: str | None = None
        self._port: int = DEFAULT_PORT
        self._token: str = ""
        self._mac: str | None = None
        self._sw_type: int | None = None
        self._type_name: str = "LANBON"

    def _set_type_name(self, name: Any | None) -> None:
        text = str(name).strip() if name is not None else ""
        self._type_name = text or "LANBON"
        self.context["title_placeholders"] = {"name": self._type_name}

    def _is_root(self, info: dict[str, Any]) -> bool:
        return info.get("is_root") is True

    def _proto_supported(self, info: dict[str, Any]) -> bool:
        return info.get("proto") == SUPPORTED_PROTO

    async def _async_validate_and_create(
        self,
        host: str,
        port: int,
        token: str,
        errors: dict[str, str],
        *,
        update_unique_id: bool,
    ) -> ConfigFlowResult | None:
        """Validate the host and create an entry, or fill errors."""
        try:
            info = await _validate(self.hass, host, port, token)
        except LanbonAuthError:
            errors["base"] = "invalid_auth"
            return None
        except LanbonConnectionError:
            errors["base"] = "cannot_connect"
            return None
        except Exception:
            _LOGGER.exception("LANBON connect failed")
            errors["base"] = "cannot_connect"
            return None

        if not self._proto_supported(info):
            errors["base"] = "unsupported_proto"
            return None
        if not self._is_root(info):
            errors["base"] = "not_root"
            return None

        mac_raw = info.get("mac")
        if not mac_raw:
            errors["base"] = "cannot_connect"
            return None
        mac = str(mac_raw).upper()
        if info.get("sw_type") is not None:
            self._sw_type = info.get("sw_type")
        self._set_type_name(
            info.get("type_name") or info.get("name") or self._type_name
        )
        await self.async_set_unique_id(mac)
        if update_unique_id:
            self._abort_if_unique_id_configured(
                updates={CONF_HOST: host, CONF_PORT: port}
            )
        else:
            self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=self._type_name,
            data={
                CONF_HOST: host,
                CONF_PORT: port,
                CONF_TOKEN: token,
                "mac": mac,
                "sw_type": self._sw_type,
                "type_name": self._type_name,
            },
        )

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            port = int(user_input[CONF_PORT])
            token = user_input[CONF_TOKEN]
            result = await self._async_validate_and_create(
                host, port, token, errors, update_unique_id=False
            )
            if result is not None:
                return result

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=self._host or ""): str,
                    vol.Required(CONF_PORT, default=self._port): int,
                    vol.Required(CONF_TOKEN, default=self._token): str,
                }
            ),
            errors=errors,
        )

    @override
    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle zeroconf discovery."""
        self._host = discovery_info.host
        self._port = discovery_info.port or DEFAULT_PORT
        props = discovery_info.properties or {}
        norm = {
            (k.decode() if isinstance(k, bytes) else k): (
                v.decode() if isinstance(v, bytes) else v
            )
            for k, v in props.items()
        }
        self._mac = (str(norm.get("mac") or "")).upper() or None
        self._token = str(norm.get("token") or "")
        sw_type_raw = norm.get("sw_type")
        try:
            self._sw_type = int(str(sw_type_raw)) if sw_type_raw is not None else None
        except (TypeError, ValueError):
            self._sw_type = None
        self._set_type_name(norm.get("type_name") or discovery_info.name.split(".")[0])

        if self._mac:
            await self.async_set_unique_id(self._mac)
            self._abort_if_unique_id_configured(
                updates={CONF_HOST: self._host, CONF_PORT: self._port}
            )
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered Mesh root."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input.get(CONF_TOKEN) or self._token
            result = await self._async_validate_and_create(
                self._host or "",
                self._port,
                token,
                errors,
                update_unique_id=True,
            )
            if result is not None:
                return result

        self._set_type_name(self._type_name)
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={
                "name": self._type_name,
                "host": self._host or "",
            },
            data_schema=vol.Schema(
                {vol.Required(CONF_TOKEN, default=self._token): str}
            ),
            errors=errors,
        )
