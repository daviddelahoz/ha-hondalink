from __future__ import annotations

from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .entity import HondaLinkEntity
from .util import dms_to_decimal, get_path, status_body, to_float


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([HondaLinkDeviceTracker(coordinator, entry)])


class HondaLinkDeviceTracker(HondaLinkEntity, TrackerEntity):
    _attr_translation_key = "location"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "location")

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        body = status_body(self.coordinator.data or {})
        return dms_to_decimal(get_path(body, "gpsData.coordinate.latitude"))

    @property
    def longitude(self) -> float | None:
        body = status_body(self.coordinator.data or {})
        return dms_to_decimal(get_path(body, "gpsData.coordinate.longitude"))

    @property
    def location_accuracy(self) -> int | None:
        body = status_body(self.coordinator.data or {})
        radius = to_float(get_path(body, "gpsData.accuracy.radius"))
        return int(radius) if radius is not None else None
