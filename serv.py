import socket
import sys
import time

# ADDR = ('', 9999)
# CONNECT_MAX = 5

# with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
#     sock.bind(ADDR)
#     sock.listen(CONNECT_MAX)

#     (client, adress) = sock.accept()
#     with client:
#         print(f'Connection established with {adress}')
#         while True:
#             data = client.recv(1024)
#             if data:
#                 print(f'Recieved: {data}')
#                 client.sendall(data)

server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

# Enable broadcasting mode
server.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

# Set a timeout so the socket does not block indefinitely when trying to receive data.
server.settimeout(2)
hostname = socket.gethostname()
if hostname:
    message = socket.gethostbyname(hostname).encode()
else:
    message = b"no hostname"
while True:
    server.sendto(message, ('<broadcast>', 37020))
    print("message sent!")
    time.sleep(1)