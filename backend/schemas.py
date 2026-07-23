from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Phase(str, Enum):
    READY = "ready"
    RECORDING = "recording"
    UNDERSTANDING = "understanding"
    EMOTION_REVIEW = "emotion_review"
    MODE_CHOICE = "mode_choice"
    MATERIALIZING = "materializing"
    SCULPTING = "sculpting"
    SAVED = "saved"


class Emotion(str, Enum):
    JOY = "joy"
    ANGER = "anger"
    SADNESS = "sadness"
    ANXIETY = "anxiety"
    NEUTRAL_MIXED = "neutral-mixed"


class Mode(str, Enum):
    EXPRESS = "express"
    SOOTHE = "soothe"


class EmotionResult(BaseModel):
    emotion: Emotion
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class AudioFeatures(BaseModel):
    volume: float = Field(default=0.0, ge=0.0, le=1.0)
    pitch: float = Field(default=0.5, ge=0.0, le=1.0)
    brightness: float = Field(default=0.5, ge=0.0, le=1.0)


class SessionState(BaseModel):
    session_id: str
    phase: Phase = Phase.READY
    transcript: str | None = None
    emotion: Emotion | None = None
    confidence: float | None = None
    reason: str | None = None
    mode: Mode | None = None
    recipe: dict[str, Any] | None = None
    features: AudioFeatures = Field(default_factory=AudioFeatures)
    original_audio_url: str | None = None
    output_audio_url: str | None = None
    saved_id: str | None = None
    last_error: str | None = None


class TranscriptRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=500)


class EmotionConfirmRequest(BaseModel):
    emotion: Emotion


class ModeSelectRequest(BaseModel):
    mode: Mode


class SaveRequest(BaseModel):
    screenshot_data_url: str | None = None
    final_motion: dict[str, float | int | str] = Field(default_factory=dict)


class EventMessage(BaseModel):
    type: str
    timestamp: int
    payload: dict[str, Any] = Field(default_factory=dict)
