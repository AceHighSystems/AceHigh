"""No physical CAN hardware is opened by these tests."""
import asyncio
import importlib
from pathlib import Path
import queue
import struct
import sys
import threading
import time

import can
import numpy as np
from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]
from acelight import acelight as ace
from can_service import CanService
from encoder import EncoderEstimator


class RangerBus:
    """Small protocol peer: use real AceLight framing with deterministic values."""
    def __init__(self):
        self.responses = queue.Queue()
        self.values = {"microstep": 256, "step_move": 0, "profile_velocity": 500,
                       "angle": 321000, "temperature": 31, "voltage": 24000, "current": -1250}
        self.read_status = {}
        self.requests = []
        self.reject_write = False
        self.drop_response = False
        self.counter = 0
        self.encoder = EncoderEstimator()
        self.set_raw_angle(123.456)

    def set_raw_angle(self, degrees):
        self.raw_channels = np.rint(
            self.encoder.decoder._basis([degrees]) @ self.encoder.decoder.coefficients
        ).astype(np.int64)[0]

    def send(self, message):
        mt, param, node, host = ace._parse_can_id(message.arbitration_id)
        name = next(name for name, definition in ace.PARAMETERS.items() if definition[0] == param)
        dtype = ace.PARAMETERS[name][1]
        self.requests.append((mt, node, name))
        time.sleep(0.001)
        if self.drop_response:
            return
        if mt == ace.MT_READ_REQ:
            self.counter += 1
            value = self.values.get(name, 2_000_000 + self.counter)
            if name.startswith("ch") and name[2:].isdigit():
                value = int(self.raw_channels[int(name[2:])])
            status = self.read_status.get(name, 2)
            payload = bytes([status]) + (struct.pack(ace.FMT[dtype], value) if status == 2 else b"")
            response_mt = ace.MT_READ_RESP
        else:
            payload = bytes([4 if self.reject_write else 1])
            if not self.reject_write:
                self.values[name] = struct.unpack(ace.FMT[dtype], bytes(message.data))[0]
            response_mt = ace.MT_WRITE_RESP
        self.responses.put(can.Message(
            arbitration_id=ace._build_can_id(response_mt, param, host, node),
            is_extended_id=True, data=payload))

    def recv(self, timeout):
        try:
            return self.responses.get(timeout=timeout)
        except queue.Empty:
            return None

    def shutdown(self):
        pass


@pytest.fixture
def application(monkeypatch):
    bus = RangerBus()
    monkeypatch.setattr(can, "Bus", lambda **kwargs: bus)
    sys.modules.pop("app", None)
    module = importlib.import_module("app")
    with TestClient(module.app) as client:
        yield client, bus


def receive_json(ws, kind):
    while True:
        message = ws.receive()
        if message.get("text"):
            import json
            value = json.loads(message["text"])
            if value.get("type") == kind:
                return value


def test_read_write_and_14_channels_continue(application):
    client, bus = application
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert any(p["name"] == "ch13" for p in hello["parameters"])
        for i in range(14):
            ws.send_json({"type": "subscribe", "node": 2, "signal": f"ch{i}", "rate_hz": 50})
            receive_json(ws, "subscribed")
        ws.send_json({"type": "write", "node": 2, "param": "microstep", "value": 64, "request_id": "terminal-1"})
        assert receive_json(ws, "write_response") == {
            "type": "write_response", "node": 2, "param": "microstep", "status": 1, "request_id": "terminal-1"}
        ws.send_json({"type": "read", "node": 2, "param": "microstep", "request_id": "terminal-2"})
        response = receive_json(ws, "read_response")
        assert (response["request_id"], response["value"]) == ("terminal-2", 64)
        signals = set()
        while len(signals) < 14:
            message = ws.receive()
            if message.get("bytes"):
                frame = message["bytes"]
                kind, node, signal, count, sequence = struct.unpack("<BBHII", frame[:12])
                assert kind == 1 and node == 2 and len(frame) == 12 + 4 * count
                signals.add(signal)
        assert signals == set(range(1, 15))
        ws.send_json({"type": "write", "node": 2, "param": "step_move", "value": -256})
        assert receive_json(ws, "write_response")["status"] == 1
        assert bus.values["step_move"] == -256


