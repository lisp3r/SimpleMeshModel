# Mesh network prototype

# mesh over tcp/ip
# https://pypi.org/project/netifaces/
# import netifaces

# addrs = netifaces.ifaddresses('node1')

# print(addrs[netifaces.AF_INET6])


# 17: AF_LINK (link layer interface, e.g. Ethernet)
# AF_INET (normal Internet addresses)
# 10 is AF_INET6 (IPv6)

# print(netifaces.gateways())

# import socket
# import sys
# import time

# CONNECT_MAX = 5

# if len(sys.argv) != 3:
#     print("Usage details: simple_mesh_api.py addr port\n")
#     sys.exit()

# addr = (str(sys.argv[1]), int(sys.argv[2]))

# sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
# sock.bind(addr)
# sock.listen(CONNECT_MAX)

# (client, adress) = sock.accept()
# with client:
#     print(f'Connection established with {adress}')
#     while True:
#         data = client.recv(1024)
#         if not data: break
#         client.sendall(data)

# sock.close()
