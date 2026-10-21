"""Read-only partition states from U-Prox Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PANEL_SERIAL, DOMAIN
from .coordinator import UProxCoordinator

_GROUP_STATES = {
    "disarmed": AlarmControlPanelState.DISARMED,
    "armedAway": AlarmControlPanelState.ARMED_AWAY,
    "armedStay": AlarmControlPanelState.ARMED_HOME,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one read-only alarm entity per reported partition."""
    coordinator: UProxCoordinator = hass.data[DOMAIN][entry.entry_id]
    groups = coordinator.data.get("groups", [])
    if not isinstance(groups, list):
        return
    async_add_entities(
        UProxPartition(coordinator, str(entry.data[CONF_PANEL_SERIAL]), group["index"])
        for group in groups
        if isinstance(group, dict) and group.get("index") is not None
    )


class UProxPartition(CoordinatorEntity[UProxCoordinator], AlarmControlPanelEntity):
    """Display partition state without sending arm or disarm commands."""

    _attr_has_entity_name = True
    _attr_supported_features = AlarmControlPanelEntityFeature(0)
    _attr_code_arm_required = False

    def __init__(
        self, coordinator: UProxCoordinator, panel_serial: str, group_index: int
    ) -> None:
        super().__init__(coordinator)
        self._panel_serial = panel_serial
        self._group_index = str(group_index)
        self._attr_unique_id = f"{panel_serial}_group_{group_index}"

    @property
    def _group(self) -> dict[str, Any]:
        groups = self.coordinator.data.get("groups", [])
        if isinstance(groups, list):
            for group in groups:
                if isinstance(group, dict) and str(group.get("index")) == self._group_index:
                    return group
        return {}

    @property
    def name(self) -> str:
        group_name = self._group.get("name")
        label = f"Partition {self._group_index.zfill(2)}"
        return f"{label} | {group_name}" if group_name else label

    @property
    def available(self) -> bool:
        return super().available and bool(self._group)

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        states = self._group.get("state", [])
        if not isinstance(states, list):
            return None
        matches = [value for key, value in _GROUP_STATES.items() if key in states]
        return matches[0] if len(matches) == 1 else None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._panel_serial)})