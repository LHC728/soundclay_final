from __future__ import annotations

import asyncio
import math
import os
import time
import uuid
from pathlib import Path

import soundfile as sf
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from audio_pipeline import analyze_audio
from emotion_analyzer import analyze_emotion_local
from event_bus import EventBus
from recipe_engine import build_recipe
from save_service import save_work
from schemas import (
    AudioFeatures,
    EmotionConfirmRequest,
    ModeSelectRequest,
    Phase,
    SaveRequest,
    SessionState,
    TranscriptRequest,
)
from stt_adapter import STTError, transcribe_audio

BASE_DIR = Path(__file__).resolve().parent
AUDIO_DIR = BASE_DIR / "audio"
WORKS_DIR = BASE_DIR.parent / "works"
AUDIO_DIR.mkdir(exist_ok=True)
WORKS_DIR.mkdir(exist_ok=True)

ORIGINAL_AUDIO = AUDIO_DIR / "original.wav"
OUTPUT_AUDIO = AUDIO_DIR / "output.wav"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

app = FastAPI(title="SoundClay Emotion Backend", version="0.2.0")
configured_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(
        dict.fromkeys(
            [configured_origin, "http://localhost:5173", "http://127.0.0.1:5173"]
        )
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/audio", StaticFiles(directory=AUDIO_DIR), name="audio")
app.mount("/works", StaticFiles(directory=WORKS_DIR), name="works")

bus = EventBus()
session = SessionState(session_id=str(uuid.uuid4()))


def event(event_type: str, payload: dict) -> dict:
    return {
        "type": event_type,
        "timestamp": int(time.time() * 1000),
        "payload": payload,
    }


async def publish(event_type: str, payload: dict) -> None:
    await bus.broadcast(event(event_type, payload))


def _clamped_number(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise HTTPException(status_code=422, detail=f"{name} must be finite")
    return float(max(0.0, min(1.0, value)))


def _store_wav(payload: bytes) -> dict:
    if not payload:
        raise ValueError("WAV upload is empty")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ValueError(f"WAV upload exceeds the {MAX_UPLOAD_BYTES}-byte limit")
    if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        raise ValueError("upload is not a RIFF/WAVE file")

    temporary = AUDIO_DIR / f"upload-{uuid.uuid4().hex}.wav"
    try:
        temporary.write_bytes(payload)
        info = sf.info(str(temporary))
        if info.frames <= 0 or info.samplerate <= 0:
            raise ValueError("WAV upload has no audio frames")
        temporary.replace(ORIGINAL_AUDIO)
    finally:
        temporary.unlink(missing_ok=True)

    return {
        "audioUrl": "/audio/original.wav",
        "bytes": len(payload),
        "sampleRate": info.samplerate,
        "channels": info.channels,
        "frames": info.frames,
    }


async def _analyze_current_audio(*, emit: bool = True) -> AudioFeatures:
    if not ORIGINAL_AUDIO.exists():
        raise HTTPException(status_code=404, detail="backend/audio/original.wav not found")
    try:
        features = await asyncio.to_thread(analyze_audio, ORIGINAL_AUDIO)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"audio analysis failed: {exc}") from exc
    session.features = features
    session.original_audio_url = "/audio/original.wav"
    if emit:
        await publish("audio_features_ready", features.model_dump())
    return features


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/api/status")
async def get_status() -> dict:
    return {
        "ringConnected": False,
        "phase": session.phase,
        "modeHint": "mock-controls-available",
        "lastError": session.last_error,
    }


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
    try:
        result = await asyncio.to_thread(_store_wav, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.original_audio_url = result["audioUrl"]
    session.last_error = None
    features = await _analyze_current_audio()
    return {**result, "features": features.model_dump()}


@app.post("/api/audio/analyze")
async def analyze_current_audio() -> dict:
    features = await _analyze_current_audio()
    return features.model_dump()


@app.post("/api/stt/transcribe")
async def transcribe_original_audio() -> dict:
    if not ORIGINAL_AUDIO.exists():
        raise HTTPException(status_code=404, detail="backend/audio/original.wav not found")

    session.phase = Phase.UNDERSTANDING
    session.last_error = None
    await publish(
        "status", {"phase": session.phase, "message": "Understanding your voice"}
    )

    try:
        transcript = await transcribe_audio(ORIGINAL_AUDIO)
    except STTError as exc:
        session.last_error = str(exc)
        await publish("error", {"code": "STT_FAILED", "message": str(exc)})
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    session.transcript = transcript
    await publish("transcript_ready", {"transcript": transcript})

    feature_error: str | None = None
    try:
        await _analyze_current_audio()
    except HTTPException as exc:
        feature_error = str(exc.detail)
        session.last_error = feature_error
        await publish(
            "error", {"code": "AUDIO_FEATURES_FAILED", "message": feature_error}
        )

    result = analyze_emotion_local(transcript)
    session.emotion = result.emotion
    session.confidence = result.confidence
    session.reason = result.reason
    session.phase = Phase.EMOTION_REVIEW
    response = {
        "transcript": transcript,
        **result.model_dump(mode="json"),
        "features": session.features.model_dump(),
        "featureError": feature_error,
    }
    await publish("emotion_ready", response)
    return response


@app.post("/api/mock/transcript")
async def mock_transcript(body: TranscriptRequest) -> dict:
    session.phase = Phase.UNDERSTANDING
    session.last_error = None
    session.transcript = body.transcript
    await publish("transcript_ready", {"transcript": body.transcript})

    result = analyze_emotion_local(body.transcript)
    session.emotion = result.emotion
    session.confidence = result.confidence
    session.reason = result.reason
    session.phase = Phase.EMOTION_REVIEW
    payload = result.model_dump(mode="json")
    await publish("emotion_ready", {"transcript": body.transcript, **payload})
    return {"transcript": body.transcript, **payload, "features": session.features.model_dump()}


@app.post("/api/emotion/confirm")
async def confirm_emotion(body: EmotionConfirmRequest) -> SessionState:
    if not session.transcript:
        raise HTTPException(status_code=409, detail="no transcript is available")
    session.emotion = body.emotion
    session.confidence = 1.0
    session.reason = "Confirmed or corrected by the user."
    session.phase = Phase.MODE_CHOICE
    await publish(
        "status", {"phase": session.phase, "message": "Choose Express or Soothe"}
    )
    return session


@app.post("/api/mode/select")
async def select_mode(body: ModeSelectRequest) -> dict:
    if session.emotion is None:
        raise HTTPException(status_code=409, detail="confirm an emotion first")
    session.mode = body.mode
    session.phase = Phase.MATERIALIZING
    session.recipe = build_recipe(session.emotion, body.mode)
    if ORIGINAL_AUDIO.exists():
        session.original_audio_url = "/audio/original.wav"
        session.output_audio_url = "/audio/original.wav"

    payload = {
        "mode": body.mode,
        "audioUrl": session.output_audio_url,
        "recipe": session.recipe,
        "features": session.features.model_dump(),
        "seed": abs(hash(session.session_id)) % 10000,
    }
    await publish("material_ready", payload)
    session.phase = Phase.SCULPTING
    return payload


@app.post("/api/mock/twist")
async def mock_twist(value: float = Query(default=0.65)) -> dict:
    clamped = _clamped_number(value, "value")
    session.motion["twist"] = clamped
    message = event("twist", {"value": clamped})
    await bus.broadcast(message)
    return message


@app.post("/api/mock/burst")
async def mock_burst(strength: float = Query(default=0.9)) -> dict:
    clamped = _clamped_number(strength, "strength")
    session.motion["burstStrength"] = clamped
    session.motion["burstCount"] = int(session.motion.get("burstCount", 0)) + 1
    message = event("burst", {"strength": clamped})
    await bus.broadcast(message)
    return message


@app.post("/api/mock/freeze")
async def mock_freeze() -> dict:
    message = event("freeze", {})
    session.motion["frozen"] = True
    session.motion["frozenAt"] = message["timestamp"]
    await bus.broadcast(message)
    return message


@app.post("/api/save")
async def save_current_work(body: SaveRequest) -> dict:
    if session.emotion is None or session.mode is None:
        raise HTTPException(status_code=409, detail="the current work is incomplete")

    final_motion = {**session.motion, **body.final_motion}
    session.motion = final_motion
    session_data = session.model_dump(mode="json")
    session_data["finalMotion"] = final_motion
    try:
        result = await asyncio.to_thread(
            save_work,
            works_dir=WORKS_DIR,
            session_data=session_data,
            original_audio=ORIGINAL_AUDIO if ORIGINAL_AUDIO.exists() else None,
            output_audio=OUTPUT_AUDIO if OUTPUT_AUDIO.exists() else None,
            screenshot_data_url=body.screenshot_data_url,
            processed_audio_data_url=body.processed_audio_data_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"save failed: {exc}") from exc

    session.saved_id = result["id"]
    session.phase = Phase.SAVED
    await publish("saved", result)
    return result


@app.post("/api/reset")
async def reset_session() -> SessionState:
    global session
    session = SessionState(session_id=str(uuid.uuid4()))
    await publish("status", {"phase": session.phase, "message": "Ready"})
    return session


@app.websocket("/ws/ring")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await bus.connect(websocket)
    try:
        await websocket.send_json(
            event("status", {"phase": session.phase, "message": "Connected"})
        )
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await bus.disconnect(websocket)
    except Exception:
        await bus.disconnect(websocket)
