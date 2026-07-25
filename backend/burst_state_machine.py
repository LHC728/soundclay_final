"""Stateful one-shot burst detection with explicit return-to-ready rearming."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math

from ring_config import RingConfig


ARMED = "armed"
OUTWARD_ACTIVE = "outward_active"
WAIT_RETURN = "wait_return"
RETURNING = "returning"


@dataclass(frozen=True)
class BurstDecision:
    triggered: bool
    strength: float
    state: str

    @property
    def armed(self) -> bool:
        return self.state == ARMED


class BurstStateMachine:
    """Emit once for an outward swing and consume the following return."""

    def __init__(self, config: RingConfig) -> None:
        if config.burst_window_samples < 1:
            raise ValueError("burst_window_samples must be at least 1")
        if not (
            1
            <= config.burst_min_active_samples
            <= config.burst_window_samples
        ):
            raise ValueError(
                "burst_min_active_samples must be between 1 and "
                "burst_window_samples"
            )
        if config.accel_max_g <= config.accel_min_g:
            raise ValueError("accel_max_g must be greater than accel_min_g")
        if config.burst_min_linear_accel_g < 0:
            raise ValueError("burst_min_linear_accel_g cannot be negative")
        if not 0 <= config.burst_max_twist_share <= 1:
            raise ValueError("burst_max_twist_share must be between 0 and 1")
        if config.burst_quiet_dwell_ms <= 0:
            raise ValueError("burst_quiet_dwell_ms must be positive")
        if config.burst_return_min_active_samples < 1:
            raise ValueError(
                "burst_return_min_active_samples must be at least 1"
            )
        self.config = config
        self._window: deque[float] = deque(
            maxlen=config.burst_window_samples
        )
        self.state = ARMED
        self._quiet_started_ms: float | None = None
        self._return_active_samples = 0

    def reset(self) -> None:
        self._window.clear()
        self.state = ARMED
        self._quiet_started_ms = None
        self._return_active_samples = 0

    def update(
        self,
        *,
        dynamic_g: float,
        gyro_magnitude_dps: float,
        timestamp_ms: float,
        linear_magnitude_g: float | None = None,
        gyro_z_dps: float = 0.0,
    ) -> BurstDecision:
        strength = max(
            0.0,
            min(
                1.0,
                (
                    dynamic_g - self.config.accel_min_g
                )
                / (
                    self.config.accel_max_g
                    - self.config.accel_min_g
                ),
            ),
        )
        quiet = (
            dynamic_g <= self.config.burst_quiet_accel_g
            and gyro_magnitude_dps <= self.config.burst_quiet_gyro_dps
        )
        # Returning the hand produces a clear translational acceleration
        # before the high-energy braking peak.  Gyroscope-only motion is not
        # sufficient here: real logs show small wrist adjustments while the
        # hand is held forward can exceed 120 dps and falsely re-arm the
        # detector before the actual return.
        return_motion = dynamic_g >= self.config.burst_return_accel_g
        triggered = False
        trigger_strength = strength
        translation_g = (
            dynamic_g
            if linear_magnitude_g is None
            else linear_magnitude_g
        )
        twist_share = (
            abs(gyro_z_dps) / gyro_magnitude_dps
            if gyro_magnitude_dps > 1e-6
            else 0.0
        )

        if self.state == ARMED:
            active_strength = (
                strength
                if (
                    strength >= self.config.burst_threshold
                    and translation_g
                    >= self.config.burst_min_linear_accel_g
                    and gyro_magnitude_dps
                    <= self.config.burst_max_gyro_dps
                    and twist_share
                    <= self.config.burst_max_twist_share
                )
                else 0.0
            )
            self._window.append(active_strength)
            if (
                len(self._window) == self.config.burst_window_samples
                and sum(value > 0.0 for value in self._window)
                >= self.config.burst_min_active_samples
            ):
                triggered = True
                trigger_strength = max(self._window, default=strength)
                self.state = OUTWARD_ACTIVE
                self._window.clear()
                self._quiet_started_ms = None
                self._return_active_samples = 0

        elif self.state == OUTWARD_ACTIVE:
            if self._quiet_elapsed(quiet, timestamp_ms):
                self.state = WAIT_RETURN
                self._quiet_started_ms = None
                self._return_active_samples = 0

        elif self.state == WAIT_RETURN:
            if return_motion:
                self._return_active_samples += 1
                if (
                    self._return_active_samples
                    >= self.config.burst_return_min_active_samples
                ):
                    self.state = RETURNING
                    self._quiet_started_ms = None
            else:
                self._return_active_samples = 0

        elif self.state == RETURNING:
            if self._quiet_elapsed(quiet, timestamp_ms):
                self.state = ARMED
                self._window.clear()
                self._quiet_started_ms = None
                self._return_active_samples = 0
        else:
            raise RuntimeError(f"unknown burst state: {self.state}")

        if not math.isfinite(trigger_strength):
            trigger_strength = 0.0
        return BurstDecision(
            triggered=triggered,
            strength=trigger_strength,
            state=self.state,
        )

    def _quiet_elapsed(self, quiet: bool, timestamp_ms: float) -> bool:
        if not quiet:
            self._quiet_started_ms = None
            return False
        if self._quiet_started_ms is None:
            self._quiet_started_ms = timestamp_ms
            return False
        return (
            timestamp_ms - self._quiet_started_ms
            >= self.config.burst_quiet_dwell_ms
        )

