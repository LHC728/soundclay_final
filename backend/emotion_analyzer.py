from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from schemas import AudioFeatures, Emotion, EmotionResult


# Weighted phrases are intentionally local and deterministic.  Longer, more
# specific phrases carry more evidence than isolated words, which keeps this
# fast enough to run synchronously after local STT while handling common
# Mandarin phrasing more accurately than a flat keyword count.
_CUES: dict[Emotion, tuple[tuple[str, float], ...]] = {
    Emotion.JOY: (
        ("终于成功", 3.0), ("太好了", 2.8), ("特别开心", 2.8),
        ("很开心", 2.5), ("开心", 2.1), ("高兴", 2.1), ("兴奋", 2.0),
        ("快乐", 2.0), ("幸福", 2.0), ("满足", 1.7), ("顺利", 1.6),
        ("期待", 1.5), ("喜欢", 1.3), ("成功", 1.5),
        ("delighted", 2.5), ("excited", 2.1), ("happy", 2.1),
        ("joy", 2.0), ("relieved", 1.7), ("great", 1.4),
    ),
    Emotion.ANGER: (
        ("气死我了", 3.2), ("受够了", 2.8), ("太过分", 2.7),
        ("特别生气", 2.8), ("很生气", 2.5), ("不公平", 2.2),
        ("生气", 2.2), ("愤怒", 2.5), ("火大", 2.4), ("恼火", 2.2),
        ("烦死", 2.5), ("很烦", 1.9), ("讨厌", 1.7), ("愤慨", 2.2),
        ("furious", 2.8), ("angry", 2.2), ("frustrated", 2.0),
        ("annoyed", 1.9), ("unfair", 1.8),
    ),
    Emotion.SADNESS: (
        ("心里很难受", 3.0), ("没有意义", 2.7), ("特别失落", 2.7),
        ("想哭", 2.5), ("难过", 2.2), ("伤心", 2.4), ("失落", 2.1),
        ("孤独", 2.1), ("低落", 2.0), ("遗憾", 1.7), ("离开", 1.3),
        ("失败", 1.5), ("委屈", 2.0), ("舍不得", 1.8),
        ("heartbroken", 2.8), ("lonely", 2.2), ("sad", 2.2),
        ("unhappy", 1.9), ("disappointed", 1.9), ("cry", 1.8),
    ),
    Emotion.ANXIETY: (
        ("脑子停不下来", 3.0), ("睡不着", 2.7), ("时间不够", 2.5),
        ("来不及", 2.5), ("怎么办", 2.1), ("特别担心", 2.8),
        ("很担心", 2.5), ("紧张", 2.2), ("担心", 2.2), ("焦虑", 2.5),
        ("害怕", 2.2), ("不安", 2.1), ("压力", 1.8), ("恐慌", 2.6),
        ("忐忑", 2.1), ("着急", 2.1),
        ("anxious", 2.5), ("worried", 2.3), ("nervous", 2.2),
        ("afraid", 2.2), ("stressed", 2.0), ("panic", 2.6),
    ),
    Emotion.NEUTRAL_MIXED: (
        ("说不上来", 2.3), ("没什么感觉", 2.4), ("心情复杂", 2.4),
        ("五味杂陈", 2.6), ("比较平静", 2.2), ("很平静", 2.3),
        ("平静", 1.8), ("还好", 1.5), ("一般", 1.4), ("普通", 1.3),
        ("mixed feelings", 2.5), ("not sure how i feel", 2.5),
        ("calm", 1.9), ("neutral", 1.8), ("okay", 1.3),
    ),
}

_NEGATIONS = (
    "并不是", "并不", "不是", "不太", "没有", "没", "不",
    "not", "never", "no", "don't", "dont", "isn't", "isnt",
    "wasn't", "wasnt", "hardly",
)
_INTENSIFIERS: tuple[tuple[str, float], ...] = (
    ("极其", 1.45), ("非常", 1.40), ("特别", 1.35), ("真的", 1.25),
    ("十分", 1.30), ("太", 1.25), ("很", 1.15),
    ("extremely", 1.45), ("absolutely", 1.40), ("very", 1.30),
    ("really", 1.20), ("so", 1.15),
)
_DIMINISHERS: tuple[tuple[str, float], ...] = (
    ("有一点", 0.72), ("有点", 0.75), ("有些", 0.78), ("稍微", 0.72),
    ("一点", 0.80), ("slightly", 0.72), ("a little", 0.75),
    ("a bit", 0.78), ("somewhat", 0.80),
)
_CONTRAST = re.compile(r"但是|不过|然而|可是|只是|但|\bbut\b|\bhowever\b|\byet\b", re.I)
_EMOTIONS = tuple(Emotion)


