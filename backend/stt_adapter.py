from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()


class STTError(RuntimeError):
    """语音转文字失败。"""


@lru_cache(maxsize=1)
def _get_whisper_model() -> Any:
    """
    模型只加载一次，避免每次请求重新加载。
    第一次运行时会下载模型，之后读取本地缓存。
    """
    model_name = os.getenv("WHISPER_MODEL", "base").strip()
    device = os.getenv("WHISPER_DEVICE", "cpu").strip()
    compute_type = os.getenv(
        "WHISPER_COMPUTE_TYPE",
        "int8",
    ).strip()

    try:
        from faster_whisper import WhisperModel

        return WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
        )
    except Exception as exc:
        raise STTError(f"Whisper模型加载失败：{exc}") from exc


def _transcribe_faster_whisper(audio_path: Path) -> str:
    if not audio_path.exists():
        raise STTError(f"找不到音频文件：{audio_path}")

    model = _get_whisper_model()
    language = os.getenv("WHISPER_LANGUAGE", "zh").strip()

    try:
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            task="transcribe",
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=(
                "这是一段中文情绪自述，"
                "请准确转写用户说出的完整内容。"
            ),
        )

        # segments 是生成器，必须遍历后转写才真正执行
        text = "".join(segment.text for segment in segments).strip()

    except Exception as exc:
        raise STTError(f"本地Whisper转写失败：{exc}") from exc

    if not text:
        raise STTError("没有识别到有效语音，请重新录制")

    return text


async def transcribe_audio(audio_path: str | Path) -> str:
    path = Path(audio_path)
    provider = os.getenv(
        "STT_PROVIDER",
        "mock",
    ).strip().lower()

    if provider == "mock":
        return os.getenv(
            "MOCK_TRANSCRIPT",
            "今天一直出错，我真的很烦。",
        ).strip()

    if provider in {"faster_whisper", "local_whisper"}:
        # 推理放在线程中，避免阻塞 FastAPI 事件循环
        return await asyncio.to_thread(
            _transcribe_faster_whisper,
            path,
        )

    raise STTError(f"不支持的STT_PROVIDER：{provider}")
