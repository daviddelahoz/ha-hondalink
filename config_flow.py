from __future__ import annotations

import logging
import uuid
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HondaLinkAPI, HondaLinkAuthError, HondaLinkError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CLIENT_REG_KEY,
    CONF_COUNTRY,
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_EXPIRES_AT,
    CONF_HIDAS_IDENT,
    CONF_LANGUAGE,
    CONF_LOCK_COMMAND,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PIN,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_SESSION_ID,
    CONF_UNLOCK_COMMAND,
    CONF_VEHICLE_INFO,
    CONF_VIN,
    DEFAULT_LOCK_COMMAND,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNLOCK_COMMAND,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _vehicle_title(vehicle: dict[str, Any] | None, vin: str, custom_name: str | None = None) -> str:
    if custom_name:
        return custom_name
    vehicle = vehicle or {}
    alias = vehicle.get("Alias Name") or vehicle.get("alias")
    if alias:
        return str(alias)
    year = vehicle.get("ModelYear")
    model = vehicle.get("ModelGroupNameFriendly") or vehicle.get("ModelCode")
    if year and model:
        return f"{year} Honda {model}"
    return f"{DEFAULT_NAME} {vin[-6:]}"


def _vehicle_label(vehicle: dict[str, Any]) -> str:
    vin = vehicle.get("VIN", "")
    title = _vehicle_title(vehicle, vin)
    return f"{title} ({vin})"


class HondaLinkConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._api: HondaLinkAPI | None = None
        self._base_data: dict[str, Any] = {}
        self._vehicles: list[dict[str, Any]] = []
        self._custom_name: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]
            pin = user_input[CONF_PIN].strip()
            vin = user_input.get(CONF_VIN, "").strip().upper()
            self._custom_name = user_input.get(CONF_NAME, "").strip() or None
            device_id = str(uuid.uuid4())
            session_id = str(uuid.uuid4())

            session = async_get_clientsession(self.hass)
            api = HondaLinkAPI(
                session,
                email=email,
                password=password,
                pin=pin,
                vin=vin or None,
                device_id=device_id,
                session_id=session_id,
            )

            try:
                await api.async_login()
                vehicles = await api.async_get_vehicles()
            except HondaLinkAuthError as err:
                _LOGGER.warning("HondaLink authentication failed during config flow: %s", err)
                errors["base"] = "invalid_auth"
            except HondaLinkError as err:
                _LOGGER.warning("HondaLink connection failed during config flow: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected HondaLink config flow error")
                errors["base"] = "unknown"
            else:
                vehicle_info: dict[str, Any] | None = None
                if vin:
                    vehicle_info = next((item for item in vehicles if item.get("VIN") == vin), None)
                    if vehicle_info is None:
                        try:
                            vehicle_info = await api.async_get_vehicle_by_vin(vin)
                        except HondaLinkError as err:
                            _LOGGER.warning(
                                "HondaLink VIN lookup failed for %s during config flow: %s",
                                vin,
                                err,
                            )
                            vehicle_info = None
                elif len(vehicles) == 1:
                    vehicle_info = vehicles[0]
                    vin = str(vehicle_info.get("VIN", "")).upper()
                    api.vin = vin
                elif len(vehicles) > 1:
                    self._api = api
                    self._vehicles = vehicles
                    self._base_data = self._entry_data(api, email, password, pin, "", None)
                    return await self.async_step_vehicle()
                else:
                    errors["base"] = "vin_required"

                if not errors:
                    if not vin:
                        errors["base"] = "vin_required"
                    else:
                        api.vin = vin
                        return await self._async_create_vehicle_entry(api, email, password, pin, vin, vehicle_info)

        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_PIN): str,
                vol.Optional(CONF_VIN, default=""): str,
                vol.Optional(CONF_NAME, default=""): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_vehicle(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        vehicles_by_vin = {item["VIN"]: item for item in self._vehicles if item.get("VIN")}

        if user_input is not None:
            vin = user_input[CONF_VIN]
            vehicle_info = vehicles_by_vin.get(vin)
            if self._api is None:
                errors["base"] = "unknown"
            else:
                self._api.vin = vin
                data = {**self._base_data, CONF_VIN: vin, CONF_VEHICLE_INFO: vehicle_info or {}}
                await self.async_set_unique_id(vin)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=_vehicle_title(vehicle_info, vin, self._custom_name),
                    data=data,
                )

        schema = vol.Schema({vol.Required(CONF_VIN): vol.In({vin: _vehicle_label(vehicle) for vin, vehicle in vehicles_by_vin.items()})})
        return self.async_show_form(step_id="vehicle", data_schema=schema, errors=errors)

    async def _async_create_vehicle_entry(
        self,
        api: HondaLinkAPI,
        email: str,
        password: str,
        pin: str,
        vin: str,
        vehicle_info: dict[str, Any] | None,
    ):
        await self.async_set_unique_id(vin)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=_vehicle_title(vehicle_info, vin, self._custom_name),
            data=self._entry_data(api, email, password, pin, vin, vehicle_info),
        )

    def _entry_data(
        self,
        api: HondaLinkAPI,
        email: str,
        password: str,
        pin: str,
        vin: str,
        vehicle_info: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            CONF_EMAIL: email,
            CONF_PASSWORD: password,
            CONF_PIN: pin,
            CONF_VIN: vin,
            CONF_VEHICLE_INFO: vehicle_info or {},
            CONF_CLIENT_REG_KEY: api.client_reg_key,
            CONF_ACCESS_TOKEN: api.access_token,
            CONF_REFRESH_TOKEN: api.refresh_token,
            CONF_EXPIRES_AT: api.expires_at,
            CONF_COUNTRY: api.country,
            CONF_LANGUAGE: api.language,
            CONF_HIDAS_IDENT: api.hidas_ident,
            CONF_DEVICE_ID: api.device_id,
            CONF_SESSION_ID: api.session_id,
        }

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return HondaLinkOptionsFlowHandler()


class HondaLinkOptionsFlowHandler(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        data = self.config_entry.data
        schema = vol.Schema(
            {
                vol.Required(CONF_PIN, default=options.get(CONF_PIN, data.get(CONF_PIN, ""))): str,
                vol.Required(CONF_SCAN_INTERVAL, default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): int,
                vol.Required(CONF_LOCK_COMMAND, default=options.get(CONF_LOCK_COMMAND, DEFAULT_LOCK_COMMAND)): str,
                vol.Required(CONF_UNLOCK_COMMAND, default=options.get(CONF_UNLOCK_COMMAND, DEFAULT_UNLOCK_COMMAND)): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
