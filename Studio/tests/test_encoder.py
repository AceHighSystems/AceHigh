import asyncio
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from encoder import AngleEstimate, EncoderEstimator, AngleOutputFilter
from telemetry import SIGNALS, TelemetryService


def test_display_direction_is_inverted_and_zero_is_preserved():
    filter_ = AngleOutputFilter()
    assert filter_.update(30, 1.0) == 330
    filter_.reset()
    assert filter_.update(0, 2.0) == 0


def test_filter_crosses_zero_using_the_short_arc():
    filter_ = AngleOutputFilter(tau_s=0.15, direction=1)
    filter_.update(359.9, 0.0)
    value = filter_.update(0.1, 0.02)
    assert 359.9 < value < 360
    for index in range(2, 101):
        value = filter_.update(0.1, index * 0.02)
    assert abs(value - 0.1) < 0.001


def test_filter_reduces_stationary_jitter():
    filter_ = AngleOutputFilter(tau_s=0.15)
    noise = np.random.default_rng(42).normal(0, 0.02, 1000)
    output = np.array([filter_.update(100 + value, index * 0.02)
                       for index, value in enumerate(noise)])
    assert np.std(output[100:]) < np.std(noise[100:]) * 0.4


def test_filter_has_consistent_time_response_and_resets_after_a_gap():
    fast = AngleOutputFilter(tau_s=0.15, direction=1)
    slow = AngleOutputFilter(tau_s=0.15, direction=1)
    fast.update(0, 0)
    slow.update(0, 0)
    for index in range(1, 51):
        fast.update(10, index * 0.01)
    for index in range(1, 6):
        result = slow.update(10, index * 0.1)
    assert abs(fast.update(10, 0.5) - result) < 1e-10
    assert slow.update(120, 2.0) == 120
    slow.reset()
    assert slow.update(250, 3.0) == 250


def test_full_pattern_reconstruction_covers_all_three_sectors():
    estimator = EncoderEstimator()
    expected = np.arange(0, 360, 1.0)
    raw = np.rint(estimator.decoder._basis(expected) @ estimator.decoder.coefficients)
    decoded = np.array([estimator.estimate(row).degrees for row in raw])
    error = (decoded - expected + 180) % 360 - 180
    assert np.max(np.abs(error)) < 0.002


@pytest.mark.parametrize("raw", [np.zeros(14), np.ones(13), np.full(14, np.nan),
                                   np.full(14, -1), np.full(14, 2**24)])
def test_bad_or_uncalibrated_raw_data_is_rejected(raw):
    with pytest.raises(ValueError):
        EncoderEstimator().estimate(raw)


def test_partial_scans_never_fill_missing_channels_from_an_older_pass():
    async def scenario():
        class Can:
            cycle = 0
            async def read(self, node, parameter):
                if parameter == "ch0":
                    self.cycle += 1
                await asyncio.sleep(0)
                if self.cycle == 1 and parameter == "ch7":
                    return 3, None
                return 2, self.cycle * 100 + int(parameter[2:])

        class Estimator:
            calls = []
            def estimate(self, values):
                self.calls.append(values)
                return AngleEstimate(12.345, 0.0)

        estimator = Estimator()
        telemetry = TelemetryService(Can(), estimator)
        for signal in SIGNALS:
            telemetry.ensure_stream(2, signal, 100)
        for _ in range(100):
            angle = telemetry.latest_angles.get(2)
            if angle and angle.sequence >= 2:
                break
            await asyncio.sleep(0.001)
        else:
            pytest.fail("Expected two completed scan attempts")
        assert estimator.calls[0] == list(range(200, 214))
        assert telemetry.latest_angles[2].degrees == 12.345
        task = telemetry._scan_tasks[2]
        for signal in SIGNALS:
            telemetry.stop_stream(2, signal)
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_supplied_display_settings_preserve_unsmoothed_response():
    output = AngleOutputFilter()
    assert output.tau_s == 0.0
    assert output.update(359.9, 0) == pytest.approx(0.1)
    assert output.update(0.1, 0.02) == pytest.approx(359.9)


@pytest.mark.parametrize('capture', [0, 1, 2])
def test_real_reassembled_module_scans_reach_angle_output(capture):
    fixture = np.load(ROOT / 'tests' / 'fixtures' / f'capture_{capture}.npz')
    estimator = EncoderEstimator()
    angles = np.array([estimator.estimate(row).degrees for row in fixture['raw']])
    assert np.isfinite(angles).all()
    # Decode in reverse order too: sector choice must not depend on prior
    # movement, a clock, a commanded velocity or a presumed rotation direction.
    reverse = np.array([estimator.estimate(row).degrees for row in fixture['raw'][::-1]])
    assert np.allclose(angles, reverse[::-1], atol=1e-10)
    if capture == 0:
        assert np.std(angles) < 0.025
    elif capture == 1:
        for hold in range(10):
            assert np.std(angles[fixture['hold'] == hold]) < 0.04
    else:
        reference = fixture['speed_reference']
        error = (angles - reference + 180) % 360 - 180
        assert np.std(error) < 0.18
        assert np.max(np.abs(error)) < 0.65
        unwrapped = np.degrees(np.unwrap(np.radians(angles)))
        assert 4.0 < (unwrapped[-1] - unwrapped[0]) / 360 < 4.05


def test_live_telemetry_accepts_real_capture_and_rejects_incomplete_scan():
    fixture = np.load(ROOT / 'tests' / 'fixtures' / 'capture_0.npz')
    estimator = EncoderEstimator()
    telemetry = TelemetryService(object(), estimator)
    scan = dict(zip(SIGNALS, fixture['raw'][0]))
    telemetry._publish_angle(2, scan, 1.0, 1.02)
    sample = telemetry.latest_angles[2]
    assert sample.error is None
    assert sample.degrees == pytest.approx(estimator.estimate(fixture['raw'][0]).degrees)
    del scan['ch7']
    telemetry._publish_angle(2, scan, 1.02, 1.04)
    assert 'Incomplete encoder scan' in telemetry.latest_angles[2].error
