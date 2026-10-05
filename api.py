from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .const import (
    API_BASE,
    APP_USER_AGENT,
    CLIENT_ID,
    CLIENT_SECRET,
    CONF_ACCESS_TOKEN,
    CONF_CLIENT_REG_KEY,
    CONF_COUNTRY,
    CONF_DEVICE_ID,
    CONF_EXPIRES_AT,
    CONF_HIDAS_IDENT,
    CONF_LANGUAGE,
    CONF_REFRESH_TOKEN,
    CONF_SESSION_ID,
    DASHBOARD_FILTER_SETS,
    DEFAULT_COUNTRY,
    DEFAULT_LANGUAGE,
    DEFAULT_LOCK_COMMAND,
    DEFAULT_UNLOCK_COMMAND,
    DEVICE_DESCRIPTION,
    HONDALINK_BUSINESS_ID,
    HONDALINK_SYSTEM_ID,
    HONDA_HEADER_VERSION,
    IDENTITY_BASE,
    LEGACY_LOCK_COMMAND,
    LEGACY_UNLOCK_COMMAND,
)

_DYNAMIC_BACKEND_ERROR_CODE = "0x01130009"
_INVALID_SCOPE_ERROR_CODE = "0001-01-1150"


class HondaLinkError(Exception):
    pass


class HondaLinkAuthError(HondaLinkError):
    pass


class HondaLinkCommandError(HondaLinkError):
    pass


@dataclass
class HondaLinkCommandResult:
    request_id: str | None
    response: dict[str, Any]


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _lower_status(value: Any) -> str:
    return str(value or "").strip().lower()


def _is_dynamic_backend_error(err: Exception) -> bool:
    text = str(err)
    return _DYNAMIC_BACKEND_ERROR_CODE in text or "Dynamic backend host not specified" in text


def _is_invalid_scope_error(err: Exception) -> bool:
    text = str(err)
    return _INVALID_SCOPE_ERROR_CODE in text or "requested scope is invalid" in text.lower()


def _redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in {
                "access_token",
                "refresh_token",
                "password",
                "pin",
                "client_reg_key",
            }:
                redacted[key] = "**REDACTED**"
            else:
                redacted[key] = _redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    return value


