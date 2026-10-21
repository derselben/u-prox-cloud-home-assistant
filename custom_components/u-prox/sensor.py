"""Diagnostic sensors for U-Prox devices."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UProxCoordinator

_COMPONENTS = {
    "sensors": "Sensor",
    "keyboards": "Keyboard",
    "keyFobs": "Key fob",
    "repeaters": "Repeater",
    "relays": "Relay",
    "reactions": "Reaction",
    "zoneExtenders": "Zone extender",
}
_COMPONENT_TYPE_NAMES = {
    ("sensors", 172): "PIR",
    ("sensors", 177): "WDC",
    ("keyFobs", 185): "Key fob",
}
_METRICS = {
    "temperature": (
        "Temperature",
        SensorDeviceClass.TEMPERATURE,
        UnitOfTemperature.CELSIUS,
        None,
        1,
    ),
    "batteryLevel": (
        "Battery",
        SensorDeviceClass.BATTERY,
        PERCENTAGE,
        EntityCategory.DIAGNOSTIC,
        0,
    ),
    "signalLevel": (
        "Signal strength",
        SensorDeviceClass.SIGNAL_STRENGTH,
        "dBm",
        EntityCategory.DIAGNOSTIC,
        0,
    ),
}
_PANEL_METRICS = {
    "batteryLevel": (
        "Battery",
        SensorDeviceClass.BATTERY,
        PERCENTAGE,
        0,
    ),
    "communication.sim1Level": (
        "SIM 1 signal strength",
        SensorDeviceClass.SIGNAL_STRENGTH,
        "dBm",
        0,
    ),
    "communication.sim2Level": (
        "SIM 2 signal strength",
        SensorDeviceClass.SIGNAL_STRENGTH,
        "dBm",
        0,
    ),
    "communication.wifiLevel": (
        "Wi-Fi signal strength",
        SensorDeviceClass.SIGNAL_STRENGTH,
        "dBm",
        0,
    ),
}
_SENSITIVE_PARTS = (
    "password",
    "pincode",
    "encryption",
    "email",
    "phone",
    "token",
    "secret",
    "authorization",
    "address",
    "owner",
    "apnuser",
    "balance",
    "wifiname",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one diagnostic sensor per discovered controller."""
    coordinator: UProxCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.config_entry_id = entry.entry_id
    panel_serial = str(entry.data["panel_serial"])
    entities: list[SensorEntity] = [UProxPanelSensor(coordinator, panel_serial)]
    panel = coordinator.data.get("panelSettings", {})
    if isinstance(panel, dict):
        for path, metric_details in _PANEL_METRICS.items():
            value = _nested_value(panel, path)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if path == "communication.wifiLevel" and value == 0:
                    continue
                entities.append(
                    UProxPanelMetricSensor(
                        coordinator, panel_serial, path, metric_details
                    )
                )
    for component_key, component_name in _COMPONENTS.items():
        components = coordinator.data.get(component_key, [])
        if not isinstance(components, list):
            continue
        for index, component in enumerate(components, start=1):
            if isinstance(component, dict):
                name = _component_name(component_key, component_name, index, component)
                entities.append(
                    UProxComponentStateSensor(
                        coordinator,
                        panel_serial,
                        component_key,
                        index,
                        component,
                        name,
                    )
                )
                for metric_key, metric_details in _METRICS.items():
                    value = component.get(metric_key)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        entities.append(
                            UProxComponentMetricSensor(
                                coordinator,
                                panel_serial,
                                component_key,
                                index,
                                component,
                                name,
                                metric_key,
                                metric_details,
                            )
                        )
    async_add_entities(entities)


def _nested_value(data: dict[str, Any], path: str) -> Any:
    """Read a dot-separated field from nested panel data."""
    value: Any = data
    for key in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _component_name(
    component_key: str,
    component_name: str,
    index: int,
    component: dict[str, Any],
) -> str:
    """Create a stable, readable name when a component has no configured name."""
    configured_name = component.get("name")
    if isinstance(configured_name, str) and configured_name.strip():
        return configured_name.strip()
    type_name = _COMPONENT_TYPE_NAMES.get((component_key, component.get("type")))
    label = type_name or component_name
    if component_key == "sensors":
        return f"Zone {index:02d} | {label}"
    return f"{label} {index:02d}"


