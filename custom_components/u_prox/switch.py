"""U-Prox diagnostic and logging switches."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MESSAGE_LOGGING, DOMAIN
from .coordinator import UProxCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the WebSocket message logger switch."""
    coordinator: UProxCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([UProxMessageLoggingSwitch(coordinator, entry)])


class UProxMessageLoggingSwitch(CoordinatorEntity[UProxCoordinator], SwitchEntity):
    """Toggle redacted WebSocket message logging to a local file."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: UProxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.data['panel_serial']}_message_logging"
        self._attr_name = "WebSocket message logging"

    @property
    def is_on(self) -> bool:
        return self.coordinator.api.message_logger.enabled

    @property
    def device_info(self) -> DeviceInfo:
        panel = self.coordinator.data.get("panelSettings", {})
        if not isinstance(panel, dict):
            panel = {}
        serial = str(self._entry.data["panel_serial"])
        return DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name=str(panel.get("name") or f"Panel {serial}"),
            manufacturer="U-Prox",
            model=str(panel.get("type")) if panel.get("type") else None,
            serial_number=serial,
        )

    async def async_turn_on(self, **kwargs) -> None:
        """Enable message logging and persist the option."""
        await self._async_set_logging(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable message logging and persist the option."""
        await self._async_set_logging(False)

    async def _async_set_logging(self, enabled: bool) -> None:
        logger = self.coordinator.api.message_logger
        logger.enabled = enabled
        options = {**self._entry.options, CONF_MESSAGE_LOGGING: enabled}
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        self.async_write_ha_state()
        if enabled:
            await logger.async_log("snapshot", self.coordinator.data)