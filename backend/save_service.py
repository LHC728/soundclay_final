from __future__ import annotations

import base64
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


def _decode_png_data_url(data_url: str) -> bytes:
    prefix = "data:image/png;base64,"
    if not data_url.startswith(prefix):
        raise ValueError("截图必须是 PNG data URL")
    return base64.b64decode(data_url[len(prefix):])


def save_work(
    works_dir: Path,
    session_data: dict[str, Any],
    original_audio: Path | None,
    output_audio: Path | None,
    screenshot_data_url: str | None,
) -> dict[str, Any]:
    works_dir.mkdir(parents=True, exist_ok=True)
    work_id = "VP-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    target = works_dir / work_id
    target.mkdir()

    files: dict[str, str] = {}

    if original_audio and original_audio.exists():
        dst = target / "original.wav"
        shutil.copy2(original_audio, dst)
        files["originalAudio"] = str(dst)

    if output_audio and output_audio.exists():
        dst = target / "output.wav"
        shutil.copy2(output_audio, dst)
        files["outputAudio"] = str(dst)

    if screenshot_data_url:
        png_path = target / "sculpture.png"
        png_path.write_bytes(_decode_png_data_url(screenshot_data_url))
        files["image"] = str(png_path)

    json_path = target / "portrait.json"
    json_path.write_text(
        json.dumps(session_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    files["metadata"] = str(json_path)

    return {"id": work_id, "files": files}
