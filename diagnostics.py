from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DATA_COORDINATOR, DOMAIN

TO_REDACT = {
    "email",
    "password",
    "pin",
    "vin",
    "VIN",
    "device",
    "access_token",
    "refresh_token",
    "client_reg_key",
    "hidas_ident",
    "device_id",
    "session_id",
    "latitude",
    "longitude",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    return async_redact_data(
        {
            "entry_data": dict(entry.data),
            "entry_options": dict(entry.options),
            "dashboard_latest": coordinator.data,
            "last_live_refresh": coordinator.last_refresh_response,
        },
        TO_REDACT,
    )
