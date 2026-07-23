from __future__ import annotations

import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from stt_adapter import STTError, transcribe_audio
from emotion_analyzer import analyze_emotion_local
from event_bus import EventBus
from recipe_engine import build_recipe
from save_service import save_work
from schemas import (
    EmotionConfirmRequest,
    ModeSelectRequest,
    Phase,
    SaveRequest,
    SessionState,
    TranscriptRequest,
)

BASE_DIR = Path(__file__).resolve().parent
AUDIO_DIR = BASE_DIR / "audio"
WORKS_DIR = BASE_DIR.parent / "works"
AUDIO_DIR.mkdir(exist_ok=True)
WORKS_DIR.mkdir(exist_ok=True)

ORIGINAL_AUDIO = AUDIO_DIR / "original.wav"
OUTPUT_AUDIO = AUDIO_DIR / "output.wav"

app = FastAPI(title="SoundClay Emotion Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/api/status")
async def get_status() -> dict:
    return {
        "ringConnected": False,
        "phase": session.phase,
        "modeHint": "recording",
        "lastError": session.last_error,
    }


@app.get("/api/session/current")
async def get_current_session() -> SessionState:
    return session

@app.post("/api/stt/transcribe")
async def transcribe_original_audio() -> dict:
    if not ORIGINAL_AUDIO.exists():
        raise HTTPException(
            status_code=404,
            detail="找不到 backend/audio/original.wav",
        )

    session.phase = Phase.UNDERSTANDING
    session.last_error = None

    await publish(
        "status",
        {
            "phase": session.phase,
            "message": "Understanding your voice",
        },
    )

    try:
        transcript = await transcribe_audio(ORIGINAL_AUDIO)
    except STTError as exc:
        session.last_error = str(exc)

        await publish(
            "error",
            {
                "code": "STT_FAILED",
                "message": str(exc),
            },
        )

        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    session.transcript = transcript

    await publish(
        "transcript_ready",
        {
            "transcript": transcript,
        },
    )

    result = analyze_emotion_local(transcript)

    session.emotion = result.emotion
    session.confidence = result.confidence
    session.reason = result.reason
    session.phase = Phase.EMOTION_REVIEW

    payload = {
        "transcript": transcript,
        **result.model_dump(mode="json"),
    }

    await publish("emotion_ready", payload)

    return payload
@app.post("/api/mock/transcript")
async def mock_transcript(body: TranscriptRequest) -> dict:
    session.phase = Phase.UNDERSTANDING
    session.transcript = body.transcript
    await publish("transcript_ready", {"transcript": body.transcript})

    result = analyze_emotion_local(body.transcript)
    session.emotion = result.emotion
    session.confidence = result.confidence
    session.reason = result.reason
    session.phase = Phase.EMOTION_REVIEW

    payload = result.model_dump(mode="json")
    await publish("emotion_ready", payload)
    return {"transcript": body.transcript, **payload}


@app.post("/api/emotion/confirm")
async def confirm_emotion(body: EmotionConfirmRequest) -> SessionState:
    if not session.transcript:
        raise HTTPException(status_code=409, detail="尚无转写文本")

    session.emotion = body.emotion
    session.confidence = 1.0
    session.reason = "用户已确认或手动修改。"
    session.phase = Phase.MODE_CHOICE
    await publish(
        "status",
        {"phase": session.phase, "message": "Choose Express or Soothe"},
    )
    return session


@app.post("/api/mode/select")
async def select_mode(body: ModeSelectRequest) -> dict:
    if session.emotion is None:
        raise HTTPException(status_code=409, detail="请先确认情绪")

    session.mode = body.mode
    session.phase = Phase.MATERIALIZING
    session.recipe = build_recipe(session.emotion, body.mode)

    # 当前先复用原声地址。成员 D 用 Web Audio Recipe 进行实时处理。
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


@app.post("/api/save")
async def save_current_work(body: SaveRequest) -> dict:
    if session.emotion is None or session.mode is None:
        raise HTTPException(status_code=409, detail="当前作品尚未完成")

    session_data = session.model_dump(mode="json")
    session_data["finalMotion"] = body.final_motion

    try:
        result = save_work(
            works_dir=WORKS_DIR,
            session_data=session_data,
            original_audio=ORIGINAL_AUDIO if ORIGINAL_AUDIO.exists() else None,
            output_audio=OUTPUT_AUDIO if OUTPUT_AUDIO.exists() else None,
            screenshot_data_url=body.screenshot_data_url,
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"保存失败：{exc}") from exc

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
            # 允许前端发送 ping 或调试消息，后端当前不强制处理。
            await websocket.receive_text()
    except WebSocketDisconnect:
        await bus.disconnect(websocket)
    except Exception:
        await bus.disconnect(websocket)
