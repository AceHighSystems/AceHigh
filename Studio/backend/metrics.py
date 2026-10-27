"""Low-rate dashboard telemetry sharing the serialized AceLight connection."""
from __future__ import annotations

import asyncio
from encoder import AngleOutputFilter

METRIC_RATES = {"temperature": 2.0, "voltage": 5.0, "current": 5.0,
                "fine_angle": 50.0}


async def stream_metrics(can_service, node, run_id, send, telemetry):
    loop = asyncio.get_running_loop()
    started = loop.time()
    due = {signal: started for signal in METRIC_RATES}
    last_angle_sequence = 0
    angle_filter = AngleOutputFilter()
    while True:
        angle = telemetry.latest_angles.get(node)
        if angle is not None and angle.completed_at >= started and angle.sequence != last_angle_sequence:
            last_angle_sequence = angle.sequence
            message = {"node": node, "run_id": run_id, "signal": "angle", "source": "pcap14",
                       "scan_sequence": angle.sequence, "scan_duration_s": angle.scan_duration_s}
            if angle.error:
                angle_filter.reset()
                message.update(type="metric_error", message=angle.error)
            else:
                displayed = angle_filter.update(angle.degrees, angle.completed_at)
                message.update(type="metric_sample", value=displayed, unit="deg",
                               unfiltered_value=angle.degrees, direction=angle_filter.direction,
                               filter_tau_s=angle_filter.tau_s,
                               fit_error=angle.fit_error, elapsed_s=angle.completed_at - started)
            await send(message)
        for signal, rate in METRIC_RATES.items():
            if loop.time() < due[signal]:
                continue
            message = {"node": node, "run_id": run_id, "signal": signal}
            # The existing "angle" metric is the computed mechanical dial.
            # Keep the firmware parameter separate and preserve signed urad.
            parameter = "angle" if signal == "fine_angle" else signal
            if signal == "fine_angle":
                message.update(parameter=parameter, source="ranger", unit="urad")
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
