# Mesh network prototype

# mesh over tcp/ip

import socket
import sys
import time

# HOST = ''    # The remote host
# PORT = 9999  # The same port as used by the server

# DATA = b'Hello, world'
# sock = None

# try:
#     sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
# except OSError as err:
#     sock = None
# try:
#     sock.connect((HOST, PORT))
# except OSError as err:
#     sock.close()
#     sock = None
# if sock is None:
#     print('could not open socket')
#     sys.exit(1)

# while True:
#     DATA = input().encode()
#     sock.sendall(DATA)
#     data = sock.recv(1024)
#     print('Received', repr(data))

client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) # UDP
client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

# Enable broadcasting mode
client.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

client.bind(("", 37020))
# while True:
data, addr = client.recvfrom(1024)
if data:
    print("received message: %s"%data)