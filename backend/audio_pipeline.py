from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from schemas import AudioFeatures


def _clamp01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def analyze_audio(path: str | Path) -> AudioFeatures:
    audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    if len(audio) == 0:
        return AudioFeatures()

    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio)) + 1e-12))
    volume = _clamp01(rms / 0.25)

    windowed = audio * np.hanning(len(audio))
    spectrum = np.abs(np.fft.rfft(windowed))
    frequencies = np.fft.rfftfreq(len(audio), d=1.0 / sample_rate)
    denom = float(np.sum(spectrum)) + 1e-12
    centroid = float(np.sum(frequencies * spectrum) / denom)
    brightness = _clamp01(centroid / 5000.0)

    # 轻量自相关基频估计；比赛版只需要稳定的 0–1 特征，不作为专业音高检测。
    centered = audio - np.mean(audio)
    corr = np.correlate(centered, centered, mode="full")[len(centered) - 1 :]
    min_lag = max(1, int(sample_rate / 500))
    max_lag = min(len(corr) - 1, int(sample_rate / 70))
    pitch_hz = 220.0
    if max_lag > min_lag and peak > 0.005:
        lag = min_lag + int(np.argmax(corr[min_lag:max_lag]))
        if lag > 0:
            pitch_hz = sample_rate / lag
    pitch = _clamp01((pitch_hz - 70.0) / (500.0 - 70.0))

    return AudioFeatures(volume=volume, pitch=pitch, brightness=brightness)
