import socket

interface = 'node0'

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(('10.1.1.150', 9999))