from __future__ import annotations

import asyncio
import importlib
import os
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Awaitable, Callable


EventSink = Callable[[dict[str, Any]], Awaitable[None]]


def _enabled_from_environment() -> bool:
    return os.getenv("SOUNDCLAY_RING_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class RingRuntimeManager:
    """Own exactly one optional RingRuntime for the FastAPI process."""

    def __init__(
        self,
        event_sink: EventSink,
        *,
        enabled: bool | None = None,
        runtime_factory: Callable[..., Any] | None = None,
        runtime_path: str | Path | None = None,
    ) -> None:
        self.event_sink = event_sink
        self.enabled = _enabled_from_environment() if enabled is None else enabled
        self.runtime_factory = runtime_factory
        self.runtime_path = runtime_path or os.getenv("SOUNDCLAY_RING_PATH")
        self.runtime: Any | None = None
        self.session_task: asyncio.Task[None] | None = None
        self.connected = False
        self.last_error: str | None = None

    def _load_runtime_factory(self) -> Callable[..., Any]:
        if self.runtime_factory is not None:
            return self.runtime_factory
        if self.runtime_path:
            resolved = Path(self.runtime_path).expanduser().resolve()
            if not resolved.is_dir():
                raise RuntimeError(f"SOUNDCLAY_RING_PATH is not a directory: {resolved}")
            path_text = str(resolved)
            if path_text not in sys.path:
                sys.path.insert(0, path_text)
        module = importlib.import_module("ring_runtime")
        factory = getattr(module, "RingRuntime", None)
        if factory is None:
            raise RuntimeError("ring_runtime.py does not export RingRuntime")
        return factory

    async def start(self) -> None:
        if not self.enabled or self.runtime is not None:
            return
        try:
            factory = self._load_runtime_factory()
            self.runtime = factory(event_sink=self.event_sink)
            await self.runtime.connect()
            self.connected = True
            self.last_error = None
            await self.runtime.get_status()
        except Exception as exc:
            self.connected = False
            self.last_error = str(exc)
            await self._emit_runtime_error("RING_CONNECT_FAILED", exc, recoverable=True)

    async def begin_session(self, session_id: str) -> None:
        if not self.enabled:
            raise RuntimeError("RingRuntime is disabled; set SOUNDCLAY_RING_ENABLED=true")
        if self.runtime is None or not self.connected:
            raise RuntimeError(self.last_error or "RingRuntime is not connected")
        if self.session_task is not None and not self.session_task.done():
            raise RuntimeError("a ring session is already running")
        self.session_task = asyncio.create_task(
            self._run_session(session_id), name=f"soundclay-ring-{session_id}"
        )

    async def _run_session(self, session_id: str) -> None:
        try:
            await self.runtime.arm_recording(session_id)
            await self.runtime.enter_motion_mode(session_id)
            await self.runtime.sculpt_until_freeze(session_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = str(exc)
            await self._emit_runtime_error("RING_SESSION_FAILED", exc, recoverable=True)

    async def close(self) -> None:
        task = self.session_task
        self.session_task = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if self.runtime is not None:
            try:
                await self.runtime.close()
            finally:
                self.runtime = None
                self.connected = False

    async def _emit_runtime_error(
        self, code: str, error: Exception, *, recoverable: bool
    ) -> None:
        await self.event_sink(
            {
                "type": "error",
                "timestamp": int(time.time() * 1000),
                "payload": {
                    "code": code,
                    "message": str(error),
                    "recoverable": recoverable,
                    "recommendedAction": (
                        "Check that the ring is charged, the phone Zilo APK is closed, "
                        "and no other Python process owns the BLE connection."
                    ),
                },
            }
        )

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "connected": self.connected,
            "sessionRunning": bool(self.session_task and not self.session_task.done()),
            "lastError": self.last_error,
            "runtimePath": str(self.runtime_path) if self.runtime_path else None,
        }
