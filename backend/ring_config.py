"""Configuration for the SoundClay Zilo ring runtime."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


DEFAULT_RING_ADDRESS = "FA:7E:92:E6:38:6D"


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None else float(value)


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None else int(value)


@dataclass(frozen=True)
class RingConfig:
    """All tunable values used by the ring-side implementation."""

    address: str = DEFAULT_RING_ADDRESS
    session_root: Path = Path("runtime/sessions")
    scan_timeout_s: float = 30.0
    post_connect_settle_s: float = 2.0
    command_interval_s: float = 0.4
    sensor_stop_settle_s: float = 0.75
    post_disconnect_settle_s: float = 2.0
    command_timeout_s: float = 10.0
    recording_timeout_s: float = 60.0
    recording_recovery_wait_s: float = 15.0
    recording_recovery_poll_s: float = 1.0
    recording_min_duration_s: float = 3.0
    recording_max_duration_s: float = 8.0
    recording_speech_frame_dbfs: float = -45.0
    recording_min_speech_ratio: float = 0.20
    mode_press_timeout_s: float = 30.0
    sensor_timeout_s: float = 5.0
    mode_switch_delay_s: float = 0.7
    connect_retry_delays_s: tuple[float, ...] = (2.0, 5.0, 10.0)
    mode_retry_count: int = 2
    motion_reconnect_count: int = 2
    console_imu_hz: float = 10.0
    ffmpeg_path: str = "ffmpeg"

    twist_sign: int = 1
    twist_deadzone_dps: float = 15.0
    twist_full_scale_dps: float = 360.0
    twist_ema_alpha: float = 0.25
    tilt_x_sign: int = -1
    tilt_x_deadzone_deg: float = 4.0
    tilt_x_enter_deg: float = 8.0
    tilt_x_return_deg: float = 5.0
    tilt_x_neutral_dwell_ms: int = 300
    tilt_x_full_scale_deg: float = 40.0
    tilt_x_ema_alpha: float = 0.18
    tilt_x_calibration_delay_s: float = 1.0
    tilt_x_calibration_s: float = 1.5
    accel_min_g: float = 0.15
    accel_max_g: float = 1.2
    accel_ema_alpha: float = 0.25
    burst_threshold: float = 0.7
    burst_window_samples: int = 30
    burst_min_active_samples: int = 20
    burst_max_gyro_dps: float = 1200.0
    burst_min_linear_accel_g: float = 0.55
    burst_max_twist_share: float = 0.68
    burst_quiet_accel_g: float = 0.10
    burst_quiet_gyro_dps: float = 80.0
    burst_quiet_dwell_ms: int = 400
    burst_return_accel_g: float = 0.20
    burst_return_min_active_samples: int = 3
    gravity_ema_alpha: float = 0.02
    freeze_cooldown_ms: int = 1500

    @classmethod
    def from_env(cls) -> "RingConfig":
        sign = _env_int("SOUNDCLAY_TWIST_SIGN", 1)
        if sign not in (-1, 1):
            raise ValueError("SOUNDCLAY_TWIST_SIGN must be -1 or 1")
        tilt_x_sign = _env_int("SOUNDCLAY_TILT_X_SIGN", -1)
        if tilt_x_sign not in (-1, 1):
            raise ValueError("SOUNDCLAY_TILT_X_SIGN must be -1 or 1")
        return cls(
            address=os.getenv("SOUNDCLAY_RING_ADDRESS", DEFAULT_RING_ADDRESS),
            session_root=Path(
                os.getenv("SOUNDCLAY_SESSION_ROOT", "runtime/sessions")
            ),
            scan_timeout_s=_env_float("SOUNDCLAY_SCAN_TIMEOUT_S", 30.0),
            post_connect_settle_s=_env_float(
                "SOUNDCLAY_POST_CONNECT_SETTLE_S", 2.0
            ),
            command_interval_s=_env_float(
                "SOUNDCLAY_COMMAND_INTERVAL_S", 0.4
            ),
            sensor_stop_settle_s=_env_float(
                "SOUNDCLAY_SENSOR_STOP_SETTLE_S", 0.75
            ),
            post_disconnect_settle_s=_env_float(
                "SOUNDCLAY_POST_DISCONNECT_SETTLE_S", 2.0
            ),
            command_timeout_s=_env_float("SOUNDCLAY_COMMAND_TIMEOUT_S", 10.0),
            recording_timeout_s=_env_float(
                "SOUNDCLAY_RECORDING_TIMEOUT_S", 60.0
            ),
            recording_recovery_wait_s=_env_float(
                "SOUNDCLAY_RECORDING_RECOVERY_WAIT_S", 15.0
            ),
            recording_recovery_poll_s=_env_float(
                "SOUNDCLAY_RECORDING_RECOVERY_POLL_S", 1.0
            ),
            recording_min_duration_s=_env_float(
                "SOUNDCLAY_RECORDING_MIN_DURATION_S", 3.0
            ),
            recording_max_duration_s=_env_float(
                "SOUNDCLAY_RECORDING_MAX_DURATION_S", 8.0
            ),
            recording_speech_frame_dbfs=_env_float(
                "SOUNDCLAY_RECORDING_SPEECH_FRAME_DBFS", -45.0
            ),
            recording_min_speech_ratio=_env_float(
                "SOUNDCLAY_RECORDING_MIN_SPEECH_RATIO", 0.20
            ),
            mode_press_timeout_s=_env_float(
                "SOUNDCLAY_MODE_PRESS_TIMEOUT_S", 30.0
            ),
            sensor_timeout_s=_env_float("SOUNDCLAY_SENSOR_TIMEOUT_S", 5.0),
            motion_reconnect_count=_env_int(
                "SOUNDCLAY_MOTION_RECONNECT_COUNT", 2
            ),
            console_imu_hz=_env_float("SOUNDCLAY_CONSOLE_IMU_HZ", 10.0),
            twist_sign=sign,
            twist_deadzone_dps=_env_float(
                "SOUNDCLAY_TWIST_DEADZONE_DPS", 15.0
            ),
            twist_full_scale_dps=_env_float(
                "SOUNDCLAY_TWIST_FULL_SCALE_DPS", 360.0
            ),
            twist_ema_alpha=_env_float(
                "SOUNDCLAY_TWIST_EMA_ALPHA", 0.25
            ),
            tilt_x_sign=tilt_x_sign,
            tilt_x_deadzone_deg=_env_float(
                "SOUNDCLAY_TILT_X_DEADZONE_DEG", 4.0
            ),
            tilt_x_enter_deg=_env_float(
                "SOUNDCLAY_TILT_X_ENTER_DEG", 8.0
            ),
            tilt_x_return_deg=_env_float(
                "SOUNDCLAY_TILT_X_RETURN_DEG", 5.0
            ),
            tilt_x_neutral_dwell_ms=_env_int(
                "SOUNDCLAY_TILT_X_NEUTRAL_DWELL_MS", 300
            ),
            tilt_x_full_scale_deg=_env_float(
                "SOUNDCLAY_TILT_X_FULL_SCALE_DEG", 40.0
            ),
            tilt_x_ema_alpha=_env_float(
                "SOUNDCLAY_TILT_X_EMA_ALPHA", 0.18
            ),
            tilt_x_calibration_delay_s=_env_float(
                "SOUNDCLAY_TILT_X_CALIBRATION_DELAY_S", 1.0
            ),
            tilt_x_calibration_s=_env_float(
                "SOUNDCLAY_TILT_X_CALIBRATION_S", 1.5
            ),
            burst_threshold=_env_float(
                "SOUNDCLAY_BURST_THRESHOLD", 0.7
            ),
            burst_window_samples=_env_int(
                "SOUNDCLAY_BURST_WINDOW_SAMPLES", 30
            ),
            burst_min_active_samples=_env_int(
                "SOUNDCLAY_BURST_MIN_ACTIVE_SAMPLES", 20
            ),
            burst_max_gyro_dps=_env_float(
                "SOUNDCLAY_BURST_MAX_GYRO_DPS", 1200.0
            ),
            burst_min_linear_accel_g=_env_float(
                "SOUNDCLAY_BURST_MIN_LINEAR_ACCEL_G", 0.55
            ),
            burst_max_twist_share=_env_float(
                "SOUNDCLAY_BURST_MAX_TWIST_SHARE", 0.68
            ),
            burst_quiet_accel_g=_env_float(
                "SOUNDCLAY_BURST_QUIET_ACCEL_G", 0.10
            ),
            burst_quiet_gyro_dps=_env_float(
                "SOUNDCLAY_BURST_QUIET_GYRO_DPS", 80.0
            ),
            burst_quiet_dwell_ms=_env_int(
                "SOUNDCLAY_BURST_QUIET_DWELL_MS", 400
            ),
            burst_return_accel_g=_env_float(
                "SOUNDCLAY_BURST_RETURN_ACCEL_G", 0.20
            ),
            burst_return_min_active_samples=_env_int(
                "SOUNDCLAY_BURST_RETURN_MIN_ACTIVE_SAMPLES", 3
            ),
            gravity_ema_alpha=_env_float(
                "SOUNDCLAY_GRAVITY_EMA_ALPHA", 0.02
            ),
            ffmpeg_path=os.getenv("SOUNDCLAY_FFMPEG", "ffmpeg"),
        )

