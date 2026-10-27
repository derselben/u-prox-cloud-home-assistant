"""Coordinator for polling U-Prox device details."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

import aiohttp
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import UProxApi, UProxApiError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
_MESSAGE_TIMEOUT_SECONDS = 180
_RECONNECT_DELAY_SECONDS = 5


class UProxCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Maintain live panel state received from the cloud WebSocket."""

    def __init__(self, hass: HomeAssistant, api: UProxApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
        )
        self.api = api
        self._serial: int | None = None
        self._websocket: aiohttp.ClientWebSocketResponse | None = None
        self._listener: asyncio.Task | None = None
        self._remove_stop_listener: Any = None

    async def async_start(self, serial: int) -> None:
        """Open the panel session, load initial state, and listen for changes."""
        self._serial = serial
        self._websocket, initial_data = await self.api.async_open_panel_session(serial)
        self.async_set_updated_data(initial_data)
        self._remove_stop_listener = self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, self._handle_homeassistant_stop
        )
        self._listener = self.hass.async_create_background_task(
            self._async_listen(), "u_prox panel session"
        )

    async def async_close(self) -> None:
        """Stop listening and close the panel WebSocket."""
        if self._remove_stop_listener:
            self._remove_stop_listener()
            self._remove_stop_listener = None
        if self._listener:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener
            self._listener = None
        if self._websocket:
            await self._websocket.close()
            self._websocket = None

    @callback
    def _handle_homeassistant_stop(self, event: Event) -> None:
        """Cancel the non-critical socket task as shutdown begins."""
        if self._listener:
            self._listener.cancel()

    async def _async_listen(self) -> None:
        """Apply panelChanges frames and reconnect if the socket drops."""
        while True:
            try:
                websocket = self._websocket
                if websocket is None:
                    await self._async_reopen_panel_session()
                    websocket = self._websocket
                    if websocket is None:
                        return
                while websocket is self._websocket:
                    refresh_in = self.api.token_refresh_in
                    receive_timeout = (
                        _MESSAGE_TIMEOUT_SECONDS
                        if refresh_in is None
                        else min(_MESSAGE_TIMEOUT_SECONDS, max(refresh_in, 0.1))
                    )
                    try:
                        message = await asyncio.wait_for(
                            websocket.receive(), timeout=receive_timeout
                        )
                    except TimeoutError:
                        refresh_in = self.api.token_refresh_in
                        if refresh_in is None or refresh_in > 0:
                            raise UProxApiError("No WebSocket messages for 180 seconds")
                        _LOGGER.debug("Refreshing U-Prox cloud session before token expiry")
                        await self._async_reopen_panel_session()
                        websocket = self._websocket
                        continue

                    if message.type is aiohttp.WSMsgType.TEXT:
                        await self.api.async_log_websocket_message("incoming", message.data)
                    else:
                        await self.api.async_log_websocket_message(
                            "incoming", {"frame_type": message.type.name}
                        )
                    if message.type is aiohttp.WSMsgType.TEXT:
                        event = json.loads(message.data)
                        if event.get("server") == "panelChanges":
                            self._apply_changes(event.get("data"))
                            keepalive = {"client": "keepPanelSession"}
                            await self.api.async_log_websocket_message("outgoing", keepalive)
                            await websocket.send_json(keepalive)
                    elif message.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        break
            except asyncio.CancelledError:
                if self._websocket:
                    await self._websocket.close()
                    self._websocket = None
                raise
            except (UProxApiError, aiohttp.ClientError, TimeoutError, ValueError) as err:
                _LOGGER.warning("U-Prox panel connection interrupted (%s)", type(err).__name__)

            if self._listener is None or self._serial is None:
                return
            self.async_set_update_error(UpdateFailed("U-Prox cloud session disconnected"))
            if self._websocket:
                await self._websocket.close()
                self._websocket = None
            await asyncio.sleep(_RECONNECT_DELAY_SECONDS)

    async def _async_reopen_panel_session(self) -> None:
        """Reauthenticate and replace the panel WebSocket session."""
        if self._websocket:
            await self._websocket.close()
            self._websocket = None
        if self._serial is None:
            return
        await self.api.async_login()
        self._websocket, initial_data = await self.api.async_open_panel_session(
            self._serial
        )
        self.async_set_updated_data(initial_data)

    def _apply_changes(self, changes: Any) -> None:
        """Merge server create/update patches into the current panel state."""
        if not isinstance(changes, dict):
            return
        current = dict(self.data or {})
        for section in ("create", "update"):
            patch = changes.get(section)
            if isinstance(patch, dict):
                self._merge(current, patch)
        self.async_set_updated_data(current)

    @classmethod
    def _merge(cls, target: dict[str, Any], patch: dict[str, Any]) -> None:
        """Recursively apply a partial server update."""
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                cls._merge(target[key], value)
            elif (
                isinstance(value, list)
                and isinstance(target.get(key), list)
                and value
                and all(isinstance(item, dict) for item in value)
            ):
                target[key] = cls._merge_component_list(target[key], value)
            else:
                target[key] = value

    @classmethod
    def _merge_component_list(
        cls, current: list[Any], patch: list[dict[str, Any]]
    ) -> list[Any]:
        """Merge object-list patches by stable serial/index identity."""
        merged = list(current)
        for item in patch:
            if cls._list_item_identity(item) is None:
                continue
            for existing in merged:
                if not isinstance(existing, dict):
                    continue
                if cls._list_items_match(existing, item):
                    cls._merge(existing, item)
                    break
            else:
                merged.append(dict(item))
        return merged

    @staticmethod
    def _list_items_match(existing: dict[str, Any], patch: dict[str, Any]) -> bool:
        """Match by serial when both exist, otherwise fall back to index."""
        existing_serial = existing.get("serial")
        patch_serial = patch.get("serial")
        if existing_serial is not None and patch_serial is not None:
            return str(existing_serial) == str(patch_serial)

        existing_index = existing.get("index")
        patch_index = patch.get("index")
        return (
            existing_index is not None
            and patch_index is not None
            and str(existing_index) == str(patch_index)
        )

    @staticmethod
    def _list_item_identity(item: dict[str, Any]) -> tuple[str, str] | None:
        """Return the stable identity used by panel component arrays."""
        for key in ("serial", "index"):
            value = item.get(key)
            if value is not None:
                return key, str(value)
        return None