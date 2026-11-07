
from ..parameter import Parameter

# AceLight standard module parameters --------------------------------------------------------------------------
sync                  = Parameter(
                            id=0x01, 
                            data_type="U8", 
                            description="Sync parameter used for synchronization event", 
                            unit="unitless", 
                            access="Read and write")

node_id               = Parameter(
                            id=0x02, 
                            data_type="U8", 
                            description="Node id for communication, settable takes effect after powercycle", 
                            unit="unitless", 
                            access="Read and Write")

device_type           = Parameter(
                            id=0x03, 
                            data_type="U32", 
                            description="Device type", 
                            unit="unitless", 
                            access="Read Only")

serial_number         = Parameter(
                            id=0x04, 
                            data_type="U32", 
                            description="Module serial number - set at manufacturing, fixed forever", 
                            unit="unitless", 
                            access="Read Only")

firmware_version      = Parameter(
                            id=0x05, 
                            data_type="U32", 
                            description="Firmware version id", 
                            unit="unitless", 
                            access="Read Only")

hardware_version      = Parameter(
                            id=0x06, 
                            data_type="U32", 
                            description="Hardware version id", 
                            unit="unitless", 
                            access="Read Only")

protocol_version      = Parameter(
                            id=0x07, 
                            data_type="U32", 
                            description="Protocol version id", 
                            unit="unitless", 
                            access="Read Only")

# Ranger Mk1 module specific parameters  
# Motion (0x40–0x5F) --------------------------------------------------------------------------------------------------
mode                  = Parameter(
                            id=0x40, 
                            data_type="U8", 
                            description="Ranger module operational mode - see datasheet for modes", 
                            unit="unitless", 
                            access="Read and write")

step_move             = Parameter(
                            id=0x41, 
                            data_type="I32", 
                            description="Stepper motor steps to move in +/- direction, input for open loop operation", 
                            unit="unitless", 
                            access="Read and Write")

target_position       = Parameter(
                            id=0x42, 
                            data_type="I32", 
                            description="Multiturn absolute target position, input for closed loop operation", 
                            unit="steps in 14-bit resolution per full 360 degrees rotation", 
                            access="Read and Write")

position              = Parameter(
                            id=0x43, 
                            data_type="I32", 
                            description="Multiturn absolute encoder output relative to absolute zero position", 
                            unit="Steps in 14-bit resolution per full 360 degrees rotation", 
                            access="Read Only")

angle                 = Parameter(
                            id=0x44, 
                            data_type="I32", 
                            description="Absolute encoder angle output, wraps at one full mechanical revolution", 
                            unit="milli degrees", 
                            access="Read Only")

profile_velocity      = Parameter(
                            id=0x45, data_type="U32", 
                            description="Set the velocity in terms of steps per second (Hz)", 
                            unit="steps/second", 
                            access="Read and Write")

profile_acceleration  = Parameter(
                            id=0x46, 
                            data_type="U32", 
                            description="Set the step acceleration", 
                            unit="steps/sec^2", 
                            access="Read and write")

profile_deceleration  = Parameter(
                            id=0x47, 
                            data_type="U32", 
                            description="Set the step deceleration", 
                            unit="steps/sec^2", 
                            access="Read and Write")

microstep             = Parameter(
                            id=0x48, 
                            data_type="U32", 
                            description="Set motor step level from full step to 1/256 microsteps", 
                            unit="unitless", 
                            access="Read and Write")

motor_current         = Parameter(
                            id=0x49, 
                            data_type="U32", 
                            description="Set motor phase nominal current regulation point", 
                            unit="milli ampere", 
                            access="Read and Write")

motor_current_max     = Parameter(
                            id=0x50, 
                            data_type="U32", 
                            description="Set the motor phase maximum current regulation point", 
                            unit="milli ampere", 
                            access="Read and Write")

motor_current_min     = Parameter(
                            id=0x51, 
                            data_type="U32", 
                            description="Set the motor phase minimum current regulation point", 
                            unit="milli ampere", 
                            access="Read and Write")

motor_full_step       = Parameter(
                            id=0x52, 
                            data_type="U32", 
                            description="Stepper motor full step count per full revolution", 
                            unit="full step / full revolution", 
                            access="Read and Write")

#  Telemetry (0x80–0x9F) ---------------------------------------------------------------------------------
voltage               = Parameter(
                            id=0x80, 
                            data_type="I32",
                            description="Input bus DC voltage as measured by onboard sensor.",
                            unit= "mV",
                            access= "Read Only")


current               = Parameter(
                            id=0x81, 
                            data_type="I32",
                            description="Input bus DC current as measured by onboard sensor",
                            unit="mA",
                            access="Read Only")


temperature           = Parameter(
                            id=0x82, 
                            data_type="I32",
                            description="Temperature as measured by onboard sensor",
                            unit="m°C",
                            access="Read Only")


# Diagnostics and calibration (0xC0–0xDF) -----------------------------------------------------
calibration           = Parameter(id=0xC0, data_type="U8", description="", unit="", access="")
led1                  = Parameter(id=0xC1, data_type="U8", description="", unit="", access="")
uptime                = Parameter(id=0xC2, data_type="U32", description="", unit="", access="")
debug                 = Parameter(id=0xC3, data_type="I32", description="", unit="", access="")
test                  = Parameter(id=0xC4, data_type="U32", description="", unit="", access="")
sector                = Parameter(id=0xC5, data_type="U8", description="", unit="", access="")
fine_angle            = Parameter(id=0xC6, data_type="I32", description="", unit="", access="")

# Raw capacitive channels ---------------------------------------------------------------------
ch0                   = Parameter(id=0xD0, data_type="U32", description="", unit="", access="")
ch1                   = Parameter(id=0xD1, data_type="U32", description="", unit="", access="")
ch2                   = Parameter(id=0xD2, data_type="U32", description="", unit="", access="")
ch3                   = Parameter(id=0xD3, data_type="U32", description="", unit="", access="")
ch4                   = Parameter(id=0xD4, data_type="U32", description="", unit="", access="")
ch5                   = Parameter(id=0xD5, data_type="U32", description="", unit="", access="")
ch6                   = Parameter(id=0xD6, data_type="U32", description="", unit="", access="")
ch7                   = Parameter(id=0xD7, data_type="U32", description="", unit="", access="")
ch8                   = Parameter(id=0xD8, data_type="U32", description="", unit="", access="")
ch9                   = Parameter(id=0xD9, data_type="U32", description="", unit="", access="")
ch10                  = Parameter(id=0xDA, data_type="U32", description="", unit="", access="")
ch11                  = Parameter(id=0xDB, data_type="U32", description="", unit="", access="")
ch12                  = Parameter(id=0xDC, data_type="U32", description="", unit="", access="")
ch13                  = Parameter(id=0xDD, data_type="U32", description="", unit="", access="")
