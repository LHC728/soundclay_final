from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from schemas import AudioFeatures


def _clamp01(value: float) -> float:
    if not np.isfinite(value):
        return 0.0
    return float(max(0.0, min(1.0, value)))


def _analysis_window(audio: np.ndarray, sample_rate: int, seconds: float = 4.0) -> np.ndarray:
    """Return a bounded center window so spectral work stays predictable."""
    limit = max(1, int(sample_rate * seconds))
    if audio.size <= limit:
        return audio
    start = (audio.size - limit) // 2
    return audio[start : start + limit]


def _estimate_pitch(audio: np.ndarray, sample_rate: int) -> float:
    """Estimate a normalized fundamental with FFT autocorrelation (O(n log n))."""
    centered = audio.astype(np.float64, copy=False) - float(np.mean(audio))
    rms = float(np.sqrt(np.mean(centered * centered)))
    if centered.size < max(32, sample_rate // 25) or rms < 1e-4:
        return 0.0

    centered = centered * np.hanning(centered.size)
    fft_size = 1 << max(1, (2 * centered.size - 1).bit_length())
    spectrum = np.fft.rfft(centered, n=fft_size)
    correlation = np.fft.irfft(spectrum * np.conjugate(spectrum), n=fft_size)
    correlation = correlation[: centered.size]

    min_hz = 60.0
    max_hz = min(500.0, sample_rate / 2.0)
    min_lag = max(1, int(sample_rate / max_hz))
    max_lag = min(correlation.size - 1, int(sample_rate / min_hz))
    if max_lag <= min_lag or correlation[0] <= 0:
        return 0.0

    candidates = correlation[min_lag : max_lag + 1]
    lag: float = min_lag + int(np.argmax(candidates))
    clarity = float(correlation[int(lag)] / (correlation[0] + 1e-12))
    if clarity < 0.1:
        return 0.0

    lag_index = int(lag)
    if 1 <= lag_index < correlation.size - 1:
        left, middle, right = correlation[lag_index - 1 : lag_index + 2]
        denominator = left - 2.0 * middle + right
        if abs(denominator) > 1e-12:
            lag += float(0.5 * (left - right) / denominator)

    pitch_hz = sample_rate / lag
    normalized = np.log(pitch_hz / min_hz) / np.log(max_hz / min_hz)
    return _clamp01(float(normalized))


def analyze_audio(path: str | Path) -> AudioFeatures:
    audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    if sample_rate <= 0:
        raise ValueError("audio sample rate must be positive")

    mono = np.mean(audio, axis=1, dtype=np.float32)
    mono = np.nan_to_num(mono, nan=0.0, posinf=1.0, neginf=-1.0)
    if mono.size == 0:
        return AudioFeatures()

    rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float64))))
    volume = _clamp01(rms / 0.25)
    if rms < 1e-5:
        return AudioFeatures(volume=volume, pitch=0.0, brightness=0.0)

    spectral_audio = _analysis_window(mono, sample_rate)
    windowed = (spectral_audio - np.mean(spectral_audio)) * np.hanning(
        spectral_audio.size
    )
    spectrum = np.abs(np.fft.rfft(windowed))
    frequencies = np.fft.rfftfreq(windowed.size, d=1.0 / sample_rate)
    denominator = float(np.sum(spectrum)) + 1e-12
    centroid = float(np.sum(frequencies * spectrum) / denominator)
    brightness = _clamp01(
        centroid / max(1.0, min(8000.0, sample_rate / 2.0))
    )
    pitch = _estimate_pitch(spectral_audio, sample_rate)

    return AudioFeatures(volume=volume, pitch=pitch, brightness=brightness)