class HondaLinkAPI:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        email: str,
        password: str,
        pin: str | None,
        vin: str | None = None,
        client_reg_key: str | None = None,
        access_token: str | None = None,
        refresh_token: str | None = None,
        expires_at: float | None = None,
        country: str = DEFAULT_COUNTRY,
        language: str = DEFAULT_LANGUAGE,
        hidas_ident: str | None = None,
        device_id: str | None = None,
        session_id: str | None = None,
        lock_command: str = DEFAULT_LOCK_COMMAND,
        unlock_command: str = DEFAULT_UNLOCK_COMMAND,
    ) -> None:
        self.session = session
        self.email = email
        self.password = password
        self.pin = pin or ""
        self.vin = vin
        self.client_reg_key = client_reg_key
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at or 0
        self.country = country or DEFAULT_COUNTRY
        self.language = language or DEFAULT_LANGUAGE
        self.hidas_ident = hidas_ident
        self.device_id = device_id or str(uuid.uuid4())
        self.session_id = session_id or str(uuid.uuid4())
        self.lock_command = lock_command or DEFAULT_LOCK_COMMAND
        self.unlock_command = unlock_command or DEFAULT_UNLOCK_COMMAND

    async def async_register_client(self) -> str:
        data = await self._request_identity(
            "POST",
            "/hidas/rs/client/register",
            data={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
        )
        try:
            self.client_reg_key = data["clientregistrationkey"]["client_reg_key"]
        except (KeyError, TypeError) as err:
            raise HondaLinkAuthError(f"Client registration failed: {_redact_payload(data)}") from err
        return self.client_reg_key

    async def async_login(self) -> None:
        if not self.client_reg_key:
            await self.async_register_client()

        data = await self._request_identity(
            "POST",
            "/hidas/rs/token/generate",
            data={
                "username": self.email,
                "password": self.password,
                "description": DEVICE_DESCRIPTION,
                "client_reg_key": self.client_reg_key,
            },
        )

        if data.get("request_status") != "success":
            raise HondaLinkAuthError(f"Login failed: {_redact_payload(data)}")

        token = data.get("token") or {}
        user = data.get("user") or {}
        access_token = token.get("access_token")
        if not access_token:
            raise HondaLinkAuthError(f"Login did not return access_token: {_redact_payload(data)}")

        self.access_token = access_token
        self.refresh_token = token.get("refresh_token")
        expires_in = int(token.get("expires_in") or 0)
        self.expires_at = time.time() + max(expires_in - 300, 60)
        self.country = user.get("country_code") or self.country or DEFAULT_COUNTRY
        self.language = user.get("language_code") or self.language or DEFAULT_LANGUAGE
        self.hidas_ident = user.get("hidas_ident") or self.hidas_ident

    async def async_ensure_login(self) -> None:
        if self.access_token and self.expires_at > time.time() and self.hidas_ident:
            return
        await self.async_login()

    def export_auth_data(self) -> dict[str, Any]:
        return {
            CONF_CLIENT_REG_KEY: self.client_reg_key,
            CONF_ACCESS_TOKEN: self.access_token,
            CONF_REFRESH_TOKEN: self.refresh_token,
            CONF_EXPIRES_AT: self.expires_at,
            CONF_COUNTRY: self.country,
            CONF_LANGUAGE: self.language,
            CONF_HIDAS_IDENT: self.hidas_ident,
            CONF_DEVICE_ID: self.device_id,
            CONF_SESSION_ID: self.session_id,
        }

    async def async_get_vehicles(self) -> list[dict[str, Any]]:
        data = await self._request_api("GET", "/REST/NGT/MyVehicle/1.0")
        if _lower_status(data.get("status")) not in ("success", ""):
            raise HondaLinkError(f"Vehicle lookup failed: {_redact_payload(data)}")
        vehicles = data.get("vehicleInfo") or []
        return vehicles if isinstance(vehicles, list) else []

    async def async_get_vehicle_by_vin(self, vin: str) -> dict[str, Any] | None:
        data = await self._request_api("GET", f"/REST/NGT/MyVehicle/1.0/{vin}")
        vehicles = data.get("vehicleInfo") or []
        if isinstance(vehicles, list) and vehicles:
            return vehicles[0]
        return None

    async def async_get_profile(self, vin: str) -> dict[str, Any]:
        return await self._request_api("GET", f"/REST/NGT/myProfile/1.0/{vin}")

    async def async_get_dashboard_latest(self, vin: str | None = None) -> dict[str, Any]:
        vin = vin or self.vin
        if not vin:
            raise HondaLinkError("VIN is required")
        data = await self._request_api(
            "POST",
            f"/REST/NGT/CIG/dbd/latest/{vin}",
            json_body={"fromDate": "", "toDate": ""},
        )
        if _lower_status(data.get("status")) != "success":
            raise HondaLinkError(f"Dashboard request failed: {_redact_payload(data)}")
        return data

    async def async_request_dashboard_update(self, vin: str | None = None) -> HondaLinkCommandResult:
        vin = vin or self.vin
        if not vin:
            raise HondaLinkError("VIN is required")
        last_error: HondaLinkError | None = None
        for filters in DASHBOARD_FILTER_SETS:
            body: dict[str, Any] = {"device": vin}
            if filters:
                body["filters"] = filters
            try:
                data = await self._request_api(
                    "POST",
                    "/REST/NGT/CIG/dbd/async",
                    json_body=body,
                )
                break
            except HondaLinkError as err:
                if not _is_invalid_scope_error(err):
                    raise
                last_error = err
        else:
            if last_error:
                raise last_error
            raise HondaLinkError("Dashboard refresh request failed")

        response_body = data.get("responseBody") or {}
        request_id = response_body.get("cigServiceRequestId")
        status = _lower_status(data.get("status"))

        if status not in ("success", "in_progress", ""):
            message = response_body.get("errorMessage") or str(data)
            raise HondaLinkCommandError(message)

        if not request_id:
            return HondaLinkCommandResult(None, data)

        result = await self._poll_cig_result("dbd", request_id, timeout=60, poll_interval=3)
        return HondaLinkCommandResult(request_id, result)

    async def async_start_engine(self, *, extend: bool = False) -> HondaLinkCommandResult:
        return await self._async_cig_command(
            "eng",
            "srt",
            {"device": self._vin(), "pin": self._pin(), "extend": bool(extend)},
        )

    async def async_stop_engine(self) -> HondaLinkCommandResult:
        return await self._async_cig_command(
            "eng",
            "sop",
            {"device": self._vin(), "pin": self._pin(), "extend": False},
        )

    async def async_lock(self) -> HondaLinkCommandResult:
        body = {"device": self._vin(), "pin": self._pin()}
        if self.lock_command == DEFAULT_LOCK_COMMAND:
            body["delay"] = {"unit": "Minutes", "value": 2}
        try:
            return await self._async_cig_command("lk", self.lock_command, body)
        except HondaLinkCommandError as err:
            if self.lock_command != LEGACY_LOCK_COMMAND or not _is_dynamic_backend_error(err):
                raise
        return await self._async_cig_command(
            "lk",
            DEFAULT_LOCK_COMMAND,
            {"device": self._vin(), "pin": self._pin(), "delay": {"unit": "Minutes", "value": 2}},
        )

    async def async_unlock(self) -> HondaLinkCommandResult:
        try:
            return await self._async_cig_command(
                "lk",
                self.unlock_command,
                {"device": self._vin(), "pin": self._pin()},
            )
        except HondaLinkCommandError as err:
            if self.unlock_command != LEGACY_UNLOCK_COMMAND or not _is_dynamic_backend_error(err):
                raise
        return await self._async_cig_command(
            "lk",
            DEFAULT_UNLOCK_COMMAND,
            {"device": self._vin(), "pin": self._pin()},
        )

    async def async_horn(self) -> HondaLinkCommandResult:
        return await self._async_cig_command(
            "cfhl",
            "hrn",
            {"device": self._vin(), "pin": self._pin()},
        )

    async def async_lights(self) -> HondaLinkCommandResult:
        return await self._async_cig_command(
            "cfhl",
            "lgt",
            {"device": self._vin(), "pin": self._pin()},
        )

    async def async_stop_horn_lights(self) -> HondaLinkCommandResult:
        return await self._async_cig_command(
            "cfhl",
            "sop",
            {"device": self._vin(), "pin": self._pin()},
        )

    async def _async_cig_command(
        self,
        engine: str,
        command: str,
        body: dict[str, Any],
        *,
        timeout: int = 75,
        poll_interval: int = 3,
    ) -> HondaLinkCommandResult:
        try:
            data = await self._request_api(
                "POST",
                f"/REST/NGT/CIG/{engine}/async/{command}",
                json_body=body,
            )
        except HondaLinkError as err:
            raise HondaLinkCommandError(str(err)) from err
        response_body = data.get("responseBody") or {}
        request_id = response_body.get("cigServiceRequestId")
        status = _lower_status(data.get("status"))

        if status not in ("success", ""):
            message = response_body.get("errorMessage") or str(data)
            raise HondaLinkCommandError(message)

        if not request_id:
            return HondaLinkCommandResult(None, data)

        result = await self._poll_cig_result(engine, request_id, timeout, poll_interval)
        return HondaLinkCommandResult(request_id, result)

    async def _poll_cig_result(
        self,
        engine: str,
        request_id: str,
        timeout: int,
        poll_interval: int,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last_data: dict[str, Any] = {}

        while time.monotonic() < deadline:
            data = await self._request_api(
                "GET",
                f"/REST/NGT/CIG/{engine}/results/{request_id}",
            )
            last_data = data
            response_body = data.get("responseBody") or {}
            status = _lower_status(data.get("status") or response_body.get("status") or response_body.get("commandStatus"))

            if status in ("success", "completed", "complete", "ok"):
                return data
            if status in ("failure", "failed", "error"):
                message = response_body.get("errorMessage") or str(data)
                raise HondaLinkCommandError(message)

            await asyncio.sleep(poll_interval)

        raise HondaLinkCommandError(f"Command timed out waiting for completion: {last_data}")

    async def _request_identity(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{IDENTITY_BASE}{path}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": APP_USER_AGENT,
        }
        return await self._send(method, url, headers=headers, data=data)

    async def _request_api(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> dict[str, Any]:
        await self.async_ensure_login()
        url = f"{API_BASE}{path}"
        headers = self._api_headers()
        try:
            data = await self._send(method, url, headers=headers, json_body=json_body)
        except HondaLinkAuthError:
            if not retry:
                raise
            self.access_token = None
            self.client_reg_key = None
            await self.async_login()
            headers = self._api_headers()
            data = await self._send(method, url, headers=headers, json_body=json_body)

        error_code = str((data.get("Header") or {}).get("ErrorCode") or "")
        if retry and error_code == "401":
            self.access_token = None
            self.client_reg_key = None
            await self.async_login()
            headers = self._api_headers()
            data = await self._send(method, url, headers=headers, json_body=json_body)

        return data

    async def _send(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        data: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with self.session.request(
            method,
            url,
            headers=headers,
            data=data,
            json=json_body,
        ) as response:
            text = await response.text()
            try:
                payload = json.loads(text) if text else {}
            except json.JSONDecodeError as err:
                raise HondaLinkError(f"Invalid JSON from HondaLink: {response.status} {text}") from err

            if response.status in (401, 403):
                raise HondaLinkAuthError(f"HondaLink authorization failed: {_redact_payload(payload)}")
            if response.status >= 400:
                raise HondaLinkError(f"HondaLink request failed: HTTP {response.status} {_redact_payload(payload)}")
            return payload

    def _api_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "bearerToken": self.access_token or "",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": APP_USER_AGENT,
            "hondaHeaderType.version": HONDA_HEADER_VERSION,
            "hondaHeaderType.messageId": str(uuid.uuid4()),
            "hondaHeaderType.siteId": self.client_reg_key or "",
            "hondaHeaderType.businessId": HONDALINK_BUSINESS_ID,
            "hondaHeaderType.systemId": HONDALINK_SYSTEM_ID,
            "hondaHeaderType.clientType": "Mobile",
            "hondaHeaderType.collectedTimestamp": utc_timestamp(),
            "hondaHeaderType.country_code": self.country,
            "hondaHeaderType.language_code": self.language,
        }
        if self.hidas_ident:
            headers["hondaHeaderType.userId"] = self.hidas_ident
        return headers

    def _vin(self) -> str:
        if not self.vin:
            raise HondaLinkCommandError("VIN is required")
        return self.vin

    def _pin(self) -> str:
        if not self.pin:
            raise HondaLinkCommandError("Remote PIN is required")
        return self.pin
