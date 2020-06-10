import sys
import yaml
import socket
import time
import logging
import threading


class Node:
    CONF_PATH = 'config.yml'
    def __init__(self, config=CONF_PATH):
        self.name, self.network, self.exit_node, self.broadcast_port = yaml.load(open(config, 'r'), Loader=yaml.Loader).values()
        self.ip_addr = socket.gethostbyname(socket.gethostname())
        self.logger = self.__create_logger__()

        self.logger.info(f'{self.name} created in {self.network} with parameters: exit_node={self.exit_node}')
        self.one_hop_neighbors = []
        self.two_hop_neighbors = []

    def __create_logger__(self):
        logger = logging.getLogger(f'{self.name}-logger')
        logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        formatter = logging.Formatter(f'%(asctime)s - [%(threadName)s] - {self.name} [{self.ip_addr}] - %(levelname)s - %(message)s', '%H:%M:%S')
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        return logger

    def __broadcast__(self, msg, broadcast_time=None, broadcast_port=None, broadcast_sleep=1):
        if not broadcast_port:
            broadcast_port = self.broadcast_port
        if isinstance(msg, str):
            msg = msg.encode()
        self.logger.debug(f'Start broadcast to: {broadcast_port}')
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1) # debug
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.2)
        sock.setblocking(0)

        timeout = (time.time() + broadcast_time) if broadcast_time else False

        while True:
            sock.sendto(msg, ('<broadcast>', broadcast_port))
            self.logger.debug(f'Broadcasting: {msg}')
            time.sleep(broadcast_sleep)
            if timeout and time.time() > timeout:
                break

    def HELLO_msg_broadcast(self, broadcast_time):
        self.__broadcast__('HELLO', broadcast_time)

    def HELLO_msg_listen(self, listerning_time=None):
        timeout = (time.time() + listerning_time) if listerning_time else False

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.setblocking(0)

        sock.settimeout(listerning_time)
        sock.bind(("", self.broadcast_port))

        self.logger.debug(f'Start listrening on: {self.broadcast_port}')

        while True:
            try:
                data, addr = sock.recvfrom(1024)
                if data == b'HELLO':
                    if addr not in self.one_hop_neighbors:
                        self.one_hop_neighbors.append(addr)
                        self.logger.debug(f'Add {addr} to neighbor table')
                    else:
                        self.logger.debug(f'{addr} already in neighbor table')
                if timeout and time.time() > timeout:
                    break
            except socket.timeout:
                return

    def update_neighbor_table(self, broadcast_time, listerning_time):
        broadcast_th = threading.Thread(target=self.HELLO_msg_broadcast, name='HELLO_broadcast', args=(broadcast_time,))
        broadcast_th.start()
        listen_th = threading.Thread(target=self.HELLO_msg_listen, name='HELLO_listen', args=(listerning_time,))
        listen_th.start()
        broadcast_th.join()
        listen_th.join()


if len(sys.argv) > 2:
    print('Usage: python node.py [config]')
    exit(1)

if len(sys.argv) == 2:
    node1 = Node(sys.argv[1])
else:
    node1 = Node()
node1.update_neighbor_table(5,5)

print(f'\nTable: {node1.one_hop_neighbors}')


