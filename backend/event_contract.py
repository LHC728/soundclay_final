"""Stable event contract shared by SoundClay roles A, B, C, and D."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
import asyncio
from dataclasses import dataclass
import inspect
import json
from pathlib import Path
import re
import time
from typing import Any


Event = dict[str, Any]
EventSink = Callable[[Event], None | Awaitable[None]]

EVENT_TYPES = frozenset(
    {
        "status",
        "audio_ready",
        "transcript_ready",
        "emotion_ready",
        "material_ready",
        "imu",
        "tiltX",
        "burst",
        "freeze",
        "saved",
        "error",
    }
)

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


@dataclass(frozen=True)
class _PersistItem:
    session_id: str
    line: str
    motion_log: bool
    committed: asyncio.Future[None] | None = None


def validate_session_id(session_id: str) -> str:
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError(
            "session_id must be 1-80 characters using letters, numbers, '.', '_' or '-'"
        )
    return session_id


def utc_timestamp_ms() -> int:
    return int(time.time() * 1000)


def make_event(
    event_type: str,
    payload: Mapping[str, Any] | None = None,
    *,
    timestamp_ms: int | None = None,
) -> Event:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unsupported event type: {event_type}")
    body = dict(payload or {})
    session_id = body.get("sessionId")
    if session_id is not None:
        validate_session_id(str(session_id))
    return {
        "type": event_type,
        "timestamp": utc_timestamp_ms() if timestamp_ms is None else timestamp_ms,
        "payload": body,
    }


def validate_event(event: Mapping[str, Any]) -> None:
    if event.get("type") not in EVENT_TYPES:
        raise ValueError(f"Unsupported event type: {event.get('type')!r}")
    if not isinstance(event.get("timestamp"), int):
        raise ValueError("event.timestamp must be an integer Unix timestamp in ms")
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("event.payload must be an object")
    session_id = payload.get("sessionId")
    if session_id is not None:
        validate_session_id(str(session_id))


class EventPublisher:
    """Emit events to C's async sink and persist per-session NDJSON."""

    def __init__(
        self,
        session_root: Path,
        sink: EventSink | None = None,
    ) -> None:
        self.session_root = session_root
        self.sink = sink
        self._persist_queue: asyncio.Queue[_PersistItem | None] = (
            asyncio.Queue()
        )
        self._writer_task: asyncio.Task[None] | None = None
        self._writer_error: BaseException | None = None
        self._batch_size = 512
        self._batch_delay_s = 0.10

    def session_dir(self, session_id: str) -> Path:
        return self.session_root / validate_session_id(session_id)

    async def emit(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timestamp_ms: int | None = None,
        motion_log: bool = False,
    ) -> Event:
        event = make_event(event_type, payload, timestamp_ms=timestamp_ms)
        await self.publish(event, motion_log=motion_log)
        return event

    async def publish(self, event: Event, *, motion_log: bool = False) -> None:
        validate_event(event)
        session_id = event["payload"].get("sessionId")
        if session_id:
            self._raise_writer_error()
            self._ensure_writer()
            line = (
                json.dumps(
                    event,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
            # IMU is the only high-frequency event. It must never await disk:
            # enqueue it and return to BLE consumption immediately. Control
            # events wait for commit so their ordering remains deterministic.
            committed = (
                None
                if event["type"] == "imu"
                else asyncio.get_running_loop().create_future()
            )
            self._persist_queue.put_nowait(
                _PersistItem(
                    session_id=str(session_id),
                    line=line,
                    motion_log=motion_log,
                    committed=committed,
                )
            )
            if committed is not None:
                await committed

        if self.sink is not None:
            result = self.sink(event)
            if inspect.isawaitable(result):
                await result

    async def flush(self) -> None:
        """Wait until every queued event has been durably appended."""

        if self._writer_task is None:
            self._raise_writer_error()
            return
        await self._persist_queue.join()
        self._raise_writer_error()

    async def close(self) -> None:
        """Flush and stop the writer; a later publish lazily restarts it."""

        writer = self._writer_task
        if writer is None:
            self._raise_writer_error()
            return
        await self.flush()
        self._persist_queue.put_nowait(None)
        await writer
        self._writer_task = None
        self._raise_writer_error()

    def _ensure_writer(self) -> None:
        if self._writer_task is not None and not self._writer_task.done():
            return
        self._writer_task = asyncio.create_task(self._writer_loop())

    def _raise_writer_error(self) -> None:
        if self._writer_error is not None:
            raise RuntimeError("event log writer failed") from self._writer_error

    async def _writer_loop(self) -> None:
        while True:
            first = await self._persist_queue.get()
            if first is None:
                self._persist_queue.task_done()
                return

            batch = [first]
            if first.committed is None:
                deadline = (
                    asyncio.get_running_loop().time()
                    + self._batch_delay_s
                )
                while len(batch) < self._batch_size:
                    try:
                        item = self._persist_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        remaining = (
                            deadline - asyncio.get_running_loop().time()
                        )
                        if remaining <= 0:
                            break
                        try:
                            item = await asyncio.wait_for(
                                self._persist_queue.get(),
                                timeout=remaining,
                            )
                        except asyncio.TimeoutError:
                            break
                    if item is None:
                        # close() always flushes before the sentinel, so this
                        # path is defensive rather than expected.
                        self._persist_queue.task_done()
                        break
                    batch.append(item)
                    if item.committed is not None:
                        break

            error: BaseException | None = None
            try:
                await asyncio.to_thread(self._append_batch, batch)
            except BaseException as exc:
                error = exc
                self._writer_error = exc
            finally:
                for item in batch:
                    committed = item.committed
                    if committed is not None and not committed.done():
                        if error is None:
                            committed.set_result(None)
                        else:
                            committed.set_exception(error)
                    self._persist_queue.task_done()

    def _append_batch(self, batch: list[_PersistItem]) -> None:
        grouped: dict[str, tuple[list[str], list[str]]] = {}
        for item in batch:
            events, motion = grouped.setdefault(
                item.session_id,
                ([], []),
            )
            events.append(item.line)
            if item.motion_log:
                motion.append(item.line)

        for session_id, (events, motion) in grouped.items():
            directory = self.session_dir(session_id)
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / "events.ndjson").open(
                "a",
                encoding="utf-8",
            ) as file:
                file.writelines(events)
            if motion:
                with (directory / "motion.ndjson").open(
                    "a",
                    encoding="utf-8",
                ) as file:
                    file.writelines(motion)


async def stdout_event_sink(event: Event) -> None:
    print(json.dumps(event, ensure_ascii=False, separators=(",", ":")), flush=True)


class ThrottledStdoutEventSink:
    """Print all control events while limiting only high-rate IMU output."""

    def __init__(self, max_imu_hz: float = 10.0) -> None:
        if max_imu_hz <= 0:
            raise ValueError("max_imu_hz must be positive")
        self.minimum_imu_interval_ms = 1000.0 / max_imu_hz
        self._last_imu_timestamp_by_session: dict[str, int] = {}

    async def __call__(self, event: Event) -> None:
        if event["type"] == "imu":
            payload = event["payload"]
            session_id = str(payload.get("sessionId", ""))
            timestamp = int(event["timestamp"])
            previous = self._last_imu_timestamp_by_session.get(session_id)
            if (
                previous is not None
                and timestamp - previous < self.minimum_imu_interval_ms
            ):
                return
            self._last_imu_timestamp_by_session[session_id] = timestamp
        await stdout_event_sink(event)

