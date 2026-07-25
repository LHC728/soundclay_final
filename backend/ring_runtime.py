"""Single-owner SoundClay runtime for the Zilo ring.

Roles A and B must share this object. Creating two runtimes for one physical
ring is unsupported because both would compete for the same BLE connection and
command queues.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import time
from typing import Any

import ring_sound as sdk

from event_contract import EventPublisher, EventSink, validate_session_id
from ring_command_gate import RingCommandGate
from ring_config import RingConfig
from ring_motion_service import RingMotionService, SensorStreamUnavailable
from ring_recording_service import (
    AudioReady,
    RecordingQualityError,
    RecordingUnavailable,
    RingRecordingService,
)


class RingNotConnected(RuntimeError):
    pass


def generate_session_id(prefix: str = "SC") -> str:
    """Create a session id from the current Unix timestamp in milliseconds."""
    return validate_session_id(f"{prefix}-{int(time.time() * 1000)}")


class RingRuntime:
    """Own the BLE client, recording service, and motion service."""

    def __init__(
        self,
        config: RingConfig | None = None,
        *,
        event_sink: EventSink | None = None,
    ) -> None:
        self.config = config or RingConfig.from_env()
        self.publisher = EventPublisher(self.config.session_root, event_sink)
        self.command_lock = RingCommandGate(self.config.command_interval_s)
        self._connection_lock = asyncio.Lock()
        self.client: sdk.RingSoundClient | None = None
        self.recording: RingRecordingService | None = None
        self.motion: RingMotionService | None = None
        self.phase = "disconnected"
        self.mode_hint = "unknown"
        self.system_info: sdk.SystemInfo | None = None
        self.audio_count: int | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._operation_task: asyncio.Task[Any] | None = None
        self._closing = False

    @property
    def is_connected(self) -> bool:
        return bool(self.client and self.client.is_connected)

    async def connect(self) -> None:
        async with self._connection_lock:
            await self._connect_locked()

    async def _connect_locked(self) -> None:
        if self.is_connected:
            return
        self._closing = False
        if self.client is not None:
            await self._discard_client()
            await asyncio.sleep(self.config.post_disconnect_settle_s)
        retry_delays = (0.0,) + self.config.connect_retry_delays_s
        last_error: Exception | None = None

        for attempt, delay in enumerate(retry_delays, 1):
            if delay:
                await asyncio.sleep(delay)
            await self._discard_client()

            transport = sdk.NusClient(
                address=self.config.address,
                scan_timeout_s=self.config.scan_timeout_s,
            )
            client = sdk.RingSoundClient(
                transport=transport,
                command_timeout_s=self.config.command_timeout_s,
            )
            self.client = client
            try:
                await client.connect()
            except Exception as error:
                last_error = error
                await self.publisher.emit(
                    "error",
                    {
                        "code": "BLE_CONNECT_FAILED",
                        "phase": "connecting",
                        "message": str(error),
                        "recoverable": attempt < len(retry_delays),
                        "recommendedAction": (
                            "关闭手机蓝牙和 APK，保持戒指靠近电脑后重试"
                        ),
                        "attempt": attempt,
                    },
                )
                await self._discard_client()
                continue

            # BLE 6.0 firmware may request time synchronization immediately
            # after connecting. Install the handler before the settle window;
            # it may answer that device-initiated request, while all proactive
            # application commands remain blocked until settling completes.
            sdk.enable_time_sync(client)
            self.phase = "connected_settling"
            await self.publisher.emit(
                "status",
                {
                    "ringConnected": True,
                    "phase": self.phase,
                    "modeHint": "unknown",
                    "address": self.config.address,
                    "attempt": attempt,
                    "settleDelayMs": round(
                        self.config.post_connect_settle_s * 1000
                    ),
                    "message": "BLE 已连接，等待戒指链路稳定",
                },
            )
            await asyncio.sleep(self.config.post_connect_settle_s)
            if not client.is_connected:
                last_error = sdk.TransportError(
                    "BLE disconnected during the post-connect settle window"
                )
                await self.publisher.emit(
                    "error",
                    {
                        "code": "BLE_CONNECT_UNSTABLE",
                        "phase": "connected_settling",
                        "message": str(last_error),
                        "recoverable": attempt < len(retry_delays),
                        "recommendedAction": (
                            "保持戒指靠近电脑；程序将重新扫描并连接"
                        ),
                        "attempt": attempt,
                    },
                )
                await self._discard_client()
                continue

            try:
                async with self.command_lock:
                    info = await sdk.get_system_info(
                        client,
                        timeout_s=self.config.command_timeout_s,
                    )
            except Exception as error:
                last_error = error
                await self.publisher.emit(
                    "error",
                    {
                        "code": "BLE_HEALTH_CHECK_FAILED",
                        "phase": "connection_health_check",
                        "message": str(error),
                        "recoverable": attempt < len(retry_delays),
                        "recommendedAction": (
                            "应用层通信未就绪；程序将断开并重新连接"
                        ),
                        "attempt": attempt,
                    },
                )
                await self._discard_client()
                continue

            self.system_info = info
            # Audio count is deliberately deferred until recording is armed.
            # Sending 0x0502 immediately after the system-info probe made the
            # freshly established firmware link substantially less stable.
            self.audio_count = None
            self.recording = RingRecordingService(
                client,
                self.config,
                self.publisher,
                self.command_lock,
            )
            self.motion = RingMotionService(
                client,
                self.config,
                self.publisher,
                self.command_lock,
            )
            self.phase = "connected"
            self.mode_hint = "unknown"
            await self.publisher.emit(
                "status",
                {
                    "ringConnected": True,
                    "phase": self.phase,
                    "modeHint": self.mode_hint,
                    "address": self.config.address,
                    "attempt": attempt,
                    "settled": True,
                    "healthChecked": True,
                },
            )
            self._start_monitor()
            return

        self.phase = "disconnected"
        raise sdk.TransportError(
            f"Unable to connect to ring {self.config.address} "
            f"after {len(retry_delays)} attempts"
        ) from last_error

    async def reconnect(self) -> None:
        async with self._connection_lock:
            await self._close_locked()
            await self._connect_locked()

    async def close(self) -> None:
        try:
            async with self._connection_lock:
                await self._close_locked()
        finally:
            # IMU samples are persisted by a background batch writer. A public
            # shutdown must drain that queue before the event loop exits.
            await self.publisher.close()

    async def _close_locked(self) -> None:
        self._closing = True
        had_client = self.client is not None
        monitor = self._monitor_task
        self._monitor_task = None
        if monitor is not None and monitor is not asyncio.current_task():
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)

        if self.motion is not None:
            await self.motion.stop()
        await self._discard_client()
        if had_client and self.config.post_disconnect_settle_s > 0:
            await asyncio.sleep(self.config.post_disconnect_settle_s)
        self.phase = "disconnected"
        self.mode_hint = "unknown"
        self.system_info = None
        self.audio_count = None
        self._operation_task = None
        await self.publisher.emit(
            "status",
            {
                "ringConnected": False,
                "phase": self.phase,
                "modeHint": self.mode_hint,
                "address": self.config.address,
            },
        )

    async def get_status(self) -> dict[str, Any]:
        client = self._require_client()
        info = self.system_info
        count = self.audio_count
        if info is None:
            async with self.command_lock:
                info = await sdk.get_system_info(
                    client,
                    timeout_s=self.config.command_timeout_s,
                )
        self.system_info = info
        payload = {
            "ringConnected": True,
            "phase": self.phase,
            "modeHint": self.mode_hint,
            "address": self.config.address,
            "firmwareVersion": info.firmware_version,
            "batteryPercent": info.battery_percent,
            "batteryCharging": info.battery_charging,
            "model": info.model,
            "sn": info.sn,
            "audioCount": count,
            "audioStorageTotal": info.audio_storage_total,
            "audioStorageAvailable": info.audio_storage_available,
        }
        await self.publisher.emit("status", payload)
        return payload

    async def clear_recordings(self) -> dict[str, int]:
        """Delete all recordings stored on the ring and verify the result."""

        client = self._require_client()
        self._begin_operation()
        self.phase = "audio_clearing"
        try:
            async with self.command_lock:
                before = await sdk.get_audio_file_count(
                    client,
                    timeout_s=self.config.command_timeout_s,
                )
            async with self.command_lock:
                await sdk.clear_audio_files(
                    client,
                    timeout_s=self.config.command_timeout_s,
                )
            async with self.command_lock:
                after = await sdk.get_audio_file_count(
                    client,
                    timeout_s=self.config.command_timeout_s,
                )
            if after != 0:
                raise RuntimeError(
                    f"ring still reports {after} recording(s) after clear"
                )
        except Exception as error:
            self.phase = "audio_clear_error"
            await self.publisher.emit(
                "error",
                {
                    "code": "AUDIO_CLEAR_FAILED",
                    "phase": self.phase,
                    "message": str(error),
                    "recoverable": True,
                    "recommendedAction": (
                        "确认没有其他程序连接戒指，保持戒指靠近电脑后重试"
                    ),
                },
            )
            raise
        else:
            self.audio_count = 0
            self.phase = "connected"
            result = {"before": before, "after": after}
            await self.publisher.emit(
                "status",
                {
                    "ringConnected": True,
                    "phase": "audio_cleared",
                    "modeHint": self.mode_hint,
                    "address": self.config.address,
                    "audioCountBefore": before,
                    "audioCountAfter": after,
                },
            )
            return result
        finally:
            self._end_operation()

    async def get_recording_count(self) -> int:
        """Read the number of recordings stored on the ring."""

        client = self._require_client()
        self._begin_operation()
        try:
            async with self.command_lock:
                count = await sdk.get_audio_file_count(
                    client,
                    timeout_s=self.config.command_timeout_s,
                )
            self.audio_count = count
            return count
        finally:
            self._end_operation()

    async def arm_recording(
        self,
        session_id: str,
        *,
        timeout_s: float | None = None,
    ) -> AudioReady:
        validate_session_id(session_id)
        self._require_client()
        if self.recording is None:
            raise RingNotConnected("recording service is unavailable")
        self._begin_operation()
        self.phase = "recording"
        self.mode_hint = "recording_expected"
        recording = self.recording
        try:
            result = await recording.arm_recording(
                session_id,
                timeout_s=timeout_s,
                baseline_count=self.audio_count,
            )
        except Exception as error:
            baseline_count = (
                recording.last_baseline_count
                if recording.last_baseline_count is not None
                else self.audio_count
            )
            if self._is_connection_error(error) and baseline_count is not None:
                try:
                    await self.publisher.emit(
                        "status",
                        {
                            "sessionId": session_id,
                            "ringConnected": False,
                            "phase": "recording_reconnecting",
                            "modeHint": "recording_expected",
                            "audioCountBefore": baseline_count,
                            "message": "录音上传中断，正在重连并补取戒指中的录音",
                        },
                    )
                    await self.reconnect()
                    self._begin_operation()
                    current_count = await self._wait_for_new_recording(
                        session_id,
                        baseline_count,
                    )
                    if self.recording is None:
                        raise RingNotConnected(
                            "recording service is unavailable after reconnect"
                        )
                    result = await self.recording.download_latest(
                        session_id,
                        file_count=current_count,
                    )
                except Exception as recovery_error:
                    error = recovery_error
                else:
                    self.audio_count = current_count
                    self.phase = "audio_ready"
                    self.mode_hint = "recording_verified"
                    await self.publisher.emit(
                        "status",
                        {
                            "sessionId": session_id,
                            "ringConnected": True,
                            "phase": "recording_recovered",
                            "modeHint": "recording_verified",
                            "audioCountBefore": baseline_count,
                            "audioCountAfter": current_count,
                            "message": "BLE 已恢复，录音已通过 quick download 补取",
                        },
                    )
                    return result

            self.phase = "recording_error"
            code = (
                error.code
                if isinstance(error, RecordingQualityError)
                else "RECORDING_FAILED"
            )
            action = (
                error.recommended_action
                if isinstance(error, RecordingQualityError)
                else "确认录音模式并保持戒指靠近电脑，然后重试"
            )
            await self._emit_operation_error(
                session_id,
                code=code,
                phase="recording",
                error=error,
                action=action,
            )
            raise error
        else:
            self.audio_count = max(
                self.audio_count or 0,
                result.file_index + 1,
            )
            self.phase = "audio_ready"
            self.mode_hint = "recording_verified"
            return result
        finally:
            self._end_operation()

    async def recover_latest_recording(self, session_id: str) -> AudioReady:
        validate_session_id(session_id)
        self._require_client()
        if self.recording is None:
            raise RingNotConnected("recording service is unavailable")
        self._begin_operation()
        self.phase = "recording_recovery"
        try:
            result = await self.recording.download_latest(
                session_id,
                file_count=self.audio_count,
            )
        except Exception as error:
            self.phase = "recording_error"
            await self._emit_operation_error(
                session_id,
                code="RECORDING_RECOVERY_FAILED",
                phase="recording_recovery",
                error=error,
                action="确认戒指中存在录音并保持连接后重试",
            )
            raise
        else:
            self.audio_count = max(
                self.audio_count or 0,
                result.file_index + 1,
            )
            self.phase = "audio_ready"
            return result
        finally:
            self._end_operation()

    async def enter_motion_mode(
        self,
        session_id: str,
        *,
        wait_for_press: bool = True,
    ) -> sdk.SensorStartInfo:
        validate_session_id(session_id)
        self._require_client()
        if self.motion is None:
            raise RingNotConnected("motion service is unavailable")
        self._begin_operation()
        self.phase = "mode_switch"
        self.mode_hint = "gesture_pending"
        try:
            result = await self.motion.enter_motion_mode(
                session_id,
                wait_for_press=wait_for_press,
            )
        except Exception as error:
            self.phase = "mode_error"
            self.mode_hint = "unknown"
            await self._emit_operation_error(
                session_id,
                code="MOTION_MODE_FAILED",
                phase="mode_switch",
                error=error,
                action="根据页面提示单击戒指，再重新开启 IMU",
            )
            raise
        else:
            self.phase = "sculpting"
            self.mode_hint = "gesture_verified"
            return result
        finally:
            self._end_operation()

    async def sculpt_until_freeze(self, session_id: str) -> str:
        validate_session_id(session_id)
        if self.motion is None:
            raise RingNotConnected("motion service is unavailable")
        self._begin_operation()
        reconnect_attempt = 0
        reenter_mode = False
        try:
            while True:
                try:
                    if self.motion is None:
                        raise RingNotConnected("motion service is unavailable")
                    if reenter_mode:
                        self.phase = "mode_switch"
                        self.mode_hint = "unknown"
                        await self.motion.enter_motion_mode(
                            session_id,
                            wait_for_press=False,
                        )
                        self.phase = "sculpting"
                        self.mode_hint = "gesture_verified"
                    reason = await self.motion.run_until_freeze(session_id)
                except Exception as error:
                    if (
                        not self._is_connection_error(error)
                        or reconnect_attempt >= self.config.motion_reconnect_count
                    ):
                        self.phase = "motion_error"
                        await self._emit_operation_error(
                            session_id,
                            code="MOTION_STREAM_FAILED",
                            phase="sculpting",
                            error=error,
                            action="保持戒指靠近电脑，然后重新进入手势模式",
                        )
                        raise

                    reconnect_attempt += 1
                    self.phase = "motion_reconnecting"
                    self.mode_hint = "unknown"
                    await self.publisher.emit(
                        "status",
                        {
                            "sessionId": session_id,
                            "ringConnected": False,
                            "phase": self.phase,
                            "modeHint": self.mode_hint,
                            "attempt": reconnect_attempt,
                            "message": (
                                "IMU 链路断开，正在重连；"
                                "连接恢复后将先尝试自动恢复手势上报"
                            ),
                        },
                    )
                    try:
                        await self.reconnect()
                    except Exception as reconnect_error:
                        self.phase = "motion_error"
                        await self._emit_operation_error(
                            session_id,
                            code="MOTION_RECONNECT_FAILED",
                            phase="sculpting",
                            error=reconnect_error,
                            action="检查电脑蓝牙和戒指距离后重新运行 sculpt",
                        )
                        raise reconnect_error
                    self._begin_operation()
                    reenter_mode = True
                    continue
                else:
                    self.phase = "frozen"
                    self.mode_hint = "recording_pending"
                    return reason
        finally:
            self._end_operation()

    async def collect_motion_for(self, session_id: str, duration_s: float) -> str:
        validate_session_id(session_id)
        if self.motion is None:
            raise RingNotConnected("motion service is unavailable")
        self._begin_operation()
        remaining_s = duration_s
        reconnect_attempt = 0
        reenter_mode = False
        try:
            while True:
                started_at: float | None = None
                try:
                    if self.motion is None:
                        raise RingNotConnected("motion service is unavailable")
                    if reenter_mode:
                        self.phase = "mode_switch"
                        self.mode_hint = "unknown"
                        await self.motion.enter_motion_mode(
                            session_id,
                            wait_for_press=False,
                        )
                        self.phase = "sculpting"
                        self.mode_hint = "gesture_verified"
                    started_at = asyncio.get_running_loop().time()
                    return await self.motion.collect_for(
                        session_id,
                        remaining_s,
                    )
                except Exception as error:
                    elapsed_s = (
                        asyncio.get_running_loop().time() - started_at
                        if started_at is not None
                        else 0.0
                    )
                    remaining_s = max(0.001, remaining_s - elapsed_s)
                    if (
                        not self._is_connection_error(error)
                        or reconnect_attempt >= self.config.motion_reconnect_count
                    ):
                        await self._emit_operation_error(
                            session_id,
                            code="MOTION_STREAM_FAILED",
                            phase="sculpting",
                            error=error,
                            action="保持戒指靠近电脑，然后重新进入手势模式",
                        )
                        raise

                    reconnect_attempt += 1
                    self.phase = "motion_reconnecting"
                    self.mode_hint = "unknown"
                    await self.publisher.emit(
                        "status",
                        {
                            "sessionId": session_id,
                            "ringConnected": False,
                            "phase": self.phase,
                            "modeHint": self.mode_hint,
                            "attempt": reconnect_attempt,
                            "remainingDurationMs": round(remaining_s * 1000),
                            "message": (
                                "IMU 链路断开，正在重连；"
                                "连接恢复后将先尝试自动恢复手势上报"
                            ),
                        },
                    )
                    await self.reconnect()
                    self._begin_operation()
                    reenter_mode = True
        finally:
            self.phase = "motion_stopped"
            self.mode_hint = (
                "gesture_verified" if self.is_connected else "unknown"
            )
            self._end_operation()

    async def stop_motion(self, session_id: str | None = None) -> None:
        if self.motion is not None:
            await self.motion.stop(session_id)
        self.phase = "motion_stopped"
        self.mode_hint = "gesture_verified" if self.is_connected else "unknown"

    def reset_tilt_neutral(self) -> None:
        """Reset the software tilt zero point without sending a BLE command."""
        if self.motion is None:
            raise RingNotConnected("motion service is unavailable")
        self.motion.reset_tilt_neutral()

    def _require_client(self) -> sdk.RingSoundClient:
        if self.client is None or not self.client.is_connected:
            raise RingNotConnected("ring is not connected")
        return self.client

    def _is_connection_error(self, error: BaseException) -> bool:
        return (
            isinstance(
                error,
                (
                    sdk.TransportError,
                    RingNotConnected,
                    SensorStreamUnavailable,
                ),
            )
            or not self.is_connected
        )

    async def _wait_for_new_recording(
        self,
        session_id: str,
        baseline_count: int,
    ) -> int:
        current_count = self.audio_count
        if current_count is not None and current_count > baseline_count:
            return current_count

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.config.recording_recovery_wait_s
        poll_attempt = 0
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise RecordingUnavailable(
                    "重连成功，但在恢复等待期内没有检测到断线前的新录音"
                )
            await asyncio.sleep(
                min(self.config.recording_recovery_poll_s, remaining)
            )
            client = self._require_client()
            async with self.command_lock:
                current_count = await sdk.get_audio_file_count(
                    client,
                    timeout_s=self.config.command_timeout_s,
                )
            self.audio_count = current_count
            poll_attempt += 1
            if current_count > baseline_count:
                return current_count
            await self.publisher.emit(
                "status",
                {
                    "sessionId": session_id,
                    "ringConnected": True,
                    "phase": "recording_recovery_wait",
                    "modeHint": "recording_expected",
                    "audioCountBefore": baseline_count,
                    "audioCountCurrent": current_count,
                    "pollAttempt": poll_attempt,
                    "message": "等待戒指完成录音文件入库",
                },
            )

    def _begin_operation(self) -> None:
        current = asyncio.current_task()
        if (
            self._operation_task is not None
            and not self._operation_task.done()
            and self._operation_task is not current
        ):
            raise RuntimeError("another ring operation is already running")
        self._operation_task = current

    def _end_operation(self) -> None:
        if self._operation_task is asyncio.current_task():
            self._operation_task = None

    async def _emit_operation_error(
        self,
        session_id: str,
        *,
        code: str,
        phase: str,
        error: Exception,
        action: str,
    ) -> None:
        with suppress(Exception):
            await self.publisher.emit(
                "error",
                {
                    "sessionId": session_id,
                    "code": code,
                    "phase": phase,
                    "message": str(error),
                    "recoverable": True,
                    "recommendedAction": action,
                },
            )

    def _start_monitor(self) -> None:
        if self._monitor_task is not None and not self._monitor_task.done():
            return
        self._monitor_task = asyncio.create_task(self._monitor_connection())

    async def _monitor_connection(self) -> None:
        try:
            while not self._closing:
                await asyncio.sleep(1.0)
                if self.client is None or self.client.is_connected:
                    continue
                self.phase = "disconnected"
                self.mode_hint = "unknown"
                await self.publisher.emit(
                    "error",
                    {
                        "code": "BLE_DISCONNECTED",
                        "phase": "connection",
                        "message": "戒指蓝牙连接已断开",
                        "recoverable": True,
                        "recommendedAction": "关闭手机蓝牙，靠近戒指并调用 reconnect()",
                    },
                )
                return
        except asyncio.CancelledError:
            raise

    async def _discard_client(self) -> None:
        client = self.client
        self.client = None
        self.recording = None
        self.motion = None
        if client is not None:
            with suppress(Exception):
                await client.disconnect()

    async def __aenter__(self) -> "RingRuntime":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

