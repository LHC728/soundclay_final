from __future__ import annotations

import math
import os
import socket
import struct
import threading
import time
from typing import Any

import mido


_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 11_000
_DEFAULT_MIDI_PORT = "SoundClay MIDI"
_MIDI_CC_TIMBRE = 20
_MIDI_CC_MAIN_GAIN = 21
_MIDI_NOTE_BURST = 70
_MIDI_BURST_HIT_COUNT = 2
_MIDI_BURST_HIT_INTERVAL_SECONDS = 0.22
_MIDI_SCENE_NOTE_HOLD_SECONDS = 0.3
_MIDI_TIMBRE_VALUES = (16, 64, 112)
_MIDI_TWIST_DEAD_ZONE = 0.25
_MIDI_SCENE_NOTES = {
    ("joy", "express"): 60,
    ("joy", "soothe"): 61,
    ("anger", "express"): 62,
    ("anger", "soothe"): 63,
    ("sadness", "express"): 64,
    ("sadness", "soothe"): 65,
    ("anxiety", "express"): 66,
    ("anxiety", "soothe"): 67,
    ("neutral_mixed", "express"): 68,
    ("neutral_mixed", "soothe"): 69,
}

_midi_lock = threading.RLock()
_midi_output: Any | None = None
_midi_output_name: str | None = None
_midi_last_error: str | None = None
_midi_last_cc: dict[int, tuple[int, float]] = {}
_midi_timbre_index = 1
_midi_twist_zone = 0