@dataclass(frozen=True)
class LocalEmotionEvidence:
    result: EmotionResult
    text_scores: dict[str, float]
    acoustic_scores: dict[str, float]
    local_scores: dict[str, float]
    text_reliability: float
    acoustic_reliability: float


def _context_multiplier(text: str, start: int, contrast_at: int) -> tuple[float, bool]:
    before = text[max(0, start - 24):start]
    compact_before = re.sub(r"\s+", " ", before)
    tail = compact_before[-18:]
    negation_pattern = "|".join(re.escape(term) for term in _NEGATIONS)
    negated = bool(re.search(
        rf"(?:{negation_pattern})(?:\s*(?:很|太|真的|really|very))?\s*$",
        tail,
        re.I,
    ))
    if negated:
        return 0.0, True

    multiplier = 1.0
    for term, value in _INTENSIFIERS:
        if term in compact_before[-12:]:
            multiplier = max(multiplier, value)
    for term, value in _DIMINISHERS:
        if term in compact_before[-12:]:
            multiplier = min(multiplier, value)

    # In “虽然……但是……” constructions, the clause after the last contrast
    # is normally the speaker's conclusion and deserves more weight.
    if contrast_at >= 0:
        multiplier *= 1.28 if start > contrast_at else 0.78
    multiplier *= 1.0 + 0.18 * (start / max(1, len(text)))
    return multiplier, False


def _acoustic_evidence(
    features: AudioFeatures | None,
) -> tuple[defaultdict[Emotion, float], float]:
    scores: defaultdict[Emotion, float] = defaultdict(float)
    if features is None or features.volume <= 0.005:
        return scores, 0.0

    volume = features.volume
    pitch = features.pitch
    brightness = features.brightness
    high_volume = max(0.0, volume - 0.55)
    high_pitch = max(0.0, pitch - 0.55)
    high_brightness = max(0.0, brightness - 0.55)

    # Acoustic evidence is deliberately weaker than one clear textual phrase.
    # It is most useful when the transcript is short or semantically ambiguous.
    scores[Emotion.JOY] += 1.8 * (
        high_volume * 0.55 + high_pitch * 0.50 + high_brightness * 1.20
    )
    scores[Emotion.ANGER] += 1.8 * (
        high_volume * 1.20
        + high_pitch * 0.35
        + max(0.0, 0.55 - brightness) * 0.65
    )
    scores[Emotion.SADNESS] += 1.8 * (
        max(0.0, 0.48 - volume) * 0.80
        + max(0.0, 0.45 - pitch) * 0.70
        + max(0.0, 0.50 - brightness) * 0.80
    )
    scores[Emotion.ANXIETY] += 1.8 * (
        high_pitch * 0.95
        + high_brightness * 0.75
        + max(0.0, 0.58 - volume) * 0.20
    )
    center_distance = (
        abs(volume - 0.45) + abs(pitch - 0.45) + abs(brightness - 0.45)
    ) / 3.0
    scores[Emotion.NEUTRAL_MIXED] += max(0.0, 0.45 - center_distance) * 1.15
    reliability = min(
        1.0,
        0.25
        + min(volume, 0.75) * 0.45
        + (0.18 if pitch > 0.0 else 0.0)
        + min(brightness, 0.8) * 0.15,
    )
    return scores, reliability


def _probabilities(scores: dict[Emotion, float]) -> dict[str, float]:
    adjusted = {
        emotion: max(0.0, float(scores.get(emotion, 0.0)))
        + (0.08 if emotion == Emotion.NEUTRAL_MIXED else 0.025)
        for emotion in _EMOTIONS
    }
    total = sum(adjusted.values())
    return {emotion.value: adjusted[emotion] / total for emotion in _EMOTIONS}


def _rank(scores: dict[str, float]) -> list[tuple[str, float]]:
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def _normalize_named(scores: dict[str, float]) -> dict[str, float]:
    clean = {emotion.value: max(0.0, float(scores.get(emotion.value, 0.0))) for emotion in _EMOTIONS}
    total = sum(clean.values()) or 1.0
    return {name: value / total for name, value in clean.items()}


