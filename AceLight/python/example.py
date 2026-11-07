
import can
import acelight
from acelight.modules import ranger_mk1_param as r

import time

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

    status = ace.write(NODE_ID, r.profile_velocity, 10000) # set steps/second 
    print(f"Write status: 0x{status:02X}") # Code 0x01 means ok write was accepted

    status = ace.write(NODE_ID, r.motor_current, 400) # Set the nominal stepper motor winding current.

    status = ace.write(NODE_ID, r.microstep, 8) # Set full step or microstep level. 8 = 256 microstepping

    status = ace.write(NODE_ID, r.mode, 1) # Open-loop mode

    print(f"\n--- Test 1: Starting +/- 360 degree with speed increase and telemetry reporting ---\n") 

    time.sleep(2)

    for iter in range(10):
        
        step_second = (iter + 1) * 10000 + 10000
        status = ace.write(NODE_ID, r.profile_velocity, step_second) # update steps/second
        print(f"New speed: {step_second} steps/sec")
        time.sleep(1)

        status = ace.write(NODE_ID, r.step_move, 51200) # Move x amount of steps in positive or negative direction
        time.sleep((51200 / step_second) + 0.5) 

        status = ace.write(NODE_ID, r.step_move, -51200) # Move x amount of steps in positive or negative direction
        time.sleep((51200 / step_second) + 0.5) 

        status, angle = ace.read(NODE_ID, r.angle)
        status, temp = ace.read(NODE_ID, r.temperature)
        status, current = ace.read(NODE_ID, r.current)
        status, voltage = ace.read(NODE_ID, r.voltage)

        print(f"Temerature: {temp/1000} degrees")
        print(f"Current: {current} mA")
        print(f"Voltage: {voltage/1000} V")
        print(f"Angle: {angle/1000} degrees\n")
        time.sleep(2)

    step_second = 10000
    status = ace.write(NODE_ID, r.profile_velocity, step_second) # update steps/second 

    print("\n --- Test 2: 10k steps with angle reporting ---\n") 

    for iter in range(10):
        status = ace.write(NODE_ID, r.step_move, 10000) # Move x amount of steps in positive or negative direction
        time.sleep((7110 / step_second) + 0.5)

        status, data = ace.read(NODE_ID, r.angle)
        print(f"Angle: {data/1000} degrees") 
        time.sleep(0.5)

    print("\n --- Test ended ---\n") 