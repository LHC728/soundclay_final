from __future__ import annotations

import base64
import binascii
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
MAX_PROCESSED_AUDIO_BYTES = 25 * 1024 * 1024


def _decode_data_url(
    data_url: str,
    *,
    prefixes: tuple[str, ...],
    max_bytes: int,
    label: str,
) -> bytes:
    prefix = next((item for item in prefixes if data_url.startswith(item)), None)
    if prefix is None:
        raise ValueError(f"{label} has an unsupported data URL MIME type")

    encoded = data_url[len(prefix) :]
    if not encoded:
        raise ValueError(f"{label} data URL is empty")
    if len(encoded) > ((max_bytes + 2) // 3) * 4 + 4:
        raise ValueError(f"{label} exceeds the {max_bytes}-byte limit")

    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"{label} contains invalid base64") from exc
    if len(decoded) > max_bytes:
        raise ValueError(f"{label} exceeds the {max_bytes}-byte limit")
    return decoded


def _decode_png_data_url(data_url: str) -> bytes:
    decoded = _decode_data_url(
        data_url,
        prefixes=("data:image/png;base64,",),
        max_bytes=MAX_SCREENSHOT_BYTES,
        label="screenshot",
    )
    if not decoded.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("screenshot is not a valid PNG payload")
    return decoded


def _decode_wav_data_url(data_url: str) -> bytes:
    decoded = _decode_data_url(
        data_url,
        prefixes=("data:audio/wav;base64,", "data:audio/x-wav;base64,"),
        max_bytes=MAX_PROCESSED_AUDIO_BYTES,
        label="processed audio",
    )
    if len(decoded) < 12 or decoded[:4] != b"RIFF" or decoded[8:12] != b"WAVE":
        raise ValueError("processed audio is not a valid WAV payload")
    return decoded


def _new_work_target(works_dir: Path) -> tuple[str, Path]:
    for _ in range(10):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")[:-3]
        work_id = f"VP-{stamp}-{uuid.uuid4().hex[:6]}"
        target = works_dir / work_id
        try:
            target.mkdir()
        except FileExistsError:
            continue
        return work_id, target
    raise OSError("could not allocate a unique work directory")


def save_work(
    works_dir: Path,
    session_data: dict[str, Any],
    original_audio: Path | None,
    output_audio: Path | None,
    screenshot_data_url: str | None,
    processed_audio_data_url: str | None = None,
) -> dict[str, Any]:
    screenshot = (
        _decode_png_data_url(screenshot_data_url) if screenshot_data_url else None
    )
    processed_audio = (
        _decode_wav_data_url(processed_audio_data_url)
        if processed_audio_data_url
        else None
    )

    works_dir.mkdir(parents=True, exist_ok=True)
    work_id, target = _new_work_target(works_dir)
    files: dict[str, str] = {}

    try:
        if original_audio and original_audio.exists():
            destination = target / "original.wav"
            shutil.copy2(original_audio, destination)
            files["originalAudio"] = str(destination)

        if processed_audio is not None:
            destination = target / "output.wav"
            destination.write_bytes(processed_audio)
            files["outputAudio"] = str(destination)
        elif output_audio and output_audio.exists():
            destination = target / "output.wav"
            shutil.copy2(output_audio, destination)
            files["outputAudio"] = str(destination)

        if screenshot is not None:
            destination = target / "sculpture.png"
            destination.write_bytes(screenshot)
            files["image"] = str(destination)

        metadata_path = target / "portrait.json"
        metadata_path.write_text(
            json.dumps(session_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        files["metadata"] = str(metadata_path)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise

    return {"id": work_id, "path": str(target), "files": files}
