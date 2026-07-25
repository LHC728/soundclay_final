from __future__ import annotations

import base64
import binascii
import io
import json
import shutil
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

import av


MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
MAX_PROCESSED_AUDIO_BYTES = 25 * 1024 * 1024
MAX_PROCESS_VIDEO_BYTES = 60 * 1024 * 1024
MAX_PROCESS_FRAME_BYTES = 700 * 1024


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


def _decode_webm_data_url(data_url: str) -> bytes:
    mime_prefix = "data:video/webm"
    marker = ";base64,"
    marker_index = data_url.find(marker, len(mime_prefix))
    if not data_url.startswith(mime_prefix) or marker_index < len(mime_prefix):
        raise ValueError("process video has an unsupported data URL MIME type")
    # MediaRecorder adds codec parameters such as
    # video/webm;codecs=vp9,opus.  The binary signature below is the actual
    # safety boundary, so normalize those harmless MIME parameters here.
    normalized_data_url = mime_prefix + marker + data_url[marker_index + len(marker) :]
    decoded = _decode_data_url(
        normalized_data_url,
        prefixes=(mime_prefix + marker,),
        max_bytes=MAX_PROCESS_VIDEO_BYTES,
        label="process video",
    )
    if len(decoded) < 4 or decoded[:4] != b"\x1aE\xdf\xa3":
        raise ValueError("process video is not a valid WebM payload")
    return decoded


def _validate_mp4(payload: bytes) -> bytes:
    if not payload or len(payload) > MAX_PROCESS_VIDEO_BYTES:
        raise ValueError(f"process video exceeds the {MAX_PROCESS_VIDEO_BYTES}-byte limit")
    if b"ftyp" not in payload[:32]:
        raise ValueError("process video is not a valid MP4 payload")
    return payload


def _decode_jpeg_data_url(data_url: str) -> bytes:
    decoded = _decode_data_url(
        data_url,
        prefixes=("data:image/jpeg;base64,", "data:image/jpg;base64,"),
        max_bytes=MAX_PROCESS_FRAME_BYTES,
        label="process frame",
    )
    if not decoded.startswith(b"\xff\xd8"):
        raise ValueError("process frame is not a valid JPEG payload")
    return decoded


def _decode_video_frame(payload: bytes) -> av.VideoFrame:
    source = av.open(io.BytesIO(payload))
    try:
        return next(source.decode(video=0))
    finally:
        source.close()


def _encode_process_mp4(target: Path, frames: list[bytes], frame_rate: float) -> None:
    first = _decode_video_frame(frames[0])
    width = max(2, first.width - first.width % 2)
    height = max(2, first.height - first.height % 2)
    temporary = target.with_suffix(".tmp.mp4")
    output = av.open(str(temporary), mode="w")
    try:
        rate = Fraction(str(frame_rate))
        stream = output.add_stream("libx264", rate=rate)
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"
        frame_time_base = Fraction(1, 1) / rate
        for index, payload in enumerate(frames):
            frame = _decode_video_frame(payload)
            rendered = frame.reformat(width=width, height=height, format="yuv420p")
            # JPEG snapshots all decode with a zero timestamp. Assign a
            # monotonic timeline so phones play the complete sculpting film.
            rendered.pts = index
            rendered.time_base = frame_time_base
            for packet in stream.encode(rendered):
                output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)
    finally:
        output.close()
    temporary.replace(target)


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

        saved_at = datetime.now(timezone.utc).isoformat()
        private_metadata = deepcopy(session_data)
        private_metadata["saved_id"] = work_id
        private_metadata["saved_at"] = saved_at
        private_metadata["phase"] = "saved"

        metadata_path = target / "portrait.json"
        metadata_path.write_text(
            json.dumps(private_metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        files["metadata"] = str(metadata_path)

        # This projection is safe to bind to a public Voice Portrait card. The
        # full transcript remains only in the local backward-compatible file.
        public_metadata = {
            "id": work_id,
            "saved_at": saved_at,
            "session_id": session_data.get("session_id"),
            "audio_id": session_data.get("audio_id"),
            "emotion": session_data.get("emotion"),
            "emotion_provider": session_data.get("emotion_provider"),
            "emotion_scores": session_data.get("emotion_scores"),
            "mode": session_data.get("mode"),
            "features": session_data.get("features", {}),
            "recipe": session_data.get("recipe"),
            "motion": session_data.get("finalMotion", session_data.get("motion", {})),
            "privateTranscriptStoredLocally": bool(session_data.get("transcript")),
        }
        public_path = target / "metadata.json"
        public_path.write_text(
            json.dumps(public_metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        files["publicMetadata"] = str(public_path)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise

    return {"id": work_id, "path": str(target), "files": files}


def save_public_work(
    public_works_dir: Path,
    *,
    screenshot_data_url: str,
    processed_audio_data_url: str,
    emotion: str,
    caption: str,
    final_motion: dict[str, Any],
    process_video_data_url: str | None = None,
    process_video_mp4: bytes | None = None,
    process_frames_data_urls: list[str] | None = None,
    process_frame_rate: float = 2.5,
) -> dict[str, Any]:
    """Store only the assets and metadata that a QR visitor may view."""
    screenshot = _decode_png_data_url(screenshot_data_url)
    processed_audio = _decode_wav_data_url(processed_audio_data_url)
    process_video = (
        _decode_webm_data_url(process_video_data_url)
        if process_video_data_url
        else None
    )
    if process_video is not None and process_video_mp4 is not None:
        raise ValueError("provide only one process video")
    process_video_mp4 = _validate_mp4(process_video_mp4) if process_video_mp4 else None
    process_frames = [
        _decode_jpeg_data_url(frame) for frame in (process_frames_data_urls or [])
    ]
    if (process_video is not None or process_video_mp4 is not None) and process_frames:
        raise ValueError("provide either a process video or process frames, not both")
    if process_frames and len(process_frames) < 2:
        raise ValueError("at least two process frames are required")

    public_works_dir.mkdir(parents=True, exist_ok=True)
    work_id, target = _new_work_target(public_works_dir)
    saved_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "id": work_id,
        "saved_at": saved_at,
        "emotion": emotion,
        "caption": caption,
        "motion": final_motion,
        "has_process_video": process_video is not None or process_video_mp4 is not None or bool(process_frames),
        "process_video_has_audio": process_video is not None or process_video_mp4 is not None,
    }

    try:
        (target / "cover.png").write_bytes(screenshot)
        (target / "audio.wav").write_bytes(processed_audio)
        if process_video is not None:
            (target / "process.webm").write_bytes(process_video)
        elif process_video_mp4 is not None:
            (target / "process.mp4").write_bytes(process_video_mp4)
        elif process_frames:
            _encode_process_mp4(target / "process.mp4", process_frames, process_frame_rate)
        (target / "public.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise

    return {
        "id": work_id,
        "saved_at": saved_at,
        "has_process_video": process_video is not None or process_video_mp4 is not None or bool(process_frames),
    }
