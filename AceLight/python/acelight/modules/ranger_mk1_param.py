
from ..parameter import Parameter

# AceLight standard module parameters
sync                  = Parameter(id=0x01, data_type="U8")
node_id               = Parameter(id=0x02, data_type="U8")
device_type           = Parameter(id=0x03, data_type="U8")
serial_number         = Parameter(id=0x04, data_type="U8")
firmware_version      = Parameter(id=0x05, data_type="U8")
hardware_version      = Parameter(id=0x06, data_type="U8")
protocol_version      = Parameter(id=0x07, data_type="U8")

# Ranger Mk1 module specific parameters 
mode                  = Parameter(id=0x40, data_type="U8")
step_move             = Parameter(id=0x41, data_type="I32")
target_position       = Parameter(id=0x42, data_type="I32")
angle                 = Parameter(id=0x44, data_type="I32")

profile_velocity      = Parameter(id=0x45, data_type="U32")
profile_acceleration  = Parameter(id=0x46, data_type="U32")

voltage               = Parameter(id=0x80, data_type="I32")
current               = Parameter(id=0x81, data_type="I32")
temperature           = Parameter(id=0x82, data_type="I32")

# Continue with the remaining parameters.