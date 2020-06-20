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

class NetWorker:

    def __init__(self, port):
        self.__logger = create_logger('networker')
        self.__interfaces_for_addr = {x: netifaces.ifaddresses(x)[netifaces.AF_INET][0]['addr'] for x in [i for i in netifaces.interfaces() if 'eth' in i]}
        self.__logger.warning(self.local_interfaces())
        self.__logger.warning(self.local_addrs())
        self.__port = port
        self.__broadcast_sockets = [self.__get_broadcast_socket(x) for x in self.local_addrs()]
        self.__listening_sockets = [self.__get_listen_socket(x) for x in self.local_interfaces()]

    def local_interfaces(self):
        #return list(self.__interfaces_for_addr.keys()
        return self.__interfaces_for_addr.keys()

    def local_addrs(self):
        #return list(self.__interfaces_for_addr.values())
        return self.__interfaces_for_addr.values()


    def is_local_addr(self, addr):
        return addr in self.local_addrs()

    def __get_broadcast_socket(self, addr):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.2)
        sock.setblocking(0)
        sock.bind((addr, self.__port))
        return sock

    def __get_listen_socket(self, iface):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.setblocking(0)
        sock.settimeout(None)
        sock.bind(('', self.__port))
        return sock

    def send_broadcast(self, msg):
         for socket in self.__broadcast_sockets:
            socket.sendto(msg, ('<broadcast>', self.__port))

    def __listener(self, sock, handler):
        while True:
            data, (addr, _) = sock.recvfrom(4096)
            handler(data, addr)

    def set_listen(self, handler):
        return [threading.Thread(target=self.__listener, args=(sock, handler)) for sock in self.__listening_sockets]

class Node:
    CONF_PATH = 'config.yml'

    def __init__(self, config=CONF_PATH):
        cfg = yaml.load(open(config, 'r'), Loader=yaml.Loader)
        self.side = cfg.get('side', 'good')
        self.name = cfg['name']
        self.net_worker = NetWorker(
            port=cfg.get('broadcast_port', 37020),
        )
        self.logger = create_logger(f'{self.name}.log', threads=False)
        # https://networkx.github.io/documentation/stable/reference/drawing.html
        visualize_mode = f"draw_{cfg.get('visualize_mode')}" if cfg.get('visualize_mode') else 'draw'
        try:
            self.visualize_method = getattr(nx, visualize_mode)
        except AttributeError:
            self.visualize_method = nx.draw
        self.network_graph = nx.Graph()
        self.network_graph.add_node(self.name, addr=self.net_worker.local_addrs())
        self.neighbor_table = []
        self.mpr_set = []
        self.lock = threading.RLock()

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

    def get_network_info(self):
        return f'{self.network_graph.edges()}\n{self.network_graph.nodes().data()}'

    def process_msg(self, data, addr):
        # Ignore self messages
        if self.net_worker.is_local_addr(addr):
            return
        with self.lock:
            m = message.Message.unpack(data)
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
                    self.parse_tc(m)
                self.send_tc(forwarded_msg=m)
            elif m.message_type == 'CUSTOM':
                if m.dest == self.name:
                    self.logger.info(f'Got CUSTOM message from {m.sender}: {m.msg}; path: {m.forwarders}')
                    try:
                        self.visualize_route(m.forwarders)
                    except Exception as e:
                        self.logger.error(f'{e}\n{self.network_graph}')
                else:
                    if self.is_am_MPR() and self.is_on_route(m):
                        if m.sender != self.name:
                            if self.side == 'good':
                                if self.name not in m.forwarders:
                                    self.logger.info(f'I am MPR for {self.get_by("mprss")}. My MPRS: {self.get_by("mpr")}. I got msg from {m.sender} to {m.dest}. Its prev path: {m.forwarders}. Forwarding...')
                                    m.forwarders.append(self.name)
                                    self.net_worker.send_broadcast(m)
                            elif self.side == 'evil':
                                self.logger.info(f'I got msg from {m.sender} to {m.dest}. Its prev path: {m.forwarders}. Dropping...')
            self.update_neighbors()
            self.update_MPRs()
            self.update_MPR_set()

    def is_on_route(self, msg):
        full_route = self.get_route(msg.dest, msg.forwarders[-1])
        return self.name in full_route and self.name not in msg.forwarders

    def parse_tc(self, msg):
        # mark as MPR (somebody's MBR, nonlocal)
        self.network_graph.add_node(msg.sender, mpr=True)
        for nbr in msg.mpr_set:
            # Node is in graph and has other MPR or didn't choose previously
            if nbr['name'] in self.network_graph and self.get_data(nbr['name']).get('choosen_mpr') != msg.sender:
                # It had other MPR
                if self.get_data(nbr['name']).get('choosen_mpr'):
                    old_nbr_mpr = self.get_data(nbr['name']).get('choosen_mpr')
                    # Unset it as MPR in our ghraph
                    if old_nbr_mpr in self.network_graph:
                        self.network_graph.nodes()[old_nbr_mpr]['mpr'] = False
                self.network_graph.add_node(nbr['name'], choosen_mpr=msg.sender)
            self.network_graph.add_edge(msg.sender, nbr['name'])

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

    def send_hello(self):
        msg =  message.Message.from_type(
                    'HELLO', sender=self.name, neighbor_table=self.neighbor_table)
        self.net_worker.send_broadcast(msg.pack())

    def send_tc(self, forwarded_msg=None):
        if forwarded_msg:
            tc_message = forwarded_msg
        else:
            tc_message = message.Message.from_type(
                'TC', sender=self.name, mpr_set=self.mpr_set)
        if self.is_am_MPR():
            self.net_worker.send_broadcast(tc_message.pack())

    def send_message(self, msg, dest_node):
        path = self.get_route(dest_node)
        self.logger.info(f'Sending "{msg}" to {dest_node}. Expected path: {path}')
        self.net_worker.send_broadcast(
            message.Message.from_type(
                'CUSTOM', sender=self.name, dest=dest_node, msg=msg).pack())

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

