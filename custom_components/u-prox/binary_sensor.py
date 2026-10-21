"""Binary status entities for a U-Prox hub."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UProxCoordinator

_HUB_STATUSES = (
    ("online", "Connectivity", BinarySensorDeviceClass.CONNECTIVITY, ("online",), ("offline",)),
    ("mains_power", "Mains power", None, ("powerOk",), ("powerLost", "mainsPowerFailure")),
    ("tamper", "Tamper", BinarySensorDeviceClass.TAMPER, ("tamperAlarm", "tamper"), ("tamperOk",)),
    ("sim1", "SIM 1 connection", BinarySensorDeviceClass.CONNECTIVITY, ("sim1Connected",), ("sim1NoCard", "sim1Disconnected")),
    ("sim2", "SIM 2 connection", BinarySensorDeviceClass.CONNECTIVITY, ("sim2Connected",), ("sim2NoCard", "sim2Disconnected")),
    ("wifi", "Wi-Fi connection", BinarySensorDeviceClass.CONNECTIVITY, ("wifiConnected",), ("wifiNoConnection",)),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up hub status entities."""
    coordinator: UProxCoordinator = hass.data[DOMAIN][entry.entry_id]
    panel_serial = str(entry.data["panel_serial"])
    async_add_entities(
        UProxHubStatusSensor(coordinator, panel_serial, *status)
        for status in _HUB_STATUSES
    )


class UProxHubStatusSensor(CoordinatorEntity[UProxCoordinator], BinarySensorEntity):
    """Represent one status flag from the hub or its communication module."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UProxCoordinator,
        panel_serial: str,
        key: str,
        name: str,
        device_class: BinarySensorDeviceClass | None,
        on_states: tuple[str, ...],
        off_states: tuple[str, ...],
    ) -> None:
        super().__init__(coordinator)
        self._panel_serial = panel_serial
        self._key = key
        self._on_states = on_states
        self._off_states = off_states
        self._attr_unique_id = f"{panel_serial}_{key}"
        self._attr_name = name
        self._attr_device_class = device_class

    @property
    def _states(self) -> list[str]:
        panel = self.coordinator.data.get("panelSettings", {})
        if not isinstance(panel, dict):
            return []
        if self._key in {"sim1", "sim2", "wifi"}:
            communication = panel.get("communication", {})
            states = communication.get("state", []) if isinstance(communication, dict) else []
        else:
            states = panel.get("state", [])
        return states if isinstance(states, list) else []

    @property
    def is_on(self) -> bool | None:
        states = set(self._states)
        if states.intersection(self._on_states):
            return True
        if states.intersection(self._off_states):
            return False
        return None

    @property
    def device_info(self) -> DeviceInfo:
        panel: dict[str, Any] = self.coordinator.data.get("panelSettings", {})
        if not isinstance(panel, dict):
            panel = {}
        return DeviceInfo(
            identifiers={(DOMAIN, self._panel_serial)},
            name=str(panel.get("name") or f"Panel {self._panel_serial}"),
            manufacturer="U-Prox",
            model=str(panel.get("type")) if panel.get("type") else None,
            serial_number=self._panel_serial,
        )