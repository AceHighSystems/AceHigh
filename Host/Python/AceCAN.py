#!/usr/bin/env python3

import can
import struct

# ============================================================
# Configuration
# ============================================================

CHANNEL = "/dev/cu.usbmodem2080317458421"
BITRATE = 1_000_000

HOST_ID   = 1
RANGER_ID = 2

# ============================================================
# AceLight
# ============================================================

BROADCAST      = 0x01
WRITE_REQUEST  = 0x02
WRITE_RESPONSE = 0x03
READ_REQUEST   = 0x04
READ_RESPONSE  = 0x05

OK           = 0x01
DATA_FOLLOWS = 0x02

# name: (parameter ID, data type)

PARAM = {
    "sync":                 (0x01, "U8"),
    "node_id":              (0x02, "U8"),
    "device_type":          (0x03, "U32"),
    "serial_number":        (0x04, "U32"),
    "firmware_version":     (0x05, "U32"),
    "hardware_version":     (0x06, "U32"),
    "protocol_version":     (0x07, "U32"),

    "mode":                 (0x40, "U8"),
    "step_move":            (0x41, "I32"),
    "target_position":      (0x42, "I32"),
    "position":             (0x43, "I32"),
    "angle":                (0x44, "I32"),
    "profile_velocity":     (0x45, "U32"),
    "profile_acceleration": (0x46, "U32"),
    "profile_deceleration": (0x47, "U32"),
    "microstep":            (0x48, "U32"),

    "voltage":              (0x80, "I32"),
    "current":              (0x81, "I32"),
    "temperature":          (0x82, "I32"),

    "led":                  (0xC0, "U8"),
    "test":                 (0xC1, "U32"),
    "debug":                (0xC2, "I32"),

    "ch0":                  (0xD0, "U32"),
    "ch1":                  (0xD1, "U32"),
    "ch2":                  (0xD2, "U32"),
    "ch3":                  (0xD3, "U32"),
    "ch4":                  (0xD4, "U32"),
    "ch5":                  (0xD5, "U32"),
    "ch6":                  (0xD6, "U32"),
    "ch7":                  (0xD7, "U32"),
    "ch8":                  (0xD8, "U32"),
    "ch9":                  (0xD9, "U32"),
    "ch10":                 (0xDA, "U32"),
    "ch11":                 (0xDB, "U32"),
    "ch12":                 (0xDC, "U32"),
    "ch13":                 (0xDD, "U32"),
}

FMT = {
    "U8":  "<B",
    "U16": "<H",
    "U32": "<I",
    "I16": "<h",
    "I32": "<i",
}

# ============================================================
# Identifier
# ============================================================

def make_id(msg_type, destination, source, parameter):
    return ((msg_type & 7) << 26 |
            (destination & 0x7F) << 18 |
            (source & 0x7F) << 10 |
            (parameter & 0x1FF))


def decode_id(identifier):
    return (
        (identifier >> 26) & 7,
        (identifier >> 18) & 0x7F,
        (identifier >> 10) & 0x7F,
        identifier & 0x1FF
    )

# ============================================================
# Request / response
# ============================================================

def request(bus, msg_type, param_id, data=b""):

    bus.send(can.Message(
        arbitration_id=make_id(msg_type, RANGER_ID, HOST_ID, param_id),
        is_extended_id=True,
        data=data
    ))

    while True:

        msg = bus.recv(1.0)

        if msg is None:
            print("No response")
            return None

        msg_type_rx, destination, source, parameter = decode_id(msg.arbitration_id)

        if (destination == HOST_ID and
            source == RANGER_ID and
            parameter == param_id and
            msg_type_rx in (READ_RESPONSE, WRITE_RESPONSE)):

            return msg.data

# ============================================================
# Commands
# ============================================================

def read_param(bus, name):

    if name not in PARAM:
        print("Unknown parameter")
        return

    param_id, data_type = PARAM[name]
    data = request(bus, READ_REQUEST, param_id)

    if not data:
        return

    if data[0] != DATA_FOLLOWS:
        print(f"Status: 0x{data[0]:02X}")
        return

    value = struct.unpack(FMT[data_type], data[1:])[0]

    print(f"{name} = {value}")


def write_param(bus, name, value):

    if name not in PARAM:
        print("Unknown parameter")
        return

    param_id, data_type = PARAM[name]

    data = struct.pack(FMT[data_type], int(value))

    response = request(bus, WRITE_REQUEST, param_id, data)

    if response:
        print("OK" if response[0] == OK else f"Status: 0x{response[0]:02X}")


# ============================================================
# Prototype plotting - to be removed again
# ============================================================

from collections import deque
import time

from PyQt6 import QtWidgets, QtCore
import pyqtgraph as pg


