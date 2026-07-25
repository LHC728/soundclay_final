from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import time
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import soundfile as sf
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from audio_pipeline import analyze_audio
from ableton_adapter import close_midi_output as close_ableton_midi
from ableton_adapter import send_control as send_ableton_control
from ableton_adapter import send_motion as send_ableton_motion
from ableton_adapter import send_scene as send_ableton_scene
from ableton_adapter import send_stop as stop_ableton_playback
from ableton_adapter import status as ableton_status
from emotion_adapter import analyze_emotion
from event_bus import EventBus
from obs_adapter import OBSControlError, start_recording as start_obs_recording
from obs_adapter import stop_recording as stop_obs_recording
from recipe_engine import build_recipe
from ring_integration import RingRuntimeManager
from ring_protocol import RingEventGuard, RingProtocolError, normalize_ring_event
from save_service import MAX_PROCESS_VIDEO_BYTES, save_public_work, save_work
from schemas import (
    AudioFeatures,
    Emotion,
    EmotionConfirmRequest,
    EventMessage,
    ModeSelectRequest,
    Phase,
    PublicWorkRequest,
    SaveRequest,
    SessionState,
    TranscriptRequest,
)
from stt_adapter import STTError, get_stt_provider, transcribe_audio
from chinese_text import normalize_transcript

BASE_DIR = Path(__file__).resolve().parent
AUDIO_DIR = BASE_DIR / "audio"
WORKS_DIR = BASE_DIR.parent / "works"
PUBLIC_WORKS_DIR = BASE_DIR.parent / "public_works"
AUDIO_DIR.mkdir(exist_ok=True)
WORKS_DIR.mkdir(exist_ok=True)
PUBLIC_WORKS_DIR.mkdir(exist_ok=True)

ORIGINAL_AUDIO = AUDIO_DIR / "original.wav"
OUTPUT_AUDIO = AUDIO_DIR / "output.wav"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


ring_manager: RingRuntimeManager | None = None
ring_audio_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(_: FastAPI):
    global ring_manager
    manager = RingRuntimeManager(_handle_ring_runtime_event)
    ring_manager = manager
    await manager.start()
    try:
        yield
    finally:
        for task in list(ring_audio_tasks):
            task.cancel()
        for task in list(ring_audio_tasks):
            with suppress(asyncio.CancelledError):
                await task
        await manager.close()
        close_ableton_midi()
        ring_manager = None


app = FastAPI(title="SoundClay Emotion Backend", version="0.4.0", lifespan=lifespan)
configured_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(
        dict.fromkeys(
            [configured_origin, "http://localhost:5173", "http://127.0.0.1:5173"]
        )
    ),
    allow_origin_regex=r"^https?://(?:localhost|127\.0\.0\.1)(?::\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/audio", StaticFiles(directory=AUDIO_DIR), name="audio")
app.mount("/works", StaticFiles(directory=WORKS_DIR), name="works")

bus = EventBus()
session = SessionState(session_id=str(uuid.uuid4()))
audio_lock = asyncio.Lock()
obs_recording_lock = asyncio.Lock()
obs_recording_path: Path | None = None
ring_event_guard = RingEventGuard()
active_ring_session_id: str | None = None
ring_status: dict = {
    "enabled": False,
    "connected": False,
    "phase": "disabled",
    "modeHint": "mock-controls-available",
    "lastError": None,
}

_PUBLIC_WORK_ID = re.compile(r"VP-\d{8}-\d{6}-\d{3}-[a-f0-9]{6}")


def _public_work_directory(work_id: str) -> Path:
    if not _PUBLIC_WORK_ID.fullmatch(work_id):
        raise HTTPException(status_code=404, detail="shared work not found")
    target = PUBLIC_WORKS_DIR / work_id
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="shared work not found")
    return target


def _read_public_work(work_id: str) -> dict:
    target = _public_work_directory(work_id)
    metadata_path = target / "public.json"
    try:
        value = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail="shared work is unavailable") from exc
    if not isinstance(value, dict) or value.get("id") != work_id:
        raise HTTPException(status_code=404, detail="shared work is unavailable")
    return value


def event(event_type: str, payload: dict, *, timestamp: int | None = None) -> dict:
    owned_payload = {
        "session_id": session.session_id,
        "audio_id": session.audio_id,
        "revision": session.revision,
        **payload,
    }
    return {
        "type": event_type,
        "timestamp": timestamp if timestamp is not None else int(time.time() * 1000),
        "payload": owned_payload,
    }


async def publish(event_type: str, payload: dict) -> None:
    await bus.broadcast(event(event_type, payload))


def _touch_session() -> None:
    session.revision += 1
    session.updated_at = datetime.now(timezone.utc).isoformat()


