# AceHigh Studio — live dashboard and command terminal

The terminal sits below Node Control. It uses the existing AceLight CAN backend alongside all 14 raw encoder plots, a separate firmware fine-angle plot, and CSV export of up to 20,000 samples per signal. The former motor/microstep controls have been removed.

## Install and run

Extract this archive and use the updated project as a whole. Restart the old backend first, then hard-refresh the browser to load the updated JavaScript.

From the extracted `AceHigh Studio` folder with your existing Python environment activated:

```sh
python3 -m pip install -r requirements.txt
cd backend
python3 app.py
```

Open http://127.0.0.1:8000. The existing serial device path and 1 Mbit/s bitrate are retained at the top of `backend/app.py`; update `CHANNEL` if the adapter path changes. Stop the backend with Ctrl+C before starting another instance.

No Ranger firmware changes are required for the terminal itself. Commands only address names already present in `acelight/acelight.py`; firmware still determines each parameter's permissions and behaviour.


## Live dashboard

Three dashboard panels sit side by side on desktop:

1. **Angle:** a 0–360° wrapping dial and a two-decimal reading in the range 0.00–359.99°.
2. **Temperature:** latest reading in °C and a rolling trace.
3. **Voltage / current:** both traces in one chart, with volts on the left axis and amps on the right. Blue is voltage; amber is current. Signed current is preserved.

A separate full-width **Fine angle** panel sits immediately below those three panels and above every raw-channel plot. It reads the Ranger's signed `angle` parameter (`0x44`, `I32`) directly. The firmware representation is radians multiplied by 1,000,000; the graph and current reading divide by 1,000,000 to display radians. Negative values and the approximately −π to +π wraps are preserved. The fine phase repeats three times per mechanical revolution and is not divided by three, unwrapped, direction-inverted or smoothed. This plot is independent of the computed mechanical-angle dial.

Run starts the dashboard, fine-angle plot and raw plots; Stop pauses them. Each new run clears the traces and CSV buffers. Terminal commands remain available during acquisition. The fine-angle plot retains up to 300 seconds / 15,000 points. Its time axis uses CAN-read completion times relative to the start of the dashboard run. These times do not assert simultaneous sensor acquisition. In the combined voltage/current plot, the latest available value of the other signal is held between its reads.

The dial shows an angle computed locally by the Python backend from `ch0` through `ch13`. It receives floating-point degrees directly; the former angle-unit selector is removed. The new fine-angle plot separately polls the firmware's `angle` parameter; those readings do not feed the dial.

Each acquisition pass builds a new 14-channel vector. Only a complete pass with successful, unsigned 24-bit channel results is decoded. A failed channel is never filled from a previous pass. The reconstruction reuses the raw reads already feeding the plots, without another set of channel requests.

`backend/encoder_calibration.json` is recalibrated for the reassembled NEMA14 module using all three supplied **18 October 2026** captures. The previous 16 October model rejected every sampled new scan during diagnosis. The new 18-harmonic full-pattern model fits the new channel offsets, swings, waveform shape and sector signatures. All fourteen channels, including ch0 and ch7, participate in independent 0–360° decoding.

Stationary noise from both the single standstill and the ten held positions supplies the noise covariance. A regularized motion-residual covariance also accounts for sector drift, repeatability and sequential-read effects. The fit gate is now **12 whitened RMS units**, set with margin over the maximum 7.09 observed across the supplied captures, including repositioning transients. This value is a channel-model mismatch score, not angular error in degrees. Incomplete/invalid/grossly mismatched scans still mark the dial unavailable.

The displayed direction is retained as `ANGLE_DIRECTION = -1`: the CCW rotating capture produces decreasing displayed degrees, matching the clockwise-positive SVG dial. **Smoothing stays disabled**, exactly as configured in the supplied `encoder.py` (`ANGLE_FILTER_TAU_S = 0.0`). For optional smoothing, set it to `0.15`; the circular filter follows the shortest arc across 0° and adds approximately 0.53° of lag at this capture's speed. Raw channels remain unfiltered.

