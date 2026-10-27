# AceLight

Python client for the AceLight CAN protocol, developed by [AceHigh ApS](https://ace-high.com).

Read and write device parameters through a small synchronous API. The package includes a parameter table for Ranger Mk1 and uses `python-can` for the CAN interface.

This is an alpha release. The API and device parameter tables may change.

## Requirements

- Python 3.9 or newer.
- A CAN adapter supported by `python-can`. The example below uses SLCAN over a serial port.
- A hardware module (Ranger Mk1) running compatible AceLight firmware. Parameter IDs and data types must match the device firmware.

The package dependency `python-can[serial]` includes the serial support used by the example. Other CAN interfaces may require their own drivers or dependencies.

## Installation

For an alpha release published on PyPI:

```bash
python -m pip install --pre acelight
```

For development, run the following from the directory containing `pyproject.toml`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

On Windows, activate the environment with `.venv\Scripts\Activate.ps1` in PowerShell instead of the `source` command.

## Quick start

Set the adapter channel, CAN bitrate, host ID, and device node ID for your setup. SLCAN channel names typically look like `/dev/cu.usbmodem...` on macOS, `/dev/ttyACM0` on Linux, or `COM4` on Windows.

```python
import can
import acelight
from acelight.client import ACE_STATUS_DATA_FOLLOWS, ACE_STATUS_OK
from acelight.modules import ranger_mk1_param as r

CHANNEL = "/dev/cu.usbmodem..."  # Replace with your adapter's serial port.
BITRATE = 1_000_000
HOST_ID = 1
NODE_ID = 2

with can.Bus(interface="slcan", channel=CHANNEL, bitrate=BITRATE) as bus:
    ace = acelight.Client(host_id=HOST_ID, bus=bus)

    try:
        status, temperature = ace.read(NODE_ID, r.temperature)
    except TimeoutError as error:
        print(f"Temperature read failed: {error}")
    else:
        if status == ACE_STATUS_DATA_FOLLOWS:
            print(f"Temperature raw: {temperature}")
        else:
            print(f"Read rejected: 0x{status:02X}")

    try:
        status = ace.write(NODE_ID, r.profile_velocity, 1000)
    except TimeoutError as error:
        print(f"Velocity write failed: {error}")
    else:
        if status == ACE_STATUS_OK:
            print("Profile velocity updated.")
        else:
            print(f"Write rejected: 0x{status:02X}")
```

This example reads temperature and writes the motion profile velocity. It does not issue a move command.

Parameter values are raw integers. Check the device documentation for units and scaling; the client does not automatically convert values into engineering units.

## API

### Client

```python
ace = acelight.Client(host_id=1, bus=bus)
```

Pass an already configured `python-can` bus. The application creates and closes the bus; the example uses a context manager for this.

### Read a parameter

```python
status, value = ace.read(node_id, parameter)
```

- On a response with status `ACE_STATUS_DATA_FOLLOWS`, returns `(status, decoded_value)`.
- On another response status, returns `(status, None)`.
- If no message arrives during a receive wait, raises `TimeoutError`.

### Write a parameter

```python
status = ace.write(node_id, parameter, value)
```

Returns the device's response status. If no message arrives during a receive wait, raises `TimeoutError`.

The application decides how to handle device status codes and exceptions. A caught timeout does not automatically retry a request.

## Parameters

Ranger Mk1 definitions are in `acelight/modules/ranger_mk1_param.py`. Each `Parameter` contains the protocol parameter ID and its data type.

Supported types are `U8`, `U16`, `I16`, `U32`, and `I32`. Multi-byte values use little-endian encoding.

The current Ranger table is a subset of the device parameters. Use only definitions that match the connected device firmware.

## Response status codes

These constants are available from `acelight.client`.

| Constant | Value |
| --- | --- |
| `ACE_STATUS_OK` | `0x01` |
| `ACE_STATUS_DATA_FOLLOWS` | `0x02` |
| `ACE_STATUS_INVALID_PARAMETER` | `0x03` |
| `ACE_STATUS_INVALID_VALUE` | `0x04` |
| `ACE_STATUS_READ_ONLY` | `0x05` |
| `ACE_STATUS_WRITE_ONLY` | `0x06` |
| `ACE_STATUS_NODE_BUSY` | `0x07` |

## Current scope

Requests are synchronous. Use one request at a time and give the client sole ownership of reception from its bus object. The request loop consumes unrelated messages while waiting for its response.

The receive timeout is currently one second per `bus.recv()` call. Unrelated traffic can extend the total request duration. The client does not automatically retry requests.

The current implementation assumes correctly formed device responses. Empty or incorrectly sized payloads can raise `IndexError` or `struct.error`.

More information: [ace-high.com](https://ace-high.com).