def analyze_emotion_evidence(
    text: str,
    features: AudioFeatures | None = None,
) -> LocalEmotionEvidence:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    if not normalized:
        result = EmotionResult(
            emotion=Emotion.NEUTRAL_MIXED,
            confidence=0.50,
            reason="没有可用于分类的转写文字。",
        )
        empty_scores = _probabilities({})
        return LocalEmotionEvidence(
            result=result,
            text_scores=empty_scores,
            acoustic_scores=empty_scores,
            local_scores=empty_scores,
            text_reliability=0.0,
            acoustic_reliability=0.0,
        )

    contrast_matches = list(_CONTRAST.finditer(normalized))
    contrast_at = contrast_matches[-1].start() if contrast_matches else -1
    text_raw: defaultdict[Emotion, float] = defaultdict(float)
    matched: defaultdict[Emotion, list[str]] = defaultdict(list)

    for emotion, cues in _CUES.items():
        occupied: list[tuple[int, int]] = []
        # Long phrases run first so “特别开心” does not also count “开心”.
        for phrase, weight in sorted(cues, key=lambda item: len(item[0]), reverse=True):
            for occurrence in re.finditer(re.escape(phrase), normalized):
                span = occurrence.span()
                if any(span[0] < end and span[1] > start for start, end in occupied):
                    continue
                multiplier, negated = _context_multiplier(normalized, span[0], contrast_at)
                occupied.append(span)
                if negated:
                    continue
                text_raw[emotion] += weight * multiplier
                if phrase not in matched[emotion]:
                    matched[emotion].append(phrase)

    acoustic_raw, acoustic_reliability = _acoustic_evidence(features)
    combined_raw: defaultdict[Emotion, float] = defaultdict(float)
    for emotion in _EMOTIONS:
        combined_raw[emotion] = text_raw[emotion] + acoustic_raw[emotion]
    acoustic_used = acoustic_reliability > 0.0
    acoustic_reason = (
        f"；声学特征 volume={features.volume:.3f}、pitch={features.pitch:.3f}、"
        f"brightness={features.brightness:.3f}"
        if acoustic_used and features is not None
        else ""
    )

    text_scores = _probabilities(text_raw)
    acoustic_scores = _probabilities(acoustic_raw)
    local_scores = _probabilities(combined_raw)
    ranked = _rank(local_scores)
    top_emotion = Emotion(ranked[0][0])
    top_probability = ranked[0][1]
    second_probability = ranked[1][1]
    total_text = sum(text_raw.values())
    text_reliability = min(1.0, total_text / 3.5)

    if total_text <= 0.0 and not acoustic_used:
        confidence = 0.66 if text_raw[Emotion.NEUTRAL_MIXED] > 0 else 0.55
        cues = matched[Emotion.NEUTRAL_MIXED][:3]
        reason = f"识别到平静或混合表达：{'、'.join(cues)}。" if cues else "未发现足够明确的单一情绪线索。"
        result = EmotionResult(emotion=Emotion.NEUTRAL_MIXED, confidence=confidence, reason=reason)
        return LocalEmotionEvidence(
            result=result,
            text_scores=text_scores,
            acoustic_scores=acoustic_scores,
            local_scores=local_scores,
            text_reliability=text_reliability,
            acoustic_reliability=acoustic_reliability,
        )

    explicit_mixed = (
        (
            text_raw[Emotion.NEUTRAL_MIXED] > 0.0
            and text_raw[Emotion.NEUTRAL_MIXED] >= max(text_raw.values()) * 0.92
        )
        or (ranked[1][1] >= ranked[0][1] - 0.08 and total_text >= 1.5)
    )
    if explicit_mixed:
        evidence = []
        for emotion_name, _ in ranked[:2]:
            evidence.extend(matched[Emotion(emotion_name)][:1])
        evidence.extend(matched[Emotion.NEUTRAL_MIXED][:1])
        result = EmotionResult(
            emotion=Emotion.NEUTRAL_MIXED,
            confidence=min(0.82, 0.58 + top_probability * 0.22),
            reason=f"同时识别到多种或混合线索：{'、'.join(evidence[:3]) or '声学表现接近中性'}{acoustic_reason}。",
        )
        local_scores = _normalize_named({
            **local_scores,
            Emotion.NEUTRAL_MIXED.value: max(
                local_scores[Emotion.NEUTRAL_MIXED.value],
                top_probability,
            ),
        })
    else:
        margin = max(0.0, top_probability - second_probability)
        confidence = min(0.96, 0.52 + top_probability * 0.34 + margin * 0.55)
        punctuation_boost = min(0.03, (normalized.count("!") + normalized.count("！")) * 0.01)
        confidence = min(0.96, confidence + punctuation_boost)
        text_evidence = "、".join(matched[top_emotion][:3]) or "文本语义较弱"
        result = EmotionResult(
            emotion=top_emotion,
            confidence=confidence,
            reason=f"本地融合依据：{text_evidence}{acoustic_reason}。",
        )

    return LocalEmotionEvidence(
        result=result,
        text_scores=text_scores,
        acoustic_scores=acoustic_scores,
        local_scores=local_scores,
        text_reliability=text_reliability,
        acoustic_reliability=acoustic_reliability,
    )


def analyze_emotion_local(
    text: str,
    features: AudioFeatures | None = None,
) -> EmotionResult:
    return analyze_emotion_evidence(text, features).result