def _clamped_number(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise HTTPException(status_code=422, detail=f"{name} must be finite")
    return float(max(0.0, min(1.0, value)))


def _safe_upload_filename(value: str | None) -> str:
    if not value:
        return "original.wav"
    decoded = unquote(value).replace("\\", "/")
    filename = Path(decoded).name.strip()
    if not filename or len(filename) > 255:
        return "original.wav"
    return filename


def _store_wav(payload: bytes, filename: str) -> dict:
    if not payload:
        raise ValueError("WAV upload is empty")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ValueError(f"WAV upload exceeds the {MAX_UPLOAD_BYTES}-byte limit")
    if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        raise ValueError("upload is not a RIFF/WAVE file")

    temporary = AUDIO_DIR / f"upload-{uuid.uuid4().hex}.wav"
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        info = sf.info(str(temporary))
        if info.frames <= 0 or info.samplerate <= 0:
            raise ValueError("WAV upload has no audio frames")
        os.replace(temporary, ORIGINAL_AUDIO)
    finally:
        temporary.unlink(missing_ok=True)

    return {
        "audio_id": hashlib.sha256(payload).hexdigest(),
        "filename": filename,
        "audioUrl": "/audio/original.wav",
        "bytes": len(payload),
        "sampleRate": info.samplerate,
        "channels": info.channels,
        "frames": info.frames,
        "format": info.format,
        "subtype": info.subtype,
        "expectedFormat": (
            info.samplerate == 16_000
            and info.channels == 1
            and info.subtype == "PCM_16"
        ),
    }


def _describe_existing_audio(path: Path) -> dict:
    payload = path.read_bytes()
    return {
        "audio_id": hashlib.sha256(payload).hexdigest(),
        "filename": path.name,
        "bytes": len(payload),
    }


def _reset_session_for_audio(metadata: dict) -> None:
    session.phase = Phase.AUDIO_READY
    session.audio_id = metadata["audio_id"]
    session.audio_filename = metadata["filename"]
    session.audio_bytes = metadata["bytes"]
    session.transcript = None
    session.emotion = None
    session.confidence = None
    session.reason = None
    session.emotion_provider = None
    session.emotion_warning = None
    session.emotion_scores = None
    session.emotion_weights = None
    session.emotion_cache_hit = False
    session.mode = None
    session.recipe = None
    session.features = AudioFeatures()
    session.features_audio_id = None
    session.original_audio_url = metadata["audioUrl"]
    session.output_audio_url = None
    session.motion = {}
    session.saved_id = None
    session.last_error = None
    _touch_session()


async def _analyze_current_audio(*, emit: bool = True) -> AudioFeatures:
    if not ORIGINAL_AUDIO.exists():
        raise HTTPException(status_code=404, detail="backend/audio/original.wav not found")
    try:
        features = await asyncio.to_thread(analyze_audio, ORIGINAL_AUDIO)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"audio analysis failed: {exc}") from exc
    session.features = features
    session.features_audio_id = session.audio_id
    session.original_audio_url = "/audio/original.wav"
    _touch_session()
    if emit:
        await publish(
            "audio_features_ready",
            {
                **features.model_dump(),
                "audio_id": session.audio_id,
                "phase": session.phase,
            },
        )
    return features


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/api/status")
async def get_status() -> dict:
    manager_status = ring_manager.status() if ring_manager else {
        "enabled": False,
        "connected": False,
        "sessionRunning": False,
        "lastError": None,
        "runtimePath": None,
        "ffmpegPath": None,
    }
    return {
        "ringConnected": manager_status["connected"],
        "ring": {**ring_status, **manager_status},
        "phase": session.phase,
        "modeHint": ring_status.get("modeHint", "mock-controls-available"),
        "lastError": session.last_error,
        "audioId": session.audio_id,
        "sessionId": session.session_id,
        "revision": session.revision,
        "ableton": ableton_status(),
    }


@app.get("/api/ableton/status")
async def get_ableton_status() -> dict:
    return ableton_status()


@app.post("/api/ableton/stop")
async def stop_ableton() -> dict:
    sent = stop_ableton_playback()
    return {"ok": sent, "midiPort": ableton_status()["midi"]["resolvedPort"]}


@app.get("/api/session/current")
async def get_current_session() -> SessionState:
    return session


@app.post("/api/audio/upload")
async def upload_audio(request: Request) -> dict:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type and content_type not in {
        "audio/wav",
        "audio/x-wav",
        "application/octet-stream",
    }:
        raise HTTPException(status_code=415, detail="upload must use a WAV content type")
    declared_length = request.headers.get("content-length")
    if declared_length:
        try:
            if int(declared_length) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="WAV upload is too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid Content-Length") from exc

    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="WAV upload is too large")
        chunks.append(chunk)
    payload = b"".join(chunks)
    filename = _safe_upload_filename(request.headers.get("x-soundclay-filename"))

    async with audio_lock:
        try:
            result = await asyncio.to_thread(_store_wav, payload, filename)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        _reset_session_for_audio(result)
        await publish(
            "status",
            {
                "phase": session.phase,
                "message": "New audio is ready",
                "audio_id": session.audio_id,
            },
        )
        await publish(
            "audio_ready",
            {
                "phase": session.phase,
                "filename": session.audio_filename,
                "bytes": session.audio_bytes,
                "sampleRate": result["sampleRate"],
                "channels": result["channels"],
                "subtype": result["subtype"],
            },
        )

        feature_error: str | None = None
        try:
            features = await _analyze_current_audio()
        except HTTPException as exc:
            features = session.features
            feature_error = str(exc.detail)
            session.last_error = feature_error
            _touch_session()
            await publish(
                "error",
                {
                    "code": "AUDIO_FEATURES_FAILED",
                    "message": feature_error,
                    "audio_id": session.audio_id,
                },
            )

        return {
            **result,
            "phase": session.phase,
            "session_id": session.session_id,
            "revision": session.revision,
            "features": features.model_dump(),
            "featureError": feature_error,
        }


@app.post("/api/audio/analyze")
async def analyze_current_audio() -> dict:
    async with audio_lock:
        features = await _analyze_current_audio()
        return {
            **features.model_dump(),
            "audio_id": session.audio_id,
            "session_id": session.session_id,
            "revision": session.revision,
        }


