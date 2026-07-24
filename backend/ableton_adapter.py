from __future__ import annotations

import math
import os
import socket
import struct
from typing import Any


_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 11_000


def _enabled() -> bool:
    return os.getenv("ABLETON_OSC_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _port() -> int:
    try:
        value = int(os.getenv("ABLETON_OSC_PORT", str(_DEFAULT_PORT)))
    except ValueError:
        return _DEFAULT_PORT
    return value if 1 <= value <= 65_535 else _DEFAULT_PORT


def status() -> dict[str, Any]:
    return {
        "enabled": _enabled(),
        "transport": "osc-udp",
        "host": os.getenv("ABLETON_OSC_HOST", _DEFAULT_HOST).strip() or _DEFAULT_HOST,
        "port": _port(),
        "addresses": {
            "mode": "/soundclay/mode",
            "twist": "/soundclay/twist",
            "filter": "/soundclay/filter",
            "burst": "/soundclay/burst",
            "freeze": "/soundclay/freeze",
            "color": "/soundclay/color",
        },
    }


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
    """Send one optional localhost OSC control without breaking the P0 flow."""
    if not _enabled():
        return False
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
    elif event_type == "burst":
        send_control("burst", float(payload["strength"]))
    elif event_type == "freeze":
        send_control("freeze", int(bool(payload["active"])))
    elif event_type == "color":
        send_control("color", float(payload["hue"]) / 360.0)
