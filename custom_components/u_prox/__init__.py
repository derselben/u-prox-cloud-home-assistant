"""U-Prox read-only Home Assistant integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import UProxApi, UProxApiError, UProxInvalidAuth
from .const import CONF_MESSAGE_LOGGING, DOMAIN
from .coordinator import UProxCoordinator
from .message_log import UProxMessageLogger

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.ALARM_CONTROL_PANEL,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up U-Prox from a config entry."""
    message_logger = UProxMessageLogger(
        hass, entry.options.get(CONF_MESSAGE_LOGGING, False)
    )
    api = UProxApi(
        hass, entry.data["username"], entry.data["password"], message_logger
    )
    coordinator = UProxCoordinator(hass, api)
    try:
        await api.async_login()
        await coordinator.async_start(entry.data["panel_serial"])
    except UProxInvalidAuth as err:
        raise ConfigEntryAuthFailed("U-Prox cloud rejected the credentials") from err
    except UProxApiError as err:
        raise ConfigEntryNotReady("Unable to open the U-Prox cloud panel session") from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await coordinator.async_close()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a U-Prox config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    coordinator: UProxCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
    await coordinator.async_close()
    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)
    return True