def _enabled() -> bool:
    return os.getenv("ABLETON_OSC_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _midi_enabled() -> bool:
    return os.getenv("ABLETON_MIDI_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _midi_channel() -> int:
    try:
        channel = int(os.getenv("ABLETON_MIDI_CHANNEL", "0"))
    except ValueError:
        return 0
    return channel if 0 <= channel <= 15 else 0


def _midi_gain_floor() -> float:
    try:
        value = float(os.getenv("ABLETON_MIDI_GAIN_FLOOR", "0.4"))
    except ValueError:
        return 0.4
    return max(0.0, min(1.0, value)) if math.isfinite(value) else 0.4


def _midi_max_hz() -> float:
    try:
        value = float(os.getenv("ABLETON_MIDI_MAX_HZ", "50"))
    except ValueError:
        return 50.0
    return max(1.0, min(200.0, value)) if math.isfinite(value) else 50.0


def _midi_port_hint() -> str:
    return os.getenv("ABLETON_MIDI_PORT", _DEFAULT_MIDI_PORT).strip() or _DEFAULT_MIDI_PORT


def _find_midi_port(names: list[str], hint: str) -> str | None:
    exact = next((name for name in names if name.casefold() == hint.casefold()), None)
    if exact:
        return exact
    return next((name for name in names if hint.casefold() in name.casefold()), None)


def _midi_port_snapshot() -> tuple[list[str], str | None, str | None]:
    try:
        names = list(mido.get_output_names())
    except Exception as exc:
        return [], None, str(exc)
    return names, _find_midi_port(names, _midi_port_hint()), None


def _port() -> int:
    try:
        value = int(os.getenv("ABLETON_OSC_PORT", str(_DEFAULT_PORT)))
    except ValueError:
        return _DEFAULT_PORT
    return value if 1 <= value <= 65_535 else _DEFAULT_PORT


def status() -> dict[str, Any]:
    midi_names, midi_resolved, discovery_error = _midi_port_snapshot()
    return {
        "enabled": _enabled(),
        "transport": "osc-udp",
        "host": os.getenv("ABLETON_OSC_HOST", _DEFAULT_HOST).strip() or _DEFAULT_HOST,
        "port": _port(),
        "addresses": {
            "mode": "/soundclay/mode",
            "twist": "/soundclay/twist",
            "energy": "/soundclay/energy",
            "filter": "/soundclay/filter",
            "burst": "/soundclay/burst",
            "freeze": "/soundclay/freeze",
            "color": "/soundclay/color",
        },
        "midi": {
            "enabled": _midi_enabled(),
            "transport": "midi",
            "portHint": _midi_port_hint(),
            "resolvedPort": _midi_output_name or midi_resolved,
            "availableOutputs": midi_names,
            "channel": _midi_channel() + 1,
            "connected": bool(_midi_output and not getattr(_midi_output, "closed", False)),
            "lastError": _midi_last_error or discovery_error,
            "controls": {
                "timbreWheel": {
                    "type": "cc",
                    "number": _MIDI_CC_TIMBRE,
                    "mode": "three-state-latched",
                    "values": list(_MIDI_TIMBRE_VALUES),
                },
                "mainGain": {"type": "cc", "number": _MIDI_CC_MAIN_GAIN},
                "burstClip": {
                    "type": "note",
                    "number": _MIDI_NOTE_BURST,
                    "hitsPerGesture": _MIDI_BURST_HIT_COUNT,
                    "intervalMs": round(_MIDI_BURST_HIT_INTERVAL_SECONDS * 1000),
                },
            },
            "scenes": {
                f"{emotion}:{mode}": note
                for (emotion, mode), note in _MIDI_SCENE_NOTES.items()
            },
        },
    }


def close_midi_output() -> None:
    global _midi_output, _midi_output_name, _midi_timbre_index, _midi_twist_zone
    with _midi_lock:
        output = _midi_output
        _midi_output = None
        _midi_output_name = None
        _midi_last_cc.clear()
        _midi_timbre_index = 1
        _midi_twist_zone = 0
        if output is not None:
            try:
                output.close()
            except Exception:
                pass


def _get_midi_output() -> Any:
    global _midi_output, _midi_output_name, _midi_last_error
    if _midi_output is not None and not getattr(_midi_output, "closed", False):
        return _midi_output
    names, resolved, discovery_error = _midi_port_snapshot()
    if discovery_error:
        _midi_last_error = discovery_error
        raise RuntimeError(discovery_error)
    if resolved is None:
        available = ", ".join(names) if names else "none"
        error = f"MIDI output matching '{_midi_port_hint()}' was not found; available: {available}"
        _midi_last_error = error
        raise RuntimeError(error)
    try:
        _midi_output = mido.open_output(resolved)
    except Exception as exc:
        _midi_last_error = str(exc)
        raise
    _midi_output_name = resolved
    _midi_last_error = None
    return _midi_output


def _send_midi(message: Any) -> bool:
    if not _midi_enabled():
        return False
    with _midi_lock:
        try:
            _get_midi_output().send(message)
        except Exception:
            close_midi_output()
            return False
    return True


def send_midi_cc(control: int, normalized_value: float) -> bool:
    if not 0 <= control <= 127:
        raise ValueError("MIDI CC must be between 0 and 127")
    value = float(normalized_value)
    if not math.isfinite(value):
        raise ValueError("MIDI CC value must be finite")
    midi_value = round(max(0.0, min(1.0, value)) * 127)
    now = time.monotonic()
    previous = _midi_last_cc.get(control)
    minimum_interval = 1.0 / _midi_max_hz()
    if previous and previous[0] == midi_value:
        return _midi_enabled()
    if previous and now - previous[1] < minimum_interval:
        return _midi_enabled()
    sent = _send_midi(
        mido.Message(
            "control_change",
            channel=_midi_channel(),
            control=control,
            value=midi_value,
        )
    )
    if sent:
        _midi_last_cc[control] = (midi_value, now)
    return sent


def send_timbre_twist(normalized_value: float) -> bool:
    """Cycle among three timbres and keep the selection after the wrist returns.

    The ring and browser both report a centered value when a twist finishes.
    Center therefore only re-arms the next gesture; it must not write CC20=64.
    """
    global _midi_timbre_index, _midi_twist_zone

    value = float(normalized_value)
    if not math.isfinite(value):
        raise ValueError("twist value must be finite")
    signed = max(-1.0, min(1.0, value * 2.0 - 1.0))

    with _midi_lock:
        if abs(signed) <= _MIDI_TWIST_DEAD_ZONE:
            _midi_twist_zone = 0
            return _midi_enabled()

        direction = -1 if signed < 0 else 1
        if _midi_twist_zone == direction:
            return _midi_enabled()

        _midi_twist_zone = direction
        _midi_timbre_index = (_midi_timbre_index + direction) % len(_MIDI_TIMBRE_VALUES)
        midi_value = _MIDI_TIMBRE_VALUES[_midi_timbre_index]
        return send_midi_cc(_MIDI_CC_TIMBRE, midi_value / 127.0)


def send_midi_note(note: int, velocity: int = 127, *, hold_seconds: float = 0.0) -> bool:
    if not 0 <= note <= 127 or not 0 <= velocity <= 127:
        raise ValueError("MIDI note and velocity must be between 0 and 127")
    if not math.isfinite(hold_seconds) or hold_seconds < 0:
        raise ValueError("MIDI note hold duration must be finite and non-negative")
    note_on = mido.Message(
        "note_on", channel=_midi_channel(), note=note, velocity=velocity
    )
    note_off = mido.Message(
        "note_off", channel=_midi_channel(), note=note, velocity=0
    )
    sent = _send_midi(note_on)
    if sent:
        if hold_seconds:
            time.sleep(hold_seconds)
        _send_midi(note_off)
    return sent


def send_burst_hits(velocity: int) -> bool:
    """Trigger the mapped Drum Layer twice for one physical wave gesture."""
    sent = False
    for index in range(_MIDI_BURST_HIT_COUNT):
        sent = send_midi_note(_MIDI_NOTE_BURST, velocity) or sent
        if index + 1 < _MIDI_BURST_HIT_COUNT:
            time.sleep(_MIDI_BURST_HIT_INTERVAL_SECONDS)
    return sent


def send_scene(emotion: str, mode: str) -> bool:
    canonical_emotion = emotion.replace("-", "_").strip().lower()
    key = (canonical_emotion, mode.strip().lower())
    note = _MIDI_SCENE_NOTES.get(key)
    if note is None:
        raise ValueError(f"unsupported Ableton scene mapping: {emotion}/{mode}")
    # Live's scene-launch mapping can miss a note whose on/off messages arrive
    # in the same scheduler tick. Match the proven manual test by holding the
    # scene note briefly; burst keeps its immediate one-shot behavior.
    return send_midi_note(note, hold_seconds=_MIDI_SCENE_NOTE_HOLD_SECONDS)


def send_stop() -> bool:
    """Stop Live through MIDI Clock and preserve the existing OSC freeze signal."""
    midi_sent = _send_midi(mido.Message("stop"))
    osc_sent = send_control("freeze", 1)
    return midi_sent or osc_sent


def _osc_string(value: str) -> bytes:
    raw = value.encode("utf-8") + b"\0"
    return raw + b"\0" * ((4 - len(raw) % 4) % 4)


def _message(address: str, *arguments: str | int | float) -> bytes:
    tags = [","]
    encoded: list[bytes] = []
    for value in arguments:
        if isinstance(value, bool) or isinstance(value, int):
            tags.append("i")
            encoded.append(struct.pack(">i", int(value)))
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("OSC float must be finite")
            tags.append("f")
            encoded.append(struct.pack(">f", value))
        else:
            tags.append("s")
            encoded.append(_osc_string(str(value)))
    return _osc_string(address) + _osc_string("".join(tags)) + b"".join(encoded)


def send_control(control: str, value: str | int | float) -> bool:
    """Send one optional MIDI/OSC control without breaking the P0 flow."""
    midi_sent = False
    if control == "twist":
        midi_sent = send_timbre_twist(float(value))
    elif control == "energy":
        energy = max(0.0, min(1.0, float(value)))
        floor = _midi_gain_floor()
        midi_sent = send_midi_cc(_MIDI_CC_MAIN_GAIN, floor + energy * (1.0 - floor))
    elif control == "burst":
        strength = max(0.0, min(1.0, float(value)))
        midi_sent = send_burst_hits(max(1, round(strength * 127)))
    if not _enabled():
        return midi_sent
    config = status()
    address = config["addresses"].get(control)
    if not address:
        raise ValueError(f"unsupported Ableton control: {control}")
    packet = _message(address, value)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(0.05)
            client.sendto(packet, (config["host"], config["port"]))
    except OSError:
        return False
    return True


def send_motion(event_type: str, payload: dict[str, Any]) -> None:
    if event_type == "twist":
        twist = float(payload["value"])
        send_control("twist", twist)
        send_control("filter", 700.0 + twist**1.7 * 15_300.0)
    elif event_type == "finger":
        finger = max(-1.0, min(1.0, float(payload["value"])))
        send_control("energy", (finger + 1.0) / 2.0)
    elif event_type == "burst":
        send_control("burst", float(payload["strength"]))
    elif event_type == "freeze":
        send_control("freeze", int(bool(payload["active"])))
    elif event_type == "color":
        send_control("color", float(payload["hue"]) / 360.0)
