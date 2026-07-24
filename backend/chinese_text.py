from __future__ import annotations

import os
from functools import lru_cache


# The native Windows converter covers the full character set used by the local
# demo.  This small fallback keeps common spoken transcripts deterministic on
# other platforms without adding a network-installed dependency.
_PHRASE_MAP = {
    "錄音": "录音",
    "現在": "现在",
    "這裡": "这里",
    "那裡": "那里",
    "裡面": "里面",
    "軟體": "软件",
    "網路": "网络",
}

_CHARACTER_MAP = str.maketrans(
    {
        "愛": "爱",
        "礙": "碍",
        "壓": "压",
        "罷": "罢",
        "辦": "办",
        "幫": "帮",
        "報": "报",
        "備": "备",
        "邊": "边",
        "變": "变",
        "標": "标",
        "別": "别",
        "賓": "宾",
        "並": "并",
        "補": "补",
        "參": "参",
        "層": "层",
        "長": "长",
        "場": "场",
        "車": "车",
        "稱": "称",
        "遲": "迟",
        "衝": "冲",
        "處": "处",
        "傳": "传",
        "創": "创",
        "錯": "错",
        "達": "达",
        "帶": "带",
        "擔": "担",
        "當": "当",
        "導": "导",
        "燈": "灯",
        "點": "点",
        "電": "电",
        "調": "调",
        "動": "动",
        "對": "对",
        "發": "发",
        "煩": "烦",
        "範": "范",
        "飛": "飞",
        "憤": "愤",
        "風": "风",
        "該": "该",
        "剛": "刚",
        "個": "个",
        "給": "给",
        "夠": "够",
        "關": "关",
        "觀": "观",
        "還": "还",
        "歡": "欢",
        "會": "会",
        "獲": "获",
        "機": "机",
        "記": "记",
        "簡": "简",
        "見": "见",
        "將": "将",
        "講": "讲",
        "進": "进",
        "緊": "紧",
        "經": "经",
        "驚": "惊",
        "覺": "觉",
        "開": "开",
        "顆": "颗",
        "塊": "块",
        "來": "来",
        "樂": "乐",
        "離": "离",
        "裡": "里",
        "連": "连",
        "慮": "虑",
        "嗎": "吗",
        "沒": "没",
        "們": "们",
        "夢": "梦",
        "難": "难",
        "腦": "脑",
        "內": "内",
        "擬": "拟",
        "您": "您",
        "啟": "启",
        "氣": "气",
        "強": "强",
        "請": "请",
        "讓": "让",
        "認": "认",
        "聲": "声",
        "實": "实",
        "時": "时",
        "識": "识",
        "輸": "输",
        "術": "术",
        "數": "数",
        "說": "说",
        "聽": "听",
        "體": "体",
        "條": "条",
        "頭": "头",
        "圖": "图",
        "團": "团",
        "萬": "万",
        "為": "为",
        "問": "问",
        "無": "无",
        "務": "务",
        "誤": "误",
        "習": "习",
        "現": "现",
        "線": "线",
        "響": "响",
        "像": "像",
        "寫": "写",
        "選": "选",
        "學": "学",
        "樣": "样",
        "應": "应",
        "憂": "忧",
        "語": "语",
        "與": "与",
        "遠": "远",
        "願": "愿",
        "雲": "云",
        "張": "张",
        "這": "这",
        "種": "种",
        "轉": "转",
        "準": "准",
        "總": "总",
        "組": "组",
        "錄": "录",
    }
)


@lru_cache(maxsize=1)
def _opencc_converter():
    """Use OpenCC when an existing local installation is available."""
    try:
        from opencc import OpenCC

        return OpenCC("t2s")
    except (ImportError, OSError, RuntimeError):
        return None


def _windows_to_simplified(text: str) -> str | None:
    if os.name != "nt":
        return None

    try:
        import ctypes
        from ctypes import wintypes

        lcmap = ctypes.windll.kernel32.LCMapStringEx
        lcmap.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.LPCWSTR,
            ctypes.c_int,
            wintypes.LPWSTR,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.LPARAM,
        ]
        lcmap.restype = ctypes.c_int
        flag = 0x02000000  # LCMAP_SIMPLIFIED_CHINESE
        size = lcmap("zh-CN", flag, text, len(text), None, 0, None, None, 0)
        if size <= 0:
            return None
        buffer = ctypes.create_unicode_buffer(size)
        written = lcmap(
            "zh-CN", flag, text, len(text), buffer, size, None, None, 0
        )
        return buffer[:written] if written > 0 else None
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def to_simplified_chinese(text: str) -> str:
    """Convert transcript text to Simplified Chinese entirely offline."""
    if not text:
        return text

    converted = text
    converter = _opencc_converter()
    if converter is not None:
        try:
            converted = converter.convert(converted)
        except (OSError, RuntimeError, ValueError):
            pass
    else:
        converted = _windows_to_simplified(converted) or converted

    for traditional, simplified in _PHRASE_MAP.items():
        converted = converted.replace(traditional, simplified)
    return converted.translate(_CHARACTER_MAP)


def normalize_transcript(text: str) -> str:
    """Return clean Simplified Chinese while leaving other scripts unchanged."""
    return to_simplified_chinese(text).strip()
