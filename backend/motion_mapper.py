"""Convert Zilo raw IMU samples into SoundClay sculpture controls."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time

import ring_sound as sdk

from burst_state_machine import BurstStateMachine
from ring_config import RingConfig


TILT_NEUTRAL = "neutral"
TILT_ACTIVE = "active"
TILT_RETURNING = "returning"


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _normalize_above(value: float, minimum: float, maximum: float) -> float:
    if maximum <= minimum:
        raise ValueError("normalization maximum must be greater than minimum")
    return _clamp((value - minimum) / (maximum - minimum), 0.0, 1.0)


@dataclass(frozen=True)
class MotionReading:
    sequence: int
    device_timestamp_ms: int
    twist: float
    tilt_x: float
    accel_mag: float
    accel_x_g: float
    accel_y_g: float
    accel_z_g: float
    gyro_x_dps: float
    gyro_y_dps: float
    gyro_z_dps: float
    gyro_xy_dps: float
    linear_accel_x_g: float
    linear_accel_y_g: float
    linear_accel_z_g: float
    burst: bool
    burst_strength: float
    burst_state: str
    burst_armed: bool


class MotionMapper:
    """Stateful normalization for tilt, twist, and burst detection."""

    def __init__(
        self,
        start_info: sdk.SensorStartInfo,
        config: RingConfig,
    ) -> None:
        self.start_info = start_info
        self.config = config
        if config.tilt_x_sign not in (-1, 1):
            raise ValueError("tilt_x_sign must be -1 or 1")
        if not 0.0 < config.tilt_x_ema_alpha <= 1.0:
            raise ValueError("tilt_x_ema_alpha must be in (0, 1]")
        if config.tilt_x_calibration_delay_s < 0:
            raise ValueError("tilt_x_calibration_delay_s cannot be negative")
        if not 0.0 <= config.tilt_x_deadzone_deg < config.tilt_x_full_scale_deg:
            raise ValueError(
                "tilt_x_deadzone_deg must be below tilt_x_full_scale_deg"
            )
        if not (
            config.tilt_x_deadzone_deg
            <= config.tilt_x_return_deg
            < config.tilt_x_enter_deg
            < config.tilt_x_full_scale_deg
        ):
            raise ValueError(
                "tilt thresholds must satisfy deadzone <= return < enter "
                "< full scale"
            )
        if config.tilt_x_neutral_dwell_ms < 0:
            raise ValueError("tilt_x_neutral_dwell_ms cannot be negative")
        if config.tilt_x_calibration_s <= 0:
            raise ValueError("tilt_x_calibration_s must be positive")
        if not 0.0 < config.gravity_ema_alpha <= 1.0:
            raise ValueError("gravity_ema_alpha must be in (0, 1]")
        self._twist_ema = 0.0
        self._tilt_x_ema = 0.0
        self._tilt_x_neutral_sum = 0.0
        self._tilt_x_neutral_deg = 0.0
        self._tilt_x_state = TILT_NEUTRAL
        self._tilt_x_direction = 0
        self._tilt_x_neutral_since_ms: float | None = None
        self._tilt_x_calibration_delay_total = max(
            0,
            round(
                float(start_info.sample_rate_hz)
                * config.tilt_x_calibration_delay_s
            ),
        )
        self._tilt_x_calibration_delay_remaining = (
            self._tilt_x_calibration_delay_total
        )
        self._tilt_x_calibration_total = max(
            1,
            round(
                float(start_info.sample_rate_hz)
                * config.tilt_x_calibration_s
            ),
        )
        self._tilt_x_calibration_remaining = self._tilt_x_calibration_total
        self._accel_ema = 0.0
        self._burst_gate = BurstStateMachine(config)
        self._gravity_g: list[float] | None = None

    def reset(self) -> None:
        self._twist_ema = 0.0
        self.reset_tilt_neutral()
        self._accel_ema = 0.0
        self._burst_gate.reset()
        self._gravity_g = None

    def reset_tilt_neutral(self) -> None:
        """Relearn only the tilt zero point without touching the BLE stream."""
        self._tilt_x_ema = 0.0
        self._tilt_x_neutral_sum = 0.0
        self._tilt_x_neutral_deg = 0.0
        self._tilt_x_state = TILT_NEUTRAL
        self._tilt_x_direction = 0
        self._tilt_x_neutral_since_ms = None
        self._tilt_x_calibration_delay_remaining = (
            self._tilt_x_calibration_delay_total
        )
        self._tilt_x_calibration_remaining = self._tilt_x_calibration_total

    def _raw_tilt_target(self, relative_tilt_deg: float) -> float:
        absolute_tilt = abs(relative_tilt_deg)
        if absolute_tilt <= self.config.tilt_x_deadzone_deg:
            return 0.0
        target = _normalize_above(
            absolute_tilt,
            self.config.tilt_x_deadzone_deg,
            self.config.tilt_x_full_scale_deg,
        )
        return -target if relative_tilt_deg < 0 else target

    def _map_tilt_state(
        self,
        relative_tilt_deg: float,
        now_ms: float,
    ) -> float:
        """Lock one tilt direction until a stable neutral return.

        The hand often overshoots zero while returning from a tilt. Without a
        state machine, that overshoot becomes a short opposite ``tiltX`` event.
        Once an outbound direction is locked, the returning phase therefore
        only decays toward zero. The opposite direction can be armed again only
        after the ring stays within the neutral band for the configured dwell.
        """

        absolute_tilt = abs(relative_tilt_deg)
        direction = 0
        if relative_tilt_deg > 0:
            direction = 1
        elif relative_tilt_deg < 0:
            direction = -1

        if self._tilt_x_state == TILT_NEUTRAL:
            if absolute_tilt < self.config.tilt_x_enter_deg:
                return 0.0
            self._tilt_x_state = TILT_ACTIVE
            self._tilt_x_direction = direction
            self._tilt_x_neutral_since_ms = None
            return self._raw_tilt_target(relative_tilt_deg)

        if self._tilt_x_state == TILT_ACTIVE:
            if (
                direction == self._tilt_x_direction
                and absolute_tilt > self.config.tilt_x_return_deg
            ):
                return self._raw_tilt_target(relative_tilt_deg)
            self._tilt_x_state = TILT_RETURNING
            self._tilt_x_neutral_since_ms = (
                now_ms
                if absolute_tilt <= self.config.tilt_x_return_deg
                else None
            )
            return 0.0

        # TILT_RETURNING: consume zero crossing and any opposite overshoot.
        if (
            direction == self._tilt_x_direction
            and absolute_tilt >= self.config.tilt_x_enter_deg
        ):
            self._tilt_x_state = TILT_ACTIVE
            self._tilt_x_neutral_since_ms = None
            return self._raw_tilt_target(relative_tilt_deg)

        if absolute_tilt <= self.config.tilt_x_return_deg:
            if self._tilt_x_neutral_since_ms is None:
                self._tilt_x_neutral_since_ms = now_ms
            if (
                now_ms - self._tilt_x_neutral_since_ms
                >= self.config.tilt_x_neutral_dwell_ms
            ):
                self._tilt_x_state = TILT_NEUTRAL
                self._tilt_x_direction = 0
                self._tilt_x_neutral_since_ms = None
        else:
            self._tilt_x_neutral_since_ms = None
        return 0.0

    def map_sample(
        self,
        sample: sdk.SensorDataSample,
        sequence: int,
        *,
        monotonic_ms: float | None = None,
    ) -> MotionReading:
        now_ms = (
            time.monotonic() * 1000.0
            if monotonic_ms is None
            else monotonic_ms
        )
        accel_range = max(1.0, float(self.start_info.accel_range_g))
        gyro_range = max(1.0, float(self.start_info.gyro_range_dps))

        accel_x_g = sample.accel_x / 32768.0 * accel_range
        accel_y_g = sample.accel_y / 32768.0 * accel_range
        accel_z_g = sample.accel_z / 32768.0 * accel_range
        gyro_x_dps = sample.gyro_x / 32768.0 * gyro_range
        gyro_y_dps = sample.gyro_y / 32768.0 * gyro_range
        gyro_z_dps = (
            sample.gyro_z
            / 32768.0
            * gyro_range
            * self.config.twist_sign
        )
        gyro_xy_dps = math.hypot(gyro_x_dps, gyro_y_dps)
        gyro_magnitude_dps = math.sqrt(
            gyro_x_dps * gyro_x_dps
            + gyro_y_dps * gyro_y_dps
            + gyro_z_dps * gyro_z_dps
        )

        acceleration = [accel_x_g, accel_y_g, accel_z_g]
        if self._gravity_g is None:
            self._gravity_g = acceleration.copy()
        linear_acceleration = [
            value - gravity
            for value, gravity in zip(acceleration, self._gravity_g, strict=True)
        ]
        gravity_alpha = self.config.gravity_ema_alpha
        self._gravity_g = [
            (1.0 - gravity_alpha) * gravity + gravity_alpha * value
            for value, gravity in zip(acceleration, self._gravity_g, strict=True)
        ]

        magnitude_g = math.sqrt(
            accel_x_g * accel_x_g
            + accel_y_g * accel_y_g
            + accel_z_g * accel_z_g
        )
        dynamic_g = abs(magnitude_g - 1.0)
        linear_magnitude_g = math.sqrt(
            sum(value * value for value in linear_acceleration)
        )
        accel_target = _normalize_above(
            dynamic_g,
            self.config.accel_min_g,
            self.config.accel_max_g,
        )
        self._accel_ema = (
            self.config.accel_ema_alpha * accel_target
            + (1.0 - self.config.accel_ema_alpha) * self._accel_ema
        )

        absolute_gyro = abs(gyro_z_dps)
        if absolute_gyro <= self.config.twist_deadzone_dps:
            twist_target = 0.0
        else:
            twist_target = _normalize_above(
                absolute_gyro,
                self.config.twist_deadzone_dps,
                self.config.twist_full_scale_dps,
            )
            if gyro_z_dps < 0:
                twist_target = -twist_target
        self._twist_ema = (
            self.config.twist_ema_alpha * twist_target
            + (1.0 - self.config.twist_ema_alpha) * self._twist_ema
        )
        if abs(self._twist_ema) < 0.005:
            self._twist_ema = 0.0

        raw_tilt_x_deg = math.degrees(
            math.atan2(
                accel_y_g,
                math.hypot(accel_x_g, accel_z_g) + 1e-6,
            )
        )
        # Accelerometer tilt is trustworthy only while the ring is relatively
        # still. A fast swing corrupts the gravity vector, so hold the previous
        # value instead of letting a burst create a false bend.
        tilt_pose_stable = (
            0.82 <= magnitude_g <= 1.18
            and gyro_magnitude_dps <= 120.0
        )
        tilt_calibration_delaying = (
            self._tilt_x_calibration_delay_remaining > 0
        )
        tilt_calibrating = self._tilt_x_calibration_remaining > 0
        if tilt_calibration_delaying:
            self._tilt_x_calibration_delay_remaining -= 1
            tilt_x_target = 0.0
        elif tilt_calibrating:
            if tilt_pose_stable:
                self._tilt_x_neutral_sum += raw_tilt_x_deg
                self._tilt_x_calibration_remaining -= 1
                if self._tilt_x_calibration_remaining == 0:
                    self._tilt_x_neutral_deg = (
                        self._tilt_x_neutral_sum
                        / self._tilt_x_calibration_total
                    )
            tilt_x_target = 0.0
        elif not tilt_pose_stable:
            tilt_x_target = self._tilt_x_ema
        else:
            relative_tilt_deg = (
                raw_tilt_x_deg - self._tilt_x_neutral_deg
            ) * self.config.tilt_x_sign
            tilt_x_target = self._map_tilt_state(
                relative_tilt_deg,
                now_ms,
            )
        self._tilt_x_ema = (
            self.config.tilt_x_ema_alpha * tilt_x_target
            + (1.0 - self.config.tilt_x_ema_alpha) * self._tilt_x_ema
        )
        if abs(self._tilt_x_ema) < 0.005:
            self._tilt_x_ema = 0.0

        burst_decision = self._burst_gate.update(
            dynamic_g=dynamic_g,
            gyro_magnitude_dps=gyro_magnitude_dps,
            timestamp_ms=now_ms,
            linear_magnitude_g=linear_magnitude_g,
            gyro_z_dps=gyro_z_dps,
        )
        return MotionReading(
            sequence=sequence,
            device_timestamp_ms=sample.timestamp_ms,
            twist=round(_clamp(self._twist_ema, -1.0, 1.0), 5),
            tilt_x=round(_clamp(self._tilt_x_ema, -1.0, 1.0), 5),
            accel_mag=round(_clamp(self._accel_ema, 0.0, 1.0), 5),
            accel_x_g=round(accel_x_g, 5),
            accel_y_g=round(accel_y_g, 5),
            accel_z_g=round(accel_z_g, 5),
            gyro_x_dps=round(gyro_x_dps, 3),
            gyro_y_dps=round(gyro_y_dps, 3),
            gyro_z_dps=round(gyro_z_dps, 3),
            gyro_xy_dps=round(gyro_xy_dps, 3),
            linear_accel_x_g=round(linear_acceleration[0], 5),
            linear_accel_y_g=round(linear_acceleration[1], 5),
            linear_accel_z_g=round(linear_acceleration[2], 5),
            burst=burst_decision.triggered,
            burst_strength=round(burst_decision.strength, 5),
            burst_state=burst_decision.state,
            burst_armed=burst_decision.armed,
        )

