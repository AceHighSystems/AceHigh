"""Calibrated absolute-angle prototype, evaluated once per complete raw scan."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math

import numpy as np

from calibrated_encoder import CalibratedEncoder

# Preserve the supplied display direction and disabled smoothing. The raw
# reconstruction is independent of motor speed, commands and previous angles.
ANGLE_DIRECTION = -1
ANGLE_FILTER_TAU_S = 0.0


class AngleOutputFilter:
    """Time-based low-pass using the shortest angular difference at each update."""
    def __init__(self, tau_s=ANGLE_FILTER_TAU_S, direction=ANGLE_DIRECTION, reset_gap_s=1.0):
        if not math.isfinite(tau_s) or tau_s < 0:
            raise ValueError("Filter time constant must be finite and non-negative.")
        if direction not in (-1, 1):
            raise ValueError("Angle direction must be -1 or 1.")
        if not math.isfinite(reset_gap_s) or reset_gap_s <= 0:
            raise ValueError("Reset gap must be finite and positive.")
        self.tau_s = tau_s
        self.direction = direction
        self.reset_gap_s = reset_gap_s
        self.reset()

    def reset(self):
        self._value = None
        self._time = None

    def update(self, degrees, timestamp):
        if not math.isfinite(degrees) or not math.isfinite(timestamp):
            raise ValueError("Angle and timestamp must be finite.")
        oriented = (self.direction * degrees) % 360.0
        if self._time is None or timestamp - self._time > self.reset_gap_s:
            self._value = oriented
        elif timestamp <= self._time:
            return self._value
        else:
            dt = timestamp - self._time
            alpha = 1.0 if self.tau_s == 0 else -math.expm1(-dt / self.tau_s)
            delta = (oriented - self._value + 180.0) % 360.0 - 180.0
            self._value = (self._value + alpha * delta) % 360.0
        self._time = timestamp
        return self._value


@dataclass(frozen=True)
class AngleEstimate:
    degrees: float
    fit_error: float


class EncoderEstimator:
    def __init__(self, calibration_path=None):
        if calibration_path is None:
            calibration_path = Path(__file__).with_name("encoder_calibration.json")
        self.decoder = CalibratedEncoder(calibration_path)
        self.max_fit_error = float(self.decoder.data["max_fit_error"])
        if not math.isfinite(self.max_fit_error) or self.max_fit_error <= 0:
            raise ValueError("Encoder fit threshold must be finite and positive.")

    def estimate(self, raw_channels):
        values = np.asarray(raw_channels, dtype=float)
        if values.shape != (14,) or not np.isfinite(values).all():
            raise ValueError("A complete finite ch0..ch13 scan is required.")
        if np.any(values < 0) or np.any(values > 0xFFFFFF) or np.any(values != np.floor(values)):
            raise ValueError("PCAP02 channels must be unsigned 24-bit integer results.")
        degrees = self.decoder.decode(values)
        fit_error = self.decoder.fit_error(values, degrees)
        if not np.isfinite(degrees) or not np.isfinite(fit_error):
            raise ValueError("Encoder reconstruction produced an invalid result.")
        if fit_error > self.max_fit_error:
            raise ValueError("Raw channels do not match the calibration; check the assembly, settings and channel mapping.")
        return AngleEstimate(float(degrees % 360.0), fit_error)
