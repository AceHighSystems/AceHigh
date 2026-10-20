from __future__ import annotations

import asyncio
import json
import math
import struct
import sys
from contextlib import suppress
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

CHANNEL = "/dev/cu.usbmodem2080317458421"
BITRATE = 1_000_000

# Make AceHigh-gui/ importable so the existing acelight/ folder can be used.
ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from can_service import CanService
from telemetry import SIGNALS, TelemetryService
from metrics import stream_metrics
from encoder import EncoderEstimator


def load_ace_backend():
    try:
        from acelight import acelight as ace
        import can

        bus = can.Bus(
            interface="slcan",
            channel=CHANNEL,
            bitrate=BITRATE
        )
        
        ace.init(bus)
        
        print("[AceHigh GUI] CAN bus initialized.")
        print("[AceHigh GUI] AceLight module imported successfully.")
        return ace

    except Exception as exc:
        print(f"[AceHigh GUI] FAILED to import AceLight and set up CAN: {exc}")
        raise


ace_backend = load_ace_backend()
can_service = CanService(ace_backend)
telemetry = TelemetryService(can_service, EncoderEstimator())

app = FastAPI(title="AceHigh GUI")
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html")


def json_safe(value):
    if hasattr(value, "item"):
        return value.item()
    return value


def validate_node(value):
    if type(value) is not int or not 0 <= value <= 127:
        raise ValueError("Node ID must be an integer from 0 to 127.")
    return value


async def parameter_command(command):
    """Validate a read/write and keep its reply correlated with the browser."""
    operation = command["type"]
    reply = {
        "request_id": command.get("request_id"),
        "node": command.get("node"),
        "param": command.get("param"),
    }
    try:
        node = validate_node(command.get("node"))
        parameter = command.get("param")
        if not isinstance(parameter, str) or parameter not in ace_backend.PARAMETERS:
            raise ValueError(f"Unknown AceLight parameter: {parameter}")
        if operation == "read":
            status, value = await can_service.read(node, parameter)
            return {**reply, "type": "read_response", "status": int(status),
                    "value": json_safe(value)}

        value = command.get("value")
        _, data_type = ace_backend.PARAMETERS[parameter]
        if type(value) is not int:
            raise ValueError(f"{parameter} requires an integer ({data_type}).")
        try:
            struct.pack(ace_backend.FMT[data_type], value)
        except (struct.error, OverflowError) as exc:
            raise ValueError(f"Value out of range for {parameter} ({data_type}).") from exc
        status = await can_service.write(node, parameter, value)
        return {**reply, "type": "write_response", "status": int(status)}
    except Exception as exc:
        return {**reply, "type": "error", "operation": operation, "message": str(exc)}


