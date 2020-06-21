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
from collections import defaultdict


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
        self.__port = port

    def local_addrs(self):
        return self.__interfaces_for_addr.values()

    def is_local_addr(self, addr):
        return addr in self.local_addrs()

    def __get_broadcast_socket(self, addr):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(True)
        sock.bind((addr, self.__port))
        return sock

    def __broadcast_sockets(self):
        return [self.__get_broadcast_socket(x) for x in self.local_addrs()]

    def send_broadcast(self, msg):
         for socket in self.__broadcast_sockets():
            socket.sendto(msg, ('<broadcast>', self.__port))
            socket.close()

    def listener(self, handler):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            sock.setblocking(True)
            sock.bind(('', self.__port))
            data, (addr, _) = sock.recvfrom(40000)
            handler(data, addr)

class Node:
    CONF_PATH = 'config.yml'

    def __init__(self, config=CONF_PATH):
        cfg = yaml.load(open(config, 'r'), Loader=yaml.Loader)
        self.__config = config
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
        self.mpr_set = []
        # IPS: object to integrate security
        self.ips = IPS()
        # IPS: Non-confirmed sent messages and time passed since sending
        self.__sent_msgs = []
        self.rlock = threading.RLock()
        self.glock = threading.Lock()

    def __get_side(self):
        cfg = yaml.load(open(self.__config, 'r'), Loader=yaml.Loader)
        return cfg.get('side', 'good')

    def get_neighbors(self, node=None, dist=1):
        if not node:
            node = self.name
        all_nbrs = nx.single_source_shortest_path_length(self.network_graph, node, cutoff=dist)
        if dist:
            return [node for node,ndist in all_nbrs.items() if ndist == dist]
        else:
            return list(all_nbrs.keys())

    def __is_mpr(self):
        if any(self.__get_by('mprss')):
            return True
        else:
            return False

    def process_msg(self, data, addr):
        if self.net_worker.is_local_addr(addr):
            return
        m = message.Message.unpack(data)
        # IPS: injection in message processing
        if self.ips.is_isolated(m.sender):
            logging.warning(f"Ignore message from {m.sender} as it's isolated")
            return
        with self.rlock:
            if m.message_type == 'HELLO':
                with self.glock:
                    self.network_graph.add_node(m.sender, addr=[addr])
                    self.network_graph.add_edge(self.name, m.sender)
                for nbr in m.neighbors:
                    # IPS: Analyze HELLO for isolated flag
                    if nbr['isolated']:
                        if self.__get_side() == 'evil' and nbr['name'] == self.name:
                            self.logger.error("They found me!")
                        else:
                            if nbr['name'] in self.network_graph.nodes():
                                self.logger.warning(f"Remove isolated node {nbr['name']} from HELLO from {m.sender}")
                                self.ips.change_rating(nbr['name'], self.ips.rating_to_isolate)
                                with self.glock:
                                    self.network_graph.remove_node(nbr['name'])
                    else:
                        # Usual HELLO processing
                        with self.glock:
                            if nbr['name'] == self.name:
                                if nbr.get('local_mpr'):
                                    self.network_graph.add_node(m.sender, addr=[addr], mprss=True)
                                else:
                                    self.network_graph.add_node(m.sender, addr=[addr], mprss=False)
                            else:
                                self.network_graph.add_node(nbr['name'], addr=[addr], mpr=nbr.get('local_mpr', False))
                            self.network_graph.add_edge(m.sender, nbr['name'])
            elif m.message_type == 'TC':
                if m.sender in self.get_neighbors(dist=None):
                    self.__parse_tc(m)
                self.send_tc(forwarded_msg=m)
            elif m.message_type == 'CUSTOM':
                self.recv_custom(m)
            self.__update_mprs()
            self.__update_mpr_set()

    def __is_on_route(self, msg):
        full_route = self.__get_route(msg.dest, msg.forwarders[-1])
        return self.name in full_route and self.name not in msg.forwarders

    def __parse_tc(self, msg):
        # mark as MPR (somebody's MBR, nonlocal)
        with self.glock:
            self.network_graph.add_node(msg.sender, mpr=True)
        for nbr in msg.mpr_set:
            with self.glock:
                # Node is in graph and has other MPR or didn't choose previously
                if nbr['name'] in self.network_graph:
                    old_nbr_mpr = self.__get_data(nbr['name']).get('local_mpr')
                    # It had other MPR
                    if old_nbr_mpr and old_nbr_mpr != msg.sender:
                        # Unset it as MPR in our ghraph
                        if old_nbr_mpr in self.network_graph:
                            self.network_graph.add_node(old_nbr_mpr, mpr=False)
                    self.network_graph.add_node(nbr['name'], local_mpr=msg.sender)
                self.network_graph.add_edge(msg.sender, nbr['name'])

    def visualize_network(self, image_postfix=None):
        with self.rlock:
            plt.clf()
            plt.plot()
            plt.axis('off')
            color_map = []
            for node in self.network_graph:
                if node in self.__get_by('local_mpr'):
                    color_map.append('red')
                elif node in self.__get_by('mpr'):
                    color_map.append('green')
                elif node in [x['name'] for x in self.mpr_set]:
                    color_map.append('yellow')
                else:
                    color_map.append('blue')
            self.visualize_method(self.network_graph, node_color=color_map, with_labels=True)
            if isinstance(image_postfix, int):
                image_name = f'artifacts/{self.name}-{image_postfix}.png'
            else:
                image_name = f'artifacts/{self.name}.png'
            plt.savefig(image_name)

    def __visualize_route(self, route):
        route_edges = [(route[i], route[i+1]) for i in range(len(route)-1)]
        route_edges += [(route[i+1], route[i]) for i in range(len(route)-1)]
        edge_color = []
        with self.rlock:
            for e in self.network_graph.edges():
                if e in route_edges:
                    edge_color.append('r')
                else:
                    edge_color.append('b')
            self.logger.info("Update image")
            plt.clf()
            plt.plot()
            plt.axis('off')
            self.visualize_method(self.network_graph, with_labels=True, edge_color=edge_color)
            plt.savefig(f'artifacts/{route[0]}->{route[-1]}.png')

    def __get_data(self, node):
        return self.network_graph.nodes().data()[node]

    def __get_by(self, arg) -> list:
        return [x[0] for x in self.network_graph.nodes().data() if x[1].get(arg)]

    def __update_mpr_set(self):
        self.mpr_set.clear()
        for node in self.__get_by("mprss"):
            self.mpr_set.append({
                    'name': node,
                    'addr': self.__get_data(node)
                })

    def __update_mprs(self):
        any_in = lambda a, b: any(i in b for i in a)
        nodes_1 = self.get_neighbors()
        nodes_2 = self.get_neighbors(dist=2)
        mpr_set = []
        with self.glock:
            for node in self.network_graph:
                if self.__get_data(node).get('local_mpr'):
                    self.network_graph.add_node(node, local_mpr=False)
        while nodes_2:
            node_1_dict = {}
            for n in nodes_1:
                node_1_dict[n] = [x for x in list(self.network_graph.neighbors(n))
                                  if x in nodes_2 and x != self.name]
            node_1_dict = {x: node_1_dict[x] for x in sorted(
                                                            node_1_dict,
                                                            key=lambda k: len(node_1_dict[k]),
                                                            reverse=True)}
            mpr = next(iter(node_1_dict))
            mpr_set.append(mpr)
            nodes_2 = [x for x in nodes_2 if x not in node_1_dict[mpr]]
            upd_nodes_1_dict = [x for x in nodes_1 if x not in mpr_set]
            nodes_1 = [x for x in upd_nodes_1_dict if any_in(nodes_2, node_1_dict[x])]

        with self.glock:
            for node in self.network_graph:
                if node in mpr_set:
                    self.network_graph.add_node(node, local_mpr=True)

    def __get_mprs(self):
        return self.__get_by('local_mpr')

    def __get_route(self, dest_node, src_node=None):
        if not src_node:
            src_node = self.name
        if dest_node not in self.network_graph.nodes():
            return []
        return nx.shortest_path(self.network_graph, src_node, dest_node)

    def send_hello(self):
        with self.rlock:
            nbrs = [
                {'name': nbr,
                'addr': self.__get_data(nbr)['addr'],
                'local_mpr': True if self.__get_data(nbr).get('local_mpr') else False,
                'mprss': self.__get_data(nbr).get('mprss',False),
                # IPS: inject isolation information to HELLO announcement
                'isolated': self.__get_data(nbr).get('isolated',False)} for nbr in list(self.network_graph.neighbors(self.name))]
            msg =  message.Message.from_type(
                        'HELLO', sender=self.name, neighbor_table=nbrs)
            self.net_worker.send_broadcast(msg.pack())

    def send_tc(self, forwarded_msg=None):
        with self.rlock:
            if forwarded_msg:
                if self.name not in forwarded_msg.route:
                    forwarded_msg.route.append(self.name)
                    tc_message = forwarded_msg
                else:
                    return
            else:
                tc_message = message.Message.from_type(
                    'TC', sender=self.name, mpr_set=self.mpr_set)
            if self.__is_mpr():
                self.net_worker.send_broadcast(tc_message.pack())

    def send_custom(self, msg, dest_node):
        if dest_node == self.name:
            return
        with self.rlock:
            path = self.__get_route(dest_node)
            self.logger.info(f'Sending "{msg}" to {dest_node}. Expected path: {path}')
            msg = message.Message.from_type(
                    'CUSTOM', sender=self.name, dest=dest_node, msg=msg)
            self.net_worker.send_broadcast(msg.pack())
            # IPS: register sent custom messages what has to be forwarded
            if dest_node not in list(self.network_graph.neighbors(self.name)):
                self.__sent_msgs.append(msg)

    def recv_custom(self, m):
        if m.dest == self.name:
            self.logger.info(f'Got CUSTOM message from {m.sender}: {m.msg}; path: {m.forwarders}')
            self.__visualize_route(m.forwarders + [self.name])
        elif m.sender == self.name:
            self.logger.warning("IPS: received from MPR self custom messages means this MPR is OK")
            msg_translator = m.forwarders[-1]
            is_from_my_mpr = msg_translator in self.__get_mprs()
            if is_from_my_mpr:
                self.logger.warning("IPS: Remove this message from sent list, increase MPR rating")
                with self.rlock:
                    del_msg = None
                    for sent_msg in self.__sent_msgs[:]:
                        if sent_msg == m:
                            del_msg = sent_msg
                    self.__sent_msgs.remove(del_msg)
                    self.ips.change_rating(msg_translator, +1)
            else:
                self.logger.warning("IPS: This means someone else casting this message but should not - let's decrease its rating")
                self.ips.change_rating(msg_translator, -1)
        else:
            if self.__is_mpr() and self.__is_on_route(m):
                if m.sender != self.name:
                    if self.__get_side() == 'good':
                        self.logger.info(f'Got msg from {m.sender} -> {m.dest}, it passed: {m.forwarders}. Forwarding...')
                        m.forwarders.append(self.name)
                        self.net_worker.send_broadcast(m.pack())
                    elif self.__get_side() == 'evil':
                        self.logger.info(f'Got msg {m.sender}->{m.dest}, it passed: {m.forwarders}. Dropping...')

    def ips_update(self):
        # IPS: Method to validate other nodes behaviour, each call equal to clock passed
        with self.rlock:
            # Increase clock for messages
            for msg in self.__sent_msgs:
                age = msg.tick()
                # Decrease rating for next hop node if it didn't forwarded for 2 clocks
                if age >= 2:
                    path = self.__get_route(msg.dest)
                    self.__sent_msgs.remove(msg)
                    self.logger.warning(f"IPS: Decrease rating for {path[1]}, message for {msg.dest} wasn't forwarded")
                    self.ips.change_rating(path[1], -2)
            with self.glock:
                for node in self.ips.get_isolated():
                    self.network_graph.add_node(node, isolated=True)
                    self.send_hello()
                    self.network_graph.remove_node(node)


