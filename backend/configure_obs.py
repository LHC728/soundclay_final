"""Configure the active OBS scene for local SoundClay process recording."""

from __future__ import annotations

import asyncio
import json

from obs_adapter import ensure_soundclay_sources


def main() -> None:
    result = asyncio.run(ensure_soundclay_sources())
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
