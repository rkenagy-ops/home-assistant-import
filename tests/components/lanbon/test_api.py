"""Tests for the LANBON HTTP/WebSocket client."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from homeassistant.components.lanbon.coordinator import LanbonApi, LanbonCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from .conftest import DEVICES, HOST, INFO_ROOT, PORT, TOKEN

from tests.common import MockConfigEntry
from tests.test_util.aiohttp import AiohttpClientMocker


async def test_api_get_info_and_devices(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test info and devices HTTP helpers."""
    aioclient_mock.get(f"http://{HOST}:{PORT}/api/v1/info", json=INFO_ROOT)
    aioclient_mock.get(f"http://{HOST}:{PORT}/api/v1/devices", json=DEVICES)
    api = LanbonApi(hass, HOST, PORT, TOKEN)
    assert await api.async_get_info() == INFO_ROOT
    assert await api.async_get_devices() == DEVICES
    assert api.base == f"http://{HOST}:{PORT}"


async def test_api_auth_errors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test 401 responses become PermissionError."""
    aioclient_mock.get(f"http://{HOST}:{PORT}/api/v1/info", status=401)
    aioclient_mock.get(f"http://{HOST}:{PORT}/api/v1/devices", status=401)
    aioclient_mock.post(f"http://{HOST}:{PORT}/api/v1/command", status=401)
    api = LanbonApi(hass, HOST, PORT, TOKEN)
    with pytest.raises(PermissionError):
        await api.async_get_info()
    with pytest.raises(PermissionError):
        await api.async_get_devices()
    with pytest.raises(PermissionError):
        await api.async_command({"op": "switch_set"})


async def test_api_command_ok_false(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test device-reported command failures raise HomeAssistantError."""
    aioclient_mock.post(
        f"http://{HOST}:{PORT}/api/v1/command",
        json={"ok": False, "err": "busy"},
    )
    api = LanbonApi(hass, HOST, PORT, TOKEN)
    with pytest.raises(HomeAssistantError, match="busy"):
        await api.async_command({"op": "switch_set"})


async def test_api_command_ok_false_without_err(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test ok:false without err uses a default message."""
    aioclient_mock.post(
        f"http://{HOST}:{PORT}/api/v1/command",
        json={"ok": False},
    )
    api = LanbonApi(hass, HOST, PORT, TOKEN)
    with pytest.raises(HomeAssistantError, match="command failed"):
        await api.async_command({"op": "switch_set"})


async def test_api_command_success(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test successful commands return the payload."""
    aioclient_mock.post(
        f"http://{HOST}:{PORT}/api/v1/command",
        json={"ok": True},
    )
    api = LanbonApi(hass, HOST, PORT, TOKEN)
    assert await api.async_command({"op": "switch_set"}) == {"ok": True}


async def test_ws_start_receives_and_stop(hass: HomeAssistant) -> None:
    """Test WebSocket start delivers messages and stop cancels the loop."""
    api = LanbonApi(hass, HOST, PORT, TOKEN)
    received: list[dict] = []

    class _Msg:
        def __init__(self, msg_type, data=None) -> None:
            self.type = msg_type
            self.data = data

    class _WS:
        def __init__(self) -> None:
            self._msgs = [
                _Msg(aiohttp.WSMsgType.TEXT, "{not-json"),
                _Msg(aiohttp.WSMsgType.TEXT, '{"type":"state","devices":[]}'),
                _Msg(aiohttp.WSMsgType.CLOSED),
            ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._msgs:
                raise StopAsyncIteration
            return self._msgs.pop(0)

    connect = MagicMock(return_value=_WS())
    with patch.object(api._session, "ws_connect", connect):
        await api.async_start_ws(received.append)
        # Second start should reuse the running task.
        await api.async_start_ws(received.append)
        for _ in range(50):
            if received:
                break
            await asyncio.sleep(0)
        await api.async_stop_ws()
        await api.async_stop_ws()

    assert received == [{"type": "state", "devices": []}]
    connect.assert_called()


async def test_ws_reconnect_on_error(hass: HomeAssistant) -> None:
    """Test WebSocket errors are logged at debug and the loop retries."""
    api = LanbonApi(hass, HOST, PORT, TOKEN)
    calls = {"n": 0}

    class _BoomWS:
        async def __aenter__(self):
            calls["n"] += 1
            raise OSError("down")

        async def __aexit__(self, *args):
            return False

    with (
        patch.object(api._session, "ws_connect", return_value=_BoomWS()),
        patch(
            "homeassistant.components.lanbon.coordinator.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleep,
    ):
        await api.async_start_ws(lambda _data: None)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await api.async_stop_ws()

    assert calls["n"] >= 1
    sleep.assert_awaited()


async def test_coordinator_update_failed(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test coordinator maps API failures to UpdateFailed."""
    mock_config_entry.add_to_hass(hass)
    api = LanbonApi(hass, HOST, PORT, TOKEN)
    coordinator = LanbonCoordinator(hass, mock_config_entry, api)
    with patch.object(api, "async_get_devices", side_effect=PermissionError("bad")):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
    with patch.object(api, "async_get_devices", side_effect=OSError("down")):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()


async def test_handle_ws_ignores_non_state(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test handle_ws ignores unrelated payloads."""
    mock_config_entry.add_to_hass(hass)
    api = LanbonApi(hass, HOST, PORT, TOKEN)
    coordinator = LanbonCoordinator(hass, mock_config_entry, api)
    coordinator.handle_ws("nope")  # type: ignore[arg-type]
    coordinator.handle_ws({"type": "pong"})
