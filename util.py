from __future__ import annotations

from datetime import datetime
from typing import Any


def get_path(data: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return default
        if cur is None:
            return default
    return cur


def status_body(data: dict[str, Any]) -> dict[str, Any]:
    body = data.get("responseBody")
    return body if isinstance(body, dict) else {}


def to_int(value: Any) -> int | None:
    try:
        if value in (None, "", "unknown"):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def to_float(value: Any) -> float | None:
    try:
        if value in (None, "", "unknown"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def first_path(data: dict[str, Any], paths: tuple[str, ...]) -> Any:
    for path in paths:
        value = get_path(data, path)
        if value not in (None, "", "unknown"):
            return value
    return None


def value_from_status_node(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    for key in (
        "status",
        "state",
        "condition",
        "value",
        "text",
        "displayValue",
        "message",
        "messageText",
        "statusText",
        "displayText",
        "description",
    ):
        item = value.get(key)
        if item not in (None, "", "unknown"):
            return value_from_status_node(item)
    return None


def find_12v_battery_status(data: dict[str, Any]) -> Any:
    warning_lamp_status = _find_12v_warning_lamp_status(data)
    if warning_lamp_status not in (None, "", "unknown"):
        return warning_lamp_status

    direct = first_path(
        data,
        (
            "12VBatteryStatus",
            "12VBattery.status",
            "12VBattery.value",
            "twelveVoltBatteryStatus",
            "twelveVoltBattery.status",
            "twelveVoltBattery.value",
            "auxBatteryStatus",
            "auxBattery.status",
            "auxBattery.value",
            "auxiliaryBatteryStatus",
            "auxiliaryBattery.status",
            "auxiliaryBattery.value",
            "battery12VStatus",
            "battery12V.status",
            "battery12V.value",
            "batteryStatus12V",
            "batteryVoltageStatus",
            "batteryStatus.batteryVoltageStatus",
            "batteryStatus.batteryChargeStatus",
            "batteryStatus.status",
            "batteryStatus.value",
        ),
    )
    if direct not in (None, "", "unknown"):
        return value_from_status_node(direct)
    text_status = _find_12v_text_status(data)
    if text_status not in (None, "", "unknown"):
        return text_status
    return _find_12v_battery_status(data)


def find_12v_battery_candidates(data: dict[str, Any]) -> dict[str, Any]:
    candidates: dict[str, Any] = {}
    _collect_12v_battery_candidates(data, "", candidates)
    return candidates


def leaf_paths(data: dict[str, Any], *, limit: int = 300) -> list[str]:
    paths: list[str] = []
    _collect_leaf_paths(data, "", paths, limit)
    return paths


def _find_12v_warning_lamp_status(data: dict[str, Any]) -> Any:
    for group in get_path(data, "warningLamps.data", []) or []:
        if not isinstance(group, dict):
            continue
        for message in group.get("messages", []) or []:
            if not isinstance(message, dict):
                continue
            text = " ".join(str(value) for value in message.values() if isinstance(value, str))
            text_lower = text.lower()
            has_12v = "12v" in text_lower or "12 v" in text_lower or "12 volt" in text_lower
            has_battery = "battery" in text_lower or "batt" in text_lower
            if has_12v and has_battery:
                return (
                    message.get("condition")
                    or message.get("status")
                    or message.get("state")
                    or message.get("value")
                    or message.get("message")
                    or message.get("messageText")
                    or message.get("text")
                    or "Detected"
                )
    return None


def _find_12v_text_status(value: Any) -> Any:
    if isinstance(value, dict):
        text = " ".join(str(item) for item in value.values() if isinstance(item, str))
        if _text_mentions_12v_battery(text):
            status = value_from_status_node(value)
            if status not in (None, "", "unknown") and not _text_mentions_12v_battery(str(status)):
                return status
            for key in (
                "normal",
                "ok",
                "active",
                "on",
                "off",
                "severity",
                "alertState",
                "lampState",
                "indicator",
                "available",
            ):
                item = value.get(key)
                if item not in (None, "", "unknown"):
                    return item
            return "Detected"
        for item in value.values():
            status = _find_12v_text_status(item)
            if status not in (None, "", "unknown"):
                return status
    elif isinstance(value, list):
        for item in value:
            status = _find_12v_text_status(item)
            if status not in (None, "", "unknown"):
                return status
    elif isinstance(value, str) and _text_mentions_12v_battery(value):
        return value
    return None


def _find_12v_battery_status(value: Any) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if _looks_like_12v_battery_key(str(key)):
                status = value_from_status_node(item)
                if status not in (None, "", "unknown"):
                    return status
            status = _find_12v_battery_status(item)
            if status not in (None, "", "unknown"):
                return status
    if isinstance(value, list):
        for item in value:
            status = _find_12v_battery_status(item)
            if status not in (None, "", "unknown"):
                return status
    return None


def _collect_12v_battery_candidates(value: Any, path: str, candidates: dict[str, Any]) -> None:
    if len(candidates) >= 20:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}" if path else str(key)
            if _looks_like_12v_battery_key(str(key)) or (
                isinstance(item, str) and _text_mentions_12v_battery(item)
            ):
                candidate = value_from_status_node(item)
                candidates[item_path] = _attribute_safe_value(candidate if candidate is not None else item)
            _collect_12v_battery_candidates(item, item_path, candidates)
    elif isinstance(value, list):
        for index, item in enumerate(value[:20]):
            _collect_12v_battery_candidates(item, f"{path}.{index}" if path else str(index), candidates)


def _collect_leaf_paths(value: Any, path: str, paths: list[str], limit: int) -> None:
    if len(paths) >= limit:
        return
    if isinstance(value, dict):
        if not value and path:
            paths.append(path)
            return
        for key, item in value.items():
            item_path = f"{path}.{key}" if path else str(key)
            _collect_leaf_paths(item, item_path, paths, limit)
    elif isinstance(value, list):
        if not value and path:
            paths.append(path)
            return
        for index, item in enumerate(value[:20]):
            item_path = f"{path}.{index}" if path else str(index)
            _collect_leaf_paths(item, item_path, paths, limit)
    elif path:
        paths.append(path)


def _looks_like_12v_battery_key(key: str) -> bool:
    key_lower = key.lower()
    has_12v = "12v" in key_lower or "12_v" in key_lower or "twelvevolt" in key_lower or "twelve_volt" in key_lower
    has_battery = "battery" in key_lower or "batt" in key_lower
    has_voltage = "volt" in key_lower
    has_status = "status" in key_lower or "state" in key_lower or "condition" in key_lower
    has_aux = "aux" in key_lower or "auxiliary" in key_lower
    has_power_supply = "powersupply" in key_lower or "power_supply" in key_lower
    return (
        has_12v
        or (has_aux and (has_battery or has_voltage or has_status))
        or (has_battery and (has_status or has_voltage))
        or (has_voltage and has_status)
        or has_power_supply
    )


def _text_mentions_12v_battery(text: str) -> bool:
    text_lower = text.lower()
    has_12v = "12v" in text_lower or "12 v" in text_lower or "12 volt" in text_lower
    has_battery = "battery" in text_lower or "batt" in text_lower
    return has_12v and has_battery


def _attribute_safe_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in list(value.items())[:10]:
            safe[str(key)] = _attribute_safe_value(item)
        return safe
    if isinstance(value, list):
        return [_attribute_safe_value(item) for item in value[:10]]
    return str(value)


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value or value == "unknown":
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def dms_to_decimal(value: Any) -> float | None:
    if not value or value == "unknown":
        return None
    try:
        if "," not in str(value):
            # Plain decimal degrees (AcuraLink) instead of "degrees,minutes,seconds".
            return float(value)
        parts = str(value).split(",")
        if len(parts) != 3:
            return None
        degrees = float(parts[0])
        sign = -1 if degrees < 0 else 1
        minutes = float(parts[1])
        seconds = float(parts[2])
        return sign * (abs(degrees) + minutes / 60 + seconds / 3600)
    except (TypeError, ValueError):
        return None


def all_door_locks_locked(body: dict[str, Any]) -> bool | None:
    doors = get_path(body, "doorStatus", {})
    if not isinstance(doors, dict):
        return None
    states: list[str] = []
    for key in ("firstRowDriver", "firstRowPassenger", "secondRowDriver", "secondRowPassenger"):
        state = get_path(doors, f"{key}.lockState")
        if state:
            states.append(str(state))
    if not states:
        return None
    return all(state.lower() == "lock" for state in states)


def any_open_state(body: dict[str, Any], base: str, keys: list[str], state_key: str = "openState") -> bool | None:
    found = False
    for key in keys:
        value = get_path(body, f"{base}.{key}.{state_key}")
        if value is not None:
            found = True
            if str(value).lower() != "closed":
                return True
    return False if found else None


def any_light_on(body: dict[str, Any]) -> bool | None:
    lights = get_path(body, "lightStatus", {})
    if not isinstance(lights, dict):
        return None
    found = False
    for item in lights.values():
        if isinstance(item, dict) and "lightState" in item:
            found = True
            if str(item.get("lightState")).upper() != "OFF":
                return True
    return False if found else None


def merge_dashboard(base: dict[str, Any], newer: dict[str, Any]) -> dict[str, Any]:
    """Overlay ``newer`` on ``base``; empty (None) values in ``newer`` keep the value from ``base``."""
    merged = dict(base)
    for key, value in newer.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dashboard(merged[key], value)
        elif value is not None and value != "":
            merged[key] = value
    return merged


_LAMP_ON_VALUES = {"ON", "1", "0X1"}


def _preferred_group(groups: Any) -> list[dict[str, Any]]:
    """Use English when the groups are per-language copies of the same data, else all groups."""
    items = [group for group in groups or [] if isinstance(group, dict)]
    if not any(group.get("languageCode") for group in items):
        return items
    english = [group for group in items if str(group.get("languageCode", "")).lower().startswith("en")]
    return english or items[:1]


def active_warning_lamps(body: dict[str, Any]) -> list[dict[str, Any]]:
    lamps: list[dict[str, Any]] = []
    for group in _preferred_group(get_path(body, "warningLamps.data", [])):
        for message in group.get("messages", []) or []:
            if isinstance(message, dict) and str(message.get("condition", "")).upper() in _LAMP_ON_VALUES:
                lamps.append(message)
    return lamps


def maintenance_items(body: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for group in _preferred_group(get_path(body, "maintenanceMinder.data", [])):
        for message in group.get("messages", []) or []:
            if isinstance(message, dict) and message.get("mmString"):
                items.append(str(message["mmString"]).strip())
    return items
