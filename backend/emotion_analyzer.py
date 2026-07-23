from __future__ import annotations

from schemas import Emotion, EmotionResult


_KEYWORDS: dict[Emotion, tuple[str, ...]] = {
    Emotion.JOY: (
        "开心",
        "高兴",
        "兴奋",
        "快乐",
        "终于成功",
        "期待",
        "幸福",
        "满足",
        "顺利",
        "喜欢",
        "happy",
        "joy",
        "excited",
        "delighted",
    ),
    Emotion.ANGER: (
        "生气",
        "愤怒",
        "烦",
        "气死",
        "受够",
        "不公平",
        "讨厌",
        "一直出错",
        "恼火",
        "angry",
        "furious",
        "annoyed",
        "frustrated",
    ),
    Emotion.SADNESS: (
        "难过",
        "伤心",
        "失落",
        "想哭",
        "孤独",
        "低落",
        "遗憾",
        "离开",
        "失败",
        "没有意义",
        "sad",
        "lonely",
        "heartbroken",
        "unhappy",
    ),
    Emotion.ANXIETY: (
        "紧张",
        "担心",
        "焦虑",
        "害怕",
        "不安",
        "来不及",
        "压力",
        "怎么办",
        "睡不着",
        "脑子停不下来",
        "anxious",
        "worried",
        "nervous",
        "afraid",
    ),
}


def analyze_emotion_local(text: str) -> EmotionResult:
    normalized = text.strip().lower()
    scores = {
        emotion: sum(1 for word in words if word in normalized)
        for emotion, words in _KEYWORDS.items()
    }
    best_emotion = max(scores, key=scores.get)
    best_score = scores[best_emotion]

    if best_score == 0:
        return EmotionResult(
            emotion=Emotion.NEUTRAL_MIXED,
            confidence=0.55,
            reason=(
                "No single expressed emotion was clear enough in the transcript; "
                "the user should confirm or correct the label."
            ),
        )

    confidence = min(0.62 + best_score * 0.10, 0.92)
    matched = [word for word in _KEYWORDS[best_emotion] if word in normalized][:3]
    return EmotionResult(
        emotion=best_emotion,
        confidence=confidence,
        reason=(
            f"Matched expressed-emotion cues: {', '.join(matched)}. "
            "This is an initial creative classification for user confirmation."
        ),
    )
