from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BufferSlice:
    start_sequence: int
    end_sequence: int
    samples: np.ndarray
    overrun: bool


class UInt32RingBuffer:
    """
    Fixed-size uint32 ring buffer.

    Intended for raw Ranger encoder/FDC measurements.

    sequence is an absolute sample counter:

        0, 1, 2, 3, ...

    This preserves the raw 32-bit integer measurement exactly.
    """

    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")

        self.capacity = int(capacity)

        self._data = np.zeros(
            self.capacity,
            dtype=np.uint32,
        )

        self._write_count = 0
        self._lock = threading.Lock()

    @property
    def write_count(self) -> int:
        with self._lock:
            return self._write_count

    def append(self, value: int) -> int:

        return self.append_block(
            np.asarray(
                [value],
                dtype=np.uint32,
            )
        )

    def append_block(self, samples) -> int:

        samples = np.asarray(
            samples,
            dtype=np.uint32,
        ).reshape(-1)

        if samples.size == 0:
            return self.write_count

        # If the incoming block is larger than the complete buffer,
        # keep only the newest samples.
        if samples.size > self.capacity:
            samples = samples[-self.capacity:]

        with self._lock:

            start = (
                self._write_count
                % self.capacity
            )

            count = int(samples.size)

            first = min(
                count,
                self.capacity - start,
            )

            self._data[
                start:start + first
            ] = samples[:first]

            remaining = count - first

            if remaining:
                self._data[
                    :remaining
                ] = samples[first:]

            self._write_count += count

            return self._write_count

    def read_since(
        self,
        sequence: int,
    ) -> BufferSlice:
        """
        Return samples written since `sequence`.

        If the reader falls more than one complete buffer behind,
        overrun=True and the oldest available sample is returned.
        """

        with self._lock:

            end = self._write_count

            oldest = max(
                0,
                end - self.capacity,
            )

            requested = max(
                0,
                int(sequence),
            )

            overrun = requested < oldest

            start_sequence = max(
                requested,
                oldest,
            )

            count = end - start_sequence

            if count <= 0:
                return BufferSlice(
                    start_sequence=end,
                    end_sequence=end,
                    samples=np.empty(
                        0,
                        dtype=np.uint32,
                    ),
                    overrun=overrun,
                )

            start_index = (
                start_sequence
                % self.capacity
            )

            first = min(
                count,
                self.capacity - start_index,
            )

            if first == count:

                out = self._data[
                    start_index:
                    start_index + count
                ].copy()

            else:

                out = np.concatenate(
                    (
                        self._data[
                            start_index:
                            start_index + first
                        ],

                        self._data[
                            :count - first
                        ],
                    )
                )

            return BufferSlice(
                start_sequence=start_sequence,
                end_sequence=end,
                samples=out,
                overrun=overrun,
            )