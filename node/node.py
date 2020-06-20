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
from random import choice, randint


def create_logger(logger_name, threads=True):
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    fh = logging.FileHandler(f'artifacts/{logger_name}')
    if not threads:
        formatter = logging.Formatter(f'%(message)s', '%H:%M:%S')
    else:
        formatter = logging.Formatter(f'%(asctime)s - [%(threadName)s] - %(levelname)s - %(message)s', '%H:%M:%S')
    ch.setFormatter(formatter)
    fh.setFormatter(formatter)
    logger.addHandler(ch)
    logger.addHandler(fh)
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
        sock.bind(('', self.PORT))
        return sock

    def run(self, return_threads=False, background=False):
        def listen(sock):
            timeout = (time.time() + self.LISTERNING_TIME) if self.LISTERNING_TIME else False
            while True:
                try:
                    data, addr = sock.recvfrom(4096)
                    if self.handler:
                        self.handler(data, addr[0])
                    if timeout and time.time() > timeout:
                        break
                except socket.timeout:
                    return
        threads = [threading.Thread(
            target=listen, name=f'listen_{iface}', args=(sc,)) for iface, sc in self.sockets.items()]
        for thread in threads:
            if background:
                thread.daemon = True
            thread.start()
        if return_threads:
            return threads

class Broadcaster:
    def __init__(self, msg, interfaces=None, msg_send_callback=None, broadcast_port=None,
                                    broadcast_time=None, broadcast_sleep=30, logger=None):
        self.UDP_IP = '<broadcast>'
        self.UDP_PORT = broadcast_port if broadcast_port else 37020
        self.interfaces = interfaces if interfaces else ['']
        self.BROADCAST_TIME = broadcast_time
        self.BROADCAST_SLEEP = broadcast_sleep
        self.msg = msg
        self.msg_send_callback = msg_send_callback if msg_send_callback else lambda: True
        self.logger = logger if logger else create_logger('broadcast-logger')
        self.sockets = {x: self.__create_socket__(x) for x in self.interfaces}

    def __create_socket__(self, iface):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.2)
        sock.setblocking(0)
        sock.bind((netifaces.ifaddresses(iface)[netifaces.AF_INET][0]['addr'], 1234))
        return sock

    def run(self, return_threads=False, background=False):
        def broadcast(sock):
            timeout = (time.time() + self.BROADCAST_TIME) if self.BROADCAST_TIME else False
            while True:
                if self.msg_send_callback():
                    sock.sendto(self.msg.make(), (self.UDP_IP, self.UDP_PORT))
                time.sleep(self.BROADCAST_SLEEP)
                if timeout and time.time() > timeout:
                    break
        threads = [threading.Thread(target=broadcast, name=f'broadcast_{iface}', args=(socket,)) for iface, socket in self.sockets.items()]
        for thread in threads:
            if background:
                thread.daemon = True
            thread.start()
        if return_threads:
            return threads

