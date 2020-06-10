# if the address family is AF_CAN the protocol should be one of CAN_RAW, CAN_BCM or CAN_ISOTP

# sudo modprobe vcan
# sudo ip link add dev vcan0 type vcan
# sudo ip link set vcan0 up


# import socket
# import struct
import can

can_interface = 'vcan0'

bus = can.interface.Bus(can_interface, bustype='socketcan')
message = bus.recv()
print(message)

# CAN frame packing/unpacking (see 'struct can_frame' in <linux/can.h>)

# can_frame_fmt = "=IB3x8s"
# can_frame_size = struct.calcsize(can_frame_fmt)

# def build_can_frame(can_id, data):
#     can_dlc = len(data)
#     data = data.ljust(8, b'\x00')
#     return struct.pack(can_frame_fmt, can_id, can_dlc, data)

# def dissect_can_frame(frame):
#     can_id, can_dlc, data = struct.unpack(can_frame_fmt, frame)
#     return(can_id, can_dlc, data[:can_dlc])


# # create a raw socket and bind it to the 'vcan0' interface
# s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
# s.bind(('vcan0',))

# while True:
#     print('start')
#     cf, addr = s.recvfrom(can_frame_size)
#     print('Received: can_id=%x, can_dlc=%x, data=%s' % dissect_can_frame(cf))

#     try:
#         s.send(cf)
#     except OSError:
#         print('Error sending CAN frame')

#     try:
#         s.send(build_can_frame(0x01, b'\x01\x02\x03'))
#     except OSError:
#         print('Error sending CAN frame')