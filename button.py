from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BRAND_ACURA, DATA_COORDINATOR, DOMAIN
from .coordinator import HondaLinkDataUpdateCoordinator
from .entity import HondaLinkEntity


@dataclass(frozen=True, kw_only=True)
class HondaLinkButtonDescription(ButtonEntityDescription):
    press_fn: Callable[[HondaLinkDataUpdateCoordinator], object]
    acura_only: bool = False


BUTTONS: tuple[HondaLinkButtonDescription, ...] = (
    HondaLinkButtonDescription(
        key="start_engine",
        translation_key="start_engine",
        icon="mdi:engine",
        press_fn=lambda coordinator: coordinator.async_start_engine(),
    ),
    HondaLinkButtonDescription(
        key="stop_engine",
        translation_key="stop_engine",
        icon="mdi:engine-off",
        press_fn=lambda coordinator: coordinator.async_stop_engine(),
    ),
    HondaLinkButtonDescription(
        key="horn",
        translation_key="horn",
        icon="mdi:bullhorn",
        press_fn=lambda coordinator: coordinator.async_horn(),
    ),
    HondaLinkButtonDescription(
        key="lights",
        translation_key="lights",
        icon="mdi:car-light-high",
        press_fn=lambda coordinator: coordinator.async_lights(),
    ),
    HondaLinkButtonDescription(
        key="stop_horn_lights",
        translation_key="stop_horn_lights",
        icon="mdi:car-light-alert",
        press_fn=lambda coordinator: coordinator.async_stop_horn_lights(),
    ),
    HondaLinkButtonDescription(
        key="update_location",
        translation_key="update_location",
        acura_only=True,
        press_fn=lambda coordinator: coordinator.async_update_location(),
    ),
    HondaLinkButtonDescription(
        key="refresh",
        translation_key="refresh",
        icon="mdi:refresh",
        press_fn=lambda coordinator: coordinator.async_force_refresh(),
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        HondaLinkButton(coordinator, entry, description)
        for description in BUTTONS
        if not description.acura_only or coordinator.api.brand == BRAND_ACURA
    )


class HondaLinkButton(HondaLinkEntity, ButtonEntity):
    entity_description: HondaLinkButtonDescription

    def __init__(self, coordinator: HondaLinkDataUpdateCoordinator, entry: ConfigEntry, description: HondaLinkButtonDescription) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        await self.entity_description.press_fn(self.coordinator)
