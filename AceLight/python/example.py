
import can
import acelight
from acelight.modules import ranger_mk1 as r

CHANNEL = "/dev/cu.usbmodem2080317458421"
BITRATE = 1_000_000

NODE_ID = 2
HOST_ID = 1

with can.Bus(
    interface="slcan",
    channel=CHANNEL,
    bitrate=BITRATE
) as bus:


    ace = acelight.Client(HOST_ID, bus)

    status = ace.write(NODE_ID, r.profile_velocity, 1000)
    print(f"Write status: 0x{status:02X}")