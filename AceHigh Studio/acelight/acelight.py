
"""
AceLight Python Library

Minimal Python implementation of the AceLight CAN protocol.

CAN hardware/interface initialization is intentionally handled outside
this library using python-can. The initialized CAN bus is then passed
to ace.init().

Example:

    import can
    import acelight as ace

    with can.Bus(
        interface="slcan",
        channel=CHANNEL,
        bitrate=BITRATE
    ) as bus:

        ace.init(bus)
        ace.set_source_id(1)

        position = ace.read(17, "device_type")
        response = ace.write(17, "microstep", 256)
"""

import can
import struct
import time


# ---------------------------------------------------------------------------
# AceLight message types
# ---------------------------------------------------------------------------

MT_PUBLICATION = 1
MT_WRITE_REQ   = 2
MT_WRITE_RESP  = 3
MT_READ_REQ    = 4
MT_READ_RESP   = 5

# ---------------------------------------------------------------------------
# AceLight status codes
# ---------------------------------------------------------------------------

ACE_STATUS_OK                = 0x01
ACE_STATUS_DATA_FOLLOWS      = 0x02
ACE_STATUS_INVALID_PARAMETER = 0x03
ACE_STATUS_INVALID_VALUE     = 0x04
ACE_STATUS_READ_ONLY         = 0x05
ACE_STATUS_WRITE_ONLY        = 0x06
ACE_STATUS_NODE_BUSY         = 0x07

# ---------------------------------------------------------------------------
# System parameters
# ---------------------------------------------------------------------------

