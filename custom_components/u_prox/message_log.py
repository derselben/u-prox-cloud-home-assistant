"""Opt-in, redacted JSONL logging for U-Prox WebSocket traffic."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
_MAX_LOG_BYTES = 4 * 1024 * 1024
_SENSITIVE_KEYS = (
    "password",
    "pincode",
    "token",
    "authorization",
    "secret",
    "encryption",
    "email",
    "phone",
    "address",
    "owner",
    "balance",
    "apnuser",
    "account",
    "name",
    "description",
    "initiator",
    "serial",
)


class UProxMessageLogger:
    """Write redacted WebSocket messages to a separate rotating file."""

    def __init__(
        self,
        hass: HomeAssistant,
        enabled: bool = False,
        path: Path | None = None,
    ) -> None:
        self._hass = hass
        self.enabled = enabled
        self.path = path or Path(__file__).resolve().parent / "websocket_messages.jsonl"
        self._lock = asyncio.Lock()
        self._pseudonyms: dict[tuple[str, str], str] = {}

    async def async_log(self, direction: str, message: Any) -> None:
        """Append a redacted message when logging is enabled."""
        if not self.enabled:
            return

        if isinstance(message, str):
            try:
                message = json.loads(message)
            except json.JSONDecodeError:
                message = {"text_frame": "<non-JSON frame redacted>", "length": len(message)}
        sanitized = self._sanitize(message)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "direction": direction,
            "message": sanitized,
        }
        line = json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n"
        async with self._lock:
            try:
                await self._hass.async_add_executor_job(self._append_line, line)
            except OSError as err:
                self.enabled = False
                _LOGGER.error(
                    "U-Prox message logging disabled; unable to write %s (%s)",
                    self.path.name,
                    type(err).__name__,
                )

    def _sanitize(self, value: Any, key: str = "") -> Any:
        """Redact secrets and pseudonymize personal labels and serials."""
        normalized_key = "".join(char for char in key.lower() if char.isalnum())
        if any(part in normalized_key for part in _SENSITIVE_KEYS):
            if value in (None, ""):
                return value
            if normalized_key.endswith("serial") or normalized_key.endswith("serialnumber"):
                return self._pseudonym(normalized_key, str(value), "SERIAL")
            if normalized_key.endswith("name"):
                return self._pseudonym(normalized_key, str(value), "LABEL")
            return "<redacted>"
        if isinstance(value, dict):
            return {str(child_key): self._sanitize(child_value, str(child_key)) for child_key, child_value in value.items()}
        if isinstance(value, list):
            return [self._sanitize(item, key) for item in value]
        return value

    def _pseudonym(self, key: str, value: str, prefix: str) -> str:
        """Keep repeated identifiers correlatable without storing their values."""
        pseudonym_key = (key, value)
        if pseudonym_key not in self._pseudonyms:
            self._pseudonyms[pseudonym_key] = f"{prefix}_{len(self._pseudonyms) + 1}"
        return self._pseudonyms[pseudonym_key]

    def _append_line(self, line: str) -> None:
        """Append a line and rotate the current file when it grows too large."""
        if self.path.exists() and self.path.stat().st_size + len(line.encode("utf-8")) > _MAX_LOG_BYTES:
            backup = Path(f"{self.path}.1")
            backup.unlink(missing_ok=True)
            self.path.replace(backup)
        with self.path.open("a", encoding="utf-8") as log_file:
            log_file.write(line)