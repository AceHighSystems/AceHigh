#!/usr/bin/env python3

import can
import struct
import csv
import signal
from datetime import datetime
from pathlib import Path

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

    "led1":                 (0xC0, "U32"),
    "uptime_s":             (0xC1, "U32"),
    "debug":                (0xC2, "U32"),
    "sector":               (0xC3, "U8"),
    "test":                 (0xC4, "U32"),

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
    POLL_MS = 100
    WINDOW_S = 60 * 4
    RESPONSE_TIMEOUT_S = 0.5

    channels = [
        ("ch0", "Channel 0", "#FF70C8"),
        ("ch7", "Channel 7", "#FF70C8"),
        ("sector", "Sector", "#B7FF00"),
        ("angle", "Angle", "#3EBBFF"),
    ]

    # Retain QApplication so the plot can be reopened.
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    plot_raw_single._app = app

    window = QtWidgets.QDialog()
    window.setWindowTitle("Ranger — ch0, ch7, Sector and Angle")
    window.resize(1100, 1000)

    layout = QtWidgets.QVBoxLayout(window)
    toolbar = QtWidgets.QHBoxLayout()
    export_status = QtWidgets.QLabel("CSV includes only the current four-minute plotting window.")
    toolbar.addWidget(export_status)
    toolbar.addStretch()
    export_button = QtWidgets.QPushButton("Export CSV…")
    toolbar.addWidget(export_button)
    layout.addLayout(toolbar)

    # Retain only the same rolling time window as the plots.
    # Each row holds a time, value and error for every sequential channel read.
    export_rows = deque()
    interrupted = False
    states = []

    for name, label, color in channels:
        param_id, data_type = PARAM[name]

        info = QtWidgets.QLabel(f"{label}: Waiting for data...")
        info.setStyleSheet(
            f"color: {color}; font-size: 14px; padding: 6px;"
        )
        layout.addWidget(info)

        plot = pg.PlotWidget(background="#172A49")
        plot.setLabel("bottom", "Elapsed time", units="s")
        plot.setLabel("left", label)
        plot.showGrid(x=True, y=True, alpha=0.25)
        plot.getAxis("left").enableAutoSIPrefix(False)
        plot.setXRange(0, WINDOW_S, padding=0)
        plot.enableAutoRange(axis="y", enable=True)
        layout.addWidget(plot, stretch=1)

        # Link all time axes to the first plot.
        if states:
            plot.setXLink(states[0]["plot"])

        states.append({
            "name": name,
            "param_id": param_id,
            "fmt": FMT[data_type],
            "size": struct.calcsize(FMT[data_type]),
            "info": info,
            "plot": plot,
            "curve": plot.plot(pen=pg.mkPen(color, width=2)),
            "samples": deque(),
            "error": None,
        })

    start = time.monotonic()
    display_end = 0.0

    def read_value(state):
        if interrupted:
            raise InterruptedError("Interrupted")
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
            if interrupted:
                raise InterruptedError("Interrupted")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("No response from Ranger")

            # Short waits let Ctrl+C interrupt even when the node is offline.
            msg = bus.recv(min(remaining, 0.05))
            if msg is None:
                continue

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
                raise ValueError(
                    f"Incomplete response: {len(data)} bytes"
                )

            return struct.unpack_from(state["fmt"], data, 1)[0]

    def update():
        nonlocal display_end
        if interrupted:
            return
        row = []
        for state in states:
            if interrupted:
                return
            try:
                value = read_value(state)
                now = time.monotonic() - start
                state["samples"].append((now, value))
                state["error"] = None
                row.extend((now, value, ""))

            except InterruptedError:
                return
            except Exception as exc:
                state["error"] = str(exc)
                row.extend((time.monotonic() - start, None, str(exc)))

        export_rows.append(tuple(row))
        now = time.monotonic() - start
        display_end = now
        cutoff = now - WINDOW_S
        while export_rows and max(export_rows[0][::3]) < cutoff:
            export_rows.popleft()

        for state in states:
            samples = state["samples"]

            while samples and samples[0][0] < now - WINDOW_S:
                samples.popleft()

            if samples:
                times, values = zip(*samples)
                state["curve"].setData(list(times), list(values))

                minimum = min(values)
                maximum = max(values)

                text = (
                    f'{state["name"]}: Raw: {values[-1]:,}     '
                    f"Min: {minimum:,}     "
                    f"Max: {maximum:,}     "
                    f"Peak-to-peak: {maximum - minimum:,}"
                )
            else:
                state["curve"].setData([], [])
                text = f'{state["name"]}: Waiting for data...'

            if state["error"] is not None:
                text = (
                    f'{state["name"]}: Read error: {state["error"]}'
                )

            state["info"].setText(text)

        # Updating the first plot also updates all linked time axes.
        states[0]["plot"].setXRange(
            max(0.0, now - WINDOW_S),
            max(WINDOW_S, now),
            padding=0,
        )

    timer = QtCore.QTimer(window)
    timer.timeout.connect(update)
    timer.start(POLL_MS)

    def export_csv():
        # Pause acquisition while choosing a path and writing the snapshot.
        timer.stop()
        now_at_export = display_end
        try:
            if not export_rows:
                export_status.setText("No data to export yet.")
                return

            filename = "Ranger-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".csv"
            # Use a Qt dialog so the interrupt timer can reject it on Ctrl+C.
            dialog = QtWidgets.QFileDialog(window, "Export current plotting window CSV")
            dialog.setOption(QtWidgets.QFileDialog.Option.DontUseNativeDialog, True)
            dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptSave)
            dialog.setNameFilter("CSV files (*.csv)")
            dialog.setDefaultSuffix("csv")
            dialog.selectFile(str(Path.cwd() / filename))
            try:
                if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted or interrupted:
                    return
                path = Path(dialog.selectedFiles()[0])
            finally:
                dialog.deleteLater()

            # Match the displayed window at the moment Export was clicked.
            # Blank any readings outside the window in a boundary-crossing scan.
            cutoff = max(0.0, now_at_export - WINDOW_S)
            rows = []
            for scan in export_rows:
                row = []
                keep = False
                for i in range(0, len(scan), 3):
                    timestamp, value, error = scan[i:i + 3]
                    if cutoff <= timestamp <= now_at_export:
                        row.extend((timestamp, value, error))
                        keep = True
                    else:
                        row.extend((None, None, ""))
                if keep:
                    rows.append(row)

            header = []
            for state in states:
                name = state["name"]
                header.extend((f"{name}_time_s", name, f"{name}_error"))

            with path.open("w", newline="", encoding="utf-8") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(header)
                writer.writerows(rows)

            export_status.setText(f"Exported {len(rows):,} scans to {path.name}")
            print(f"CSV exported: {path} ({len(rows):,} scans)")
        except Exception as exc:
            export_status.setText(f"CSV export failed: {exc}")
            print(f"CSV export failed: {exc}")
        finally:
            if not interrupted:
                timer.start(POLL_MS)

    export_button.clicked.connect(export_csv)

    def handle_sigint(signum, frame):
        # Avoid raising exceptions inside Qt callbacks. Exit after Qt unwinds.
        nonlocal interrupted
        interrupted = True

    def check_interrupt():
        if interrupted:
            timer.stop()
            modal = app.activeModalWidget()
            if isinstance(modal, QtWidgets.QDialog) and modal is not window:
                modal.reject()
            window.reject()

    # Regular Python callbacks allow SIGINT processing while Qt owns the loop.
    interrupt_timer = QtCore.QTimer(window)
    interrupt_timer.timeout.connect(check_interrupt)
    previous_sigint = signal.signal(signal.SIGINT, handle_sigint)
    interrupt_timer.start(50)

    try:
        window.exec()
    finally:
        timer.stop()
        interrupt_timer.stop()
        signal.signal(signal.SIGINT, previous_sigint)
        window.deleteLater()

    if interrupted:
        raise KeyboardInterrupt

# ============================================================
# Main
# ============================================================

def main():
    with can.Bus(
        interface="slcan",
        channel=CHANNEL,
        bitrate=BITRATE
    ) as bus:

        print("AceLight connected")
        print("Commands: read <parameter>, write <parameter> <value>, plot, exit")

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

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nAceLight disconnected.")
