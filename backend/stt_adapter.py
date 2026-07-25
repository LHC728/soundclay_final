from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from dotenv import load_dotenv

from chinese_text import normalize_transcript
from schemas import Emotion

load_dotenv()


class STTError(RuntimeError):
    """A local speech-to-text provider failed."""


class RecognizedTranscript(str):
    """Transcript text with optional emotion metadata from an audio model.

    It intentionally remains a ``str`` subclass so existing route and client
    contracts continue to receive ordinary transcript text.
    """

    provider: str
    speech_emotion: Emotion | None
    raw_emotion: str | None

    def __new__(
        cls,
        text: str,
        *,
        provider: str,
        speech_emotion: Emotion | None = None,
        raw_emotion: str | None = None,
    ) -> "RecognizedTranscript":
        instance = super().__new__(cls, text)
        instance.provider = provider
        instance.speech_emotion = speech_emotion
        instance.raw_emotion = raw_emotion
        return instance


@dataclass(frozen=True)
class SpeechRecognition:
    text: str
    provider: str
    speech_emotion: Emotion | None = None
    raw_emotion: str | None = None


_SENSEVOICE_EMOTION_MAP: dict[str, Emotion] = {
    "HAPPY": Emotion.JOY,
    "SAD": Emotion.SADNESS,
    "ANGRY": Emotion.ANGER,
    "FEARFUL": Emotion.ANXIETY,
    "NEUTRAL": Emotion.NEUTRAL_MIXED,
    "SURPRISED": Emotion.NEUTRAL_MIXED,
    "DISGUSTED": Emotion.NEUTRAL_MIXED,
    "EMO_UNKNOWN": Emotion.NEUTRAL_MIXED,
    "EMO_UNK": Emotion.NEUTRAL_MIXED,
}
_SENSEVOICE_TOKEN = re.compile(r"<\|([^|]+)\|>")


def _json_safe_text(text: str) -> str:
    """Replace invalid lone Unicode surrogates before an HTTP JSON response."""
    return text.encode("utf-8", errors="replace").decode("utf-8")


def _cached_model_path(model_name: str) -> str:
    """Prefer an existing ModelScope snapshot so later runs stay offline."""
    cache_root = Path(
        os.getenv("MODELSCOPE_CACHE", str(Path.home() / ".cache" / "modelscope"))
    )
    snapshots = cache_root / "models" / model_name.replace("/", "--") / "snapshots"
    if snapshots.is_dir():
        preferred = snapshots / "master"
        if preferred.is_dir():
            return str(preferred)
        candidates = sorted(path for path in snapshots.iterdir() if path.is_dir())
        if candidates:
            return str(candidates[-1])
    return model_name


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


@lru_cache(maxsize=2)
def _get_sensevoice_model(model_name: str, device: str) -> Any:
    """Load the local SenseVoice checkpoint once per configuration."""
    try:
        from funasr import AutoModel

        return AutoModel(
            model=_cached_model_path(model_name),
            trust_remote_code=False,
            disable_update=True,
            vad_model=_cached_model_path("iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"),
            vad_kwargs={"max_single_segment_time": 30000},
            device=device,
        )
    except Exception as exc:
        raise STTError(
            "Unable to load the local SenseVoice model. Install funasr and "
            "ensure the model is available locally or can be downloaded: "
            f"{exc}"
        ) from exc


def _sensevoice_emotion(raw_text: str) -> tuple[Emotion | None, str | None]:
    """Extract SenseVoice's tagged speech emotion before text post-processing."""
    for token in _SENSEVOICE_TOKEN.findall(raw_text):
        normalized = token.strip().upper().replace("-", "_")
        emotion = _SENSEVOICE_EMOTION_MAP.get(normalized)
        if emotion is not None:
            return emotion, normalized
    return None, None


def _transcribe_sensevoice(audio_path: Path) -> SpeechRecognition:
    if not audio_path.exists():
        raise STTError(f"Audio file not found: {audio_path}")

    model_name = os.getenv("SENSEVOICE_MODEL", "iic/SenseVoiceSmall").strip()
    device = os.getenv("SENSEVOICE_DEVICE", "cpu").strip() or "cpu"
    language = os.getenv("SENSEVOICE_LANGUAGE", "auto").strip() or "auto"
    if not model_name:
        raise STTError("SENSEVOICE_MODEL must not be empty")
    model = _get_sensevoice_model(model_name, device)

    try:
        result = model.generate(
            input=str(audio_path),
            cache={},
            language=language,
            use_itn=True,
            batch_size_s=60,
            merge_vad=True,
            merge_length_s=15,
            ban_emo_unk=True,
        )
        if not result or not isinstance(result[0], dict):
            raise ValueError("SenseVoice returned no result")
        raw_text = str(result[0].get("text", ""))
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        text = _json_safe_text(rich_transcription_postprocess(raw_text)).strip()
    except STTError:
        raise
    except Exception as exc:
        raise STTError(f"Local SenseVoice transcription failed: {exc}") from exc

    if not text:
        raise STTError("No speech was recognized. Record again or use a mock transcript.")
    speech_emotion, raw_emotion = _sensevoice_emotion(raw_text)
    return SpeechRecognition(
        text=text,
        provider="sensevoice",
        speech_emotion=speech_emotion,
        raw_emotion=raw_emotion,
    )