class NodeWorker:
    """
    Spanw threads for Node object
    In a charge for timers
    """

    THREADS = []
    SLEEPS = {
        'main': 60,
        'visualize': 20,
        'workload': 120,
        'casts': 5
    }

    @classmethod
    def run(cls, node):
        cls.add_thread(cls.visualize, node)
        cls.add_thread(cls.workload, node)
        cls.add_thread(cls.cast_hello, node)
        cls.add_thread(cls.listen, node)
        cls.add_thread(cls.cast_tc, node)

        [t.start() for t in cls.THREADS]
        while True:
            time.sleep(cls.SLEEPS['main'])

    @classmethod
    def add_thread(cls, t, n):
        cls.THREADS.append(threading.Thread(target=t, args=(n,)))

    @classmethod
    def visualize(cls, node):
        node.logger.info("Vizualization thread")
        while(True):
            time.sleep(cls.SLEEPS['visualize'])
            node.visualize_network(with_mpr=True)

    @classmethod
    def workload(cls, node):
        while True:
            if node.name == 'nw7-n1':
                if 'nw5-n1' in node.get_neighbors(dist=None):
                    node.logger.info(f"Route: {node.get_route('nw5-n1')}")
                    node.send_message(f'Hello, X-hop friend!', 'nw5-n1')
                    break
                else:
                    node.logger.info("Node nw5-n1' not known")
            else:
                break
            time.sleep(cls.SLEEPS['workload'])

    @classmethod
    def cast_hello(cls, node):
        while True:
            node.send_hello()
            time.sleep(cls.SLEEPS['casts'])

    @classmethod
    def listen(cls, node):
        l_threads = node.net_worker.set_listen(node.process_msg)
        [l.start() for l in l_threads]
        # They're infinite
        [l.join() for l in l_threads]

    @classmethod
    def cast_tc(cls, node):
        while True:
            node.send_tc()
            time.sleep(cls.SLEEPS['casts'])

if __name__ == '__main__':

    if len(sys.argv) > 2:
        print('Usage: python node.py [config]')
        exit(1)

    if len(sys.argv) == 2:
        node = Node(sys.argv[1])
    else:
        node = Node()
    NodeWorker.run(node)