def plot_raw_single(bus):
    POLL_MS = 50
    WINDOW_S = 60*10
    RESPONSE_TIMEOUT_S = 0.25

    channels = [
        ("ch0", "PCAP_A PC1", "#B7FF00"),
        ("ch1", "PCAP_A PC2", "#3EBBFF"),
    ]

    # Retain QApplication so the plot can be reopened.
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    plot_raw_single._app = app

    window = QtWidgets.QDialog()
    window.setWindowTitle("Ranger — PCAP_A PC1 and PC2")
    window.resize(1100, 800)

    layout = QtWidgets.QVBoxLayout(window)
    states = []

    for name, label, color in channels:
        param_id, data_type = PARAM[name]

        info = QtWidgets.QLabel(f"{name} / {label}: Waiting for data...")
        info.setStyleSheet(
            f"color: {color}; font-size: 14px; padding: 6px;"
        )
        layout.addWidget(info)

        plot = pg.PlotWidget(background="#172A49")
        plot.setLabel("bottom", "Elapsed time", units="s")
        plot.setLabel("left", f"{name} / {label}", units="counts")
        plot.showGrid(x=True, y=True, alpha=0.25)
        plot.getAxis("left").enableAutoSIPrefix(False)
        plot.setXRange(0, WINDOW_S, padding=0)
        plot.enableAutoRange(axis="y", enable=True)
        layout.addWidget(plot)

        states.append({
            "name": name,
            "param_id": param_id,
            "fmt": FMT[data_type],
            "size": struct.calcsize(FMT[data_type]),
            "info": info,
            "plot": plot,
            "curve": plot.plot(pen=pg.mkPen(color, width=2)),
            "samples": deque(),
        })

    start = time.monotonic()

    def read_value(state):
        bus.send(
            can.Message(
                arbitration_id=make_id(
                    READ_REQUEST,
                    RANGER_ID,
                    HOST_ID,
                    state["param_id"],
                ),
                is_extended_id=True,
                data=b"",
            ),
            timeout=RESPONSE_TIMEOUT_S,
        )

        deadline = time.monotonic() + RESPONSE_TIMEOUT_S

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("No response from Ranger")

            msg = bus.recv(remaining)
            if msg is None:
                raise TimeoutError("No response from Ranger")

            if (
                not msg.is_extended_id
                or msg.is_error_frame
                or msg.is_remote_frame
            ):
                continue

            msg_type, destination, source, parameter = decode_id(
                msg.arbitration_id
            )

            if not (
                msg_type == READ_RESPONSE
                and destination == HOST_ID
                and source == RANGER_ID
                and parameter == state["param_id"]
            ):
                continue

            data = msg.data

            if not data:
                raise ValueError("Empty response")

            if data[0] != DATA_FOLLOWS:
                raise ValueError(f"AceLight status: 0x{data[0]:02X}")

            if len(data) < 1 + state["size"]:
                raise ValueError(f"Incomplete response: {len(data)} bytes")

            return struct.unpack_from(state["fmt"], data, 1)[0]

    def update():
        for state in states:
            try:
                value = read_value(state)
                now = time.monotonic() - start
                state["samples"].append((now, value))

                state["info"].setText(f'{state["name"]}: Raw: {value:,}')

            except Exception as exc:
                state["info"].setText(
                    f'{state["name"]}: Read error: {exc}'
                )

        # Keep both plots on the same time axis.
        now = time.monotonic() - start

        for state in states:
            samples = state["samples"]

            while samples and samples[0][0] < now - WINDOW_S:
                samples.popleft()

            if samples:
                times, values = zip(*samples)
                state["curve"].setData(list(times), list(values))

                # Preserve any error message from this polling cycle.
                if "Read error:" not in state["info"].text():
                    minimum = min(values)
                    maximum = max(values)

                    state["info"].setText(
                        f'{state["name"]}: Raw: {values[-1]:,}     '
                        f"Min: {minimum:,}     "
                        f"Max: {maximum:,}     "
                        f"Peak-to-peak: {maximum - minimum:,}"
                    )
            else:
                state["curve"].setData([], [])

            state["plot"].setXRange(
                max(0.0, now - WINDOW_S),
                max(WINDOW_S, now),
                padding=0,
            )

    timer = QtCore.QTimer(window)
    timer.timeout.connect(update)
    timer.start(POLL_MS)

    try:
        window.exec()
    finally:
        timer.stop()
        window.deleteLater()

# ============================================================
# Main
# ============================================================

with can.Bus(
    interface="slcan",
    channel=CHANNEL,
    bitrate=BITRATE
) as bus:

    print("AceLight connected")
    print("Commands: read <parameter>, write <parameter> <value>, exit")

    while True:

        cmd = input("> ").lower().split()

        if not cmd:
            continue

        if cmd[0] == "exit":
            break

        if cmd[0] == "read" and len(cmd) == 2:
            read_param(bus, cmd[1])

        elif cmd[0] == "write" and len(cmd) == 3:
            write_param(bus, cmd[1], cmd[2])

        elif cmd[0] == "plot":
                    plot_raw_single(bus)

        else:
            print("Invalid command")