The new reference zero is the first retained rotating-capture scan. It is arbitrary and can differ from the previous calibration's zero; no surveyed mechanical zero was supplied. The offline fit uses a constant-speed assumption and locally smoothed browser receipt times; fitted period is **102.4009 s**, versus 102.4 s expected for 500 STEP pulses/s, 256 microsteps and 200 full steps per revolution. The runtime decoder uses only current raw measurements: it does not derive angle from elapsed time, motor settings or previous motion, and can decode either direction and standstill.

Replay results (no live hardware connected):

| Capture | Complete scans | Rejected | Result |
| --- | ---: | ---: | --- |
| Single standstill | 20,000 | 0 | 0.0146° RMS jitter; 0.1232° peak-to-peak |
| Ten held positions | 19,999 | 0 | 0.0132–0.0263° RMS within trimmed holds |
| Continuous CCW rotation | 20,000 | 0 | 4.0245 turns; no 120° sector jumps |

The holds export has two edge indices with incomplete channel sets; these are omitted, leaving 19,999 complete scans. No missing value is fabricated. Against the assumed constant-speed reference, rotation residual RMS is 0.1268° and maximum absolute deviation is 0.5433°. Fitting on alternating complete revolutions and evaluating the other revolutions gives 0.1280° RMS and 0.5658° maximum deviation. The reference period and covariance are shared across that validation; template coefficients exclude the evaluated revolutions. This checks repeatability and branch continuity, **not independently measured absolute accuracy**. Sequential CAN reads and asynchronous PCAP updates contribute dynamic error.

The calibration is specific to this assembly and acquisition configuration. Recalibrate after changing the mechanical stack, electrode mapping or PCAP settings. A complete machine-readable replay report is in `CALIBRATION-2026-10-18.json`. The original captures are not bundled into this code ZIP; keep them for future recalibration.

To reproduce calibration with the original exports, from the project root run:

```sh
python3 tools/calibrate_encoder.py /path/to/AceHigh-PCAP-A-2026-10-18T13-28-21-829Z.csv /path/to/AceHigh-PCAP-A-2026-10-18T13-35-42-241Z.csv /path/to/AceHigh-PCAP-A-2026-10-18T13-43-31-373Z.csv
```

This is an offline operation and never commands the motor. It overwrites `backend/encoder_calibration.json` and the JSON report; back up a calibration you want to keep first. At least three complete revolutions at steady speed are required. `--nominal-period` specifies seconds per full mechanical revolution if using a different calibration speed. Live operation does not require repeating this step: the updated calibration is already included.

Voltage and current are divided by 1000 for V and A, matching the supplied firmware's millivolt/milliamp values. Temperature is displayed in °C, matching its integer-degree value. The Node Control voltage readout now applies the same millivolt conversion.

The computed angle follows successful complete raw scans, with dashboard delivery capped at approximately 50 updates/s. Requested polling rates are 50 Hz for the firmware fine-angle parameter, 2 Hz for temperature and 5 Hz each for voltage and current. All requests share the existing CAN lock with raw acquisition and terminal commands; actual rates depend on CAN response time and bus load. The cards distinguish Waiting, Live, Stale, Paused, Disconnected and unavailable/partial data. Failed reads use a one-second retry interval.

**Export CSV** includes ch0–ch13 and the firmware parameter under the exact signal name **`angle`**. The existing long-format columns remain `channel,sample_index,raw_value,host_receive_elapsed_s,host_receive_utc`. Rows with `channel=angle` contain the unchanged signed integer in microradians, not displayed radians and not the computed mechanical dial angle. Each signal retains its latest 20,000 samples and has its own sample index. Angle and raw-channel rows are not simultaneous scans; their browser receipt timestamps provide the common time reference. Export remains available after Stop and resets on the next Run. No synthetic angle samples are exported after a failed read.

The computed-angle integration adds `backend/encoder.py`, `backend/calibrated_encoder.py`, `backend/encoder_calibration.json` and SciPy to the requirements. Install the updated requirements before starting the backend. Replace the project together, restart the backend and hard-refresh Studio so the matching backend and frontend load.

## Terminal commands