async def telemetry_sender(
    websocket: WebSocket,
    subscriptions: dict[str, dict],
):
    """
    Send plot updates at browser-friendly frame rate.

    CAN acquisition rate and GUI update rate are intentionally decoupled.
    """
    while True:
        for signal, state in list(subscriptions.items()):
            chunk = telemetry.read_since(signal, state["sequence"])

            if chunk.samples.size == 0:
                continue

            signal_id = telemetry.signal_id(signal)
            node_id = state["node"]

            # MVP binary frame, little endian:
            #
            # byte  0      packet_type   uint8   (1 = telemetry)
            # byte  1      node_id       uint8
            # byte  2..3   signal_id     uint16
            # byte  4..7   sample_count  uint32
            # byte  8..11  sequence      uint32  first sample sequence
            # byte 12..    samples       uint32[sample_count]
            #
            header = struct.pack(
                "<BBHII",
                1,
                node_id & 0xFF,
                signal_id,
                int(chunk.samples.size),
                int(chunk.start_sequence) & 0xFFFFFFFF,
            )

            await websocket.send_bytes(header + chunk.samples.tobytes())
            state["sequence"] = chunk.end_sequence

        # ~30 GUI updates/s. Acquisition can be much faster than this.
        await asyncio.sleep(1.0 / 30.0)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    subscriptions: dict[str, dict] = {}
    metrics_task = None

    async def stop_metrics():
        nonlocal metrics_task
        if metrics_task is not None:
            metrics_task.cancel()
            with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError, OSError):
                await metrics_task
            metrics_task = None

    sender = asyncio.create_task(
        telemetry_sender(websocket, subscriptions)
    )

    await websocket.send_json(
        {
            "type": "hello",
            "acelight_connected": can_service.connected,
            "parameters": [
                {"name": name, "type": definition[1]}
                for name, definition in ace_backend.PARAMETERS.items()
            ],
        }
    )

    try:
        while True:
            message = await websocket.receive_text()
            try:
                command = json.loads(message)
                if not isinstance(command, dict):
                    raise ValueError("Expected a JSON command object.")
            except (ValueError, TypeError) as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                continue

            command_type = command.get("type")

            if command_type in ("read", "write"):
                await websocket.send_json(await parameter_command(command))

            elif command_type == "metrics_start":
                try:
                    node = validate_node(command.get("node"))
                    run_id = command.get("run_id")
                    if type(run_id) is not int or run_id < 0:
                        raise ValueError("run_id must be a non-negative integer.")
                except ValueError as exc:
                    await websocket.send_json({"type": "error", "operation": "metrics_start", "message": str(exc)})
                    continue
                await stop_metrics()
                metrics_task = asyncio.create_task(
                    stream_metrics(can_service, node, run_id, websocket.send_json, telemetry))
                await websocket.send_json({"type": "metrics_started", "node": node, "run_id": run_id})

            elif command_type == "metrics_stop":
                await stop_metrics()
                await websocket.send_json({"type": "metrics_stopped"})

            elif command_type == "subscribe":
                try:
                    node = validate_node(command.get("node"))
                    signal = str(command["signal"])
                    rate_hz = float(command.get("rate_hz", 100.0))
                    if not math.isfinite(rate_hz) or not 0.1 <= rate_hz <= 1000:
                        raise ValueError("Scan rate must be from 0.1 to 1000 Hz.")
                except (KeyError, TypeError, ValueError) as exc:
                    await websocket.send_json({"type": "error", "operation": "subscribe", "message": str(exc)})
                    continue

                if signal not in SIGNALS:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "operation": "subscribe",
                            "message": f"Unknown signal: {signal}",
                        }
                    )
                    continue

                # If this WebSocket was already subscribed to the same signal,
                # stop the old node/signal poller before replacing it.
                previous = subscriptions.get(signal)
                if previous is not None and previous["node"] != node:
                    telemetry.stop_stream(previous["node"], signal)

                telemetry.ensure_stream(node, signal, rate_hz)

                # Start this client at the newest sample rather than replaying
                # stale buffer contents on first subscription.
                sequence = telemetry.buffers[signal].write_count
                subscriptions[signal] = {
                    "node": node,
                    "sequence": sequence,
                }

                await websocket.send_json(
                    {
                        "type": "subscribed",
                        "signal": signal,
                        "rate_hz": rate_hz,
                    }
                )

            elif command_type == "unsubscribe":
                signal = str(command.get("signal", ""))
                state = subscriptions.pop(signal, None)

                if state is not None:
                    telemetry.stop_stream(state["node"], signal)

                await websocket.send_json(
                    {
                        "type": "unsubscribed",
                        "signal": signal,
                    }
                )

            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": f"Unknown command type: {command_type}",
                    }
                )

    except WebSocketDisconnect:
        pass
    finally:
        await stop_metrics()
        for signal, state in list(subscriptions.items()):
            telemetry.stop_stream(state["node"], signal)

        subscriptions.clear()

        sender.cancel()
        with suppress(asyncio.CancelledError):
            await sender


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
