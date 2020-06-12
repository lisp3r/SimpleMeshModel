import sys
import yaml
import socket
import time
import logging
import threading
import netifaces
import re
import message
import networkx as nx
import matplotlib.pyplot as plt
import random


def create_logger(logger_name, threads=True):
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    if not threads:
        formatter = logging.Formatter(f'%(asctime)s - %(levelname)s - %(message)s', '%H:%M:%S')
    else:
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
                    data, addr = sock.recvfrom(4096)
                    # self.logger.info(f'Recieved data; from {addr[0]}')
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
                sock.sendto(self.msg.make(), (self.UDP_IP, self.UDP_PORT))
                time.sleep(self.BROADCAST_SLEEP)
                if timeout and time.time() > timeout:
                    # self.logger.debug(f'Broadcasting timeout')
                    break

        threads = [threading.Thread(target=broadcast, name=f'broadcast_{iface}', args=(socket,)) for iface, socket in self.sockets.items()]
        [t.start() for t in threads]
        if return_threads:
            return threads

class Node:

    def __init__(self):
        random.seed(socket.gethostname())
        self.name = f'node{int(random.random()*100)}'
        self.logger = create_logger(f'{self.name}-logger', threads=False)
        self.broadcast_port = 37020
        self.interface_pattern = 'eth'
        self.ip_addr = socket.gethostbyname(socket.gethostname())
        self.local_interfaces = {x: netifaces.ifaddresses(x)[netifaces.AF_INET][0]['addr'] for x in [i for i in netifaces.interfaces() if self.interface_pattern in i]}
        self.neighbor_graph = []
        self.logger.info(f'Node {self.name} created on {", ".join(list(self.local_interfaces.values()))}')
        self.lock = threading.RLock()

    def __create_neighbor__(self, data):
        return {
            'name': data.sender,
            'addr': data.addr,
            'neighbors': data.neighbors
        }

    def is_neighbor_exists(self, neighbor):
        for x in self.neighbor_graph:
            if x['addr'] == neighbor['addr']:
                return True
            if x['name'] == neighbor['name']:
                return True
        return False

    def __update_neighbor_graph__(self, data, addr):
        with self.lock:
            m = message.MessageHandler().unpack(data)
            if m.message_type == 'HELLO':
                if addr not in self.local_interfaces.values():
                    m.addr = addr
                    m_neighbor = self.__create_neighbor__(m)
                    m_neighbor['neighbors'] = [x for x in m_neighbor['neighbors'] if x not in self.local_interfaces.values()]
                    # self.logger.info(f'Recieved HELLO from {addr}')
                    if not self.is_neighbor_exists(m_neighbor):
                        self.neighbor_graph.append(m_neighbor)
                    else:
                        # self.logger.info(f'{addr} already in table, updating neighbors with {m.neighbors}')
                        for x in self.neighbor_graph:
                            if x['addr'] == m_neighbor['addr']:
                                x['neighbors'] = m_neighbor['neighbors']

    def update_neighbor_table(self, broadcast_time, listerning_time):
        b_threads = Broadcaster(
            message.MessageHandler().hello_message(self.name, self.neighbor_graph),
            self.local_interfaces.keys(),
            self.broadcast_port,
            broadcast_time,
            logger=self.logger).run(True)
        l_threads = Listerner(
            self.local_interfaces.keys(),
            self.broadcast_port,
            listerning_time,
            self.logger,
            self.__update_neighbor_graph__).run(True)
        [x.join() for x in [*b_threads, *l_threads]]

    def visualize_neighbors(self):
        G = nx.Graph()
        G.add_node(self.name)
        for neighbor in self.neighbor_graph:
            G.add_edge(self.name, neighbor['name'])
            for neighbor_2 in neighbor['neighbors']:
                G.add_edge(neighbor['name'], neighbor_2['name'])
        plt.subplot()
        # plt.subplots_adjust(top=0.1, bottom=0.0, right=0.1, left=0.0)
        nx.draw(G, with_labels=True, font_weight='bold')
        plt.savefig(f'artefacts/{self.name}.png')


node = Node()
node.update_neighbor_table(5,5)
node.visualize_neighbors()

node.logger.info(f'Neighbor graph: {node.neighbor_graph}\n')


# while True:
#     node.update_neighbor_table(5,5)

#     node.logger.info(f'\nOne neighbor table: {node.one_hop_neighbors}\n')