def _safe_attributes(data: dict[str, Any]) -> dict[str, Any]:
    """Remove credentials and personal data before publishing state attributes."""
    safe: dict[str, Any] = {}
    for key, value in data.items():
        lowered = key.lower().replace("_", "")
        if any(part in lowered for part in _SENSITIVE_PARTS):
            continue
        if isinstance(value, dict):
            safe[key] = _safe_attributes(value)
        elif isinstance(value, list):
            safe[key] = [
                _safe_attributes(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            safe[key] = value
    return safe


class UProxPanelSensor(CoordinatorEntity[UProxCoordinator], SensorEntity):
    """Expose the selected panel's state and safe settings."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: UProxCoordinator, serial: str) -> None:
        super().__init__(coordinator)
        self._serial = serial
        self._attr_unique_id = f"{serial}_panel"

    @property
    def _panel(self) -> dict[str, Any]:
        value = self.coordinator.data.get("panelSettings", {})
        return value if isinstance(value, dict) else {}

    @property
    def name(self) -> str:
        return "Panel status"

    @property
    def native_value(self) -> str:
        states = self._panel.get("state", [])
        return ", ".join(states) if isinstance(states, list) and states else "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return _safe_attributes(self._panel)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=str(self._panel.get("name") or f"Panel {self._serial}"),
            manufacturer="U-Prox",
            model=str(self._panel.get("type")) if self._panel.get("type") else None,
            serial_number=self._serial,
        )


class UProxPanelMetricSensor(CoordinatorEntity[UProxCoordinator], SensorEntity):
    """Expose a numeric hub measurement."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: UProxCoordinator,
        serial: str,
        path: str,
        metric_details: tuple[str, SensorDeviceClass, str, int],
    ) -> None:
        super().__init__(coordinator)
        name, device_class, unit, precision = metric_details
        self._serial = serial
        self._path = path
        self._attr_unique_id = f"{serial}_{path.replace('.', '_')}"
        self._attr_name = name
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_suggested_display_precision = precision

    @property
    def native_value(self) -> int | float | None:
        panel = self.coordinator.data.get("panelSettings", {})
        if not isinstance(panel, dict):
            return None
        value = _nested_value(panel, self._path)
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    @property
    def device_info(self) -> DeviceInfo:
        panel = self.coordinator.data.get("panelSettings", {})
        if not isinstance(panel, dict):
            panel = {}
        return DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=str(panel.get("name") or f"Panel {self._serial}"),
            manufacturer="U-Prox",
            model=str(panel.get("type")) if panel.get("type") else None,
            serial_number=self._serial,
        )


class UProxComponentEntity(CoordinatorEntity[UProxCoordinator]):
    """Base entity for a panel component."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UProxCoordinator,
        panel_serial: str,
        component_key: str,
        index: int,
        initial_data: dict[str, Any],
        component_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._panel_serial = panel_serial
        self._component_key = component_key
        self._index = index
        self._component_serial = initial_data.get("serial")
        self._component_index = initial_data.get("index")
        self._serial = str(self._component_serial or self._component_index or index)
        self._component_name = component_name

    @property
    def _component(self) -> dict[str, Any]:
        components = self.coordinator.data.get(self._component_key, [])
        if isinstance(components, list):
            for component in components:
                if not isinstance(component, dict):
                    continue
                if (
                    self._component_serial is not None
                    and component.get("serial") is not None
                    and str(component["serial"]) == str(self._component_serial)
                ):
                    return component
                if (
                    self._component_index is not None
                    and component.get("index") is not None
                    and str(component["index"]) == str(self._component_index)
                ):
                    return component
        return {}

    @property
    def device_info(self) -> DeviceInfo:
        component = self._component
        parent = dr.async_get(self.hass).async_get_device_by_identifier(
            (DOMAIN, self._panel_serial), self.coordinator.config_entry_id
        )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._panel_serial}_{self._serial}")},
            via_device_id=parent.id if parent else None,
            name=self._component_name,
            manufacturer="U-Prox",
            model=str(component.get("type")) if component.get("type") else None,
            serial_number=self._serial,
        )


class UProxComponentStateSensor(UProxComponentEntity, SensorEntity):
    """Expose the component's state flags for diagnostics."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: UProxCoordinator,
        panel_serial: str,
        component_key: str,
        index: int,
        initial_data: dict[str, Any],
        component_name: str,
    ) -> None:
        super().__init__(
            coordinator,
            panel_serial,
            component_key,
            index,
            initial_data,
            component_name,
        )
        self._attr_unique_id = f"{panel_serial}_{component_key}_{self._serial}_state"
        self._attr_name = "State"

    @property
    def native_value(self) -> str:
        states = self._component.get("state", [])
        return ", ".join(states) if isinstance(states, list) and states else "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return _safe_attributes(self._component)


class UProxComponentMetricSensor(UProxComponentEntity, SensorEntity):
    """Expose a numeric component measurement with Home Assistant metadata."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: UProxCoordinator,
        panel_serial: str,
        component_key: str,
        index: int,
        initial_data: dict[str, Any],
        component_name: str,
        metric_key: str,
        metric_details: tuple[str, SensorDeviceClass, str, EntityCategory | None, int],
    ) -> None:
        super().__init__(
            coordinator,
            panel_serial,
            component_key,
            index,
            initial_data,
            component_name,
        )
        metric_name, device_class, unit, entity_category, precision = metric_details
        self._metric_key = metric_key
        self._attr_unique_id = (
            f"{panel_serial}_{component_key}_{self._serial}_{metric_key}"
        )
        self._attr_name = metric_name
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_entity_category = entity_category
        self._attr_suggested_display_precision = precision

    @property
    def native_value(self) -> int | float | None:
        value = self._component.get(self._metric_key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        return None