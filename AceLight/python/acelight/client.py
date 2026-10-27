
import struct
import can

# ============================================================
# AceLight protocol message types
# ============================================================
BROADCAST      = 0x01
WRITE_REQUEST  = 0x02
WRITE_RESPONSE = 0x03
READ_REQUEST   = 0x04
READ_RESPONSE  = 0x05

# ============================================================
# AceLight protocol message responses
# ============================================================
OK           = 0x01
DATA_FOLLOWS = 0x02

# ============================================================
# AceLight parameter data types
# ============================================================
FMT = {
    "U8":  "<B",
    "U16": "<H",
    "U32": "<I",
    "I16": "<h",
    "I32": "<i",
}


class Client:
    def __init__(self, host_id, bus):
        # Store the Host ID in this particular client object.
        self.host_id = host_id
        self.bus = bus

    # ============================================================
    # Read request
    # ============================================================
    def read(self, node_id, parameter):

        data = self._request(READ_REQUEST, node_id, parameter.id)

        if not data:
            raise TimeoutError("No response")

        status = data[0]


        if status != DATA_FOLLOWS:
            return status, None 

        data_payload = struct.unpack(FMT[parameter.data_type], data[1:])[0]

        return status, data_payload

    
    # ============================================================
    # Write request
    # ============================================================
    def write(self, node_id, parameter, value):

        data = struct.pack(FMT[parameter.data_type], int(value))

        response = self._request(WRITE_REQUEST, node_id, parameter.id, data)

        if not response:
            raise TimeoutError("No response")

        return response[0]
        


    # ============================================================
    # Request / response handler
    # ============================================================
    # Shared request handling:
    # 1. Build the message using self.host_id.
    # 2. Transmit it.
    # 3. Wait for a matching response or timeout.
    # 4. Return (raw response payload).
    def _request(self, msg_type, node_id, param_id, data=b""):

        bus = self.bus
        host_id = self.host_id

        bus.send(can.Message(
            arbitration_id=self._make_id(msg_type, node_id, host_id, param_id),
            is_extended_id=True,
            data=data
        ))

        while True:

            msg = bus.recv(1.0)

            if msg is None:
                return None

            msg_type_rx, destination, source, parameter = self._decode_id(msg.arbitration_id)

            if (destination == host_id and
                source == node_id and
                parameter == param_id and
                msg_type_rx in (READ_RESPONSE, WRITE_RESPONSE)):

                return msg.data


    # ============================================================
    # CAN Identifier encoder
    # ============================================================
    @staticmethod
    def _make_id(msg_type, destination, source, parameter):
        return ((msg_type & 7) << 26 |
                (destination & 0x7F) << 18 |
                (source & 0x7F) << 10 |
                (parameter & 0x1FF))

    @staticmethod
    def _decode_id(identifier):
        return (
            (identifier >> 26) & 7,
            (identifier >> 18) & 0x7F,
            (identifier >> 10) & 0x7F,
            identifier & 0x1FF)