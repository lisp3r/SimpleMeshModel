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
from copy import copy

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
                    # self.logger.info(f'Recieved msg from {addr[0]}')
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
    CONF_PATH = 'config.yml'

    def __init__(self, config=CONF_PATH):
        self.name, self.network, self.broadcast_port, self.interface_pattern = yaml.load(open(config, 'r'), Loader=yaml.Loader).values()
        self.ip_addr = socket.gethostbyname(socket.gethostname())
        self.logger = create_logger(f'{self.name}-logger', threads=False)
        self.local_interfaces = {x: netifaces.ifaddresses(x)[netifaces.AF_INET][0]['addr'] for x in [i for i in netifaces.interfaces() if self.interface_pattern in i]}
        self.logger.info(f'{self.name} created in {self.network}. Local interfaces: {self.local_interfaces}')
        self.network_graph = nx.Graph()
        self.network_graph.add_node(self.name, addr=self.local_interfaces.values())
        self.neighbor_table = []
        self.mpr_set = []
        self.lock = threading.RLock()

    def get_neighbors(self, node=None, dist=1):
        if not node:
            node = self.name
        return [
            x for x in nx.single_source_shortest_path_length(self.network_graph, node, cutoff=dist) 
            if nx.single_source_shortest_path_length(self.network_graph, node, cutoff=dist)[x] == dist
        ]

    def is_am_MPR(self):
        if not self.get_by('mprss'):
            return False
        return True

    def get_notwork_info(self):
        return f'{self.network_graph.edges()}\n{self.network_graph.nodes().data()}'

    def __update_topology__(self, data, addr):
        with self.lock:
            m = message.MessageHandler().unpack(data)
            if m.message_type == 'HELLO':
                if addr not in self.local_interfaces.values(): # not our broadcast msg
                    # add node and edge
                    self.network_graph.add_node(m.sender, addr=[addr])
                    self.network_graph.add_edge(self.name, m.sender)
                    for nbr in m.neighbors:
                        # if me in sender's neighbors and he marked me as a MPR - mark he as mprss
                        if nbr['name'] == self.name and nbr.get('local_mpr'):
                            self.network_graph.add_node(m.sender, addr=[addr], mprss=True)
                            self.logger.debug(f'Node {m.sender} added me in a MBR set! I added it "mprss" flag')
                        self.network_graph.add_edge(m.sender, nbr['name'])
            elif m.message_type == 'TC':
                if addr not in self.local_interfaces.values():
                    if m.sender in self.neighbor_table or m.sender in self.get_neighbors(dist=2):
                        # mark as MPR (somebodie's MBR, nonlocal)
                        self.network_graph.add_node(m.sender, mpr=True)
                        for nbr in m.mpr_set:
                            self.network_graph.add_edge(m.sender, nbr['name'])
                    if self.is_am_MPR():
                        Broadcaster(m, self.local_interfaces.keys(),
                        self.broadcast_port, 5, logger=self.logger).run()
            self.update_neighbors()
            self.update_MPRs()
            self.update_MPR_set()

    def update_topology(self, broadcast_time, listerning_time):
        b_threads = Broadcaster(
            message.MessageHandler().hello_message(self.name, self.neighbor_table),
            self.local_interfaces.keys(),
            self.broadcast_port,
            broadcast_time,
            logger=self.logger).run(True)
        l_threads = Listerner(
            self.local_interfaces.keys(),
            self.broadcast_port,
            listerning_time,
            self.logger,
            self.__update_topology__).run(True)
        if self.is_am_MPR():
            Broadcaster(
                message.MessageHandler().tc_message(self.name, self.mpr_set),
                self.local_interfaces.keys(),
                self.broadcast_port,
                broadcast_time,
                logger=self.logger).run()
        [x.join() for x in [*b_threads, *l_threads]]

    def visualize_network(self, with_mpr=False, image_postfix=None):
        plt.plot()
        plt.axis('off')
        if with_mpr:
            color_map = []
            for node in self.network_graph:
                if node in self.get_by('local_mpr'):
                    color_map.append('red')
                elif node in self.get_by('mpr'):
                    color_map.append('green')
                else:
                    color_map.append('blue')
            nx.draw(self.network_graph, node_color=color_map, with_labels=True)
            #nx.draw_shell(self.network_graph, node_color=color_map, with_labels=True)
        else:
            nx.draw(self.network_graph, with_labels=True)
            #nx.draw_shell(self.network_graph, with_labels=True)
        if index:
            image_name = f'artifacts/{self.name}-{image_postfix}.png'
        else:
            image_name = f'artifacts/{self.name}.png'
        plt.savefig(image_name)

    def get_data(self, node):
        return self.network_graph.nodes().data()[node]

    def get_by(self, arg) -> list:
        # return: ['node13', 'node14', 'node15', ...]
        return [x[0] for x in self.network_graph.nodes().data() if x[1].get(arg)]

    def update_neighbors(self):
        self.neighbor_table.clear()
        for nbr in list(self.network_graph.neighbors(self.name)): 
            self.neighbor_table.append({ 
                'name': nbr,
                'addr': self.network_graph.nodes().data()[nbr]['addr'], # self.get_data(nbr)['addr']
                'local_mpr': True if self.network_graph.nodes().data()[nbr].get('local_mpr') else False,
                'mprss': True if self.network_graph.nodes().data()[nbr].get('mprss') else False
            })

    def update_MPR_set(self):
        self.mpr_set.clear()
        for node in self.get_by("mprss"):
            self.mpr_set.append({
                    'name': node,
                    'addr': self.get_data(node)
                })

    def update_MPRs(self):
        self.logger.info(f'Update MPR set')
        self.update_neighbors()
        any_in = lambda a, b: any(i in b for i in a)

        nodes_1 = self.get_neighbors()
        nodes_2 = self.get_neighbors(dist=2)

        mpr_set = []

        # clean existing mpr set
        for node in self.network_graph:
            if self.get_data(node).get('local_mpr'):
                self.network_graph.add_node(node, local_mpr=False)

        while nodes_2:
            node_1_dict = {}
            for n in nodes_1:
                # all two my 2-neighbors
                node_1_dict[n] = [x for x in list(self.network_graph.neighbors(n)) if x in nodes_2 and x != self.name]

            node_1_dict = {x: node_1_dict[x] for x in sorted(node_1_dict, key=lambda k: len(node_1_dict[k]), reverse=True)}
            mpr = next(iter(node_1_dict)) # first in sorted dict
            mpr_set.append(mpr)

            nodes_2 = [x for x in nodes_2 if x not in node_1_dict[mpr]]

            upd_nodes_1_dict = [x for x in nodes_1 if x not in mpr_set]
            nodes_1 = [x for x in upd_nodes_1_dict if any_in(nodes_2, node_1_dict[x])]

        for node in self.network_graph:
            if node in mpr_set:
                self.network_graph.add_node(node, local_mpr=True)

if len(sys.argv) > 2:
    print('Usage: python node.py [config]')
    exit(1)

if len(sys.argv) == 2:
    node = Node(sys.argv[1])
else:
    node = Node()

cycle_idx = 0
while True:
    node.update_topology(5,10)
    node.visualize_network(with_mpr=True, image_postfix=cycle_idx)
    cycle_idx += 1

# # node.logger.info(f'MPR list: {node.get_by("mpr")}, MPR selector set: {node.get_by("mprss")}')

# # node.visualize_network()
# node.update_topology(3,3)
# # node.logger.info(f'MPR list: {node.get_by("mpr")}, MPR selector set: {node.get_by("mprss")}')
# node.update_topology(5,5)
# # node.logger.info(f'MPR list: {node.get_by("mpr")}, MPR selector set: {node.get_by("mprss")}')
# node.update_topology(5,5)
# # node.update_topology(5,5)
# node.visualize_network(with_mpr=True)

# # node.logger.info(f'Network graph: {node.network_graph.nodes().data()}\n')
# node.logger.info(f'MPR list: {node.get_by("local_mpr")}, MPR selector set: {node.get_by("mprss")}')
# node.logger.info(node.get_notwork_info())
