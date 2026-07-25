from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, replace

from emotion_analyzer import LocalEmotionEvidence, analyze_emotion_evidence
from schemas import AudioFeatures, Emotion, EmotionResult


_EMOTION_NAMES = tuple(emotion.value for emotion in Emotion)
_CACHE_LIMIT = 256
_CACHE: OrderedDict[str, "EmotionDecision"] = OrderedDict()
_STATE_LOCK = threading.Lock()
_CONSECUTIVE_FAILURES = 0
_CIRCUIT_OPEN_UNTIL = 0.0


@dataclass(frozen=True)
class GlmEmotionResult:
    scores: dict[str, float]
    reason: str


@dataclass(frozen=True)
class EmotionDecision:
    result: EmotionResult
    scores: dict[str, float]
    local_scores: dict[str, float]
    weights: dict[str, float]
    provider: str
    timing_ms: float
    warning: str | None = None
    cache_hit: bool = False


def _float_setting(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    if not math.isfinite(value):
        return default
    return max(minimum, min(maximum, value))


def _integer_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _extract_json_object(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("GLM response did not contain a JSON object")
    value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("GLM response JSON must be an object")
    return value


def _normalize_scores(raw: object) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise ValueError("scores must be an object")
    clean: dict[str, float] = {}
    for name in _EMOTION_NAMES:
        value = raw.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"scores.{name} must be a number")
        number = float(value)
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            raise ValueError(f"scores.{name} must be finite and between 0 and 1")
        clean[name] = number
    total = sum(clean.values())
    if total <= 0.0:
        raise ValueError("scores must contain positive evidence")
    return {name: value / total for name, value in clean.items()}


def _legacy_scores(value: dict) -> dict[str, float]:
    result = EmotionResult.model_validate(value)
    remainder = max(0.0, 1.0 - result.confidence) / 4.0
    return {
        name: result.confidence if name == result.emotion.value else remainder
        for name in _EMOTION_NAMES
    }


def _parse_glm_content(content: str) -> GlmEmotionResult:
    value = _extract_json_object(content)
    scores = _normalize_scores(value["scores"]) if "scores" in value else _legacy_scores(value)
    reason = str(value.get("reason", "GLM 完成五类概率判断。"))
    return GlmEmotionResult(scores=scores, reason=reason.strip()[:300])


def _request_glm(
    transcript: str,
    features: AudioFeatures,
    local: LocalEmotionEvidence,
    *,
    api_key: str,
    base_url: str,
    model: str,
    timeout_seconds: float,
) -> GlmEmotionResult:
    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    prompt = {
        "task": "Classify only the emotion expressed by the speech, not a hidden mental state.",
        "allowed_emotions": list(_EMOTION_NAMES),
        "transcript": transcript,
        "normalized_audio_features": features.model_dump(),
        "feature_notes": {
            "volume": "normalized RMS loudness, 0 to 1",
            "pitch": "normalized fundamental frequency, 0 to 1; zero may mean unavailable",
            "brightness": "normalized spectral centroid, 0 to 1",
        },
        "local_evidence": {
            "text_scores": local.text_scores,
            "acoustic_scores": local.acoustic_scores,
            "combined_scores": local.local_scores,
            "text_reliability": local.text_reliability,
            "acoustic_reliability": local.acoustic_reliability,
        },
        "output_contract": {
            "scores": {name: "number from 0 to 1" for name in _EMOTION_NAMES},
            "reason": "one concise Simplified Chinese sentence using text and audio evidence",
        },
        "rules": [
            "All five scores are required and should sum to 1.",
            "Use neutral_mixed when evidence conflicts or no emotion dominates.",
            "Do not infer diagnosis, personality, or hidden mental state.",
        ],
    }
    body = json.dumps(
        {
            "model": model,
            "temperature": 0,
            "max_tokens": 220,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are SoundClay's calibrated expressed-emotion scorer. "
                        "Return exactly one JSON object and no markdown."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(1_000_001)
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise RuntimeError(f"GLM request failed: {exc}") from exc
    if len(raw) > 1_000_000:
        raise RuntimeError("GLM response exceeded the 1 MB safety limit")
    try:
        envelope = json.loads(raw.decode("utf-8"))
        content = envelope["choices"][0]["message"]["content"]
        return _parse_glm_content(content)
    except (AttributeError, KeyError, IndexError, TypeError, UnicodeError, ValueError) as exc:
        raise RuntimeError(f"GLM returned an invalid emotion response: {exc}") from exc


def _normalized_weights(local: LocalEmotionEvidence, *, include_glm: bool) -> dict[str, float]:
    text = 0.45 * max(0.25, local.text_reliability)
    acoustic = 0.20 * local.acoustic_reliability
    glm = 0.35 if include_glm else 0.0
    if local.text_reliability < 0.25 and include_glm:
        glm += 0.10
    total = text + acoustic + glm
    return {
        "text": text / total,
        "acoustic": acoustic / total,
        "glm": glm / total,
    }


def _local_decision(
    local: LocalEmotionEvidence,
    started: float,
    *,
    warning: str | None = None,
) -> EmotionDecision:
    return EmotionDecision(
        result=local.result,
        scores=local.local_scores,
        local_scores=local.local_scores,
        weights=_normalized_weights(local, include_glm=False),
        provider="local_fusion",
        timing_ms=round((time.perf_counter() - started) * 1000, 2),
        warning=warning,
    )


def _sensevoice_decision(
    local: LocalEmotionEvidence,
    started: float,
    speech_emotion: Emotion,
    speech_emotion_tag: str | None,
) -> EmotionDecision:
    """Use SenseVoice directly, with strong-text correction for neutral audio."""
    text_ranked = sorted(local.text_scores.items(), key=lambda item: item[1], reverse=True)
    text_name, text_score = text_ranked[0]
    text_margin = text_score - text_ranked[1][1]
    text_emotion = Emotion(text_name)
    use_text_override = (
        speech_emotion == Emotion.NEUTRAL_MIXED
        and text_emotion != Emotion.NEUTRAL_MIXED
        and text_score >= 0.72
        and text_margin >= 0.30
    )
    decided_emotion = text_emotion if use_text_override else speech_emotion
    scores = {
        name: (
            local.text_scores[name]
            if use_text_override
            else 1.0 if name == decided_emotion.value else 0.0
        )
        for name in _EMOTION_NAMES
    }
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_name, top_score = ranked[0]
    margin = top_score - ranked[1][1]
    confidence = min(0.94, max(0.60, 0.50 + top_score * 0.28 + margin * 0.32))
    label = speech_emotion_tag or speech_emotion.value.upper()
    if use_text_override:
        reason = (
            f"SenseVoice speech-emotion tag {label} was neutral; strong text "
            f"evidence automatically selected {decided_emotion.value}."
        )
        provider = "sensevoice:text_override"
        weights = {"text": 1.0, "acoustic": 0.0, "glm": 0.0, "sensevoice": 0.0, "local": 0.0}
    else:
        reason = (
            f"SenseVoice speech-emotion tag {label} mapped to "
            f"{decided_emotion.value}; the SenseVoice result is the "
            "sole emotion decision signal."
        )
        provider = "local:sensevoice"
        weights = {"text": 0.0, "acoustic": 0.0, "glm": 0.0, "sensevoice": 1.0, "local": 0.0}
    return EmotionDecision(
        result=EmotionResult(
            emotion=Emotion(top_name),
            confidence=confidence,
            reason=reason,
        ),
        scores=scores,
        local_scores=local.local_scores,
        weights=weights,
        provider=provider,
        timing_ms=round((time.perf_counter() - started) * 1000, 2),
    )


def _fuse(
    local: LocalEmotionEvidence,
    remote: GlmEmotionResult,
    features: AudioFeatures,
) -> tuple[EmotionResult, dict[str, float], dict[str, float]]:
    weights = _normalized_weights(local, include_glm=True)
    scores = {
        name: (
            local.text_scores[name] * weights["text"]
            + local.acoustic_scores[name] * weights["acoustic"]
            + remote.scores[name] * weights["glm"]
        )
        for name in _EMOTION_NAMES
    }
    scores = _normalize_scores(scores)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_name, top_score = ranked[0]
    margin = top_score - ranked[1][1]
    local_top = max(local.local_scores, key=local.local_scores.get)
    glm_top = max(remote.scores, key=remote.scores.get)
    agreement = local_top == glm_top

    # Ambiguous or unresolved disagreement is deliberately represented as
    # neutral_mixed instead of producing an unstable forced label.
    if margin < 0.12 or (not agreement and margin < 0.18):
        top_name = Emotion.NEUTRAL_MIXED.value
        scores = _normalize_scores({
            **scores,
            top_name: max(scores[top_name], top_score),
        })
        top_score = scores[top_name]
        margin = top_score - max(value for name, value in scores.items() if name != top_name)

    confidence = min(
        0.97,
        max(0.50, 0.48 + top_score * 0.34 + max(0.0, margin) * 0.65 + (0.05 if agreement else 0.0)),
    )
    result = EmotionResult(
        emotion=Emotion(top_name),
        confidence=confidence,
        reason=(
            f"{remote.reason} 声学特征 volume={features.volume:.3f}、"
            f"pitch={features.pitch:.3f}、brightness={features.brightness:.3f}；"
            f"本地与 GLM {'一致' if agreement else '存在分歧'}。"
        )[:300],
    )
    return result, scores, weights
def _cache_key(
    transcript: str,
    features: AudioFeatures,
    provider: str,
    base_url: str,
    model: str,
) -> str:
    payload = json.dumps(
        {
            "transcript": transcript,
            "features": features.model_dump(),
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "fusion_version": 2,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _get_cached(key: str, started: float) -> EmotionDecision | None:
    with _STATE_LOCK:
        decision = _CACHE.get(key)
        if decision is None:
            return None
        _CACHE.move_to_end(key)
    return replace(
        decision,
        timing_ms=round((time.perf_counter() - started) * 1000, 2),
        cache_hit=True,
    )


def _store_cached(key: str, decision: EmotionDecision) -> None:
    with _STATE_LOCK:
        _CACHE[key] = replace(decision, cache_hit=False)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)


def _circuit_is_open() -> bool:
    with _STATE_LOCK:
        return time.monotonic() < _CIRCUIT_OPEN_UNTIL


def _record_failure() -> None:
    global _CONSECUTIVE_FAILURES, _CIRCUIT_OPEN_UNTIL
    threshold = _integer_setting("EMOTION_CIRCUIT_FAILURES", 3, 1, 10)
    cooldown = _float_setting("EMOTION_CIRCUIT_SECONDS", 30.0, 1.0, 300.0)
    with _STATE_LOCK:
        _CONSECUTIVE_FAILURES += 1
        if _CONSECUTIVE_FAILURES >= threshold:
            _CIRCUIT_OPEN_UNTIL = time.monotonic() + cooldown


def _record_success() -> None:
    global _CONSECUTIVE_FAILURES, _CIRCUIT_OPEN_UNTIL
    with _STATE_LOCK:
        _CONSECUTIVE_FAILURES = 0
        _CIRCUIT_OPEN_UNTIL = 0.0


def _reset_runtime_state() -> None:
    """Clear cache/circuit state for deterministic offline tests."""
    global _CONSECUTIVE_FAILURES, _CIRCUIT_OPEN_UNTIL
    with _STATE_LOCK:
        _CACHE.clear()
        _CONSECUTIVE_FAILURES = 0
        _CIRCUIT_OPEN_UNTIL = 0.0


async def analyze_emotion(
    transcript: str,
    features: AudioFeatures,
    *,
    speech_emotion: Emotion | None = None,
    speech_emotion_tag: str | None = None,
) -> EmotionDecision:
    started = time.perf_counter()
    local = analyze_emotion_evidence(transcript, features)
    if speech_emotion is not None:
        return _sensevoice_decision(
            local,
            started,
            speech_emotion,
            speech_emotion_tag,
        )
    provider = os.getenv("EMOTION_PROVIDER", "hybrid").strip().lower() or "hybrid"
    api_key = os.getenv("EMOTION_API_KEY", "").strip()
    if provider == "local" or not api_key:
        return _local_decision(local, started)
    if provider not in {"hybrid", "glm"}:
        return _local_decision(
            local,
            started,
            warning=f"Unsupported EMOTION_PROVIDER={provider}; used local fusion.",
        )
    if _circuit_is_open():
        return _local_decision(
            local,
            started,
            warning="GLM circuit breaker is open; used local fusion.",
        )

    base_url = os.getenv("EMOTION_BASE_URL", "https://aiping.cn/api/v1").strip()
    model = os.getenv("EMOTION_MODEL", "GLM-5.2").strip() or "GLM-5.2"
    cache_key = _cache_key(transcript, features, provider, base_url, model)
    cached = _get_cached(cache_key, started)
    if cached is not None:
        return cached

    hard_timeout = _float_setting("EMOTION_TIMEOUT_SECONDS", 3.0, 1.0, 30.0)
    soft_timeout = _float_setting("EMOTION_SOFT_TIMEOUT_SECONDS", 1.5, 0.25, hard_timeout)
    try:
        remote = await asyncio.wait_for(
            asyncio.to_thread(
                _request_glm,
                transcript,
                features,
                local,
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout_seconds=hard_timeout,
            ),
            timeout=soft_timeout,
        )
    except TimeoutError:
        _record_failure()
        return _local_decision(
            local,
            started,
            warning=f"GLM exceeded the {soft_timeout:g}s decision deadline; used local fusion.",
        )
    except RuntimeError as exc:
        _record_failure()
        return _local_decision(local, started, warning=f"{exc}; used local fusion.")

    _record_success()
    result, scores, weights = _fuse(local, remote, features)
    decision = EmotionDecision(
        result=result,
        scores=scores,
        local_scores=local.local_scores,
        weights=weights,
        provider=f"hybrid:glm:{model}",
        timing_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    _store_cached(cache_key, decision)
    return decision
