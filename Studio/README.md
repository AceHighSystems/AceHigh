# AceHigh Studio

Live Ranger telemetry, command terminal and CSV export using the existing AceLight CAN connection.

## Install and run

Extract the updated archive as a complete `Studio` folder, then run with your Python environment activated:

```sh
cd Studio
python3 -m pip install -r requirements.txt
cd backend
python3 app.py
```

Open http://127.0.0.1:8000. The existing serial adapter path and 1 Mbit/s bitrate are at the top of `backend/app.py`; update `CHANNEL` if your adapter path changes. Stop the previous backend before starting the updated one, then hard-refresh the browser to load the matching frontend.

## Plots and firmware parameters

The old standalone Fine angle panel is replaced by three full-width plots stacked vertically, followed by the existing raw-channel grid:

| Order | Plot / CSV signal | Firmware parameter | Wire type | Display unit |
| --- | --- | --- | --- | --- |
| 1 | Angle / `angle` | `0x44` | `I32` | Degrees |
| 2 | Fine angle / `fine_angle` | `0xC5` | `I32` | Radians, −π to +π |
| 3 | Sector / `sector` | `0xC3` | `U8` | Sector count |
| 4 | Raw channels / `ch0`–`ch13` | `0xD0`–`0xDD` | `U32` | Raw counts |

**ch0 and ch7 use pink traces and current-value readouts.** Other raw channels retain their existing lime traces and grid layout. Sector uses a stepped trace and integer tick labels.

The **Angle dial reads the firmware `angle` parameter (`0x44`)**. The dial and degree plot receive the same successful CAN read; the dial wraps its display to 0–360°, while the plot and CSV preserve the signed firmware degree value. For example, a returned angle of −45 plots/exports as −45° and displays as 315.00° on the dial. There is no Python angle reconstruction, calibration, direction inversion or angle smoothing. The encoder estimation modules, calibration data/report, calibration tool, capture fixtures and SciPy dependency have been removed.

### Fine-angle fixed-point scale

The supplied fine-angle wire type is `I32`. The project therefore retains its existing convention of **1,000,000 integer units per radian**. For example, raw −1570796 displays as −1.570796 rad. If the updated firmware uses another fixed-point scale, change `FINE_ANGLE_UNITS_PER_RADIAN` near the top of `frontend/plot.js`. The fine-angle graph has a fixed vertical range of −π to +π; phase wraps are preserved. The degree-valued `angle` parameter is interpreted directly as integer degrees and is not divided by this factor.

All three firmware parameters are read-only in the acquisition path. Requested polling rates are 50 Hz each for sector, fine angle and angle, 2 Hz for temperature, and 5 Hz each for voltage and current. Raw acquisition requests 50 complete sequential ch0–ch13 scans per second. All reads share the serialized CAN connection with terminal commands, so actual rates depend on response time and bus load. Reads are sequential and do not assert simultaneous sensor snapshots. An unsupported parameter reports Unavailable, retries after one second, and does not stop the other signals.

The existing temperature and voltage/current dashboard panels remain. Their conversions and display behavior are retained from the supplied project.

## Run, Stop and export

The dashboard toolbar also includes **Run Calibration** and **Firmware Update** beside Run, Stop and Export CSV. These two buttons are UI placeholders: clicking either displays a status message that its workflow is not configured yet. Calibration and firmware-update routines still need to be connected.

**Run** starts all plots and the dashboard. Each new Run clears the traces, sample indices and CSV history. **Stop** pauses updates and leaves the recorded data available for export. Node selection is locked during acquisition. Terminal commands remain available during a run.

Each firmware plot retains up to 300 seconds / 15,000 points. Parameter plot time axes use CAN-read completion time relative to the start of the run. Raw plots retain their sample-index axes and 15,000-point history. The parameter cards distinguish Waiting, Live, Stale, Unavailable, Paused and Disconnected.

**Export CSV** includes `angle`, `fine_angle`, `sector`, then `ch0`–`ch13` in plot order. Each signal retains its latest 20,000 samples independently. The existing five long-format columns are preserved, followed by two added columns:

```text
channel,sample_index,raw_value,host_receive_elapsed_s,host_receive_utc,value,unit
```

- `raw_value` preserves the exact returned integer: unsigned sector, signed fine angle, signed degree angle or unsigned raw channel count.
- `value` is the plotted value: sector count, fine angle converted to radians, angle in degrees or raw channel count.
- `unit` is `count`, `rad` or `deg` respectively.

For example, fine angle exports `raw_value=-1570796,value=-1.570796,unit=rad`. Angle exports `raw_value=-45,value=-45,unit=deg`. The dial shares the angle sample, so it does not add a duplicate CSV row.

Each signal has its own sample index. Host receipt timestamps provide a common browser time reference, not a sensor acquisition timestamp. Failed reads and updates received after Stop do not create parameter samples. The next Run clears the previous export history.

## Command terminal

The terminal sits below Node Control. It accepts AceLight commands, not arbitrary Python or shell commands.

| Command | Function |
| --- | --- |
| `read <parameter>` | Read from the selected node |
| `write <parameter> <integer>` | Write to the selected node |
| `params` | List known parameter names and integer types |
| `params angle` | Filter the parameter list |
| `node 3` | Select a node while the scope is stopped |
| `help` | Show syntax and examples |
| `clear` | Clear the visible terminal output |

Examples:

```text
read sector
read fine_angle
read angle
read microstep
write microstep 256
read microstep
```

Decimal, signed decimal and hexadecimal integers are accepted. Up/Down arrows recall command history. Replies include the raw returned value, AceLight status and browser-observed round-trip time. Firmware determines read/write permissions. Node IDs are limited to 0–127 by the supplied AceLight implementation. Use one Studio tab/node for acquisition, as in the supplied project.

Writes are not automatically retried. A timeout or disconnect can leave a write's outcome unknown; read back configuration before repeating a write. Movement commands such as `write step_move 256` request movement immediately.

## Verification

Run the automated backend/protocol checks without physical CAN hardware:

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q tests
```

All 31 backend/protocol tests pass on Python 3.12. The protocol peer responds to actual AceLight CAN frames and covers all three firmware parameter mappings, signed I32 values, U8 sectors through 255, raw acquisition alongside dashboard/terminal reads, unsupported-parameter recovery, command validation, timeouts and cancellation. It does not depend on an encoder model or calibration files.

Browser verification covers the ordered replacement plots, pink ch0/ch7 traces, shared firmware angle for dial/plot, physical display units, all 17 exported signals, Stop/new Run behavior, read-error recovery, desktop/mobile layout and plot/CSV history retention. Physical Ranger operation still needs a local check with your module and firmware fixed-point scale.