PARAMETERS = {
    # AceLight system parameters
    "sync":                 (0x01, "U8"),
    "node_id":              (0x02, "U8"),
    "device_type":          (0x03, "U32"),
    "serial_number":        (0x04, "U32"),
    "firmware_version":     (0x05, "U32"),
    "hardware_version":     (0x06, "U32"),
    "protocol_version":     (0x07, "U32"),
    "boot_counter":         (0x08, "U32"),

    # Ranger specific parameters
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
    "error_flag":           (0xC2, "U32"),

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

# ============================================================
# AceLight parameter formats
# ============================================================

FMT = {
    "U8":  "<B",
    "U16": "<H",
    "U32": "<I",
    "I8":  "<b",
    "I16": "<h",
    "I32": "<i",
}

# ---------------------------------------------------------------------------
# Library state
# ---------------------------------------------------------------------------

_bus = None
_source_id = 1

DEFAULT_TIMEOUT = 0.5


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AceLightError(Exception):
    """Base exception for AceLight errors."""
    pass


class AceLightNotInitializedError(AceLightError):
    """Raised when AceLight has not been initialized with a CAN bus."""
    pass


class AceLightTimeoutError(AceLightError):
    """Raised when an expected AceLight response is not received."""
    pass


class AceLightParameterError(AceLightError):
    """Raised when an unknown or invalid parameter is requested."""
    pass


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def init(bus):
    """
    Initialize AceLight with an existing python-can Bus instance.

    CAN interface configuration is handled by the application, not by
    AceLight.
    """
    global _bus

    if bus is None:
        raise ValueError("bus cannot be None")

    _bus = bus


def set_source_id(source_id=1):
    """
    Set the AceLight source node ID used by this host/master.

    Valid range: 0..255
    """
    global _source_id

    if not isinstance(source_id, int):
        raise TypeError("source_id must be an integer")

    if not 0 <= source_id <= 0x7F:
        raise ValueError("source_id must be between 0 and 127")

    _source_id = source_id


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_bus():
    """Verify that AceLight has been initialized."""
    if _bus is None:
        raise AceLightNotInitializedError(
            "AceLight is not initialized. Call ace.init(bus) first."
        )


def _get_parameter(parameter):
    """
    Resolve a parameter name.

    Returns:
        parameter_id, data_type
    """

    if isinstance(parameter, str):
        try:
            return PARAMETERS[parameter]
        except KeyError:
            raise AceLightParameterError(
                f"Unknown AceLight parameter: {parameter}"
            )

    raise TypeError("parameter must be a string")


def _build_can_id(message_type, parameter_id, dest_id, source_id):
    """
    Build AceLight 29-bit extended CAN identifier.

    Layout:
        MT(3) | DestID(8) | SrcID(8) | Reserved(1) | ParamID(9)

    Current implementation uses 7-bit node IDs.
    """

    return (
        ((message_type & 0x07) << 26)
        | ((dest_id & 0x7F) << 18)
        | ((source_id & 0x7F) << 10)
        | (parameter_id & 0x1FF)
    )


def _parse_can_id(can_id):
    """
    Decode an AceLight CAN identifier.
    """

    message_type = (can_id >> 26) & 0x07
    dest_id      = (can_id >> 18) & 0x7F
    source_id    = (can_id >> 10) & 0x7F
    parameter_id = can_id & 0x1FF

    return message_type, parameter_id, dest_id, source_id


# ---------------------------------------------------------------------------
# Public AceLight API
# ---------------------------------------------------------------------------

def read(node_id, parameter, timeout=DEFAULT_TIMEOUT):
    """
    Read an AceLight parameter from a node.

    Example:

        status, value = acelight.read(2, "voltage")

    Returns:
        tuple:
            (status, value)

        If status == ACE_STATUS_DATA_FOLLOWS:
            value contains the decoded parameter value.

        Otherwise:
            value is None.
    """

    _require_bus()

    parameter_id, data_type = _get_parameter(parameter)

    request_id = _build_can_id(
        MT_READ_REQ,
        parameter_id,
        node_id,
        _source_id
    )

    message = can.Message(
        arbitration_id=request_id,
        is_extended_id=True,
        data=[]
    )

    _bus.send(message)

    deadline = time.monotonic() + timeout

    while True:

        remaining = deadline - time.monotonic()
        response = _bus.recv(remaining) if remaining > 0 else None

        if response is None:
            raise AceLightTimeoutError(
                f"No response from node {node_id} "
                f"for parameter 0x{parameter_id:03X}"
            )

        if not response.is_extended_id:
            continue

        mt, param, dest, src = _parse_can_id(
            response.arbitration_id
        )

        if (
            mt == MT_READ_RESP
            and param == parameter_id
            and dest == _source_id
            and src == node_id
        ):

            # AceLight responses must contain at least
            # the status byte.
            if len(response.data) < 1:
                raise AceLightError(
                    "Received ReadResp without status byte"
                )

            status = response.data[0]

            # No parameter data follows for error/status responses.
            if status != ACE_STATUS_DATA_FOLLOWS:
                return status, None

            # Parameter data starts at byte 1.
            payload = bytes(response.data[1:])

            expected_size = struct.calcsize(FMT[data_type])

            if len(payload) != expected_size:
                raise AceLightError(
                    f"Invalid payload length for parameter "
                    f"'{parameter}': expected {expected_size} bytes, "
                    f"received {len(payload)}"
                )

            value = struct.unpack(
                FMT[data_type],
                payload
            )[0]

            return status, value

def write(node_id, parameter, data, timeout=DEFAULT_TIMEOUT):
    """
    Write an AceLight parameter to a node.

    Example:

        status = acelight.write(2, "microstep", 256)

    Returns:
        AceLight status code from the WriteResp.

        Example:
            0x01 = ACE_STATUS_OK
            0x03 = ACE_STATUS_INVALID_PARAMETER
            0x04 = ACE_STATUS_INVALID_VALUE
            0x05 = ACE_STATUS_READ_ONLY
            0x07 = ACE_STATUS_NODE_BUSY
    """

    _require_bus()

    # Get parameter ID and datatype
    parameter_id, data_type = _get_parameter(parameter)

    # Encode data according to the parameter datatype
    try:
        payload = struct.pack(
            FMT[data_type],
            data
        )
    except (struct.error, TypeError) as e:
        raise AceLightParameterError(
            f"Invalid value for parameter '{parameter}': {data}"
        ) from e

    # Build AceLight WRITE_REQ identifier
    request_id = _build_can_id(
        MT_WRITE_REQ,
        parameter_id,
        node_id,
        _source_id
    )

    # Construct CAN message
    message = can.Message(
        arbitration_id=request_id,
        is_extended_id=True,
        data=payload
    )

    # Send request
    _bus.send(message)

    deadline = time.monotonic() + timeout

    # Wait for matching WRITE_RESP
    while True:

        remaining = deadline - time.monotonic()
        response = _bus.recv(remaining) if remaining > 0 else None

        if response is None:
            raise AceLightTimeoutError(
                f"No WriteResp from node {node_id} "
                f"for parameter 0x{parameter_id:03X}"
            )

        if not response.is_extended_id:
            continue

        mt, param, dest, src = _parse_can_id(
            response.arbitration_id
        )

        if (
            mt == MT_WRITE_RESP
            and param == parameter_id
            and dest == _source_id
            and src == node_id
        ):

            # WriteResp must contain at least the status byte
            if len(response.data) < 1:
                raise AceLightError(
                    "Received WriteResp without status byte"
                )

            # Byte 0 is the AceLight status code
            status = response.data[0]

            return status