Select Node ID 2, click Run to plot, then enter one command at a time:

```text
read microstep
write microstep 256
read microstep
write profile_velocity 500
read profile_velocity
```

`write step_move 256` or `write step_move -256` sends a signed movement request immediately; the actual movement and enabling/mode requirements follow the current Ranger firmware.

| Command | Function |
| --- | --- |
| `read <parameter>` | Read from the selected node |
| `write <parameter> <integer>` | Write to the selected node immediately |
| `params` | List the backend's parameter names and integer types |
| `params ch` | Filter the parameter list |
| `node 3` | Select a node, while the scope is stopped |
| `help` | Show syntax and examples |
| `clear` | Clear the visible terminal output |

Decimal, signed decimal and hexadecimal integers are accepted, e.g. `256`, `-256`, `0x100`. Parameter suggestions are available in the input. Use Up/Down arrows for this page's command history; Send or Enter submits. Clear only clears the visible log.

Replies show the node, parameter, raw returned value, AceLight status name/code, and browser-observed round-trip time. `OK (0x01)` means a write was acknowledged; `DATA_FOLLOWS (0x02)` is a successful read. Device rejection is displayed as an error. An acknowledgement does not assert that physical movement has completed.

Node IDs are limited to 0–127 because the supplied AceLight implementation masks IDs to seven bits. Stop the scope before selecting another node. Use one Studio tab/node for acquisition, as in the supplied starter.

Writes are never automatically retried. A timeout or disconnect can leave a write's outcome unknown; read back configuration before repeating a write. Repeating a movement request can cause additional movement.

## Changes

- `frontend/index.html`: terminal under Node Control; removed motor controls; corrected ch0–ch13 label.
- `frontend/style.css`: terminal layout in the existing black/lime style, mobile layout and keyboard focus states.
- `frontend/terminal.js`: command parser, suggestions, history, parameter help and timestamped replies. This accepts AceLight commands, not arbitrary Python or shell commands.
- `frontend/app.js`: connects terminal to the existing WebSocket; locks node selection during a scope run.
- `backend/app.py`: parameter catalogue in the hello message, validated commands, request/node correlation, recoverable malformed-command errors.
- `backend/can_service.py`: retains exclusive CAN ownership until an in-flight worker finishes when a scan task is cancelled.
- The CAN lock is created inside the running server loop on first use, avoiding the Python 3.9 "Future attached to a different loop" error when telemetry and terminal commands contend for the bus.
- `acelight/acelight.py`: read/write timeout now uses an overall deadline so unrelated frames cannot extend a transaction indefinitely. CAN identifiers and parameter mappings are unchanged.

## Verification

Run the automated backend/protocol checks without physical hardware:

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q tests
```

All **38 automated tests pass on Python 3.12**. Tests cover signed firmware-angle values, the separate computed mechanical angle, unsupported-parameter recovery, and simultaneous raw-channel acquisition and terminal access. A Chromium browser check with a simulated CAN peer also verified the new panel's position, signed radian display, raw `angle` CSV rows, export after Stop, reset on a new run, error recovery, 15,000-point plot / 20,000-sample CSV retention, and desktop/mobile layout. No live hardware was connected.

The regression suite includes small raw subsets from all three supplied 18 October captures. It checks acceptance, stationary stability, full-turn continuity and agreement with the constant-speed reference. Reverse-order replay verifies that the decoder does not depend on prior travel. Additional checks cover the live telemetry path, complete-scan handling, synthetic full-turn coverage, invalid data and optional smoothing. Smoothing tests request 150 ms explicitly so they also work with the supplied unsmoothed default.

The protocol peer responds to actual AceLight request frames without opening physical CAN hardware. Its checks cover dashboard metrics alongside 14 raw channels and terminal read/write commands, signed movement values, validation errors, device rejection, timeouts and cancellation. See the included calibration JSON for full-capture replay results and limitations.

Physical Ranger operation still needs a local check with your module. The terminal returns raw parameter values; their units/scaling follow your existing firmware and parameter definitions. CSV timestamps remain browser receipt timestamps, rather than converter acquisition timestamps.
