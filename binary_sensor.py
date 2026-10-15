from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .entity import HondaLinkEntity
from .util import any_light_on, any_open_state, get_path, status_body


@dataclass(frozen=True, kw_only=True)
class HondaLinkBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], bool | None]


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
        key="front_driver_door",
        translation_key="front_driver_door",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=lambda body: any_open_state(body, "doorStatus", ["firstRowDriver"]),
    ),
    HondaLinkBinarySensorDescription(
        key="front_passenger_door",
        translation_key="front_passenger_door",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=lambda body: any_open_state(body, "doorStatus", ["firstRowPassenger"]),
    ),
    HondaLinkBinarySensorDescription(
        key="rear_driver_side_door",
        translation_key="rear_driver_side_door",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=lambda body: any_open_state(body, "doorStatus", ["secondRowDriver"]),
    ),
    HondaLinkBinarySensorDescription(
        key="rear_passenger_side_door",
        translation_key="rear_passenger_side_door",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=lambda body: any_open_state(body, "doorStatus", ["secondRowPassenger"]),
    ),
    HondaLinkBinarySensorDescription(
        key="front_driver_window",
        translation_key="front_driver_window",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=lambda body: any_open_state(body, "windowStatus", ["frontWindowDR"], "closeState"),
    ),
    HondaLinkBinarySensorDescription(
        key="front_passenger_window",
        translation_key="front_passenger_window",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=lambda body: any_open_state(body, "windowStatus", ["frontWindowAS"], "closeState"),
    ),
    HondaLinkBinarySensorDescription(
        key="rear_left_window",
        translation_key="rear_left_window",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=lambda body: any_open_state(body, "windowStatus", ["rearWindowRL"], "closeState"),
    ),
    HondaLinkBinarySensorDescription(
        key="rear_right_window",
        translation_key="rear_right_window",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=lambda body: any_open_state(body, "windowStatus", ["rearWindowRR"], "closeState"),
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
        value_fn=lambda body: any(
            str(message.get("condition", "")).upper() == "ON"
            for group in get_path(body, "warningLamps.data", []) or []
            if isinstance(group, dict)
            for message in group.get("messages", [])
            if isinstance(message, dict)
        ),
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
