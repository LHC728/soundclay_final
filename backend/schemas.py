from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Phase(str, Enum):
    READY = "ready"
    RECORDING = "recording"
    AUDIO_READY = "audio_ready"
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
    NEUTRAL_MIXED = "neutral_mixed"

    @classmethod
    def _missing_(cls, value: object) -> Emotion | None:
        # The first P0 contract used a hyphen. Continue accepting it while
        # serializing the taskbook's canonical underscore form.
        if isinstance(value, str) and value.strip().lower() == "neutral-mixed":
            return cls.NEUTRAL_MIXED
        return None


class Mode(str, Enum):
    EXPRESS = "express"
    SOOTHE = "soothe"


class EmotionResult(BaseModel):
    emotion: Emotion
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class AudioFeatures(BaseModel):
    volume: float = Field(default=0.0, ge=0.0, le=1.0)
    pitch: float = Field(default=0.0, ge=0.0, le=1.0)
    brightness: float = Field(default=0.0, ge=0.0, le=1.0)


class VoiceFxRecipe(BaseModel):
    playbackRate: float = Field(ge=0.5, le=2.0)
    lowpassHz: float = Field(ge=20.0, le=20_000.0)
    distortion: float = Field(ge=0.0, le=1.0)
    reverb: float = Field(ge=0.0, le=1.0)
    gain: float = Field(ge=0.0, le=2.0)


class AudioBedRecipe(BaseModel):
    stemId: str = Field(min_length=1, max_length=100)
    emotionStemId: str | None = Field(default=None, min_length=1, max_length=100)
    pulseRate: float = Field(ge=0.0, le=1.0)
    stemGain: float = Field(ge=0.0, le=1.0)


class VisualRecipe(BaseModel):
    sharpness: float = Field(ge=0.0, le=1.0)
    density: float = Field(ge=0.0, le=1.0)
    breathing: float = Field(ge=0.0, le=1.0)
    motion: str = Field(min_length=1, max_length=100)


class MaterialRecipe(BaseModel):
    emotion: Emotion
    mode: Mode
    voiceFx: VoiceFxRecipe
    soundscape: AudioBedRecipe
    audioBed: AudioBedRecipe
    visual: VisualRecipe


class SessionState(BaseModel):
    session_id: str
    revision: int = Field(default=0, ge=0)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    phase: Phase = Phase.READY
    audio_id: str | None = None
    audio_filename: str | None = None
    audio_bytes: int | None = Field(default=None, ge=0)
    transcript: str | None = None
    emotion: Emotion | None = None
    confidence: float | None = None
    reason: str | None = None
    emotion_provider: str | None = None
    emotion_warning: str | None = None
    emotion_scores: dict[str, float] | None = None
    emotion_weights: dict[str, float] | None = None
    emotion_cache_hit: bool = False
    mode: Mode | None = None
    recipe: dict[str, Any] | None = None
    features: AudioFeatures = Field(default_factory=AudioFeatures)
    features_audio_id: str | None = None
    original_audio_url: str | None = None
    output_audio_url: str | None = None
    motion: dict[str, Any] = Field(default_factory=dict)
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
    processed_audio_data_url: str | None = None
    final_motion: dict[str, Any] = Field(default_factory=dict)

    @field_validator("final_motion")
    @classmethod
    def validate_final_motion(cls, value: dict[str, Any]) -> dict[str, Any]:
        def check(item: Any) -> None:
            if isinstance(item, bool) or item is None or isinstance(item, str):
                return
            if isinstance(item, (int, float)):
                if not math.isfinite(float(item)):
                    raise ValueError("motion values must be finite")
                return
            if isinstance(item, dict):
                for nested in item.values():
                    check(nested)
                return
            if isinstance(item, list):
                for nested in item:
                    check(nested)
                return
            raise ValueError("motion values must be JSON-compatible")

        check(value)
        return value


class EventMessage(BaseModel):
    type: str
    timestamp: int
    payload: dict[str, Any] = Field(default_factory=dict)