class STTProviderAdapter(Protocol):
    name: str

    async def transcribe(self, audio_path: Path) -> SpeechRecognition: ...


class MockSTTAdapter:
    name = "mock"

    async def transcribe(self, audio_path: Path) -> SpeechRecognition:
        del audio_path
        transcript = os.getenv(
            "MOCK_TRANSCRIPT",
            "Today has been frustrating and I feel angry.",
        ).strip()
        if not transcript:
            raise STTError("MOCK_TRANSCRIPT is empty")
        return SpeechRecognition(text=transcript, provider=self.name)


class FasterWhisperAdapter:
    name = "faster_whisper"

    async def transcribe(self, audio_path: Path) -> SpeechRecognition:
        timeout_seconds = _float_setting(
            "STT_TIMEOUT_SECONDS", 120.0, 1.0, 3600.0
        )
        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(_transcribe_faster_whisper, audio_path),
                timeout=timeout_seconds,
            )
            return SpeechRecognition(text=text, provider=self.name)
        except TimeoutError as exc:
            raise STTError(
                f"Local transcription timed out after {timeout_seconds:g} seconds. "
                "Retry with a shorter WAV or increase STT_TIMEOUT_SECONDS."
            ) from exc


class SenseVoiceAdapter:
    name = "sensevoice"

    async def transcribe(self, audio_path: Path) -> SpeechRecognition:
        timeout_seconds = _float_setting(
            "STT_TIMEOUT_SECONDS", 120.0, 1.0, 3600.0
        )
        try:
            isolate_default = "true" if os.name == "nt" else "false"
            isolate = os.getenv(
                "SENSEVOICE_ISOLATE_PROCESS", isolate_default
            ).strip().lower() in {"1", "true", "yes", "on"}
            if isolate:
                return await asyncio.wait_for(
                    _transcribe_sensevoice_isolated(audio_path),
                    timeout=timeout_seconds,
                )
            return await asyncio.wait_for(
                asyncio.to_thread(_transcribe_sensevoice, audio_path),
                timeout=timeout_seconds,
            )
        except TimeoutError as exc:
            raise STTError(
                f"Local transcription timed out after {timeout_seconds:g} seconds. "
                "Retry with a shorter WAV or increase STT_TIMEOUT_SECONDS."
            ) from exc


async def _transcribe_sensevoice_isolated(audio_path: Path) -> SpeechRecognition:
    """Run SenseVoice outside the WinRT BLE process on Windows.

    The ``winrt`` wheel and Torch both load native C++ runtimes. On the target
    Windows machine that combination can terminate Python with an access
    violation, which cannot be caught as a normal exception. A local worker
    process keeps those native dependency sets isolated.
    """
    worker = Path(__file__).with_name("sensevoice_worker.py")
    environment = os.environ.copy()
    environment.setdefault("PYTHONUTF8", "1")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(worker),
        str(audio_path.resolve()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )
    try:
        stdout, stderr = await process.communicate()
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise

    output = stdout.decode("utf-8", errors="replace")
    marker = "SOUNDCLAY_RESULT_JSON="
    payload_line = next(
        (line[len(marker) :] for line in reversed(output.splitlines()) if line.startswith(marker)),
        None,
    )
    if process.returncode != 0 or payload_line is None:
        details = stderr.decode("utf-8", errors="replace").strip()
        if not details:
            details = output.strip()
        if len(details) > 1200:
            details = details[-1200:]
        raise STTError(
            "Isolated local SenseVoice process failed"
            + (f": {details}" if details else f" (exit {process.returncode})")
        )

    try:
        payload = json.loads(payload_line)
        speech_emotion = (
            Emotion(payload["speech_emotion"])
            if payload.get("speech_emotion")
            else None
        )
        return SpeechRecognition(
            text=str(payload["text"]),
            provider=str(payload.get("provider", "sensevoice")),
            speech_emotion=speech_emotion,
            raw_emotion=payload.get("raw_emotion"),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise STTError(f"Invalid response from isolated SenseVoice process: {exc}") from exc


def get_stt_adapter() -> STTProviderAdapter:
    provider = get_stt_provider()
    if provider == "mock":
        return MockSTTAdapter()
    if provider in {"faster_whisper", "local_whisper"}:
        return FasterWhisperAdapter()
    if provider == "sensevoice":
        return SenseVoiceAdapter()
    raise STTError(f"Unsupported STT_PROVIDER: {provider}")


async def transcribe_audio(audio_path: str | Path) -> RecognizedTranscript:
    recognition = await get_stt_adapter().transcribe(Path(audio_path))
    return RecognizedTranscript(
        _json_safe_text(normalize_transcript(recognition.text)),
        provider=recognition.provider,
        speech_emotion=recognition.speech_emotion,
        raw_emotion=recognition.raw_emotion,
    )
