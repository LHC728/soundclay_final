"""Role B: mode verification and twist, tiltX, burst, freeze events."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import time

import ring_sound as sdk

from event_contract import EventPublisher, validate_session_id
from motion_mapper import MotionMapper
from ring_command_gate import RingCommandGate
from ring_config import RingConfig


class MotionModeUnavailable(RuntimeError):
    """The ring could not be verified in gesture mode."""


class SensorStreamUnavailable(RuntimeError):
    """The live IMU stream stalled repeatedly."""


class RingMotionService:
    def __init__(
        self,
        client: sdk.RingSoundClient,
        config: RingConfig,
        publisher: EventPublisher,
        command_lock: RingCommandGate | asyncio.Lock,
    ) -> None:
        self.client = client
        self.config = config
        self.publisher = publisher
        self.command_lock = command_lock
        self.start_info: sdk.SensorStartInfo | None = None
        self.mapper: MotionMapper | None = None
        self.active = False
        self.expected_sequence: int | None = None

    async def enter_motion_mode(
        self,
        session_id: str,
        *,
        wait_for_press: bool = True,
    ) -> sdk.SensorStartInfo:
        validate_session_id(session_id)
        total_attempts = self.config.mode_retry_count + 1

        for attempt in range(1, total_attempts + 1):
            if wait_for_press or attempt > 1:
                await self.publisher.emit(
                    "status",
                    {
                        "sessionId": session_id,
                        "ringConnected": self.client.is_connected,
                        "phase": "gesture_mode_prompt",
                        "modeHint": "gesture_pending",
                        "attempt": attempt,
                        "message": "请单击戒指切换到手势模式",
                    },
                )
                press = await sdk.wait_sensor_key_single_press_event(
                    self.client,
                    timeout_s=self.config.mode_press_timeout_s,
                )
                await self.publisher.emit(
                    "status",
                    {
                        "sessionId": session_id,
                        "ringConnected": self.client.is_connected,
                        "phase": "key_single_press",
                        "modeHint": "gesture_pending",
                        "deviceTimestampMs": press.timestamp_ms,
                    },
                )
                await asyncio.sleep(self.config.mode_switch_delay_s)

            try:
                async with self.command_lock:
                    start_info = await sdk.start_sensor_report(
                        self.client,
                        timeout_s=self.config.command_timeout_s,
                    )
            except sdk.DeviceError as error:
                if error.error_code != int(sdk.ErrorCode.DEVICE_BUSY):
                    raise
                await self.publisher.emit(
                    "error",
                    {
                        "sessionId": session_id,
                        "code": "GESTURE_MODE_BUSY",
                        "phase": "mode_switch",
                        "message": str(error),
                        "recoverable": attempt < total_attempts,
                        "recommendedAction": "请再次单击戒指，然后重试",
                    },
                )
                continue

            self.start_info = start_info
            self.mapper = MotionMapper(start_info, self.config)
            self.expected_sequence = None
            self.active = True
            await self.publisher.emit(
                "status",
                {
                    "sessionId": session_id,
                    "ringConnected": self.client.is_connected,
                    "phase": "sculpting",
                    "modeHint": "gesture_verified",
                    "sampleRateHz": start_info.sample_rate_hz,
                    "accelRangeG": start_info.accel_range_g,
                    "gyroRangeDps": start_info.gyro_range_dps,
                },
            )
            return start_info

        raise MotionModeUnavailable(
            f"gesture mode could not be verified after {total_attempts} attempts"
        )

    async def run_until_freeze(self, session_id: str) -> str:
        return await self._run_stream(
            session_id,
            duration_s=None,
            stop_on_freeze=True,
        )

    async def collect_for(self, session_id: str, duration_s: float) -> str:
        if duration_s <= 0:
            raise ValueError("duration_s must be positive")
        return await self._run_stream(
            session_id,
            duration_s=duration_s,
            stop_on_freeze=False,
        )

    def reset_tilt_neutral(self) -> None:
        """Recalibrate tilt in memory without stopping sensor reporting."""
        if not self.active or self.mapper is None:
            raise MotionModeUnavailable(
                "IMU stream must be active before recalibrating tilt"
            )
        self.mapper.reset_tilt_neutral()

    async def _run_stream(
        self,
        session_id: str,
        *,
        duration_s: float | None,
        stop_on_freeze: bool,
    ) -> str:
        validate_session_id(session_id)
        if not self.active or self.mapper is None:
            raise MotionModeUnavailable(
                "start_sensor_report must succeed before consuming IMU data"
            )

        loop = asyncio.get_running_loop()
        deadline = None if duration_s is None else loop.time() + duration_s
        imu_task = asyncio.create_task(self._wait_imu())
        freeze_task = (
            asyncio.create_task(
                sdk.wait_sensor_key_double_press_event(
                    self.client,
                    timeout_s=3600.0,
                )
            )
            if stop_on_freeze
            else None
        )
        timeouts = 0
        completion = "error"

        try:
            while True:
                timeout = None
                if deadline is not None:
                    timeout = max(0.0, deadline - loop.time())
                    if timeout == 0.0:
                        completion = "duration_complete"
                        return "duration_complete"

                tasks = {imu_task}
                if freeze_task is not None:
                    tasks.add(freeze_task)
                done, _ = await asyncio.wait(
                    tasks,
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    completion = "duration_complete"
                    return "duration_complete"

                if freeze_task is not None and freeze_task in done:
                    freeze = freeze_task.result()
                    await self.publisher.emit(
                        "freeze",
                        {
                            "sessionId": session_id,
                            "source": "key_double_press",
                            "deviceTimestampMs": freeze.timestamp_ms,
                        },
                        motion_log=True,
                    )
                    completion = "freeze"
                    return "freeze"

                if imu_task in done:
                    try:
                        batch = imu_task.result()
                    except sdk.TimeoutError as error:
                        timeouts += 1
                        await self.publisher.emit(
                            "error",
                            {
                                "sessionId": session_id,
                                "code": "IMU_TIMEOUT",
                                "phase": "sculpting",
                                "message": str(error),
                                "recoverable": timeouts < 3,
                                "recommendedAction": "保持戒指连接；连续超时请重新进入手势模式",
                            },
                        )
                        if timeouts >= 3:
                            raise SensorStreamUnavailable(
                                "IMU stream timed out three times"
                            ) from error
                    else:
                        timeouts = 0
                        await self._consume_batch(session_id, batch)
                    imu_task = asyncio.create_task(self._wait_imu())
        finally:
            for task in (imu_task, freeze_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (imu_task, freeze_task) if task is not None),
                return_exceptions=True,
            )
            await self.stop(session_id, frozen=completion == "freeze")

    async def _wait_imu(self) -> sdk.SensorDataBatch:
        return await sdk.wait_sensor_data(
            self.client,
            timeout_s=self.config.sensor_timeout_s,
        )

    async def _consume_batch(
        self,
        session_id: str,
        batch: sdk.SensorDataBatch,
    ) -> None:
        if self.mapper is None:
            raise MotionModeUnavailable("motion mapper has not been initialized")

        if (
            self.expected_sequence is not None
            and batch.sequence_start != self.expected_sequence
        ):
            await self.publisher.emit(
                "error",
                {
                    "sessionId": session_id,
                    "code": "IMU_SEQUENCE_GAP",
                    "phase": "sculpting",
                    "message": (
                        f"expected sequence {self.expected_sequence}, "
                        f"received {batch.sequence_start}"
                    ),
                    "recoverable": True,
                    "recommendedAction": "继续采集；若频繁出现请靠近电脑或重新连接",
                },
                motion_log=True,
            )

        for index, sample in enumerate(batch.samples):
            sequence = batch.sequence_start + index
            reading = self.mapper.map_sample(
                sample,
                sequence,
                monotonic_ms=float(sample.timestamp_ms),
            )
            await self.publisher.emit(
                "imu",
                {
                    "sessionId": session_id,
                    "sequence": reading.sequence,
                    "deviceTimestampMs": reading.device_timestamp_ms,
                    "twist": reading.twist,
                    "tiltX": reading.tilt_x,
                    "accelMag": reading.accel_mag,
                    "accelX": reading.accel_x_g,
                    "accelY": reading.accel_y_g,
                    "accelZ": reading.accel_z_g,
                    "gyroX": reading.gyro_x_dps,
                    "gyroY": reading.gyro_y_dps,
                    "gyroZ": reading.gyro_z_dps,
                    "gyroXY": reading.gyro_xy_dps,
                    "linearAccelX": reading.linear_accel_x_g,
                    "linearAccelY": reading.linear_accel_y_g,
                    "linearAccelZ": reading.linear_accel_z_g,
                    "burstState": reading.burst_state,
                    "burstArmed": reading.burst_armed,
                },
                motion_log=True,
            )
            if reading.burst:
                await self.publisher.emit(
                    "burst",
                    {
                        "sessionId": session_id,
                        "strength": reading.burst_strength,
                    },
                    motion_log=True,
                )
        self.expected_sequence = batch.sequence_start + batch.frame_count

    async def stop(
        self,
        session_id: str | None = None,
        *,
        frozen: bool = False,
    ) -> None:
        if not self.active:
            return
        try:
            if self.client.is_connected:
                async with self.command_lock:
                    await sdk.stop_sensor_report(
                        self.client,
                        timeout_s=self.config.command_timeout_s,
                    )
        except sdk.RingSoundError as error:
            if session_id:
                with suppress(Exception):
                    await self.publisher.emit(
                        "error",
                        {
                            "sessionId": session_id,
                            "code": "IMU_STOP_FAILED",
                            "phase": "sculpting",
                            "message": str(error),
                            "recoverable": True,
                            "recommendedAction": "断开连接会自动关闭实时上报",
                        },
                    )
        finally:
            self.active = False
            self.start_info = None
            self.mapper = None
            self.expected_sequence = None
            # Give the firmware time to finish disabling continuous 0x0703
            # notifications before another command or a disconnect is issued.
            if (
                self.client.is_connected
                and self.config.sensor_stop_settle_s > 0
            ):
                await asyncio.sleep(self.config.sensor_stop_settle_s)
            if session_id:
                with suppress(Exception):
                    await self.publisher.emit(
                        "status",
                        {
                            "sessionId": session_id,
                            "ringConnected": self.client.is_connected,
                            "phase": "frozen" if frozen else "motion_stopped",
                            "modeHint": (
                                "recording_pending"
                                if frozen
                                else "gesture_verified"
                            ),
                            "message": (
                                "雕刻已停止；下次录音前请单击返回录音模式"
                                if frozen
                                else "实时 IMU 采集已停止"
                            ),
                        },
                    )