class IPS:

    def __init__(self):
        # IPS: nodes ratings
        self.__node_ratings = defaultdict(int)
        # IPS: List of isolated nodes
        self.__isolated_nodes = []
        # Limit node rating
        self.__max_node_rating = 10
        # Rating to isolate node
        self.rating_to_isolate = -10
        self.logger = create_logger('IPS')

    # IPS: drop rating only for non-isolated nodes, inc only if it allowed
    def change_rating(self, node, diff=-1):
        if node not in self.__isolated_nodes and self.__node_ratings[node] <= self.__max_node_rating:
            self.__node_ratings[node] += diff
        rating = self.__node_ratings[node]
        # Some node rating threshold
        if rating <= self.rating_to_isolate:
            self.logger.warning(f"Isolating {node} because of low rating")
            self.__isolated_nodes.append(node)
        # Some nodes can be de justified
        if rating > 0 and node in self.__isolated_nodes:
            self.logger.warning(f"Justify {node} as it behaves better")
            self.__isolated_nodes.remove(node)

    # IPS: Ignore all messages from isolated nodes
    def is_isolated(self, node):
        return node in self.__isolated_nodes

    # IPS: Get isolated nodes to remove
    def get_isolated(self):
        return self.__isolated_nodes[:]


class NodeWorker:
    """
    Spanw threads for Node object
    In a charge for timers
    """

    THREADS = []
    SLEEPS = {
        'main': 60,
        'visualize': 10,
        'workload': 20,
        'casts': 5
    }

    @classmethod
    def run(cls, node):
        cls.add_thread(cls.visualize, node)
        cls.add_thread(cls.workload, node)
        cls.add_thread(cls.cast_hello, node)
        cls.add_thread(cls.listen, node)
        cls.add_thread(cls.cast_tc, node)
        cls.add_thread(cls.ips, node)

        if node.name == 'gw18':
            time.sleep(10)
        [t.start() for t in cls.THREADS]
        while True:
            time.sleep(cls.SLEEPS['main'])

    @classmethod
    def add_thread(cls, t, n):
        cls.THREADS.append(threading.Thread(target=t, args=(n,)))

    @classmethod
    def visualize(cls, node):
        node.logger.info("Vizualization started")
        while(True):
            time.sleep(cls.SLEEPS['visualize'])
            node.visualize_network()
        node.logger.info("Vizualization end")

    @classmethod
    def workload(cls, node):
        node.logger.info("Workload started")
        while True:
            time.sleep(cls.SLEEPS['workload'])
            if node.name in ['nw7-n1']:
                target_node = choice(node.get_neighbors(dist=None))
                node.send_custom(f'Hello from {node.name}, X-hop friend!', target_node)
            else:
                break
        node.logger.info("Workload end")

    @classmethod
    def ips(cls, node):
        node.logger.info("IPS started")
        while True:
            node.ips_update()
            time.sleep(cls.SLEEPS['workload'])
        node.logger.info("IPS end")

    @classmethod
    def cast_hello(cls, node):
        node.logger.info("Cast hello started")
        while True:
            node.send_hello()
            time.sleep(cls.SLEEPS['casts'])
        node.logger.info("Cast hello end")

    @classmethod
    def listen(cls, node):
        node.logger.info("Listen started")
        while True:
            node.net_worker.listener(node.process_msg)
        node.logger.info("END Listen")

    @classmethod
    def cast_tc(cls, node):
        node.logger.info("TC cast started")
        while True:
            node.send_tc()
            time.sleep(cls.SLEEPS['casts'])
        node.logger.info("TC cast end")

if __name__ == '__main__':

    if len(sys.argv) > 2:
        print('Usage: python node.py [config]')
        exit(1)

    if len(sys.argv) == 2:
        node = Node(sys.argv[1])
    else:
        node = Node()
    NodeWorker.run(node)
