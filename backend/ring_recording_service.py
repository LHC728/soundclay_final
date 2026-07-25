"""Role A: resilient recording reception and WAV production."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
import asyncio
import math
from pathlib import Path
import sys
import time
import wave

import ring_sound as sdk

from event_contract import EventPublisher, validate_session_id
from ring_command_gate import RingCommandGate
from ring_config import RingConfig


class RecordingUnavailable(RuntimeError):
    """No new recording could be received or recovered."""


class SessionConflictError(RuntimeError):
    """A session already contains a recording and must not be overwritten."""


class RecordingQualityError(RuntimeError):
    """A decoded recording is too short or too quiet for the P0 flow."""

    def __init__(self, code: str, message: str, recommended_action: str) -> None:
        super().__init__(message)
        self.code = code
        self.recommended_action = recommended_action


@dataclass(frozen=True)
class WavQuality:
    duration_ms: int
    rms_dbfs: float
    speech_activity_ratio: float
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AudioReady:
    session_id: str
    file_index: int
    raw_path: Path
    wav_path: Path
    duration_ms: int
    record_time: int
    recovered: bool
    rms_dbfs: float | None = None
    speech_activity_ratio: float | None = None
    warnings: tuple[str, ...] = ()

    def payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "sessionId": self.session_id,
            "fileIndex": self.file_index,
            "rawPath": str(self.raw_path.resolve()),
            "wavPath": str(self.wav_path.resolve()),
            "durationMs": self.duration_ms,
            "recordTime": self.record_time,
            "recovered": self.recovered,
        }
        if self.rms_dbfs is not None:
            payload["rmsDbfs"] = self.rms_dbfs
        if self.speech_activity_ratio is not None:
            payload["speechActivityRatio"] = self.speech_activity_ratio
        if self.warnings:
            payload["warnings"] = list(self.warnings)
        return payload


class RingRecordingService:
    def __init__(
        self,
        client: sdk.RingSoundClient,
        config: RingConfig,
        publisher: EventPublisher,
        command_lock: RingCommandGate | asyncio.Lock,
    ) -> None:
        self.client = client
        self.config = config
        self.publisher = publisher
        self.command_lock = command_lock
        self._audio_lock = asyncio.Lock()
        self.last_baseline_count: int | None = None

    async def arm_recording(
        self,
        session_id: str,
        *,
        timeout_s: float | None = None,
        baseline_count: int | None = None,
    ) -> AudioReady:
        """Arm before the user records, then receive or recover one file."""
        validate_session_id(session_id)
        timeout = (
            self.config.recording_timeout_s if timeout_s is None else timeout_s
        )
        session_dir = self.publisher.session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        self._assert_empty_recording_targets(session_dir)

        async with self._audio_lock:
            if baseline_count is None:
                async with self.command_lock:
                    baseline_count = await sdk.get_audio_file_count(self.client)
            self.last_baseline_count = baseline_count
            await self.publisher.emit(
                "status",
                {
                    "sessionId": session_id,
                    "ringConnected": self.client.is_connected,
                    "phase": "recording_armed",
                    "modeHint": "recording_expected",
                    "audioCountBefore": baseline_count,
                    "message": "长按戒指说话，完成后松开",
                },
            )

            recovered = False
            record_time = int(time.time())
            try:
                file_index, raw_audio = await sdk.receive_auto_audio_file(
                    self.client,
                    timeout_s=timeout,
                )
            except (sdk.TimeoutError, sdk.ProtocolError) as auto_error:
                await self.publisher.emit(
                    "error",
                    {
                        "sessionId": session_id,
                        "code": "AUTO_AUDIO_MISSED",
                        "phase": "recording",
                        "message": str(auto_error),
                        "recoverable": True,
                        "recommendedAction": "正在查询戒指录音并尝试 quick download",
                    },
                )
                async with self.command_lock:
                    current_count = await sdk.get_audio_file_count(self.client)
                if current_count <= baseline_count or current_count <= 0:
                    raise RecordingUnavailable(
                        "没有检测到新录音；请确认戒指处于录音模式后重试"
                    ) from auto_error
                file_index = current_count - 1
                async with self.command_lock:
                    info, raw_audio = await sdk.download_audio_file(
                        self.client,
                        timeout_s=timeout,
                        file_index=file_index,
                        quick=True,
                    )
                record_time = info.record_time
                recovered = True

            ready = await self._save_and_validate(
                session_id=session_id,
                file_index=file_index,
                raw_audio=raw_audio,
                record_time=record_time,
                recovered=recovered,
            )
            await self.publisher.emit("audio_ready", ready.payload())
            return ready

    async def download_latest(
        self,
        session_id: str,
        *,
        file_count: int | None = None,
    ) -> AudioReady:
        """Explicit operator recovery: quick-download the newest stored file."""
        validate_session_id(session_id)
        session_dir = self.publisher.session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        self._assert_empty_recording_targets(session_dir)

        async with self._audio_lock:
            count = file_count
            if count is None:
                async with self.command_lock:
                    count = await sdk.get_audio_file_count(
                        self.client,
                        timeout_s=self.config.command_timeout_s,
                    )
            if count <= 0:
                raise RecordingUnavailable("戒指中没有可补取的录音")
            file_index = count - 1
            async with self.command_lock:
                info, raw_audio = await sdk.download_audio_file(
                    self.client,
                    file_index=file_index,
                    timeout_s=self.config.recording_timeout_s,
                    quick=True,
                )
            ready = await self._save_and_validate(
                session_id=session_id,
                file_index=file_index,
                raw_audio=raw_audio,
                record_time=info.record_time,
                recovered=True,
            )
            await self.publisher.emit("audio_ready", ready.payload())
            return ready

    def _assert_empty_recording_targets(self, session_dir: Path) -> None:
        targets = (
            session_dir / "ring_raw.bin",
            session_dir / "original.bin",
            session_dir / "original.wav",
        )
        existing = [str(path) for path in targets if path.exists()]
        if existing:
            raise SessionConflictError(
                "session recording files already exist: " + ", ".join(existing)
            )

    async def _save_and_validate(
        self,
        *,
        session_id: str,
        file_index: int,
        raw_audio: bytes,
        record_time: int,
        recovered: bool,
    ) -> AudioReady:
        session_dir = self.publisher.session_dir(session_id)
        output_path = session_dir / "original.wav"
        temporary_raw_path = session_dir / "original.bin"
        raw_path = session_dir / "ring_raw.bin"

        try:
            bundle = await asyncio.to_thread(
                sdk.save_audio_bundle,
                file_index=file_index,
                data=raw_audio,
                metadata={"record_time": record_time},
                output_path=output_path,
                ffmpeg_path=self.config.ffmpeg_path,
            )
        except Exception:
            if temporary_raw_path.exists() and not raw_path.exists():
                temporary_raw_path.replace(raw_path)
            raise

        if bundle.raw_path != raw_path:
            if raw_path.exists():
                raise SessionConflictError(f"refusing to overwrite {raw_path}")
            bundle.raw_path.replace(raw_path)

        quality = await asyncio.to_thread(self._validate_wav, bundle.play_path)
        if quality.warnings:
            await self.publisher.emit(
                "status",
                {
                    "sessionId": session_id,
                    "ringConnected": self.client.is_connected,
                    "phase": "recording_length_warning",
                    "modeHint": "recording_verified",
                    "durationMs": quality.duration_ms,
                    "warnings": list(quality.warnings),
                    "message": "录音已保存，但建议将情绪自述控制在 3–8 秒",
                },
            )
        return AudioReady(
            session_id=session_id,
            file_index=file_index,
            raw_path=raw_path,
            wav_path=bundle.play_path,
            duration_ms=quality.duration_ms,
            record_time=record_time,
            recovered=recovered,
            rms_dbfs=quality.rms_dbfs,
            speech_activity_ratio=quality.speech_activity_ratio,
            warnings=quality.warnings,
        )

    def _validate_wav(self, path: Path) -> WavQuality:
        if not path.exists() or path.stat().st_size <= 44:
            raise sdk.AudioDecodeError(f"decoded WAV is empty or missing: {path}")
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frames = wav.getnframes()
            pcm_bytes = wav.readframes(frames)
        if (channels, sample_width, sample_rate) != (1, 2, 16000):
            raise sdk.AudioDecodeError(
                "unexpected WAV format: "
                f"channels={channels}, sample_width={sample_width}, "
                f"sample_rate={sample_rate}"
            )
        if frames <= 0:
            raise sdk.AudioDecodeError("decoded WAV contains no audio frames")

        duration_ms = round(frames / sample_rate * 1000)
        samples = array("h")
        samples.frombytes(pcm_bytes)
        if sys.byteorder == "big":
            samples.byteswap()
        if not samples:
            raise sdk.AudioDecodeError("decoded WAV contains no PCM samples")

        mean_square = sum(sample * sample for sample in samples) / len(samples)
        rms = math.sqrt(mean_square)
        rms_dbfs = (
            -float("inf")
            if rms <= 0
            else 20.0 * math.log10(rms / 32768.0)
        )
        rounded_rms_dbfs = (
            -120.0 if not math.isfinite(rms_dbfs) else round(rms_dbfs, 2)
        )
        frame_size = max(1, round(sample_rate * 0.020))
        frame_count = len(samples) // frame_size
        active_frame_count = 0
        for frame_index in range(frame_count):
            start = frame_index * frame_size
            stop = start + frame_size
            frame = samples[start:stop]
            frame_mean_square = (
                sum(sample * sample for sample in frame) / frame_size
            )
            frame_rms = math.sqrt(frame_mean_square)
            frame_dbfs = (
                -float("inf")
                if frame_rms <= 0
                else 20.0 * math.log10(frame_rms / 32768.0)
            )
            if frame_dbfs >= self.config.recording_speech_frame_dbfs:
                active_frame_count += 1
        speech_activity_ratio = (
            active_frame_count / frame_count if frame_count else 0.0
        )
        rounded_speech_activity_ratio = round(speech_activity_ratio, 4)

        minimum_ms = round(self.config.recording_min_duration_s * 1000)
        maximum_ms = round(self.config.recording_max_duration_s * 1000)
        if duration_ms < minimum_ms:
            raise RecordingQualityError(
                "RECORDING_TOO_SHORT",
                (
                    f"录音只有 {duration_ms / 1000:.1f} 秒，"
                    f"至少需要 {self.config.recording_min_duration_s:g} 秒"
                ),
                "请使用新的 session，长按戒指说满 3–8 秒后再松开",
            )
        if speech_activity_ratio < self.config.recording_min_speech_ratio:
            raise RecordingQualityError(
                "RECORDING_SILENT",
                (
                    "没有检测到足够的有效语音"
                    f"（有效帧 {speech_activity_ratio:.1%}，"
                    f"最低要求 {self.config.recording_min_speech_ratio:.0%}；"
                    f"整段 RMS {rounded_rms_dbfs:.2f} dBFS）"
                ),
                "请靠近戒指麦克风正常说话，并使用新的 session 重试",
            )

        warnings: tuple[str, ...] = ()
        if duration_ms > maximum_ms:
            warnings = (
                (
                    f"录音时长 {duration_ms / 1000:.1f} 秒超过建议的 "
                    f"{self.config.recording_max_duration_s:g} 秒"
                ),
            )
        return WavQuality(
            duration_ms=duration_ms,
            rms_dbfs=rounded_rms_dbfs,
            speech_activity_ratio=rounded_speech_activity_ratio,
            warnings=warnings,
        )

