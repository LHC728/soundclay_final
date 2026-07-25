"""Serialized and paced access to command/response operations."""

from __future__ import annotations

import asyncio
from types import TracebackType


class RingCommandGate:
    """An async lock that enforces spacing between hardware command groups."""

    def __init__(self, minimum_interval_s: float) -> None:
        if minimum_interval_s < 0:
            raise ValueError("minimum_interval_s must not be negative")
        self.minimum_interval_s = minimum_interval_s
        self._lock = asyncio.Lock()
        self._last_release: float | None = None

    async def __aenter__(self) -> "RingCommandGate":
        await self._lock.acquire()
        try:
            if self._last_release is not None and self.minimum_interval_s > 0:
                loop = asyncio.get_running_loop()
                remaining = self.minimum_interval_s - (
                    loop.time() - self._last_release
                )
                if remaining > 0:
                    await asyncio.sleep(remaining)
        except BaseException:
            self._lock.release()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._last_release = asyncio.get_running_loop().time()
        self._lock.release()

