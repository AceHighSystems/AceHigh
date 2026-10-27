"""Offline assembly-specific calibration from three Studio CSV exports.

No CAN connection is opened. Requires only the project's numpy/scipy dependencies.
Run from the project root; pass standstill, holds and rotation captures in that order.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.signal import find_peaks, savgol_filter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from calibrated_encoder import CalibratedEncoder


def load_capture(path):
    """Join channels by sample_index, never by their order or rounded receipt time."""
    channels = [dict() for _ in range(14)]
    with Path(path).open(newline='') as stream:
        for row in csv.DictReader(stream):
            name = row['channel']
            if name not in {f'ch{i}' for i in range(14)}:
                continue
            channel = channels[int(name[2:])]
            index = int(row['sample_index'])
            if index in channel:
                raise ValueError(f'Duplicate sample {name}/{index} in {path}')
            raw = int(row['raw_value'])
            timestamp = float(row['host_receive_elapsed_s'])
            if not 0 <= raw <= 0xFFFFFF or not np.isfinite(timestamp):
                raise ValueError(f'Invalid PCAP value or timestamp in {path}')
            channel[index] = (raw, timestamp)
    common = sorted(set.intersection(*(set(channel) for channel in channels)))
    union = set.union(*(set(channel) for channel in channels))
    if len(common) < 200:
        raise ValueError('At least 200 complete fourteen-channel scans are required.')
    values = np.array([[channel[index][0] for channel in channels] for index in common], dtype=float)
    times = np.array([[channel[index][1] for channel in channels] for index in common])
    return {'y': values, 't': times.mean(axis=1), 'index': np.array(common),
            'dropped_incomplete_indices': len(union) - len(common)}


def basis(degrees, harmonics):
    phase = np.radians(np.asarray(degrees).reshape(-1, 1)) * np.arange(1, harmonics + 1)
    return np.column_stack([np.ones(len(phase)), np.sin(phase), np.cos(phase)])


def stable_holds(values, spans):
    """Find gross repositioning events, then trim settling around each plateau."""
    normalized = values / spans
    changes = np.linalg.norm(normalized[25:] - normalized[:-25], axis=1)
    peaks, _ = find_peaks(changes, prominence=0.08, distance=500)
    edges = np.r_[0, peaks + 12, len(values)]
    return [(int(start + 150), int(stop - 150)) for start, stop in zip(edges[:-1], edges[1:])
            if stop - start >= 500]


def calibrate(paths, output, report_path, nominal_period=102.4):
    captures = [load_capture(path) for path in paths]
    stationary, holds, rotating = captures
    y = rotating['y']
    span = np.ptp(y, axis=0)
    if np.any(span <= 0):
        raise ValueError('Every channel must vary during calibration.')
    # Receipt batches repeat timestamps. Smooth just the OFFLINE time reference
    # over ~2 seconds, preserving slow scan-rate variation. Never synthesize a
    # live angle from elapsed time or motor commands.
    times = savgol_filter(rotating['t'], 101, 2)
    if np.any(np.diff(times) <= 0):
        raise ValueError('Rotation capture time must increase.')
    stride = np.arange(0, len(y), 10)
    z = (y - y.mean(axis=0)) / span
    harmonics = 18

    def loss(period):
        matrix = basis(360 * (times[stride] - times[0]) / period, harmonics)
        coefficients = np.linalg.lstsq(matrix, z[stride], rcond=None)[0]
        return float(np.mean((matrix @ coefficients - z[stride]) ** 2))

    optimum = minimize_scalar(loss, bounds=(nominal_period * 0.98, nominal_period * 1.02),
                              method='bounded', options={'xatol': 1e-7})
    period = float(optimum.x)
    if not optimum.success or abs(period / nominal_period - 1) > 0.019:
        raise ValueError('Rotation is inconsistent with the supplied nominal speed.')
    phase = 360 * (times - times[0]) / period
    if np.ptp(phase) < 3 * 360:
        raise ValueError('Record at least three complete constant-speed revolutions.')
    matrix = basis(phase, harmonics)
    coefficients = np.linalg.lstsq(matrix, y, rcond=None)[0]
    residual = y - matrix @ coefficients
    windows = stable_holds(holds['y'], span)
    if len(windows) < 2:
        raise ValueError('Could not identify stationary holds.')
    # Include slow stationary variation; repeated PCAP values are not independent
    # noise samples, so differencing adjacent scans would underestimate variance.
    noise_blocks = [stationary['y'] - stationary['y'].mean(axis=0)]
    for start, stop in windows:
        block = holds['y'][start:stop]
        noise_blocks.append(block - np.median(block, axis=0))
    noise = np.cov(np.vstack(noise_blocks), rowvar=False)
    motion = np.cov(residual, rowvar=False)
    # Shrink correlations for conditioning and include model/sequential-scan error
    # to avoid overweighting small but drifting sector signals (ch0/ch7).
    covariance = noise + 0.75 * motion + 0.25 * np.diag(np.diag(motion))
    covariance += np.eye(14) * max(float(np.trace(covariance)) / 14 * 1e-8, 1.0)
    minimum = y.min(axis=0)
    normalized = 2 * (y - minimum) / span - 1
    fine = [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13]
    target = np.column_stack([np.cos(np.radians(3 * phase)), np.sin(np.radians(3 * phase))])
    qfit = np.linalg.lstsq(np.column_stack([np.ones(len(y)), normalized[:, fine]]), target, rcond=None)[0]
    weights = np.zeros((14, 2)); weights[fine] = qfit[1:]
    data = {
        'source_channels': list(range(14)),
        'normalization_min': minimum.tolist(), 'normalization_span': span.tolist(),
        'fine_channels': fine,
        'template_model': {'harmonics': harmonics,
                           'coefficient_basis': '1, sin(k theta), cos(k theta); theta mechanical radians',
                           'coefficients': coefficients.tolist()},
        'calibration': {'combined': {'weights_C_S': weights.tolist(),
                                    'offset_C_S': qfit[0].tolist(),
                                    'ellipse_parameters': [0, 0, 0, 0, 0]}},
        'GLS': {'noise_covariance': covariance.tolist()},
        'max_fit_error': 12.0,
        'reference': {
            'assembly': 'Ranger NEMA14 PCAP02, reassembled, 18 October 2026',
            'captures': [{'name': Path(path).name,
                          'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                          'complete_scans': len(capture['y']),
                          'dropped_incomplete_indices': capture['dropped_incomplete_indices']}
                         for path, capture in zip(paths, captures)],
            'zero': 'First retained rotating-capture scan; not a surveyed mechanical zero',
            'channel_order': [f'ch{i}' for i in range(14)],
            'nominal_step_pulses_s': 51200 / nominal_period, 'microsteps': 256, 'full_steps_per_turn': 200,
            'nominal_period_s': nominal_period, 'fitted_period_s': period,
            'angle_reference': 'Constant-speed assumption, locally smoothed browser receipt times',
            'method': '18-harmonic full-pattern model; stationary noise plus shrunk motion-residual covariance',
            'fit_gate': 'Whitened RMS <=12; gross mismatch check, not an angular accuracy bound.'}}
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2) + '\n')
    decoder = CalibratedEncoder(output)
    summary = {'fitted_period_s': period, 'nominal_period_s': nominal_period, 'captures': [],
               'stationary_holds': [], 'limits': [
                   'Offline replay only; physical CAN/module operation has not been tested.',
                   'Motor speed and capture time supply the angle reference; no independent angle standard.',
                   'Sequential CAN reads and asynchronous PCAP updates limit dynamic reconstruction.',
                   'Specific to this assembly. Recalibrate after mechanical/settings changes.']}
    decoded = []
    for capture in captures:
        a = decoder.decode(capture['y']); decoded.append(a)
        errors = np.sqrt(np.mean(((capture['y'] - decoder._basis(a) @ coefficients)
                                 @ decoder.whiten.T) ** 2, axis=1))
        summary['captures'].append({'complete_scans': len(a),
            'rejected_scans': int(np.sum(errors > data['max_fit_error'])),
            'fit_error_median': float(np.median(errors)), 'fit_error_max': float(errors.max())})
    unwrapped = np.degrees(np.unwrap(np.radians(decoded[0])))
    summary['standstill_rms_deg'] = float(np.std(unwrapped))
    summary['standstill_peak_to_peak_deg'] = float(np.ptp(unwrapped))
    for start, stop in windows:
        a = np.degrees(np.unwrap(np.radians(decoded[1][start:stop])))
        summary['stationary_holds'].append({'start_index': int(holds['index'][start]),
            'stop_index_exclusive': int(holds['index'][stop - 1]) + 1,
            'mean_deg': float(np.mean(a) % 360), 'rms_deg': float(np.std(a))})
    motion_error = (decoded[2] - phase + 180) % 360 - 180
    unwrapped = np.degrees(np.unwrap(np.radians(decoded[2])))
    summary['rotation_rms_about_speed_reference_deg'] = float(np.std(motion_error))
    summary['rotation_max_abs_about_speed_reference_deg'] = float(np.max(np.abs(motion_error)))
    summary['rotation_turns'] = float((unwrapped[-1] - unwrapped[0]) / 360)
    summary['rotation_max_adjacent_change_deg'] = float(np.max(np.abs(np.diff(unwrapped))))
    # Different complete revolutions for training and validation. Reference period
    # is shared; coefficients are never trained on the held-out revolutions.
    train = np.floor(phase / 360).astype(int) % 2 == 0
    held_coefficients = np.linalg.lstsq(matrix[train], y[train], rcond=None)[0]
    held_data = dict(data); held_data['template_model'] = dict(data['template_model'])
    held_data['template_model']['coefficients'] = held_coefficients.tolist()
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
        candidate = Path(directory) / 'held.json'; candidate.write_text(json.dumps(held_data))
        held_decoder = CalibratedEncoder(candidate)
        a = held_decoder.decode(y[~train]); e = (a - phase[~train] + 180) % 360 - 180
        summary['held_out_rotation_rms_deg'] = float(np.std(e))
        summary['held_out_rotation_max_abs_deg'] = float(np.max(np.abs(e)))
    Path(report_path).write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))
    return captures, decoded, summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('standstill', type=Path)
    parser.add_argument('holds', type=Path)
    parser.add_argument('rotation', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'backend/encoder_calibration.json')
    parser.add_argument('--report', type=Path, default=ROOT / 'CALIBRATION-2026-10-18.json')
    parser.add_argument('--nominal-period', type=float, default=102.4)
    args = parser.parse_args()
    calibrate([args.standstill, args.holds, args.rotation], args.output, args.report, args.nominal_period)
