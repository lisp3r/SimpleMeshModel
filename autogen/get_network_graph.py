import yaml
import os
import networkx
import matplotlib.pyplot as plt


def visualize_network(network_graph):
    plt.clf()
    plt.plot()
    plt.axis('off')

    networkx.draw(
        network_graph,
        pos = networkx.nx_pydot.graphviz_layout(network_graph),
        node_size=200,
        node_color='lightblue',
        linewidths=1,
        font_size=10,
        font_weight='bold', with_labels=True)

    # networkx.draw_spring(network_graph, with_labels=True)
    image_name = f'network-graph.png'
    plt.savefig(image_name)

def get_network_graph():

    swd = os.path.dirname(__file__)
    config_file = os.path.join(swd, "docker-compose.yml")
    cfg = yaml.load(open(config_file), Loader=yaml.Loader)
    networks = dict.fromkeys(cfg['networks'], None)
    for node in cfg['services'].keys():
        for nw in cfg['services'][node]['networks']:
            if not networks[nw]:
                networks[nw] = list()
            networks[nw].append(node)

    G = networkx.Graph()
    g = []
    for nw in networks:
        for x1 in networks[nw]:
            for x2 in networks[nw]:
                if x1 != x2:
                    g.append((x1,x2))
    G.add_edges_from(g)

    visualize_network(G)

    print(networks)

get_network_graph()