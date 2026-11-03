"""MQTT push channel used by the AcuraLink app for remote command and refresh results.

On 2GX vehicles the REST ``/CIG/<engine>/results/<id>`` endpoint answers ``Unauthorized``; the
result of an async request is published to an AWS IoT shadow topic instead.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
import json
import logging
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)

IOT_ENDPOINT = "am7ptks1rwalc-ats.iot.us-east-2.amazonaws.com"
IOT_AUTHORIZER = "CPSD-IOT-CustAuthorizer-prod"
IOT_TOKEN_KEY = "prod_key"

FEATURES = (
    "DASHBOARD_ASYNC",
    "LOCK_ASYNC",
    "ENGINE_START_STOP_ASYNC",
    "CARFINDER_HORN_LIGHT_ASYNC",
    "CARFINDER_LOCATION_ASYNC",
)
CONNECT_TIMEOUT = 20
MAX_TRACKED_REQUESTS = 50
WAIT_SLICE = 5


class HondaLinkPushError(Exception):
    pass


class HondaLinkPushDisconnected(HondaLinkPushError):
    """The push channel dropped while waiting for a result."""


class HondaLinkPushClient:
    """Keeps a subscription to the vehicle's result topics and hands results to waiters."""

    def __init__(
        self,
        device_id: str,
        vin: str,
        fetch_token: Callable[[], Awaitable[dict[str, Any]]],
    ) -> None:
        self._device_id = device_id
        self._vin = vin
        self._fetch_token = fetch_token
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: mqtt.Client | None = None
        self._closed = False
        self._ready = asyncio.Event()
        self._start_lock = asyncio.Lock()
        self._suback_count = 0
        self._queues: OrderedDict[str, asyncio.Queue] = OrderedDict()
        self._thread_lock = threading.Lock()

    @property
    def is_ready(self) -> bool:
        return self._ready.is_set()

    @property
    def closed(self) -> bool:
        return self._closed

    async def async_ensure_ready(self) -> None:
        """Connect (or reconnect with a fresh token) and wait for all subscriptions."""
        if self._closed:
            raise HondaLinkPushError("The HondaLink push channel is closed")
        if self.is_ready:
            return
        async with self._start_lock:
            if self._closed:
                raise HondaLinkPushError("The HondaLink push channel is closed")
            if self.is_ready:
                return
            self._loop = asyncio.get_running_loop()
            await self.async_stop()
            token, signature = await self._async_get_token()
            client = await self._loop.run_in_executor(None, self._build_and_connect, token, signature)
            self._client = client
            try:
                await asyncio.wait_for(self._ready.wait(), CONNECT_TIMEOUT)
            except asyncio.TimeoutError as err:
                await self.async_stop()
                raise HondaLinkPushError("Timed out connecting to the HondaLink push channel") from err
            if self._closed:
                await self.async_stop()
                raise HondaLinkPushError("The HondaLink push channel is closed")

    async def async_stop(self) -> None:
        """Drop the connection; it is rebuilt by the next ``async_ensure_ready``."""
        client, self._client = self._client, None
        self._ready.clear()
        if client is not None:
            await asyncio.get_running_loop().run_in_executor(None, self._shutdown, client)

    async def async_close(self) -> None:
        """Drop the connection for good (the config entry is unloading)."""
        self._closed = True
        await self.async_stop()
        self._loop = None
        self._queues.clear()

    async def async_wait_result(self, request_id: str, timeout: float) -> dict[str, Any]:
        """Wait for the next message for a request id and return its ``reported`` state."""
        loop = asyncio.get_running_loop()
        queue = self._queue(request_id)
        deadline = loop.time() + timeout
        while True:
            if not self.is_ready:
                raise HondaLinkPushDisconnected("The HondaLink push channel disconnected")
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise HondaLinkPushError("Timed out waiting for the vehicle's result")
            try:
                return await asyncio.wait_for(queue.get(), min(remaining, WAIT_SLICE))
            except asyncio.TimeoutError:
                continue

    def release(self, request_id: str) -> None:
        """Forget a request once its caller is done with it."""
        self._queues.pop(request_id, None)

    async def _async_get_token(self) -> tuple[str, str]:
        data = await self._fetch_token()
        body = data.get("responseBody") or {}
        token, signature = body.get("token"), body.get("tokenSignature")
        if not token or not signature:
            raise HondaLinkPushError("Push channel token request did not return a token")
        return token, signature

    def _build_and_connect(self, token: str, signature: str) -> mqtt.Client:
        # Imported here (in an executor thread) so the integration still loads for accounts
        # that never use the push channel.
        import paho.mqtt.client as mqtt  # noqa: PLC0415

        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self._device_id,
            transport="websockets",
            protocol=mqtt.MQTTv311,
            clean_session=False,
        )
        client.tls_set()
        client.ws_set_options(
            path="/mqtt",
            headers={
                "X-Amz-CustomAuthorizer-Name": IOT_AUTHORIZER,
                "X-Amz-CustomAuthorizer-Signature": signature,
                IOT_TOKEN_KEY: token,
            },
        )
        client.on_connect = self._on_connect
        client.on_subscribe = self._on_subscribe
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        client.connect(IOT_ENDPOINT, 443, keepalive=60)
        client.loop_start()
        return client

    @staticmethod
    def _shutdown(client: mqtt.Client) -> None:
        try:
            client.disconnect()
            client.loop_stop()
        except Exception:  # noqa: BLE001 - best effort cleanup
            _LOGGER.debug("Error shutting down push client", exc_info=True)

    def _topics(self) -> list[tuple[str, int]]:
        return [(f"$aws/things/thing_{self._vin}/shadow/name/{feature}/update", 1) for feature in FEATURES]

    def _call_in_loop(self, func: Callable[..., Any], *args: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(func, *args)
        except RuntimeError:
            # The loop shut down between the check and the call.
            pass

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            _LOGGER.warning("HondaLink push channel connection refused: %s", reason_code)
            return
        with self._thread_lock:
            self._suback_count = 0
        for topic, qos in self._topics():
            client.subscribe(topic, qos=qos)

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties) -> None:
        with self._thread_lock:
            self._suback_count += 1
            done = self._suback_count >= len(FEATURES)
        if done:
            self._call_in_loop(self._ready.set)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            _LOGGER.warning("HondaLink push channel disconnected: %s", reason_code)
        else:
            _LOGGER.debug("HondaLink push channel disconnected: %s", reason_code)
        self._call_in_loop(self._ready.clear)

    def _on_message(self, client, userdata, message) -> None:
        try:
            payload = json.loads(message.payload.decode())
            reported = (payload.get("state") or {}).get("reported") or {}
        except (ValueError, AttributeError):
            return
        request_id = reported.get("cigServiceRequestId")
        if request_id:
            self._call_in_loop(self._deliver, request_id, reported)

    def _deliver(self, request_id: str, reported: dict[str, Any]) -> None:
        self._queue(request_id).put_nowait(reported)

    def _queue(self, request_id: str) -> asyncio.Queue:
        queue = self._queues.get(request_id)
        if queue is None:
            queue = self._queues[request_id] = asyncio.Queue()
            while len(self._queues) > MAX_TRACKED_REQUESTS:
                self._queues.popitem(last=False)
        return queue
