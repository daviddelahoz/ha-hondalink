from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .const import (
    API_BASE,
    ACURA_DASHBOARD_FILTERS,
    BRAND_ACURA,
    BRANDS,
    DEFAULT_BRAND,
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
    HONDA_HEADER_VERSION,
    IDENTITY_BASE,
    LEGACY_LOCK_COMMAND,
    LEGACY_UNLOCK_COMMAND,
    PUSH_TOKEN_PATH,
)
from .push import HondaLinkPushClient, HondaLinkPushDisconnected, HondaLinkPushError

_LOGGER = logging.getLogger(__name__)
DASHBOARD_REFRESH_WAIT = 20
PUSH_RETRY_DELAY = 60
_DYNAMIC_BACKEND_ERROR_CODE = "0x01130009"
_INVALID_SCOPE_ERROR_CODE = "0001-01-1150"
_UNAUTHORIZED_ERROR_CODE = "0001-01-1154"


class HondaLinkError(Exception):
    pass


class HondaLinkAuthError(HondaLinkError):
    pass


class HondaLinkCommandError(HondaLinkError):
    pass


class HondaLinkResultUnavailable(HondaLinkError):
    """The command was accepted but its result can't be read (e.g. the push channel dropped)."""


@dataclass
class HondaLinkCommandResult:
    request_id: str | None
    response: dict[str, Any]


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lower_status(value: Any) -> str:
    return str(value or "").strip().lower()


def _is_dynamic_backend_error(err: Exception) -> bool:
    text = str(err)
    return _DYNAMIC_BACKEND_ERROR_CODE in text or "Dynamic backend host not specified" in text


