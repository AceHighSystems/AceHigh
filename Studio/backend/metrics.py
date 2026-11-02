"""Firmware parameter telemetry sharing the serialized AceLight connection."""
from __future__ import annotations

import asyncio

METRIC_RATES = {"sector": 50.0, "fine_angle": 50.0, "angle": 50.0,
                "temperature": 2.0, "voltage": 5.0, "current": 5.0}
PARAMETER_UNITS = {"sector": "count", "fine_angle": "urad", "angle": "mdeg"}


async def stream_metrics(can_service, node, run_id, send):
    loop = asyncio.get_running_loop()
    started = loop.time()
    due = {signal: started for signal in METRIC_RATES}
    while True:
        for signal, rate in METRIC_RATES.items():
            if loop.time() < due[signal]:
                continue
            message = {"node": node, "run_id": run_id, "signal": signal}
            # One angle read supplies both the degree plot and the dial.
            parameter = signal
            if signal in PARAMETER_UNITS:
                message.update(parameter=parameter, source="ranger",
                               unit=PARAMETER_UNITS[signal])
            try:
                status, value = await can_service.read(node, parameter)
                if status != 2 or value is None:
                    raise ValueError(f"AceLight read status 0x{int(status):02X}")
                message.update(type="metric_sample", value=int(value),
                               elapsed_s=loop.time() - started)
                due[signal] = loop.time() + 1.0 / rate
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                message.update(type="metric_error", message=str(exc))
                # Unsupported parameters or a missing node must not flood CAN.
                due[signal] = loop.time() + max(1.0, 1.0 / rate)
            await send(message)

        await asyncio.sleep(max(0.001, min(0.02, min(due.values()) - loop.time())))