def test_dashboard_metrics_with_raw_plots_and_terminal(application):
    client, bus = application
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        for i in range(14):
            ws.send_json({"type": "subscribe", "node": 2, "signal": f"ch{i}", "rate_hz": 50})
            receive_json(ws, "subscribed")
        ws.send_json({"type": "metrics_start", "node": 2, "run_id": 1})
        assert receive_json(ws, "metrics_started")["run_id"] == 1
        samples = {}
        for _ in range(50):
            message = receive_json(ws, "metric_sample")
            assert message["node"] == 2 and message["run_id"] == 1
            assert message["elapsed_s"] >= 0
            samples[message["signal"]] = message["value"]
            if len(samples) == 5:
                break
        assert abs(samples.pop("angle") - (360.0 - 123.456)) < 0.001
        assert samples == {"temperature": 31, "voltage": 24000, "current": -1250,
                           "fine_angle": 321000}
        assert any(name == "angle" for _, _, name in bus.requests)
        ws.send_json({"type": "read", "node": 2, "param": "microstep", "request_id": "terminal-metrics"})
        assert receive_json(ws, "read_response")["value"] == 256
        while True:
            message = ws.receive()
            if message.get("bytes"):
                frame = message["bytes"]
                break
        assert struct.unpack("<BBHII", frame[:12])[0] == 1
        ws.send_json({"type": "metrics_stop"})
        receive_json(ws, "metrics_stopped")
        # A later command must still work, and no metric remains in flight.
        ws.send_json({"type": "read", "node": 2, "param": "current"})
        while True:
            message = ws.receive()
            if message.get("text"):
                import json
                response = json.loads(message["text"])
                assert response["type"] not in ("metric_sample", "metric_error")
                if response["type"] == "read_response":
                    assert response["value"] == -1250
                    break


def test_real_reassembled_capture_is_sent_to_dashboard(application):
    client, bus = application
    capture = np.load(ROOT / 'tests' / 'fixtures' / 'capture_0.npz')
    bus.raw_channels = capture['raw'][0].astype(np.int64)
    expected = (-bus.encoder.estimate(bus.raw_channels).degrees) % 360
    with client.websocket_connect('/ws') as ws:
        ws.receive_json()
        for index in range(14):
            ws.send_json({'type': 'subscribe', 'node': 2, 'signal': f'ch{index}', 'rate_hz': 50})
            receive_json(ws, 'subscribed')
        ws.send_json({'type': 'metrics_start', 'node': 2, 'run_id': 1})
        receive_json(ws, 'metrics_started')
        for _ in range(30):
            sample = receive_json(ws, 'metric_sample')
            if sample['signal'] == 'angle':
                assert sample['source'] == 'pcap14' and sample['unit'] == 'deg'
                assert sample['value'] == pytest.approx(expected)
                assert sample['fit_error'] < bus.encoder.max_fit_error
                break
        else:
            pytest.fail('Real capture did not produce a dashboard angle')


def test_one_unsupported_dashboard_parameter_does_not_stop_other_metrics(application):
    client, bus = application
    bus.read_status["temperature"] = 3
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "metrics_start", "node": 2, "run_id": 2})
        receive_json(ws, "metrics_started")
        error = receive_json(ws, "metric_error")
        assert error["signal"] == "temperature" and "0x03" in error["message"]
        assert receive_json(ws, "metric_sample")["signal"] == "voltage"
        assert receive_json(ws, "metric_sample")["signal"] == "current"
        assert receive_json(ws, "metric_sample")["signal"] == "fine_angle"
        assert any(name == "angle" for _, _, name in bus.requests)
        ws.send_json({"type": "metrics_stop"})
        receive_json(ws, "metrics_stopped")


@pytest.mark.parametrize("raw", [-3141593, -1, 0, 1, 3141593])
def test_firmware_fine_angle_preserves_signed_parameter_and_units(application, raw):
    client, bus = application
    bus.values["angle"] = raw
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "metrics_start", "node": 2, "run_id": 7})
        receive_json(ws, "metrics_started")
        for _ in range(20):
            message = receive_json(ws, "metric_sample")
            if message["signal"] == "fine_angle":
                assert message["value"] == raw
                assert message["unit"] == "urad"
                assert message["source"] == "ranger"
                assert message["parameter"] == "angle"
                assert message["node"] == 2 and message["run_id"] == 7
                break
        else:
            pytest.fail("Firmware angle parameter did not reach the browser")
        ws.send_json({"type": "metrics_stop"})
        receive_json(ws, "metrics_stopped")


