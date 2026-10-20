from __future__ import annotations

import asyncio
from dataclasses import dataclass

from can_service import CanService
from ringbuffer import BufferSlice, UInt32RingBuffer


@dataclass(frozen=True)
class SignalDefinition:
    signal_id: int
    capacity: int = 16_384


@dataclass(frozen=True)
class AngleSample:
    sequence: int
    completed_at: float
    scan_duration_s: float
    degrees: float | None = None
    fit_error: float | None = None
    error: str | None = None


# Raw Ranger encoder channels.
#
# AceLight API:
#
#     ace.read(node_id, "ch0")
#     ...
#     ace.read(node_id, "ch13")
#
# signal_id is used by the compact binary WebSocket packet.
SIGNALS = {
    f"ch{i}": SignalDefinition(signal_id=i + 1)
    for i in range(14)
}


class TelemetryService:
    """
    Ranger raw-channel acquisition service.

    One acquisition task is created per Ranger node.

    Instead of creating one asyncio task for every raw channel, the task
    performs a complete sequential encoder scan:

        ch0 -> ch1 -> ... -> ch13

    The requested rate_hz therefore represents complete scans per second.

    Raw encoder values are preserved as uint32 end-to-end.
    """

    def __init__(self, can_service: CanService, angle_estimator=None):
        self.can = can_service
        self.angle_estimator = angle_estimator
        self.latest_angles: dict[int, AngleSample] = {}
        self._angle_sequences: dict[int, int] = {}

        self.buffers = {
            name: UInt32RingBuffer(definition.capacity)
            for name, definition in SIGNALS.items()
        }

        # One task per Ranger node.
        self._scan_tasks: dict[int, asyncio.Task] = {}

        # Signals currently requested for each node.
        self._active_signals: dict[int, set[str]] = {}

        # Requested complete scan rate for each node.
        self._scan_rates: dict[int, float] = {}

    def signal_id(self, signal: str) -> int:
        return SIGNALS[signal].signal_id

    def ensure_stream(
        self,
        node_id: int,
        signal: str,
        rate_hz: float = 10.0,
    ):
        """
        Enable one signal in the node's acquisition scan.

        Calling this fourteen times for ch0...ch13 still creates only ONE
        polling task.
        """

        if signal not in SIGNALS:
            raise KeyError(f"Unknown telemetry signal: {signal}")

        node_id = int(node_id)
        rate_hz = max(float(rate_hz), 0.1)

        active = self._active_signals.setdefault(node_id, set())
        active.add(signal)

        # All raw channels currently use one common scan rate.
        self._scan_rates[node_id] = rate_hz

        task = self._scan_tasks.get(node_id)

        if task is None or task.done():
            self._scan_tasks[node_id] = asyncio.create_task(
                self._scan_loop(node_id)
            )

    def stop_stream(self, node_id: int, signal: str):
        """
        Remove one signal from the node's acquisition scan.

        The scan task is cancelled only when no signals remain.
        """

        node_id = int(node_id)

        active = self._active_signals.get(node_id)

        if active is None:
            return

        active.discard(signal)

        if active:
            return

        # No remaining signals for this node.
        self._active_signals.pop(node_id, None)
        self._scan_rates.pop(node_id, None)
        self.latest_angles.pop(node_id, None)

        task = self._scan_tasks.pop(node_id, None)

        if task is not None and not task.done():
            task.cancel()

    async def _scan_loop(self, node_id: int):
        """
        Sequentially acquire all enabled channels.

        One iteration represents one complete encoder scan.
        """

        loop = asyncio.get_running_loop()

        try:
            while True:
                scan_started = loop.time()

                active = self._active_signals.get(node_id)

                if not active:
                    return

                # Each pass builds a new vector; never reuse a failed channel
                # from an older pass. Completed scans are still sequential CAN
                # reads, not simultaneous PCAP02 conversion snapshots.
                scan = {}
                # SIGNALS preserves insertion order: ch0, ch1, ... ch13.
                for signal in SIGNALS:

                    if signal not in active:
                        continue

                    try:
                        status, value = await self.can.read(
                            node_id,
                            signal,
                        )

                        if status == 2 and value is not None and 0 <= value <= 0xFFFFFF:
                            self.buffers[signal].append(value)
                            scan[signal] = int(value)

                    except asyncio.CancelledError:
                        raise

                    except Exception:
                        # One failed CAN transaction should not kill
                        # the complete encoder acquisition task.
                        pass

                completed = loop.time()
                if set(SIGNALS).issubset(active):
                    self._publish_angle(node_id, scan, scan_started, completed)
                scan_elapsed = loop.time() - scan_started

                rate_hz = self._scan_rates.get(
                    node_id,
                    10.0,
                )

                scan_period = 1.0 / max(rate_hz, 0.1)

                await asyncio.sleep(
                    max(0.0, scan_period - scan_elapsed)
                )

        except asyncio.CancelledError:
            raise

    def _publish_angle(self, node_id, scan, started, completed):
        sequence = self._angle_sequences.get(node_id, 0) + 1
        self._angle_sequences[node_id] = sequence
        metadata = {"sequence": sequence, "completed_at": completed,
                    "scan_duration_s": completed - started}
        try:
            if len(scan) != 14:
                missing = ", ".join(signal for signal in SIGNALS if signal not in scan)
                raise ValueError(f"Incomplete encoder scan: {missing}")
            if self.angle_estimator is None:
                raise ValueError("Encoder calibration is not loaded.")
            estimate = self.angle_estimator.estimate([scan[signal] for signal in SIGNALS])
            self.latest_angles[node_id] = AngleSample(
                **metadata, degrees=estimate.degrees, fit_error=estimate.fit_error)
        except Exception as exc:
            self.latest_angles[node_id] = AngleSample(**metadata, error=str(exc))

    def read_since(
        self,
        signal: str,
        sequence: int,
    ) -> BufferSlice:

        return self.buffers[signal].read_since(sequence)
