from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from dotenv import load_dotenv

from chinese_text import normalize_transcript

load_dotenv()


class STTError(RuntimeError):
    """A local speech-to-text provider failed."""


def get_stt_provider() -> str:
    return os.getenv("STT_PROVIDER", "mock").strip().lower()


def _integer_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise STTError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise STTError(f"{name} must be between {minimum} and {maximum}")
    return value


def _float_setting(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise STTError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise STTError(f"{name} must be between {minimum:g} and {maximum:g}")
    return value


@lru_cache(maxsize=4)
def _get_whisper_model(model_name: str, device: str, compute_type: str) -> Any:
    """Load each local faster-whisper configuration once per process."""
    try:
        from faster_whisper import WhisperModel

        return WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
        )
    except Exception as exc:
        raise STTError(f"Unable to load the local Whisper model: {exc}") from exc


def _transcribe_faster_whisper(audio_path: Path) -> str:
    if not audio_path.exists():
        raise STTError(f"Audio file not found: {audio_path}")

    model_name = os.getenv("WHISPER_MODEL", "base").strip() or "base"
    device = os.getenv("WHISPER_DEVICE", "cpu").strip() or "cpu"
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8").strip() or "int8"
    language = os.getenv("WHISPER_LANGUAGE", "zh").strip() or None
    beam_size = _integer_setting("WHISPER_BEAM_SIZE", 1, 1, 20)
    model = _get_whisper_model(model_name, device, compute_type)

    prompt = (
        "请使用简体中文准确转写说话者的完整原话，不要推断其隐藏情绪。"
        if language and language.lower().startswith("zh")
        else (
            "This is a spoken reflection. Transcribe the speaker's complete "
            "words accurately without inferring hidden emotions."
        )
    )

    try:
        segments, _info = model.transcribe(
            str(audio_path),
            language=language,
            task="transcribe",
            beam_size=beam_size,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=prompt,
        )
        text = "".join(segment.text for segment in segments).strip()
    except STTError:
        raise
    except Exception as exc:
        raise STTError(f"Local Whisper transcription failed: {exc}") from exc

    if not text:
        raise STTError("No speech was recognized. Record again or use a mock transcript.")
    return text


class STTProviderAdapter(Protocol):
    name: str

    async def transcribe(self, audio_path: Path) -> str: ...


class MockSTTAdapter:
    name = "mock"

    async def transcribe(self, audio_path: Path) -> str:
        del audio_path
        transcript = os.getenv(
            "MOCK_TRANSCRIPT",
            "Today has been frustrating and I feel angry.",
        ).strip()
        if not transcript:
            raise STTError("MOCK_TRANSCRIPT is empty")
        return transcript


class FasterWhisperAdapter:
    name = "faster_whisper"

    async def transcribe(self, audio_path: Path) -> str:
        timeout_seconds = _float_setting(
            "STT_TIMEOUT_SECONDS", 120.0, 1.0, 3600.0
        )
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_transcribe_faster_whisper, audio_path),
                timeout=timeout_seconds,
            )
        except TimeoutError as exc:
            raise STTError(
                f"Local transcription timed out after {timeout_seconds:g} seconds. "
                "Retry with a shorter WAV or increase STT_TIMEOUT_SECONDS."
            ) from exc


def get_stt_adapter() -> STTProviderAdapter:
    provider = get_stt_provider()
    if provider == "mock":
        return MockSTTAdapter()
    if provider in {"faster_whisper", "local_whisper"}:
        return FasterWhisperAdapter()
    raise STTError(f"Unsupported STT_PROVIDER: {provider}")


async def transcribe_audio(audio_path: str | Path) -> str:
    transcript = await get_stt_adapter().transcribe(Path(audio_path))
    return normalize_transcript(transcript)