@app.post("/api/stt/transcribe")
async def transcribe_original_audio(
    request: Request,
    auto_confirm: bool = Query(default=False),
) -> dict:
    async with audio_lock:
        if not ORIGINAL_AUDIO.exists():
            raise HTTPException(status_code=404, detail="backend/audio/original.wav not found")
        if session.audio_id is None:
            metadata = await asyncio.to_thread(_describe_existing_audio, ORIGINAL_AUDIO)
            session.audio_id = metadata["audio_id"]
            session.audio_filename = metadata["filename"]
            session.audio_bytes = metadata["bytes"]
            session.original_audio_url = "/audio/original.wav"
            _touch_session()

        expected_audio_id = request.headers.get("x-soundclay-audio-id")
        if expected_audio_id and expected_audio_id != session.audio_id:
            raise HTTPException(
                status_code=409,
                detail="The selected audio is no longer current. Refresh the session and retry.",
            )

        audio_id = session.audio_id
        provider = get_stt_provider()
        started = time.perf_counter()
        session.phase = Phase.UNDERSTANDING
        session.last_error = None
        _touch_session()
        await publish(
            "status",
            {
                "phase": session.phase,
                "message": "Understanding your voice",
                "audio_id": audio_id,
            },
        )

        transcription_started = time.perf_counter()
        try:
            recognized = await transcribe_audio(ORIGINAL_AUDIO)
            transcript = normalize_transcript(str(recognized))
        except STTError as exc:
            session.phase = Phase.AUDIO_READY
            session.last_error = str(exc)
            _touch_session()
            await publish(
                "error",
                {"code": "STT_FAILED", "message": str(exc), "audio_id": audio_id},
            )
            await publish(
                "status",
                {
                    "phase": session.phase,
                    "message": "Transcription failed; audio remains ready",
                    "audio_id": audio_id,
                },
            )
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        transcription_ms = round((time.perf_counter() - transcription_started) * 1000, 2)

        session.transcript = transcript
        await publish(
            "transcript_ready", {"transcript": transcript, "audio_id": audio_id}
        )

        feature_error: str | None = None
        if session.features_audio_id != audio_id:
            try:
                await _analyze_current_audio()
            except HTTPException as exc:
                feature_error = str(exc.detail)
                session.last_error = feature_error
                await publish(
                    "error",
                    {
                        "code": "AUDIO_FEATURES_FAILED",
                        "message": feature_error,
                        "audio_id": audio_id,
                    },
                )

        emotion_started = time.perf_counter()
        decision = await analyze_emotion(
            transcript,
            session.features,
            speech_emotion=getattr(recognized, "speech_emotion", None),
            speech_emotion_tag=getattr(recognized, "raw_emotion", None),
        )
        result = decision.result
        session.emotion = result.emotion
        session.confidence = result.confidence
        session.reason = result.reason
        session.emotion_provider = decision.provider
        session.emotion_warning = decision.warning
        session.emotion_scores = decision.scores
        session.emotion_weights = decision.weights
        session.emotion_cache_hit = decision.cache_hit
        session.phase = Phase.MODE_CHOICE if auto_confirm else Phase.EMOTION_REVIEW
        _touch_session()
        response = {
            "transcript": transcript,
            **result.model_dump(mode="json"),
            "features": session.features.model_dump(),
            "emotionProvider": decision.provider,
            "emotionWarning": decision.warning,
            "emotionScores": decision.scores,
            "emotionWeights": decision.weights,
            "emotionCacheHit": decision.cache_hit,
            "featureError": feature_error,
            "phase": session.phase,
            "audio_id": audio_id,
            "session_id": session.session_id,
            "revision": session.revision,
            "filename": session.audio_filename,
            "bytes": session.audio_bytes,
            "provider": provider,
            "timing": {
                "transcription_ms": transcription_ms,
                "emotion_ms": round((time.perf_counter() - emotion_started) * 1000, 2),
                "total_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        }
        await publish("emotion_ready", response)
        await publish(
            "status",
            {
                "phase": session.phase,
                "message": "Choose Express or Soothe" if auto_confirm else "Emotion ready for review",
                "audio_id": audio_id,
            },
        )
        return response


async def _mock_recording_impl() -> dict:
    await asyncio.to_thread(ORIGINAL_AUDIO.unlink, missing_ok=True)
    await asyncio.to_thread(OUTPUT_AUDIO.unlink, missing_ok=True)
    session.phase = Phase.RECORDING
    session.audio_id = None
    session.audio_filename = None
    session.audio_bytes = None
    session.transcript = None
    session.emotion = None
    session.confidence = None
    session.reason = None
    session.emotion_provider = None
    session.emotion_warning = None
    session.emotion_scores = None
    session.emotion_weights = None
    session.emotion_cache_hit = False
    session.mode = None
    session.recipe = None
    session.features = AudioFeatures()
    session.features_audio_id = None
    session.original_audio_url = None
    session.output_audio_url = None
    session.motion = {}
    session.saved_id = None
    session.last_error = None
    _touch_session()
    message = event("recording", {"phase": session.phase, "mock": True})
    await bus.broadcast(message)
    await publish("status", {"phase": session.phase, "message": "Mock recording"})
    return message


@app.post("/api/mock/recording")
async def mock_recording() -> dict:
    async with audio_lock:
        return await _mock_recording_impl()


async def _mock_transcript_impl(body: TranscriptRequest, *, auto_confirm: bool = False) -> dict:
    transcript = normalize_transcript(body.transcript)
    session.phase = Phase.UNDERSTANDING
    session.last_error = None
    session.transcript = transcript
    session.emotion = None
    session.confidence = None
    session.reason = None
    session.emotion_provider = None
    session.emotion_warning = None
    session.emotion_scores = None
    session.emotion_weights = None
    session.emotion_cache_hit = False
    session.mode = None
    session.recipe = None
    session.output_audio_url = None
    session.motion = {}
    session.saved_id = None
    _touch_session()
    await publish(
        "transcript_ready",
        {"transcript": transcript, "audio_id": session.audio_id},
    )

    decision = await analyze_emotion(transcript, session.features)
    result = decision.result
    session.emotion = result.emotion
    session.confidence = result.confidence
    session.reason = result.reason
    session.emotion_provider = decision.provider
    session.emotion_warning = decision.warning
    session.emotion_scores = decision.scores
    session.emotion_weights = decision.weights
    session.emotion_cache_hit = decision.cache_hit
    session.phase = Phase.MODE_CHOICE if auto_confirm else Phase.EMOTION_REVIEW
    _touch_session()
    payload = result.model_dump(mode="json")
    await publish(
        "emotion_ready",
        {
            "transcript": transcript,
            **payload,
            "phase": session.phase,
            "audio_id": session.audio_id,
            "emotionProvider": decision.provider,
            "emotionWarning": decision.warning,
            "emotionScores": decision.scores,
            "emotionWeights": decision.weights,
            "emotionCacheHit": decision.cache_hit,
        },
    )
    return {
        "transcript": transcript,
        **payload,
        "features": session.features.model_dump(),
        "emotionProvider": decision.provider,
        "emotionWarning": decision.warning,
        "emotionScores": decision.scores,
        "emotionWeights": decision.weights,
        "emotionCacheHit": decision.cache_hit,
        "phase": session.phase,
        "audio_id": session.audio_id,
        "session_id": session.session_id,
        "revision": session.revision,
    }


@app.post("/api/mock/transcript")
async def mock_transcript(
    body: TranscriptRequest,
    auto_confirm: bool = Query(default=False),
) -> dict:
    async with audio_lock:
        return await _mock_transcript_impl(body, auto_confirm=auto_confirm)


@app.post("/api/emotion/confirm")
async def confirm_emotion(body: EmotionConfirmRequest) -> SessionState:
    if not session.transcript:
        raise HTTPException(status_code=409, detail="no transcript is available")
    session.emotion = body.emotion
    session.confidence = 1.0
    session.reason = "Confirmed or corrected by the user."
    session.emotion_provider = "user"
    session.emotion_warning = None
    session.emotion_scores = {
        emotion.value: 1.0 if emotion == body.emotion else 0.0
        for emotion in Emotion
    }
    session.emotion_weights = {"text": 0.0, "acoustic": 0.0, "glm": 0.0, "user": 1.0}
    session.emotion_cache_hit = False
    session.phase = Phase.MODE_CHOICE
    session.mode = None
    session.recipe = None
    session.saved_id = None
    _touch_session()
    await publish(
        "status",
        {
            "phase": session.phase,
            "message": "Choose Express or Soothe",
            "audio_id": session.audio_id,
        },
    )
    return session


@app.post("/api/mode/select")
async def select_mode(body: ModeSelectRequest) -> dict:
    # The default Member D experience now starts with direction selection and
    # deliberately performs no emotion inference.  Keep a neutral material
    # base internally so the existing recipe/save contracts remain compatible.
    if session.emotion is None:
        session.emotion = Emotion.NEUTRAL_MIXED
        session.confidence = None
        session.reason = "Direct mode selection; no emotion classification was performed."
        session.emotion_provider = "direct_mode"
        session.emotion_warning = None
        session.emotion_scores = None
        session.emotion_weights = None
        session.emotion_cache_hit = False
    session.mode = body.mode
    session.phase = Phase.MATERIALIZING
    session.saved_id = None
    session.last_error = None
    _touch_session()
    await publish(
        "status",
        {"phase": session.phase, "message": "Generating local material recipe"},
    )
    session.recipe = build_recipe(session.emotion, body.mode)
    send_ableton_control("mode", body.mode.value)
    send_ableton_scene(session.emotion.value, body.mode.value)
    if ORIGINAL_AUDIO.exists():
        session.original_audio_url = "/audio/original.wav"
        session.output_audio_url = "/audio/original.wav"

    session.phase = Phase.SCULPTING
    _touch_session()
    payload = {
        "mode": body.mode,
        "audio_id": session.audio_id,
        "audioUrl": session.output_audio_url,
        "recipe": session.recipe,
        "features": session.features.model_dump(),
        "seed": abs(hash(session.session_id)) % 10000,
        "phase": session.phase,
        "session_id": session.session_id,
        "revision": session.revision,
    }
    await publish("material_ready", payload)
    await publish("status", {"phase": session.phase, "message": "Sculpting"})
    return payload


@app.post("/api/recipe/preview")
async def preview_recipe(body: ModeSelectRequest) -> dict:
    """Build a direction preview without advancing or mutating the session."""
    material_base = session.emotion or Emotion.NEUTRAL_MIXED
    return {
        "mode": body.mode,
        "audio_id": session.audio_id,
        "recipe": build_recipe(material_base, body.mode),
        "features": session.features.model_dump(),
        "phase": session.phase,
        "session_id": session.session_id,
        "revision": session.revision,
    }


def _motion_event(event_type: str, payload: dict, timestamp: int | None = None) -> dict:
    emitted_at = timestamp if timestamp is not None else int(time.time() * 1000)
    clean_payload: dict = {}
    ableton_event_type = event_type
    if event_type == "twist":
        value = _clamped_number(float(payload.get("value", 0.0)), "value")
        session.motion["twist"] = value
        clean_payload["value"] = value
    elif event_type in {"tiltX", "finger"}:
        raw_value = float(payload.get("value", payload.get("x", 0.0)))
        if not math.isfinite(raw_value):
            raise HTTPException(status_code=422, detail="value must be finite")
        value = max(-1.0, min(1.0, raw_value))
        gain = (value + 1.0) / 2.0
        session.motion["finger"] = value
        session.motion["tiltX"] = value
        session.motion["size"] = value
        session.motion["gain"] = gain
        clean_payload.update({"value": value, "gain": gain})
        ableton_event_type = "finger"
    elif event_type == "burst":
        strength = _clamped_number(
            float(payload.get("strength", 0.0)), "strength"
        )
        session.motion["burstStrength"] = strength
        session.motion["burstCount"] = int(session.motion.get("burstCount", 0)) + 1
        clean_payload["strength"] = strength
    elif event_type == "freeze":
        active = bool(payload.get("active", True))
        session.motion["frozen"] = active
        clean_payload["active"] = active
        if active:
            session.motion["frozenAt"] = emitted_at
        else:
            session.motion["unfrozenAt"] = emitted_at
    elif event_type == "color":
        hue = float(payload.get("hue", 0.0))
        if not math.isfinite(hue):
            raise HTTPException(status_code=422, detail="hue must be finite")
        hue = hue % 360.0
        session.motion["colorHue"] = hue
        session.motion["colorChanges"] = int(session.motion.get("colorChanges", 0)) + 1
        clean_payload["hue"] = hue
    else:
        raise HTTPException(status_code=422, detail=f"unsupported motion event: {event_type}")

    trace = session.motion.setdefault("trace", [])
    trace.append({"type": event_type, "timestamp": emitted_at, **clean_payload})
    if len(trace) > 500:
        del trace[:-500]
    _touch_session()
    send_ableton_motion(ableton_event_type, clean_payload)
    return event(event_type, clean_payload, timestamp=emitted_at)


def _track_ring_audio_task(task: asyncio.Task) -> None:
    ring_audio_tasks.add(task)
    task.add_done_callback(ring_audio_tasks.discard)


def _accept_ring_session(event_type: str, payload: dict) -> None:
    global active_ring_session_id
    incoming = payload.get("sessionId")
    if not incoming:
        return
    if active_ring_session_id is None or incoming == active_ring_session_id:
        active_ring_session_id = incoming
        return

    phase = str(payload.get("phase", "")).lower()
    begins_new_session = event_type == "audio_ready" or (
        event_type == "status" and phase in {"connected", "ready", "recording"}
    )
    if not begins_new_session:
        raise RingProtocolError("ring event belongs to a different active session")

    active_ring_session_id = incoming
    ring_event_guard.reset()
    session.motion = {"ringSessionId": incoming}
    _touch_session()


async def _run_ring_audio_pipeline(expected_audio_id: str) -> None:
    class InternalRequest:
        headers = {"x-soundclay-audio-id": expected_audio_id}

    try:
        await transcribe_original_audio(InternalRequest(), auto_confirm=False)  # type: ignore[arg-type]
    except HTTPException:
        # The transcription route already publishes a readable error and restores
        # the recoverable audio_ready phase.
        return
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        session.last_error = str(exc)
        _touch_session()
        await publish(
            "error",
            {
                "code": "RING_AUDIO_PIPELINE_FAILED",
                "message": str(exc),
                "recoverable": True,
            },
        )


async def _ingest_ring_event(raw: dict, *, source: str) -> dict:
    normalized = normalize_ring_event(raw)
    event_type = normalized["type"]
    timestamp = normalized["timestamp"]
    payload = normalized["payload"]
    _accept_ring_session(event_type, payload)

    if not ring_event_guard.accept(normalized):
        return {"accepted": False, "reason": "duplicate_or_out_of_order", "event": normalized}

    if event_type == "status":
        ring_status.update(payload)
        ring_status["enabled"] = bool(ring_manager and ring_manager.enabled)
        if source == "ring_runtime" and ring_manager and "connected" in payload:
            ring_manager.connected = payload["connected"]
        if "connected" not in payload and payload.get("phase") == "connected":
            ring_status["connected"] = True
        message = event("status", {**payload, "source": source}, timestamp=timestamp)
        await bus.broadcast(message)
        return {"accepted": True, "event": message}

    if event_type == "error":
        ring_status["lastError"] = payload["message"]
        if source == "ring_runtime" and payload.get("code") == "BLE_DISCONNECTED":
            ring_status["connected"] = False
            ring_status["ringConnected"] = False
            if ring_manager:
                ring_manager.connected = False
        session.last_error = payload["message"]
        _touch_session()
        message = event("error", {**payload, "source": source}, timestamp=timestamp)
        await bus.broadcast(message)
        return {"accepted": True, "event": message}

    if event_type == "audio_ready":
        audio_path = Path(payload["wavPath"]).expanduser()
        if not audio_path.is_absolute():
            raise RingProtocolError("audio_ready.wavPath must be an absolute local path")
        try:
            audio_path = audio_path.resolve(strict=True)
        except OSError as exc:
            raise RingProtocolError(f"audio_ready.wavPath is unavailable: {exc}") from exc
        if not audio_path.is_file() or audio_path.suffix.lower() != ".wav":
            raise RingProtocolError("audio_ready.wavPath must point to a WAV file")
        if audio_path.stat().st_size > MAX_UPLOAD_BYTES:
            raise RingProtocolError("ring WAV exceeds the upload size limit")

        async with audio_lock:
            try:
                wav_bytes = await asyncio.to_thread(audio_path.read_bytes)
                metadata = await asyncio.to_thread(_store_wav, wav_bytes, audio_path.name)
            except (OSError, RuntimeError, ValueError) as exc:
                raise RingProtocolError(f"ring WAV validation failed: {exc}") from exc
            _reset_session_for_audio(metadata)
            session.motion["ringSessionId"] = payload.get("sessionId")
            _touch_session()
            await publish(
                "status",
                {
                    "phase": session.phase,
                    "message": "Ring audio is ready",
                    "ringSessionId": payload.get("sessionId"),
                },
            )
            message = event(
                "audio_ready",
                {
                    "sessionId": payload.get("sessionId"),
                    **{
                        key: payload[key]
                        for key in (
                            "fileIndex",
                            "durationMs",
                            "recordTime",
                            "recovered",
                            "rmsDbfs",
                            "speechActivityRatio",
                            "warnings",
                        )
                        if key in payload
                    },
                    "filename": metadata["filename"],
                    "bytes": metadata["bytes"],
                    "sampleRate": metadata["sampleRate"],
                    "channels": metadata["channels"],
                    "subtype": metadata["subtype"],
                    "audioUrl": "/audio/original.wav",
                    "phase": session.phase,
                    "source": source,
                },
                timestamp=timestamp,
            )
            await bus.broadcast(message)
            try:
                await _analyze_current_audio()
            except HTTPException as exc:
                await publish(
                    "error",
                    {
                        "code": "AUDIO_FEATURES_FAILED",
                        "message": str(exc.detail),
                        "recoverable": True,
                    },
                )

        task = asyncio.create_task(
            _run_ring_audio_pipeline(metadata["audio_id"]),
            name=f"ring-stt-{metadata['audio_id'][:12]}",
        )
        _track_ring_audio_task(task)
        return {"accepted": True, "event": message}

    ring_session_id = payload["sessionId"]
    if active_ring_session_id and ring_session_id != active_ring_session_id:
        raise RingProtocolError("motion event belongs to a different active session")

    if event_type == "imu":
        twist = payload["twist"]
        tilt_x = payload.get("tiltX", 0.0)
        session.motion["ringSessionId"] = ring_session_id
        session.motion["twist"] = twist
        session.motion["tiltX"] = tilt_x
        session.motion["finger"] = tilt_x
        session.motion["size"] = tilt_x
        session.motion["gain"] = (tilt_x + 1.0) / 2.0
        session.motion["accelMag"] = payload["accelMag"]
        session.motion["gyroZ"] = payload["gyroZ"]
        trace = session.motion.setdefault("trace", [])
        trace.append({"type": "imu", "timestamp": timestamp, **payload})
        if len(trace) > 500:
            del trace[:-500]
        _touch_session()
        # Ableton's established route remains 0..1; only this adapter converts.
        send_ableton_motion(
            "twist",
            {"value": (twist + 1.0) / 2.0},
        )
        send_ableton_motion("finger", {"value": tilt_x})
        message = event("imu", {**payload, "source": source}, timestamp=timestamp)
    else:
        message = _motion_event(event_type, payload, timestamp)
        message["payload"].update(
            {
                "sessionId": ring_session_id,
                "source": payload.get("source", source),
            }
        )
        if "sequence" in payload:
            message["payload"]["sequence"] = payload["sequence"]
        session.motion["ringSessionId"] = ring_session_id

    await bus.broadcast(message)
    return {"accepted": True, "event": message}


async def _handle_ring_runtime_event(raw: dict) -> None:
    try:
        await _ingest_ring_event(raw, source="ring_runtime")
    except (RingProtocolError, HTTPException, OSError, TypeError, ValueError) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        ring_status["lastError"] = detail
        await publish(
            "error",
            {
                "code": "INVALID_RING_RUNTIME_EVENT",
                "message": detail,
                "recoverable": True,
                "recommendedAction": "Check the RingRuntime event contract and retry.",
            },
        )


@app.post("/api/mock/twist")
async def mock_twist(value: float = Query(default=0.65)) -> dict:
    message = _motion_event("twist", {"value": value})
    await bus.broadcast(message)
    return message


@app.post("/api/mock/burst")
async def mock_burst(strength: float = Query(default=0.9)) -> dict:
    message = _motion_event("burst", {"strength": strength})
    await bus.broadcast(message)
    return message


@app.post("/api/mock/finger")
async def mock_finger(value: float = Query(default=0.0)) -> dict:
    message = _motion_event("finger", {"value": value})
    await bus.broadcast(message)
    return message


@app.post("/api/mock/tilt-x")
async def mock_tilt_x(value: float = Query(default=0.0)) -> dict:
    message = _motion_event("tiltX", {"value": value})
    await bus.broadcast(message)
    return message


@app.post("/api/ableton/motion/{motion_type}")
async def ableton_motion(motion_type: str, value: float = Query(...)) -> dict:
    """Drive Ableton from the frontend's no-ring interaction simulator."""
    if not math.isfinite(value):
        raise HTTPException(status_code=422, detail="value must be finite")
    if motion_type == "twist":
        normalized = max(0.0, min(1.0, (value + 1.0) / 2.0))
        send_ableton_motion("twist", {"value": normalized})
    elif motion_type in {"tiltX", "finger"}:
        normalized = max(-1.0, min(1.0, value))
        send_ableton_motion("finger", {"value": normalized})
    elif motion_type == "burst":
        normalized = max(0.0, min(1.0, value))
        send_ableton_motion("burst", {"strength": normalized})
    else:
        raise HTTPException(status_code=422, detail=f"unsupported Ableton motion: {motion_type}")
    return {"ok": True, "type": motion_type, "value": normalized}


@app.post("/api/mock/freeze")
async def mock_freeze(active: bool = Query(default=True)) -> dict:
    message = _motion_event("freeze", {"active": active})
    await bus.broadcast(message)
    return message


@app.post("/api/mock/color")
async def mock_color(hue: float = Query(default=205.0)) -> dict:
    message = _motion_event("color", {"hue": hue})
    await bus.broadcast(message)
    return message


@app.get("/api/ring/status")
async def get_ring_status() -> dict:
    manager_status = ring_manager.status() if ring_manager else {
        "enabled": False,
        "connected": False,
        "sessionRunning": False,
        "lastError": None,
        "runtimePath": None,
        "ffmpegPath": None,
    }
    return {**ring_status, **manager_status, "activeSessionId": active_ring_session_id}


@app.post("/api/ring/session/start")
async def start_ring_session() -> dict:
    if ring_manager is None:
        raise HTTPException(status_code=503, detail="RingRuntime manager is not available")
    try:
        await ring_manager.begin_session(session.session_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await publish(
        "status",
        {
            "phase": "recording",
            "message": "Ring recording is armed; long-press the ring and speak",
            "sessionId": session.session_id,
        },
    )
    return {"started": True, "sessionId": session.session_id, **ring_manager.status()}


@app.post("/api/mock/ring-event")
async def mock_ring_event(body: EventMessage) -> dict:
    if ring_manager and ring_manager.enabled:
        raise HTTPException(
            status_code=409,
            detail="mock ring ingestion is disabled while real RingRuntime is enabled",
        )
    try:
        return await _ingest_ring_event(body.model_dump(), source="mock_replay")
    except RingProtocolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/save")
async def save_current_work(body: SaveRequest) -> dict:
    if session.emotion is None or session.mode is None:
        raise HTTPException(status_code=409, detail="the current work is incomplete")

    final_motion = {**session.motion, **body.final_motion}
    session.motion = final_motion
    previous_phase = session.phase
    session.phase = Phase.SAVED
    session.last_error = None
    _touch_session()
    session_data = session.model_dump(mode="json")
    session_data["finalMotion"] = final_motion
    try:
        result = await asyncio.to_thread(
            save_work,
            works_dir=WORKS_DIR,
            session_data=session_data,
            original_audio=ORIGINAL_AUDIO if ORIGINAL_AUDIO.exists() else None,
            output_audio=(
                OUTPUT_AUDIO
                if session.output_audio_url == "/audio/output.wav"
                and OUTPUT_AUDIO.exists()
                else None
            ),
            screenshot_data_url=body.screenshot_data_url,
            processed_audio_data_url=body.processed_audio_data_url,
        )
    except ValueError as exc:
        session.phase = previous_phase
        session.last_error = str(exc)
        _touch_session()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        session.phase = previous_phase
        session.last_error = str(exc)
        _touch_session()
        raise HTTPException(status_code=500, detail=f"save failed: {exc}") from exc

    session.saved_id = result["id"]
    _touch_session()
    response = {
        **result,
        "session_id": session.session_id,
        "audio_id": session.audio_id,
        "phase": session.phase,
        "emotion": session.emotion,
        "mode": session.mode,
        "features": session.features.model_dump(),
        "motion": session.motion,
        "revision": session.revision,
    }
    await publish("saved", response)
    return response


@app.post("/api/public/works")
async def create_public_work(body: PublicWorkRequest) -> dict:
    """Save a QR-safe work bundle without exposing the private session."""
    global obs_recording_path
    obs_video: bytes | None = None
    if body.use_obs_recording:
        async with obs_recording_lock:
            path = obs_recording_path
            obs_recording_path = None
        if path is None or not path.is_file():
            raise HTTPException(
                status_code=422,
                detail="OBS recording was not found; finish sculpting after OBS starts",
            )
        try:
            if path.suffix.lower() != ".mp4" or path.stat().st_size > MAX_PROCESS_VIDEO_BYTES:
                raise ValueError("OBS recording must be an MP4 no larger than 60 MB")
            obs_video = await asyncio.to_thread(path.read_bytes)
        except OSError as exc:
            raise HTTPException(
                status_code=422, detail=f"could not read OBS recording: {exc}"
            ) from exc
    try:
        result = await asyncio.to_thread(
            save_public_work,
            public_works_dir=PUBLIC_WORKS_DIR,
            screenshot_data_url=body.screenshot_data_url,
            processed_audio_data_url=body.processed_audio_data_url,
            emotion=body.emotion.value,
            caption=body.caption,
            final_motion=body.final_motion,
            process_video_data_url=body.process_video_data_url,
            process_video_mp4=obs_video,
            process_frames_data_urls=body.process_frames_data_urls,
            process_frame_rate=body.process_frame_rate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"public save failed: {exc}") from exc

    work_id = result["id"]
    return {
        **result,
        "workId": work_id,
        "workUrl": f"/api/public/works/{work_id}",
        "coverUrl": f"/api/public/works/{work_id}/cover",
        "audioUrl": f"/api/public/works/{work_id}/audio",
        "videoUrl": (
            f"/api/public/works/{work_id}/video"
            if result["has_process_video"]
            else None
        ),
    }


@app.post("/api/obs/recording/start")
async def begin_obs_recording() -> dict:
    global obs_recording_path
    async with obs_recording_lock:
        try:
            result = await start_obs_recording()
        except OBSControlError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        obs_recording_path = None
    return result


@app.post("/api/obs/recording/stop")
async def end_obs_recording() -> dict:
    global obs_recording_path
    async with obs_recording_lock:
        try:
            path = await stop_obs_recording()
        except OBSControlError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        obs_recording_path = path
    return {"provider": "obs", "ready": True}


@app.get("/api/public/works/{work_id}")
async def get_public_work(work_id: str) -> dict:
    metadata = await asyncio.to_thread(_read_public_work, work_id)
    return {
        **metadata,
        "coverUrl": f"/api/public/works/{work_id}/cover",
        "audioUrl": f"/api/public/works/{work_id}/audio",
        "videoUrl": (
            f"/api/public/works/{work_id}/video"
            if metadata.get("has_process_video")
            else None
        ),
    }


@app.get("/api/public/works/{work_id}/cover")
async def get_public_work_cover(work_id: str) -> FileResponse:
    target = _public_work_directory(work_id) / "cover.png"
    if not target.is_file():
        raise HTTPException(status_code=404, detail="shared cover not found")
    return FileResponse(target, media_type="image/png")


@app.get("/api/public/works/{work_id}/audio")
async def get_public_work_audio(work_id: str) -> FileResponse:
    target = _public_work_directory(work_id) / "audio.wav"
    if not target.is_file():
        raise HTTPException(status_code=404, detail="shared audio not found")
    return FileResponse(target, media_type="audio/wav")


@app.get("/api/public/works/{work_id}/video")
async def get_public_work_video(work_id: str) -> FileResponse:
    directory = _public_work_directory(work_id)
    webm = directory / "process.webm"
    mp4 = directory / "process.mp4"
    target = webm if webm.is_file() else mp4
    if not target.is_file():
        raise HTTPException(status_code=404, detail="shared process video not found")
    media_type = "video/webm" if target.suffix == ".webm" else "video/mp4"
    return FileResponse(target, media_type=media_type)


@app.post("/api/reset")
async def reset_session() -> SessionState:
    global session, active_ring_session_id
    async with audio_lock:
        await asyncio.to_thread(ORIGINAL_AUDIO.unlink, missing_ok=True)
        await asyncio.to_thread(OUTPUT_AUDIO.unlink, missing_ok=True)
        session = SessionState(session_id=str(uuid.uuid4()))
        active_ring_session_id = None
        ring_event_guard.reset()
    await publish("status", {"phase": session.phase, "message": "Ready"})
    return session


@app.websocket("/ws/ring")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await bus.connect(websocket)
    try:
        await websocket.send_json(
            event(
                "status",
                {
                    "phase": session.phase,
                    "message": "Connected",
                    "audio_id": session.audio_id,
                    "ringConnected": bool(ring_manager and ring_manager.connected),
                    "ringEnabled": bool(ring_manager and ring_manager.enabled),
                },
            )
        )
        while True:
            incoming = await websocket.receive_json()
            try:
                if not isinstance(incoming, dict):
                    raise ValueError("ring event must be a JSON object")
                event_type = incoming.get("type")
                payload = incoming.get("payload", {})
                if not isinstance(event_type, str) or not isinstance(payload, dict):
                    raise ValueError("ring event requires string type and object payload")

                has_ring_session = bool(payload.get("sessionId") or payload.get("session_id"))
                if event_type in {"status", "imu", "error"} or (
                    event_type in {"tiltX", "finger", "burst", "freeze"} and has_ring_session
                ):
                    await _ingest_ring_event(incoming, source="websocket")
                    continue

                aliases = {
                    "imu/twist": "twist",
                    "imu/tiltX": "tiltX",
                    "imu/finger": "finger",
                    "finger_move": "finger",
                    "size": "finger",
                    "scale": "finger",
                    "depth": "finger",
                    "imu/burst": "burst",
                    "imu/freeze": "freeze",
                    "ui/color": "color",
                }
                event_type = aliases.get(event_type, event_type)
                if event_type not in {"twist", "tiltX", "finger", "burst", "freeze", "color"}:
                    raise ValueError(f"unsupported inbound ring event: {event_type}")
                incoming_session = payload.get("session_id")
                incoming_audio = payload.get("audio_id")
                if incoming_session and incoming_session != session.session_id:
                    raise ValueError("ring event belongs to an older session")
                if incoming_audio and incoming_audio != session.audio_id:
                    raise ValueError("ring event belongs to older audio")

                raw_timestamp = incoming.get("timestamp")
                timestamp = None
                if raw_timestamp is not None:
                    timestamp_number = float(raw_timestamp)
                    if not math.isfinite(timestamp_number) or timestamp_number < 0:
                        raise ValueError("ring event timestamp must be finite and positive")
                    timestamp = int(timestamp_number)
                message = _motion_event(event_type, payload, timestamp)
                await bus.broadcast(message)
            except (HTTPException, TypeError, ValueError) as exc:
                detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                await websocket.send_json(
                    event("error", {"code": "INVALID_RING_EVENT", "message": detail})
                )
    except WebSocketDisconnect:
        await bus.disconnect(websocket)
    except Exception:
        await bus.disconnect(websocket)