def _is_unauthorized_error(err: Exception) -> bool:
    return _UNAUTHORIZED_ERROR_CODE in str(err)


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
                "token",
                "tokensignature",
                "bearertoken",
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
        brand: str = DEFAULT_BRAND,
    ) -> None:
        self.session = session
        self.brand = brand if brand in BRANDS else DEFAULT_BRAND
        self.push: HondaLinkPushClient | None = None
        self._push_retry_at = 0.0
        self._brand = BRANDS[self.brand]
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
            data={"client_id": self._brand["client_id"], "client_secret": self._brand["client_secret"]},
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

    @property
    def push_active(self) -> bool:
        return self.push is not None and self.push.is_ready

    async def async_start_push(self) -> None:
        """Connect the MQTT push channel that delivers results on AcuraLink 2GX vehicles."""
        if self.brand != BRAND_ACURA or not self.vin:
            return
        if self.push is None:
            self.push = HondaLinkPushClient(self.device_id, self.vin, self._async_fetch_push_token)
        await self.async_ensure_login()
        await self.push.async_ensure_ready()

    async def async_stop_push(self) -> None:
        if self.push is not None:
            await self.push.async_close()

    async def async_ensure_push(self) -> None:
        """Start the push channel if needed; on failure fall back to REST and retry later."""
        if self.brand != BRAND_ACURA or (self.push is not None and self.push.closed):
            return
        if self.push_active or time.monotonic() < self._push_retry_at:
            return
        try:
            await self.async_start_push()
        except (HondaLinkError, HondaLinkPushError, OSError) as err:
            self._push_retry_at = time.monotonic() + PUSH_RETRY_DELAY
            _LOGGER.warning("HondaLink push channel unavailable, falling back to REST results: %s", err)

    async def _async_fetch_push_token(self) -> dict[str, Any]:
        return await self._request_api("POST", PUSH_TOKEN_PATH, json_body={"device": self.vin})

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
        path = f"/REST/NGT/CIG/dbd/latest/{vin}"
        dated_body = {"fromDate": "", "toDate": ""}
        if self.brand == BRAND_ACURA:
            # The Acura app posts an empty body.
            try:
                data = await self._request_api("POST", path, json_body={})
            except HondaLinkAuthError:
                raise
            except HondaLinkError:
                data = await self._request_api("POST", path, json_body=dated_body)
        else:
            data = await self._request_api("POST", path, json_body=dated_body)
        if _lower_status(data.get("status")) != "success":
            raise HondaLinkError(f"Dashboard request failed: {_redact_payload(data)}")
        return data

    async def async_request_dashboard_update(self, vin: str | None = None) -> HondaLinkCommandResult:
        vin = vin or self.vin
        if not vin:
            raise HondaLinkError("VIN is required")
        await self.async_ensure_push()
        last_error: HondaLinkError | None = None
        filter_sets = DASHBOARD_FILTER_SETS
        if self.brand == BRAND_ACURA:
            filter_sets = (ACURA_DASHBOARD_FILTERS, *DASHBOARD_FILTER_SETS)
        for filters in filter_sets:
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
                # AcuraLink answers an unsupported filter list with 'Unauthorized'.
                if not (_is_invalid_scope_error(err) or (self.brand == BRAND_ACURA and _is_unauthorized_error(err))):
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

        try:
            result = await self._poll_cig_result("dbd", request_id, timeout=60, poll_interval=3)
        except HondaLinkCommandError:
            raise
        except HondaLinkError as err:
            # AcuraLink 2GX vehicles deliver refresh results over MQTT, not the REST results
            # endpoint; the request was accepted, so give the car time to report, then the
            # caller re-reads /dbd/latest.
            if self.brand != BRAND_ACURA:
                raise
            _LOGGER.debug("Dashboard results endpoint unavailable (%s); waiting for latest data", err)
            await asyncio.sleep(DASHBOARD_REFRESH_WAIT)
            result = {"status": "submitted", "responseBody": response_body}
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

    async def async_request_location(self) -> HondaLinkCommandResult:
        """Ask the vehicle for its current position (the app's Locate / Update Location)."""
        return await self._async_cig_command(
            "cfl",
            "",
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
        await self.async_ensure_push()
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

        try:
            result = await self._poll_cig_result(engine, request_id, timeout, poll_interval)
        except HondaLinkCommandError:
            raise
        except HondaLinkError as err:
            # AcuraLink 2GX vehicles report command results over MQTT; the REST results
            # endpoint answers 'Unauthorized'. The command itself was accepted, so treat
            # it as submitted rather than failed.
            if self.brand != BRAND_ACURA or not (
                isinstance(err, HondaLinkResultUnavailable) or _is_unauthorized_error(err)
            ):
                raise
            _LOGGER.debug("Command %s/%s accepted; result not readable (%s)", engine, command, err)
            result = {"status": "submitted", "responseBody": response_body}
        return HondaLinkCommandResult(request_id, result)

    async def _poll_cig_result(
        self,
        engine: str,
        request_id: str,
        timeout: int,
        poll_interval: int,
    ) -> dict[str, Any]:
        if self.push_active:
            return await self._poll_push_result(request_id, timeout)

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

    async def _poll_push_result(self, request_id: str, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        try:
            while True:
                remaining = deadline - time.monotonic()
                try:
                    reported = await self.push.async_wait_result(request_id, max(remaining, 0.1))
                except HondaLinkPushDisconnected as err:
                    raise HondaLinkResultUnavailable(str(err)) from err
                except HondaLinkPushError as err:
                    raise HondaLinkCommandError(str(err)) from err
                response_body = reported.get("responseBody") or {}
                status = _lower_status(reported.get("status"))
                data = {"status": reported.get("status"), "responseBody": response_body}
                if status in ("success", "completed", "complete", "ok"):
                    return data
                if status in ("failure", "failed", "error"):
                    raise HondaLinkCommandError(response_body.get("errorMessage") or str(data))
                if remaining <= 0:
                    raise HondaLinkCommandError(f"Command timed out waiting for completion: {data}")
        finally:
            self.push.release(request_id)

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
            "User-Agent": self._brand["user_agent"],
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
        data = await self._send(method, url, headers=headers, json_body=json_body)

        error_code = str((data.get("Header") or {}).get("ErrorCode") or "")
        if retry and error_code == "401":
            self.access_token = None
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
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": self._brand["user_agent"],
            "hondaHeaderType.version": HONDA_HEADER_VERSION,
            "hondaHeaderType.messageId": str(uuid.uuid4()),
            "hondaHeaderType.siteId": self.client_reg_key or "",
            "hondaHeaderType.businessId": self._brand["business_id"],
            "hondaHeaderType.systemId": self._brand["system_id"],
            "hondaHeaderType.collectedTimestamp": utc_timestamp(),
            "hondaHeaderType.collectedTimeStamp": utc_timestamp(),
            "hondaHeaderType.clientType": "Mobile",
            "hondaHeaderType.deviceID": self.device_id,
            "hondaHeaderType.sessionID": self.session_id,
            "hondaHeaderType.country_code": self.country,
            "hondaHeaderType.language_code": self.language,
        }
        if self.brand == BRAND_ACURA:
            headers["bearerToken"] = self.access_token or ""
        if self.hidas_ident:
            headers["hondaHeaderType.userId"] = self.hidas_ident
            headers["hondaHeaderType.hidasId"] = self.hidas_ident
        return headers

    def _vin(self) -> str:
        if not self.vin:
            raise HondaLinkCommandError("VIN is required")
        return self.vin

    def _pin(self) -> str:
        if not self.pin:
            raise HondaLinkCommandError("Remote PIN is required")
        return self.pin
