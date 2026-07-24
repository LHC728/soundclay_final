from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _load_events(path: Path, wav_override: Path | None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(event, dict):
            raise ValueError(f"{path}:{line_number}: each line must be a JSON object")
        if event.get("type") == "audio_ready" and wav_override is not None:
            payload = event.setdefault("payload", {})
            payload["wavPath"] = str(wav_override.resolve())
        events.append(event)
    if not events:
        raise ValueError(f"{path} does not contain any events")
    return events


def _post_event(url: str, event: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(event, ensure_ascii=False).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"backend rejected {event.get('type')}: HTTP {exc.code} {detail}") from exc


def replay(events: list[dict[str, Any]], url: str, speed: float) -> None:
    previous_timestamp: int | None = None
    for event in events:
        timestamp = int(event.get("timestamp", 0))
        if previous_timestamp is not None and timestamp >= previous_timestamp:
            delay = min(5.0, (timestamp - previous_timestamp) / 1000 / speed)
            if delay > 0:
                time.sleep(delay)
        result = _post_event(url, event)
        print(
            json.dumps(
                {
                    "type": event.get("type"),
                    "accepted": result.get("accepted"),
                    "reason": result.get("reason"),
                },
                ensure_ascii=False,
            )
        )
        previous_timestamp = timestamp


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay RingRuntime NDJSON into SoundClay")
    parser.add_argument("path", type=Path, help="NDJSON file using the AB event contract")
    parser.add_argument("--speed", type=float, default=1.0, help="Timing multiplier")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000/api/mock/ring-event",
        help="SoundClay mock ingestion endpoint",
    )
    parser.add_argument(
        "--wav",
        type=Path,
        help="Replace every audio_ready.wavPath placeholder with this local WAV",
    )
    args = parser.parse_args()
    if not 0.1 <= args.speed <= 100:
        parser.error("--speed must be between 0.1 and 100")
    if not args.path.is_file():
        parser.error(f"event file not found: {args.path}")
    if args.wav is not None and not args.wav.is_file():
        parser.error(f"WAV override not found: {args.wav}")
    replay(_load_events(args.path, args.wav), args.url, args.speed)


if __name__ == "__main__":
    main()
