
import struct
import can

# ============================================================
# AceLight protocol message types
# ============================================================
ACE_MSG_BROADCAST       = 0x01
ACE_MSG_WRITE_REQUEST   = 0x02
ACE_MSG_WRITE_RESPONSE  = 0x03
ACE_MSG_READ_REQUEST    = 0x04
ACE_MSG_READ_RESPONSE   = 0x05

# ============================================================
# AceLight protocol response status codes
# ============================================================
ACE_STATUS_OK                = 0x01
ACE_STATUS_DATA_FOLLOWS      = 0x02
ACE_STATUS_INVALID_PARAMETER = 0x03
ACE_STATUS_INVALID_VALUE     = 0x04
ACE_STATUS_READ_ONLY         = 0x05
ACE_STATUS_WRITE_ONLY        = 0x06
ACE_STATUS_NODE_BUSY         = 0x07

# ============================================================
# AceLight parameter data types
# ============================================================
FMT = {
    "U8":  "<B",
    "U16": "<H",
    "I16": "<h",
    "U32": "<I",
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

        data = self._request(ACE_MSG_READ_REQUEST, node_id, parameter.id)
       
        status = data[0]

        if status != ACE_STATUS_DATA_FOLLOWS:
            return status, None

        data_payload = struct.unpack(FMT[parameter.data_type], data[1:])[0]

        return status, data_payload

    
    # ============================================================
    # Write request
    # ============================================================
    def write(self, node_id, parameter, value):
        
        data = struct.pack(FMT[parameter.data_type], int(value))

        data = self._request(ACE_MSG_WRITE_REQUEST, node_id, parameter.id, data)

        status = data[0]

        return status
        

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

        if msg_type == ACE_MSG_READ_REQUEST:
            expected_msg_type_rx = ACE_MSG_READ_RESPONSE

        elif msg_type == ACE_MSG_WRITE_REQUEST:
            expected_msg_type_rx = ACE_MSG_WRITE_RESPONSE

        else:
            raise ValueError("Unsupported request type")


        while True:
            msg = bus.recv(1.0)

            if msg is None:
                raise TimeoutError("No response received")

            msg_type_rx, destination, source, parameter = self._decode_id(msg.arbitration_id)
            
            # Filter the responses on the bus and return correct response with data
            if (destination == host_id and
                source == node_id and
                parameter == param_id and
                msg_type_rx == expected_msg_type_rx):

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