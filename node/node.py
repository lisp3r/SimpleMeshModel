import sys
import yaml
import socket
import time
import logging
import threading
import netifaces
import re


def create_logger(logger_name, formatter=None):
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    if not formatter:
        formatter = logging.Formatter(f'%(asctime)s - [%(threadName)s] - %(levelname)s - %(message)s', '%H:%M:%S')
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger

class Listerner:
    def __init__(self, interfaces, listerning_port, listerning_time=None, logger=None, handler=None):
         self.logger = logger if logger else create_logger('listener-logger')
         self.PORT = listerning_port
         self.LISTERNING_TIME = listerning_time
         self.interfaces = interfaces if interfaces else ['']
         self.sockets = {x: self.__create_socket__(x) for x in self.interfaces}
         self.handler = handler

    def __create_socket__(self, iface):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.setblocking(0)
        sock.settimeout(self.LISTERNING_TIME)
        # sock.bind((netifaces.ifaddresses(iface)[netifaces.AF_INET][0]['addr'], self.PORT))
        sock.bind(('', self.PORT))
        return sock

    def run(self, return_threads=False):
        def listen(sock):
            timeout = (time.time() + self.LISTERNING_TIME) if self.LISTERNING_TIME else False
            while True:
                try:
                    data, addr = sock.recvfrom(1024)
                    # self.logger.info(f'Recieved: {data}; from {addr[0]}')
                    if self.handler:
                        self.handler(data, addr[0])
                    if timeout and time.time() > timeout:
                        break
                except socket.timeout:
                    # self.logger.debug(f'Listerning timeout')
                    return
        threads = [threading.Thread(target=listen, name=f'listen_{iface}', args=(sc,)) for iface, sc in self.sockets.items()]
        [t.start() for t in threads]
        if return_threads:
            return threads

class Broadcaster:
    def __init__(self, msg, interfaces=None, broadcast_port=None, broadcast_time=None, broadcast_sleep=1, logger=None):
        self.UDP_IP = '<broadcast>'
        self.UDP_PORT = broadcast_port if broadcast_port else 37020
        self.interfaces = interfaces if interfaces else ['']
        self.BROADCAST_TIME = broadcast_time
        self.BROADCAST_SLEEP = broadcast_sleep
        if isinstance(msg, str):
            msg = msg.encode()
        self.msg = msg
        self.logger = logger if logger else create_logger('broadcast-logger')
        self.sockets = {x: self.__create_socket__(x) for x in self.interfaces}

    def __create_socket__(self, iface):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1) # debug
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.2)
        sock.setblocking(0)
        # self.logger.debug(f'creating broadcasting socket on: {(netifaces.ifaddresses(iface)[netifaces.AF_INET][0]["addr"], 44444)}')
        sock.bind((netifaces.ifaddresses(iface)[netifaces.AF_INET][0]['addr'], 1234))
        return sock

    def run(self, return_threads=False):
        def broadcast(sock):
            timeout = (time.time() + self.BROADCAST_TIME) if self.BROADCAST_TIME else False
            while True:
                # self.logger.debug(f'Broadcasting: {self.msg}')
                sock.sendto(self.msg, (self.UDP_IP, self.UDP_PORT))
                time.sleep(self.BROADCAST_SLEEP)
                if timeout and time.time() > timeout:
                    # self.logger.debug(f'Broadcasting timeout')
                    break

        threads = [threading.Thread(target=broadcast, name=f'broadcast_{iface}', args=(socket,)) for iface, socket in self.sockets.items()]
        [t.start() for t in threads]
        if return_threads:
            return threads

class Node:
    CONF_PATH = 'config.yml'
    def __init__(self, config=CONF_PATH):
        self.name, self.network, self.exit_node, self.broadcast_port, self.interface_pattern = yaml.load(open(config, 'r'), Loader=yaml.Loader).values()
        self.ip_addr = socket.gethostbyname(socket.gethostname())
        self.logger = self.__create_logger__()
        self.logger.info(f'{self.name} created in {self.network} with parameters: exit_node={self.exit_node}')
        self.local_interfaces = {x: netifaces.ifaddresses(x)[netifaces.AF_INET][0]['addr'] for x in [i for i in netifaces.interfaces() if self.interface_pattern in i]}
        self.one_hop_neighbors = []
        self.two_hop_neighbors = []
        self.lock = threading.RLock()

    def __create_logger__(self):
        logger = logging.getLogger(f'{self.name}-logger')
        logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        formatter = logging.Formatter(f'%(asctime)s - {self.name} - %(levelname)s - %(message)s', '%H:%M:%S')
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        return logger

    def __update_one_neighbor_table__(self, data, addr):
        with self.lock:
            if b'HELLO' == data:
                if addr not in self.one_hop_neighbors and addr not in self.local_interfaces.values():
                    self.one_hop_neighbors.append(addr)

    def update_neighbor_table(self, broadcast_time, listerning_time):
        b_threads = Broadcaster('HELLO', self.local_interfaces.keys(), self.broadcast_port, broadcast_time, logger=self.logger).run(True)
        l_threads = Listerner(self.local_interfaces.keys(), self.broadcast_port, listerning_time, self.logger, self.__update_one_neighbor_table__).run(True)
        [x.join() for x in [*b_threads, *l_threads]]

if len(sys.argv) > 2:
    print('Usage: python node.py [config]')
    exit(1)

if len(sys.argv) == 2:
    node = Node(sys.argv[1])
else:
    node = Node()

node.update_neighbor_table(5,5)
node.logger.info(f'One neighbor table: {node.one_hop_neighbors}\n')


# while True:
#     node.update_neighbor_table(5,5)

#     node.logger.info(f'\nOne neighbor table: {node.one_hop_neighbors}\n')
