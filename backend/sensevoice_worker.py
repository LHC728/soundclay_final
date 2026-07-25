from __future__ import annotations

import json
import sys
from pathlib import Path

from stt_adapter import _transcribe_sensevoice


RESULT_MARKER = "SOUNDCLAY_RESULT_JSON="


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: sensevoice_worker.py <audio.wav>", file=sys.stderr)
        return 2

    recognition = _transcribe_sensevoice(Path(sys.argv[1]))
    payload = {
        "text": recognition.text,
        "provider": recognition.provider,
        "speech_emotion": (
            recognition.speech_emotion.value if recognition.speech_emotion else None
        ),
        "raw_emotion": recognition.raw_emotion,
    }
    print(RESULT_MARKER + json.dumps(payload, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