class Node:
    CONF_PATH = 'config.yml'

    def __init__(self, config=CONF_PATH):
        cfg = yaml.load(open(config, 'r'), Loader=yaml.Loader)
        self.side = cfg.get('side', 'good')
        self.name = cfg['name']
        self.network = cfg['networks']
        self.broadcast_port = cfg.get('broadcast_port', 37020)
        self.interface_pattern = cfg.get('interface_pattern', 'eth')
        self.ip_addr = socket.gethostbyname(socket.gethostname())
        self.logger = create_logger(f'{self.name}.log', threads=False)
        # https://networkx.github.io/documentation/stable/reference/drawing.html
        visualize_mode = cfg.get('visualize_mode')
        if visualize_mode:
            visualize_mode = f'draw_{visualize_mode}'
        else:
            visualize_mode = 'draw'
        try:
            self.visualize_method = getattr(nx, visualize_mode)
        except AttributeError:
            self.visualize_method = nx.draw
        self.local_interfaces = {x: netifaces.ifaddresses(x)[netifaces.AF_INET][0]['addr'] for x in [i for i in netifaces.interfaces() if self.interface_pattern in i]}
        self.network_graph = nx.Graph()
        self.network_graph.add_node(self.name, addr=self.local_interfaces.values())
        self.neighbor_table = []
        self.mpr_set = []
        self.lock = threading.RLock()
        self.update_topology()

    def get_neighbors(self, node=None, dist=1):
        if not node:
            node = self.name
        all_nbrs = nx.single_source_shortest_path_length(self.network_graph, node, cutoff=dist)
        if dist:
            return [node for node,ndist in all_nbrs.items() if ndist == dist]
        else:
            return list(all_nbrs.keys())

    def is_am_MPR(self):
        if not self.get_by('mprss'):
            return False
        return True

    def get_notwork_info(self):
        return f'{self.network_graph.edges()}\n{self.network_graph.nodes().data()}'

    def __update_topology__(self, data, addr):
        # Ignore self messages
        if addr in self.local_interfaces.values():
            return
        with self.lock:
            m = message.MessageHandler().unpack(data)
            if m.message_type == 'HELLO':
                # add node and edge
                self.network_graph.add_node(m.sender, addr=[addr])
                self.network_graph.add_edge(self.name, m.sender)
                for nbr in m.neighbors:
                    # if me in sender's neighbors and he marked me as a MPR - mark him as mprss
                    if nbr['name'] == self.name and nbr.get('local_mpr'):
                        self.network_graph.add_node(m.sender, addr=[addr], mprss=True)
                    self.network_graph.add_edge(m.sender, nbr['name'])
            elif m.message_type == 'TC':
                if m.sender in self.get_neighbors(dist=None):
                    # mark as MPR (somebody's MBR, nonlocal)
                    self.network_graph.add_node(m.sender, mpr=True)
                    for nbr in m.mpr_set:
                        # print(f"Adding {nbr['name']}")
                        self.network_graph.add_edge(m.sender, nbr['name'])
                if self.is_am_MPR():
                    Broadcaster(m, self.local_interfaces.keys(),
                    broadcast_port=self.broadcast_port, broadcast_time=5, logger=self.logger).run()
            elif m.message_type == 'CUSTOM':
                if m.dest == self.name:
                    self.logger.info(f'Got CUSTOM message from {m.sender}: {m.msg}; path: {m.forwarders}')
                    try:
                        self.visualize_route(m.forwarders)
                    except Exception as e:
                        self.logger.error(f'{e}\n{self.network_graph}')
                else:
                    if self.is_am_MPR() and self.is_am_in_route(m):
                        if m.sender != self.name:
                            if self.side == 'good':
                                if self.name not in m.forwarders:
                                    self.logger.info(f'I am MPR for {self.get_by("mprss")}. My MPRS: {self.get_by("mpr")}. I got msg from {m.sender} to {m.dest}. Its prev path: {m.forwarders}. Forwarding...')
                                    m.forwarders.append(self.name)
                                    Broadcaster(m, self.local_interfaces.keys(),
                                    broadcast_port=self.broadcast_port, broadcast_time=1, logger=self.logger).run()
                            elif self.side == 'evil':
                                self.logger.info(f'I got msg from {m.sender} to {m.dest}. Its prev path: {m.forwarders}. Dropping...')
            self.update_neighbors()
            self.update_MPRs()
            self.update_MPR_set()

    def is_am_in_route(self, msg):
        return True
        full_route = self.get_route(msg.dest, msg.forwarders[-1])

    def update_topology(self):
        Broadcaster(
            message.MessageHandler().hello_message(self.name, self.neighbor_table),
            interfaces=self.local_interfaces.keys(),
            broadcast_port=self.broadcast_port,
            logger=self.logger).run(True)
        Listerner(
            self.local_interfaces.keys(),
            self.broadcast_port,
            logger=self.logger,
            handler=self.__update_topology__).run(True)
        Broadcaster(
            message.MessageHandler().tc_message(self.name, self.mpr_set),
            interfaces=self.local_interfaces.keys(),
            msg_send_callback=self.is_am_MPR,
            broadcast_port=self.broadcast_port,
            logger=self.logger).run()

    def visualize_network(self, with_mpr=False, image_postfix=None):
        plt.clf()
        plt.plot()
        plt.axis('off')
        with self.lock:
            if with_mpr:
                color_map = []
                for node in self.network_graph:
                    if node in self.get_by('local_mpr'):
                        color_map.append('red')
                    elif node in self.get_by('mpr'):
                        color_map.append('green')
                    else:
                        color_map.append('blue')
                self.visualize_method(self.network_graph, node_color=color_map, with_labels=True)
            else:
                self.visualize_method(self.network_graph, with_labels=True)
        if isinstance(image_postfix, int):
            image_name = f'artifacts/{self.name}-{image_postfix}.png'
        else:
            image_name = f'artifacts/{self.name}.png'
        plt.savefig(image_name)

    def visualize_route(self, route):
        def_col = 'b'
        copy_graph = copy(self.network_graph)
        plt.clf()
        plt.plot()
        plt.axis('off')
        start_node = route[0]
        for hop in route[1:]:
            copy_graph.edges[start_node, hop]['color'] = 'r'
            start_node = hop
        edges_color = []
        for x in copy_graph.edges().data():
            if(col := x[2].get('color')):
                edges_color.append(col)
            else:
                edges_color.append(def_col)
        self.logger.info("Update image")
        self.visualize_method(self.network_graph, with_labels=True, edge_color=edges_color)
        plt.savefig(f'artifacts/{self.name}-route.png')

    def get_data(self, node):
        return self.network_graph.nodes().data()[node]

    def get_by(self, arg) -> list:
        return [x[0] for x in self.network_graph.nodes().data() if x[1].get(arg)]

    def update_neighbors(self):
        self.neighbor_table.clear()
        for nbr in list(self.network_graph.neighbors(self.name)): 
            self.neighbor_table.append({ 
                'name': nbr,
                'addr': self.get_data(nbr)['addr'],
                'local_mpr': True if self.get_data(nbr).get('local_mpr') else False,
                'mprss': True if self.get_data(nbr).get('mprss') else False
            })

    def update_MPR_set(self):
        self.mpr_set.clear()
        for node in self.get_by("mprss"):
            self.mpr_set.append({
                    'name': node,
                    'addr': self.get_data(node)
                })

    def update_MPRs(self):
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
                node_1_dict[n] = [x for x in list(self.network_graph.neighbors(n))
                                  if x in nodes_2 and x != self.name]

            node_1_dict = {x: node_1_dict[x] for x in sorted(
                                                            node_1_dict,
                                                            key=lambda k: len(node_1_dict[k]),
                                                            reverse=True)}
            mpr = next(iter(node_1_dict)) # first in sorted dict
            mpr_set.append(mpr)

            nodes_2 = [x for x in nodes_2 if x not in node_1_dict[mpr]]

            upd_nodes_1_dict = [x for x in nodes_1 if x not in mpr_set]
            nodes_1 = [x for x in upd_nodes_1_dict if any_in(nodes_2, node_1_dict[x])]

        for node in self.network_graph:
            if node in mpr_set:
                self.network_graph.add_node(node, local_mpr=True)

    def get_route(self, dest_node, src_node=None):
        if not src_node:
            src_node = self.name
        if dest_node not in self.network_graph.nodes():
            return []
        return nx.shortest_path(self.network_graph, src_node, dest_node)

    def send_message(self, msg, dest_node):
        path = self.get_route(dest_node)
        self.logger.info(f'Sending "{msg}" to {dest_node}. Expected path: {path}')
        Broadcaster(
            message.MessageHandler().custom_message(self.name, dest_node, msg),
            self.local_interfaces.keys(),
            broadcast_port=self.broadcast_port,
            broadcast_time=5,
            logger=self.logger,
        ).run(background=True)

def test_path(node, visualize=False):
    dist = 5
    second_node = None
    while not second_node:
        second_node = choice(node.get_neighbors(dist=dist))
        dist = dist-1
    route = node.get_route(second_node)
    node.logger.info(f'Shortest path to {second_node}: {route}')
    if visualize:
        node.visualize_route(route)


if __name__ == '__main__':

    if len(sys.argv) > 2:
        print('Usage: python node.py [config]')
        exit(1)

    if len(sys.argv) == 2:
        node = Node(sys.argv[1])
    else:
        node = Node()

    node.logger.info("Spanw endless vizualization thread")
    def viz_wl():
        while(True):
            time.sleep(30)
            node.visualize_network(with_mpr=True)
    th = threading.Thread(target=viz_wl)
    th.daemon = True
    th.start()

    while(True):
        time.sleep(30)
        if node.name == 'nw7-n1':
            if 'nw5-n1' in node.get_neighbors(dist=None):
                node.logger.info(f"Route: {node.get_route('nw5-n1')}")
                node.send_message(f'Hello, X-hop friend!', 'nw5-n1')
            else:
                node.logger.info("Node nw5-n1' not known")
