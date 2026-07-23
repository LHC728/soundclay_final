from __future__ import annotations

import os
from pathlib import Path


class STTError(RuntimeError):
    pass


async def transcribe_audio(audio_path: str | Path) -> str:
    """
    当前为可运行的 mock Provider。
    接真实 STT 时，只替换此函数内部，不改 server.py 的调用方式。
    """
    provider = os.getenv("STT_PROVIDER", "mock").lower()

    if provider == "mock":
        return os.getenv("MOCK_TRANSCRIPT", "今天一直出错，我真的很烦。").strip()

    raise STTError(
        f"尚未实现 STT_PROVIDER={provider}。先使用 mock，之后再接真实服务。"
    )
