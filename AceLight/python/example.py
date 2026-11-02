
import can
import acelight
from acelight.modules import ranger_mk1_param as r

# For a better understanding of the Ranger Mk1 module, its capabilities and how to easily operate it
# start with a sneak peek at the parameter list of the module, file: python/acelight/modules --> "ranger_mk1_param.py"
# The list expose all the parameters that are used to operate and control the module.

# Next take a look at the Ranger Mk1 datasheet for more details.

CHANNEL = "/dev/cu.usbmodem2080317458421"  # Replace with your CAN adapter's serial port.
BITRATE = 1_000_000

HOST_ID = 1
NODE_ID = 2

with can.Bus(
    interface="slcan",  # Replace with OS supported interface
    channel=CHANNEL,
    bitrate=BITRATE
) as bus:

    ace = acelight.Client(HOST_ID, bus)

    status = ace.write(NODE_ID, r.profile_velocity, 1000) # In steps/second 
    print(f"Write status: 0x{status:02X}")

    status = ace.write(NODE_ID, r.motor_current, 400) # In steps/second 
    print(f"Write status: 0x{status:02X}")

    status = ace.write(NODE_ID, r.microstep, 8) # Set full step or microstep level.
    print(f"Write status: 0x{status:02X}")

    status = ace.write(NODE_ID, r.mode, 1) # open-loop mode
    print(f"Write status: 0x{status:02X}")

    status = ace.write(NODE_ID, r.step_move, -10000) # Move x amount of steps in positive or negative direction
    print(f"Write status: 0x{status:02X}")