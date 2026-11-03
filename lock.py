from __future__ import annotations

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BRAND_ACURA, DATA_COORDINATOR, DOMAIN
from .entity import HondaLinkEntity
from .util import all_door_locks_locked, status_body


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([HondaLinkDoorLock(coordinator, entry)])


class HondaLinkDoorLock(HondaLinkEntity, LockEntity):
    _attr_translation_key = "doors"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "doors_lock")
        self._assumed_locked: bool | None = None
        self._track_assumed = coordinator.api.brand == BRAND_ACURA

    def _reported_locked(self) -> bool | None:
        return all_door_locks_locked(status_body(self.coordinator.data or {}))

    @property
    def assumed_state(self) -> bool:
        # Some vehicles (e.g. AcuraLink 2GX) never report door lock state in the cached data.
        return self._track_assumed and self._reported_locked() is None

    @property
    def is_locked(self) -> bool | None:
        reported = self._reported_locked()
        if reported is None and self._track_assumed:
            return self._assumed_locked
        return reported

    async def async_lock(self, **kwargs) -> None:
        await self.coordinator.async_lock()
        if self._track_assumed:
            self._assumed_locked = True
            self.async_write_ha_state()

    async def async_unlock(self, **kwargs) -> None:
        await self.coordinator.async_unlock()
        if self._track_assumed:
            self._assumed_locked = False
            self.async_write_ha_state()
