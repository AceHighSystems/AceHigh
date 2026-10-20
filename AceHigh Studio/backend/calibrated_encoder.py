"""Assembly-specific fourteen-channel full-pattern absolute-angle decoder.

Dependencies: numpy and scipy. The zero is the fitted capture reference,
not a surveyed mechanical zero. Calibration is specific to this assembly and
acquisition configuration. Absolute accuracy is not independently established.

Usage:
    encoder = CalibratedEncoder('encoder_calibration.json')
    angle_deg = encoder.decode([ch0, ch1, ..., ch13])
    cosine, sine = encoder.quadrature([ch0, ch1, ..., ch13])
"""

import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree


class CalibratedEncoder:
    def __init__(self, calibration_path):
        data = json.loads(Path(calibration_path).read_text())
        self.data = data
        self.coefficients = np.asarray(data['template_model']['coefficients'])
        self.frequency = np.arange(1, data['template_model']['harmonics'] + 1)
        covariance = np.asarray(data['GLS']['noise_covariance'])
        if (self.coefficients.shape != (1 + 2 * len(self.frequency), 14)
                or covariance.shape != (14, 14)
                or not np.isfinite(self.coefficients).all()
                or not np.isfinite(covariance).all()):
            raise ValueError('Invalid fourteen-channel encoder calibration.')
        self.whiten = np.linalg.inv(np.linalg.cholesky(covariance))
        self.grid = np.arange(0, 360, 0.05)
        template = self._basis(self.grid) @ self.coefficients
        self.tree = cKDTree(template @ self.whiten.T)

    def _basis(self, angles, derivative=False):
        phase = np.radians(np.asarray(angles).reshape(-1))[:, None] * self.frequency
        if derivative:
            w = np.pi / 180 * self.frequency
            return np.column_stack([
                np.zeros(len(phase)), np.cos(phase) * w, -np.sin(phase) * w
            ])
        return np.column_stack([
            np.ones(len(phase)), np.sin(phase), np.cos(phase)
        ])

    @staticmethod
    def _input(raw_channels):
        values = np.asarray(raw_channels, dtype=float)
        scalar = values.ndim == 1
        values = np.atleast_2d(values)
        if values.ndim != 2 or values.shape[1] != 14:
            raise ValueError('Expected fourteen channels in ch0..ch13 order.')
        if not np.isfinite(values).all():
            raise ValueError('Channel values must be finite.')
        return values, scalar

    def decode(self, raw_channels):
        """Decode each vector independently to the fitted 0..360 degree reference.

        No angular tracking or temporal smoothing is applied. Callers must
        supply consistent scans; host timestamps do not guarantee alignment.
        """
        y, scalar = self._input(raw_channels)
        _, index = self.tree.query(y @ self.whiten.T)
        angles = self.grid[index].copy()
        for _ in range(7):
            residual = (self._basis(angles) @ self.coefficients - y) @ self.whiten.T
            gradient = (self._basis(angles, True) @ self.coefficients) @ self.whiten.T
            denominator = np.sum(gradient * gradient, axis=1)
            if np.any(denominator <= 0) or not np.isfinite(denominator).all():
                raise ValueError('Encoder calibration has no usable angular sensitivity.')
            step = np.sum(gradient * residual, axis=1) / denominator
            angles -= np.clip(step, -0.3, 0.3)
        angles %= 360
        return float(angles[0]) if scalar else angles

    def fit_error(self, raw_channels, degrees):
        """Whitened channel RMS; this is a model-match score, not degrees."""
        values, scalar = self._input(raw_channels)
        prediction = self._basis(degrees) @ self.coefficients
        if prediction.shape != values.shape:
            raise ValueError('Supply one angle for each fourteen-channel vector.')
        residual = (values - prediction) @ self.whiten.T
        result = np.sqrt(np.mean(residual ** 2, axis=1))
        return float(result[0]) if scalar else result

    def quadrature(self, raw_channels):
        """Return measured offset/gain/ellipse-corrected twelve-electrode C/S."""
        y, scalar = self._input(raw_channels)
        minimum = np.asarray(self.data['normalization_min'])
        span = np.asarray(self.data['normalization_span'])
        normalized = 2 * (y - minimum) / span - 1
        calibration = self.data['calibration']['combined']
        q = (normalized @ np.asarray(calibration['weights_C_S'])
             + np.asarray(calibration.get('offset_C_S', [0.0, 0.0])))
        p = np.asarray(calibration['ellipse_parameters'])
        matrix = np.array([[np.exp(p[2]), p[3]], [0, np.exp(p[4])]])
        q = (q - p[:2]) @ matrix.T
        return q[0] if scalar else q
