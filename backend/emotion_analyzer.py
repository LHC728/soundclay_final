from __future__ import annotations

from schemas import Emotion, EmotionResult


_KEYWORDS: dict[Emotion, tuple[str, ...]] = {
    Emotion.JOY: (
        "开心", "高兴", "兴奋", "快乐", "终于成功", "太棒", "期待",
        "幸福", "满足", "顺利", "喜欢",
    ),
    Emotion.ANGER: (
        "生气", "愤怒", "烦", "气死", "受够", "不公平", "讨厌",
        "一直出错", "崩溃", "恼火",
    ),
    Emotion.SADNESS: (
        "难过", "伤心", "失落", "想哭", "孤独", "低落", "遗憾",
        "离开", "失败", "没有意义",
    ),
    Emotion.ANXIETY: (
        "紧张", "担心", "焦虑", "害怕", "不安", "来不及", "压力",
        "怎么办", "睡不着", "脑子停不下来",
    ),
}


def analyze_emotion_local(text: str) -> EmotionResult:
    normalized = text.strip().lower()
    scores: dict[Emotion, int] = {}

    for emotion, words in _KEYWORDS.items():
        scores[emotion] = sum(1 for word in words if word in normalized)

    best_emotion = max(scores, key=scores.get)
    best_score = scores[best_emotion]

    if best_score == 0:
        return EmotionResult(
            emotion=Emotion.NEUTRAL_MIXED,
            confidence=0.55,
            reason="文本中没有出现足够明确的单一情绪表达，请用户确认或修改。",
        )

    confidence = min(0.62 + best_score * 0.10, 0.92)
    matched = [word for word in _KEYWORDS[best_emotion] if word in normalized][:3]
    return EmotionResult(
        emotion=best_emotion,
        confidence=confidence,
        reason=f"检测到明确表达：{', '.join(matched)}。结果仅作为用户确认前的初步判断。",
    )
