from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .entity import HondaLinkEntity
from .util import active_warning_lamps, any_light_on, any_open_state, get_path, maintenance_items, status_body


@dataclass(frozen=True, kw_only=True)
class HondaLinkBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], bool | None]
    attr_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


DOOR_KEYS = ["firstRowDriver", "firstRowPassenger", "secondRowDriver", "secondRowPassenger"]
WINDOW_KEYS = ["frontWindowDR", "frontWindowAS", "rearWindowRR", "rearWindowRL"]


BINARY_SENSORS: tuple[HondaLinkBinarySensorDescription, ...] = (
    HondaLinkBinarySensorDescription(
        key="any_door_open",
        translation_key="any_door_open",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=lambda body: any_open_state(body, "doorStatus", DOOR_KEYS),
    ),
    HondaLinkBinarySensorDescription(
        key="hood_open",
        translation_key="hood_open",
        device_class=BinarySensorDeviceClass.OPENING,
        value_fn=lambda body: any_open_state(body, "doorStatus", ["hood"]),
    ),
    HondaLinkBinarySensorDescription(
        key="trunk_open",
        translation_key="trunk_open",
        device_class=BinarySensorDeviceClass.OPENING,
        value_fn=lambda body: any_open_state(body, "doorStatus", ["trunk"]),
    ),
    HondaLinkBinarySensorDescription(
        key="any_window_open",
        translation_key="any_window_open",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=lambda body: any_open_state(body, "windowStatus", WINDOW_KEYS, "closeState"),
    ),
    HondaLinkBinarySensorDescription(
        key="any_light_on",
        translation_key="any_light_on",
        device_class=BinarySensorDeviceClass.LIGHT,
        value_fn=any_light_on,
    ),
    HondaLinkBinarySensorDescription(
        key="warning_lamp_on",
        translation_key="warning_lamp_on",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda body: bool(active_warning_lamps(body)),
        attr_fn=lambda body: {
            "warnings": [lamp.get("titleString") for lamp in active_warning_lamps(body)],
            "messages": [lamp.get("messageString") for lamp in active_warning_lamps(body)],
        },
    ),
    HondaLinkBinarySensorDescription(
        key="tire_pressure_low",
        translation_key="tire_pressure_low",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda body: any(lamp.get("lampName") == "PUNCTURE_LAMP" for lamp in active_warning_lamps(body)),
    ),
    HondaLinkBinarySensorDescription(
        key="maintenance_due",
        translation_key="maintenance_due",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda body: bool(maintenance_items(body)) if get_path(body, "maintenanceMinder") is not None else None,
        attr_fn=lambda body: {
            "codes": get_path(body, "maintenanceMinder.mmCodes"),
            "items": maintenance_items(body),
        },
    ),
    HondaLinkBinarySensorDescription(
        key="remote_engine_running",
        translation_key="remote_engine_running",
        value_fn=lambda body: str(get_path(body, "remoteEngineStart.vehicleStartEvent.resStatus", "")).upper() == "ON",
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(HondaLinkBinarySensor(coordinator, entry, description) for description in BINARY_SENSORS)


class HondaLinkBinarySensor(HondaLinkEntity, BinarySensorEntity):
    entity_description: HondaLinkBinarySensorDescription

    def __init__(self, coordinator, entry: ConfigEntry, description: HondaLinkBinarySensorDescription) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(status_body(self.coordinator.data or {}))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attr_fn is None:
            return None
        return self.entity_description.attr_fn(status_body(self.coordinator.data or {}))
