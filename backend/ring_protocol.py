from __future__ import annotations

import math
import re
import time
from collections import deque
from typing import Any


RING_EVENT_TYPES = {"status", "audio_ready", "imu", "burst", "freeze", "error"}
MOTION_EVENT_TYPES = {"imu", "burst", "freeze"}
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class RingProtocolError(ValueError):
    """A RingRuntime event does not match the frozen C/D handoff contract."""


def _finite_number(
    value: Any,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool):
        raise RingProtocolError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RingProtocolError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise RingProtocolError(f"{name} must be a finite number")
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _identifier(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RingProtocolError(f"{name} must be a string")
    if not _SESSION_ID_RE.fullmatch(value):
        raise RingProtocolError(
            f"{name} must be 1-80 characters using letters, numbers, '.', '_' or '-'"
        )
    return value


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise RingProtocolError(f"{name} must be a boolean")
    return value


def _integer(
    value: Any,
    name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    number = _finite_number(value, name, minimum=minimum, maximum=maximum)
    if not number.is_integer():
        raise RingProtocolError(f"{name} must be an integer")
    return int(number)


def _bounded_text(value: Any, name: str, maximum: int, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise RingProtocolError(f"{name} must be a string")
    cleaned = value.strip()
    if required and not cleaned:
        raise RingProtocolError(f"{name} is required")
    if len(cleaned) > maximum:
        raise RingProtocolError(f"{name} exceeds {maximum} characters")
    return cleaned


def normalize_ring_event(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RingProtocolError("ring event must be a JSON object")

    event_type = raw.get("type")
    payload = raw.get("payload", {})
    if event_type not in RING_EVENT_TYPES:
        raise RingProtocolError(f"unsupported RingRuntime event: {event_type}")
    if not isinstance(payload, dict):
        raise RingProtocolError("ring event payload must be an object")

    timestamp = raw.get("timestamp", int(time.time() * 1000))
    timestamp_number = _finite_number(timestamp, "timestamp", minimum=0)
    normalized_payload: dict[str, Any] = {}

    session_id = _identifier(
        payload.get("sessionId", payload.get("session_id")), "sessionId"
    )
    if event_type in MOTION_EVENT_TYPES and session_id is None:
        raise RingProtocolError(f"{event_type} requires payload.sessionId")
    if session_id is not None:
        normalized_payload["sessionId"] = session_id

    if event_type == "status":
        for key in (
            "phase",
            "modeHint",
            "firmware",
            "firmwareVersion",
            "address",
            "model",
            "sn",
            "message",
        ):
            maximum = 1000 if key == "message" else 128
            value = _bounded_text(payload.get(key), key, maximum)
            if value is not None:
                normalized_payload[key] = value
        connection_value = payload.get("ringConnected", payload.get("connected"))
        if connection_value is not None:
            connected = _boolean(connection_value, "ringConnected")
            normalized_payload["ringConnected"] = connected
            normalized_payload["connected"] = connected
        if "battery" in payload:
            normalized_payload["battery"] = _finite_number(
                payload["battery"], "battery", minimum=0, maximum=100
            )
        if "batteryPercent" in payload:
            normalized_payload["batteryPercent"] = _finite_number(
                payload["batteryPercent"], "batteryPercent", minimum=0, maximum=100
            )
        for key in (
            "attempt",
            "settleDelayMs",
            "audioCount",
            "audioCountBefore",
            "audioCountAfter",
            "audioStorageTotal",
            "audioStorageAvailable",
            "sampleRateHz",
            "accelRangeG",
            "gyroRangeDps",
            "deviceTimestampMs",
        ):
            if key in payload:
                normalized_payload[key] = _integer(payload[key], key, minimum=0)
        for key in ("batteryCharging", "settled", "healthChecked"):
            if key in payload:
                normalized_payload[key] = _boolean(payload[key], key)
    elif event_type == "audio_ready":
        wav_path = _bounded_text(payload.get("wavPath"), "wavPath", 4096, required=True)
        normalized_payload["wavPath"] = wav_path
        raw_path = _bounded_text(payload.get("rawPath"), "rawPath", 4096)
        if raw_path is not None:
            normalized_payload["rawPath"] = raw_path
        for key in ("fileIndex", "durationMs", "recordTime"):
            if key in payload:
                normalized_payload[key] = _integer(payload[key], key, minimum=0)
        if "rmsDbfs" in payload:
            normalized_payload["rmsDbfs"] = _finite_number(payload["rmsDbfs"], "rmsDbfs")
        if "speechActivityRatio" in payload:
            normalized_payload["speechActivityRatio"] = _finite_number(
                payload["speechActivityRatio"],
                "speechActivityRatio",
                minimum=0,
                maximum=1,
            )
        if "recovered" in payload:
            normalized_payload["recovered"] = _boolean(payload["recovered"], "recovered")
        if "warnings" in payload:
            warnings = payload["warnings"]
            if not isinstance(warnings, list) or len(warnings) > 20:
                raise RingProtocolError("warnings must be an array of at most 20 strings")
            normalized_payload["warnings"] = [
                _bounded_text(item, "warning", 500, required=True) for item in warnings
            ]
    elif event_type == "imu":
        normalized_payload["twist"] = _finite_number(
            payload.get("twist", 0), "twist", minimum=-1, maximum=1
        )
        normalized_payload["accelMag"] = _finite_number(
            payload.get("accelMag", 0), "accelMag", minimum=0, maximum=1
        )
        for key in ("accelX", "accelY", "accelZ", "gyroX", "gyroY", "gyroZ", "gyroXY"):
            normalized_payload[key] = _finite_number(payload.get(key, 0), key)
        if "sequence" in payload:
            normalized_payload["sequence"] = _integer(payload["sequence"], "sequence", minimum=0)
        if "deviceTimestampMs" in payload:
            normalized_payload["deviceTimestampMs"] = _integer(
                payload["deviceTimestampMs"], "deviceTimestampMs", minimum=0
            )
    elif event_type == "burst":
        normalized_payload["strength"] = _finite_number(
            payload.get("strength", 1), "strength", minimum=0, maximum=1
        )
        source = _bounded_text(payload.get("source"), "source", 128)
        if source is not None:
            normalized_payload["source"] = source
        if "sequence" in payload:
            normalized_payload["sequence"] = _integer(payload["sequence"], "sequence", minimum=0)
        if "deviceTimestampMs" in payload:
            normalized_payload["deviceTimestampMs"] = _integer(
                payload["deviceTimestampMs"], "deviceTimestampMs", minimum=0
            )
    elif event_type == "freeze":
        normalized_payload["active"] = _boolean(payload.get("active", True), "active")
        source = _bounded_text(payload.get("source", "key_double_press"), "source", 128)
        normalized_payload["source"] = source
        if "sequence" in payload:
            normalized_payload["sequence"] = _integer(payload["sequence"], "sequence", minimum=0)
        if "deviceTimestampMs" in payload:
            normalized_payload["deviceTimestampMs"] = _integer(
                payload["deviceTimestampMs"], "deviceTimestampMs", minimum=0
            )
    elif event_type == "error":
        normalized_payload["message"] = _bounded_text(
            payload.get("message"), "message", 1000, required=True
        )
        code = _bounded_text(payload.get("code"), "code", 128)
        action = _bounded_text(payload.get("recommendedAction"), "recommendedAction", 1000)
        if code is not None:
            normalized_payload["code"] = code
        if action is not None:
            normalized_payload["recommendedAction"] = action
        phase = _bounded_text(payload.get("phase"), "phase", 128)
        if phase is not None:
            normalized_payload["phase"] = phase
        if "attempt" in payload:
            normalized_payload["attempt"] = _integer(payload["attempt"], "attempt", minimum=0)
        normalized_payload["recoverable"] = _boolean(
            payload.get("recoverable", False), "recoverable"
        )

    return {
        "type": event_type,
        "timestamp": int(timestamp_number),
        "payload": normalized_payload,
    }


class RingEventGuard:
    """Bounded per-session ordering and discrete-event idempotency."""

    def __init__(self, maximum_discrete_events: int = 512) -> None:
        self.maximum_discrete_events = maximum_discrete_events
        self.last_imu_sequence: dict[str, int] = {}
        self.freeze_state: dict[str, bool] = {}
        self._seen_discrete: set[tuple[str, str, int]] = set()
        self._discrete_order: deque[tuple[str, str, int]] = deque()

    def accept(self, message: dict[str, Any]) -> bool:
        event_type = message["type"]
        payload = message["payload"]
        session_id = payload.get("sessionId")
        if event_type not in MOTION_EVENT_TYPES or not session_id:
            return True

        if event_type == "imu" and "sequence" in payload:
            sequence = payload["sequence"]
            previous = self.last_imu_sequence.get(session_id)
            if previous is not None and sequence <= previous:
                return False
            self.last_imu_sequence[session_id] = sequence
            return True

        if event_type == "freeze":
            active = payload["active"]
            if self.freeze_state.get(session_id) is active:
                return False
            self.freeze_state[session_id] = active

        discriminator = int(payload.get("sequence", message["timestamp"]))
        key = (session_id, event_type, discriminator)
        if key in self._seen_discrete:
            return False
        self._seen_discrete.add(key)
        self._discrete_order.append(key)
        while len(self._discrete_order) > self.maximum_discrete_events:
            self._seen_discrete.discard(self._discrete_order.popleft())
        return True

    def reset(self) -> None:
        self.last_imu_sequence.clear()
        self.freeze_state.clear()
        self._seen_discrete.clear()
        self._discrete_order.clear()
