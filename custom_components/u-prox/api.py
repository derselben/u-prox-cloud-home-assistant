"""Client for the U-Prox cloud API and panel-session WebSocket."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time
from typing import Any
from urllib.parse import quote

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .message_log import UProxMessageLogger

CLOUD_API_URL = "https://account.maks.systems:10001"
PANEL_SESSION_URL = "wss://c3po.maks.systems:50100/userSession"
REGION = "international"
TOKEN_REFRESH_MARGIN_SECONDS = 60
_LOGGER = logging.getLogger(__name__)


class UProxApiError(Exception):
    """Raised when the U-Prox cloud API returns an unusable response."""


class UProxInvalidAuth(UProxApiError):
    """Raised when U-Prox rejects the supplied credentials."""


class UProxApi:
    """Authenticate with the cloud API and read one panel over WebSocket."""

    def __init__(
        self,
        hass: HomeAssistant,
        login: str,
        password: str,
        message_logger: UProxMessageLogger,
    ) -> None:
        self._session = async_get_clientsession(hass)
        self._login = login
        self._password = password
        self._authorization: str | None = None
        self._token_refresh_at: float | None = None

    @property
    def token_refresh_in(self) -> float | None:
        """Seconds until proactive refresh, or None when exp is unavailable."""
        if self._token_refresh_at is None:
            return None
        return max(0.0, self._token_refresh_at - time.monotonic())
        self.message_logger = message_logger

    async def async_log_websocket_message(self, direction: str, message: Any) -> None:
        """Log one WebSocket application frame when logging is enabled."""
        await self.message_logger.async_log(direction, message)

    @staticmethod
    def _password_hash(password: str) -> str:
        """Match the lowercase MD5 hash sent by the cloud login page."""
        return hashlib.md5(password.encode("utf-8")).hexdigest()

    async def async_login(self) -> None:
        """Log in and capture the Authorization response header."""
        login_payload = {
            "login": self._login,
            "password": self._password_hash(self._password),
        }
        _LOGGER.info(
            "U-Prox cloud login request: POST %s/login?region=%s; "
            "JSON fields=login,password; login=<redacted>; "
            "password=lowercase-MD5 (32 hex chars, value redacted)",
            CLOUD_API_URL,
            REGION,
        )
        try:
            async with self._session.post(
                f"{CLOUD_API_URL}/login",
                params={"region": REGION},
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "en-US,en;q=0.9,uk;q=0.8",
                },
                json=login_payload,
                timeout=20,
            ) as response:
                status = response.status
                response.raise_for_status()
                data = await response.json(content_type=None)
                authorization = response.headers.get("Authorization")
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.warning(
                "U-Prox cloud login transport/HTTP/JSON failure (%s)",
                type(err).__name__,
            )
            raise UProxApiError("Cloud login request failed") from err

        if not isinstance(data, dict):
            _LOGGER.warning(
                "U-Prox cloud login response: HTTP %s; JSON type=%s",
                status,
                type(data).__name__,
            )
            raise UProxApiError("Cloud login returned a non-object JSON response")
        result = data.get("result")
        error = data.get("error")
        if error is not None or result is False:
            result_type = type(result).__name__
            error_present = error is not None
            _LOGGER.warning(
                "U-Prox cloud login response: HTTP %s; result type=%s; "
                "error present=%s; Authorization header present=%s",
                status,
                result_type,
                error_present,
                bool(authorization),
            )
            raise UProxInvalidAuth(
                f"HTTP {status}; result type {result_type}; error present {error_present}"
            )
        if not authorization:
            _LOGGER.warning(
                "U-Prox cloud login succeeded (HTTP %s) but Authorization header is missing",
                status,
            )
            raise UProxApiError("Cloud login response did not include Authorization")
        self._token_refresh_at = self._get_token_refresh_deadline(authorization)
        _LOGGER.info(
            "U-Prox cloud login succeeded (HTTP %s; result type=%s; "
            "Authorization header present; expiry=%s)",
            status,
            type(result).__name__,
            "available" if self._token_refresh_at is not None else "unavailable",
        )
        self._authorization = authorization

    @staticmethod
    def _get_token_refresh_deadline(authorization: str) -> float | None:
        """Decode exp for scheduling only; this does not verify the JWT signature."""
        token = authorization.strip()
        if token.startswith("MAKS"):
            token = token[4:].lstrip(" :")
        elif " " in token:
            _, token = token.split(None, 1)

        parts = token.split(".")
        if len(parts) != 3:
            return None
        try:
            payload_part = parts[1]
            payload_part += "=" * (-len(payload_part) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_part))
            expires_at = payload.get("exp") if isinstance(payload, dict) else None
            if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
                return None
        except (ValueError, TypeError, json.JSONDecodeError):
            return None

        remaining = max(0.0, float(expires_at) - time.time())
        refresh_margin = min(TOKEN_REFRESH_MARGIN_SECONDS, remaining * 0.1)
        return time.monotonic() + max(0.0, remaining - refresh_margin)

    async def async_get_panels(self) -> list[dict[str, Any]]:
        """Return all panels visible to the account."""
        if self._authorization is None:
            raise UProxApiError("Not authenticated")

        panels: list[dict[str, Any]] = []
        offset = 0
        limit = 50
        while True:
            try:
                async with self._session.get(
                    f"{CLOUD_API_URL}/api/panel/panels-with-sorting-web",
                    params={
                        "region": REGION,
                        "offset": offset,
                        "limit": limit,
                        "order_by": "account",
                        "order_direction": "ASC",
                    },
                    headers={"Authorization": self._authorization},
                    timeout=20,
                ) as response:
                    response.raise_for_status()
                    data = await response.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise UProxApiError("Cloud panel-list request failed") from err

            result = data.get("result") if isinstance(data, dict) else None
            if not isinstance(result, dict) or not isinstance(
                result.get("panels"), list
            ):
                raise UProxApiError("Cloud panel-list response has an unexpected shape")
            if data.get("error"):
                raise UProxApiError("Cloud panel-list request returned an error")

            page = [item for item in result["panels"] if isinstance(item, dict)]
            panels.extend(page)
            total = result.get("total")
            offset += len(page)
            if not page or offset >= (total if isinstance(total, int) else offset):
                break
        return panels

    async def async_open_panel_session(
        self, serial: int
    ) -> tuple[aiohttp.ClientWebSocketResponse, dict[str, Any]]:
        """Open a panel setup session and return its initial panelChanges data."""
        if self._authorization is None:
            raise UProxApiError("Not authenticated")

        url = f"{PANEL_SESSION_URL}?token={quote(self._authorization, safe='')}"
        try:
            websocket = await self._session.ws_connect(
                url, heartbeat=30, autoping=True, timeout=20
            )
            open_message = {
                "client": "openPanelSession",
                "commandId": 3,
                "data": {
                    "serial": serial,
                    "sessionType": "Setup",
                    "region": REGION,
                    "clientInfo": "U-PROX Home Assistant",
                },
            }
            await self.async_log_websocket_message("outgoing", open_message)
            await websocket.send_json(open_message)
            async with asyncio.timeout(30):
                async for message in websocket:
                    if message.type is aiohttp.WSMsgType.TEXT:
                        await self.async_log_websocket_message("incoming", message.data)
                        event = json.loads(message.data)
                        if event.get("server") == "openPanelSession":
                            if event.get("data") is not True:
                                raise UProxApiError("Cloud rejected the panel session")
                        elif event.get("server") == "panelChanges":
                            data = event.get("data")
                            initial = data.get("create") if isinstance(data, dict) else None
                            if isinstance(initial, dict):
                                return websocket, initial
                    elif message.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        await self.async_log_websocket_message(
                            "incoming", {"frame_type": message.type.name}
                        )
                        raise UProxApiError("Cloud panel session closed before data arrived")
        except UProxApiError:
            await websocket.close()
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError, json.JSONDecodeError) as err:
            if "websocket" in locals():
                await websocket.close()
            raise UProxApiError("Unable to open the cloud panel session") from err
        await websocket.close()
        raise UProxApiError("Cloud panel session returned no initial panel data")