def test_unsupported_fine_angle_does_not_stop_other_metrics_and_recovers(application):
    client, bus = application
    bus.read_status["angle"] = 3
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "metrics_start", "node": 2, "run_id": 8})
        receive_json(ws, "metrics_started")
        error = receive_json(ws, "metric_error")
        assert error["signal"] == "fine_angle"
        assert error["parameter"] == "angle" and "0x03" in error["message"]
        # A firmware parameter failure must not stop the other dashboard reads.
        others = set()
        for _ in range(20):
            message = receive_json(ws, "metric_sample")
            others.add(message["signal"])
            if others.issuperset({"temperature", "voltage", "current"}):
                break
        assert others.issuperset({"temperature", "voltage", "current"})
        bus.read_status["angle"] = 2
        for _ in range(50):
            message = receive_json(ws, "metric_sample")
            if message["signal"] == "fine_angle":
                assert message["value"] == 321000
                break
        else:
            pytest.fail("Fine-angle acquisition did not recover")
        ws.send_json({"type": "metrics_stop"})
        receive_json(ws, "metrics_stopped")


@pytest.mark.parametrize("bad", [
    {"type": "read", "node": 128, "param": "microstep"},
    {"type": "read", "node": 2.5, "param": "microstep"},
    {"type": "read", "node": 2, "param": "unknown"},
    {"type": "write", "node": 2, "param": "microstep", "value": -1},
    {"type": "write", "node": 2, "param": "microstep", "value": 2**32},
    {"type": "write", "node": 2, "param": "microstep", "value": 1.2},
    {"type": "write", "node": 2, "param": "microstep", "value": True},
])
def test_invalid_commands_do_not_send_can(application, bad):
    client, bus = application
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({**bad, "request_id": "bad"})
        assert ws.receive_json()["request_id"] == "bad"
        assert not bus.requests
        ws.send_json({"type": "read", "node": 2, "param": "microstep"})
        assert ws.receive_json()["value"] == 256


def test_rejection_timeout_and_malformed_json(application):
    client, bus = application
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        for payload in ["{", "[]", "null"]:
            ws.send_text(payload)
            assert ws.receive_json()["type"] == "error"
        bus.reject_write = True
        ws.send_json({"type": "write", "node": 2, "param": "microstep", "value": 3, "request_id": "reject"})
        assert ws.receive_json()["status"] == 4
        assert bus.values["microstep"] == 256
        bus.drop_response = True
        ws.send_json({"type": "read", "node": 2, "param": "microstep", "request_id": "timeout"})
        response = ws.receive_json()
        assert response["type"] == "error" and response["request_id"] == "timeout"
        bus.drop_response = False
        ws.send_json({"type": "read", "node": 2, "param": "microstep"})
        assert ws.receive_json()["value"] == 256


def test_cancelled_poll_keeps_lock_until_can_worker_finishes():
    async def scenario():
        entered = threading.Event()
        release = threading.Event()
        calls = []
        class Backend:
            def read(self, node, parameter):
                calls.append(parameter)
                if parameter == "ch0":
                    entered.set()
                    release.wait(1)
                return 2, 42
        service = CanService(Backend())
        poll = asyncio.create_task(service.read(2, "ch0"))
        await asyncio.to_thread(entered.wait, 1)
        poll.cancel()
        command = asyncio.create_task(service.read(2, "microstep"))
        await asyncio.sleep(0.03)
        assert calls == ["ch0"]
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await poll
        assert await command == (2, 42)
        assert calls == ["ch0", "microstep"]
    asyncio.run(scenario())


def test_service_created_before_server_creates_lock_only_in_running_loop(monkeypatch):
    original_lock = asyncio.Lock
    created_in = []

    def loop_bound_lock():
        created_in.append(asyncio.get_running_loop())
        return original_lock()

    monkeypatch.setattr(asyncio, "Lock", loop_bound_lock)

    class Backend:
        def read(self, node, parameter):
            time.sleep(0.005)
            return 2, 256

    # Match app.py's module-level construction before Uvicorn starts.
    service = CanService(Backend())
    assert not created_in

    async def scenario():
        results = await asyncio.gather(
            service.read(2, "ch0"), service.read(2, "node_id"))
        assert results == [(2, 256), (2, 256)]
        assert created_in == [asyncio.get_running_loop()]

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["read", "write"])
def test_unrelated_bus_traffic_does_not_extend_timeout(operation):
    class NoisyBus:
        def send(self, message):
            pass
        def recv(self, timeout):
            time.sleep(min(0.002, timeout))
            return can.Message(arbitration_id=0, is_extended_id=False, data=[])
    ace.init(NoisyBus())
    started = time.monotonic()
    with pytest.raises(ace.AceLightTimeoutError):
        if operation == "read":
            ace.read(2, "microstep", timeout=0.03)
        else:
            ace.write(2, "microstep", 256, timeout=0.03)
    assert time.monotonic() - started < 0.2
