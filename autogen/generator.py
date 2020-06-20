#!/usr/bin/env python3

import yaml
import os
import jinja2
import shutil
import logging
import random
import itertools
import networkx
import matplotlib.pyplot as plt

logger = logging.getLogger('generator')
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)

swd = os.path.dirname(os.path.abspath(__file__))

config_file = os.path.join(swd, "config.yml")
node_config_file = os.path.join(swd, "node.conf.j2")
dc_template_file = os.path.join(swd, "dc.yml.j2")
node_temp_config_dest = os.path.join(swd, "node-configs")
dc_outfile = os.path.join(swd, "docker-compose.yml")

logger.info("Read tool config")
cfg = yaml.load(open(config_file), Loader=yaml.Loader)

logger.info("Make dir for nodes config")
if os.path.exists(node_temp_config_dest):
    shutil.rmtree(node_temp_config_dest)
os.makedirs(node_temp_config_dest)

logger.info("Read templates")
with open(node_config_file, 'r') as f:
    node_j2_cfg_template = jinja2.Template(f.read())
with open(dc_template_file, 'r') as f:
    dc_j2_template = jinja2.Template(f.read())


logger.info("Cook network")
networks = []
gateways_count = [0] * cfg['networks count']
nodes = []
for nw_idx in range(cfg['networks count']):
    logger.info(f"Work on {nw_idx} network")
    nw_name = f"network{nw_idx}"
    networks.append(nw_name)
    logger.info(f"{nw_idx} | Make pure nodes")
    for n_idx in range(cfg['network peers']):
        n_name = f"nw{nw_idx}-node{n_idx}"
        nodes.append({
            'name': n_name,
            'networks': [nw_name],
            'cfgfile': os.path.join(node_temp_config_dest, n_name)})
    logger.info(f"{nw_idx} | Make gateways")
    # Check we need to make a new GW for current network
    gws_count = random.randint(1, cfg['max gateways'])
    if gws_count <= gateways_count[nw_idx]:
        logger.info(f"{nw_idx} | Gateways already filled by others")
    else:
        other_nw_idxs = list(range(cfg['networks count']))
        other_nw_idxs.remove(nw_idx)
        for gw_idx in range(random.randint(1, cfg['max gateways'])):
            gateways_count[nw_idx] += 1
            gw_name = f"node{len(nodes)}"
            gw_networks = [nw_name]
            gw_conn_cnt = random.randint(1, cfg['max gateway connectivity'])
            for _ in range(gw_conn_cnt):
                # Here we need to select only "Free" networks, but it leads to parted graph
                oth_nw_idx = random.choice(other_nw_idxs)
                other_nw_idxs.remove(oth_nw_idx)
                gw_networks.append(f"network{oth_nw_idx}")
                gateways_count[oth_nw_idx] += 1
            nodes.append({
                'name': gw_name,
                'networks': gw_networks,
                'cfgfile': os.path.join(node_temp_config_dest, gw_name)})

logger.warning(f"Made {len(nodes)} nodes to fulfill config")

logger.info("Make nodes config")

for node in nodes:
    output_text = node_j2_cfg_template.render(node)
    with open(node['cfgfile'], 'w') as f:
        f.write(output_text)

logger.info(f"Make docker-compose file '{dc_outfile}'")

with open(dc_outfile, 'w') as dc_file:
    dc_file.write(dc_j2_template.render({
        'networks': networks,
        'nodes': nodes
    }))


logger.info("Visualize network just made")

edges = []
for nw_name in networks:
    # Just to visualize graph
    nw_node_names = [n['name'] for n in nodes if nw_name in n['networks']]
    edges += list(itertools.combinations(nw_node_names, 2))
G = networkx.Graph()
G.add_edges_from(edges)

plt.clf()
plt.plot()
plt.axis('off')
networkx.draw(
    G,
    pos = networkx.nx_pydot.graphviz_layout(G),
    node_size=200,
    node_color='lightblue',
    linewidths=1,
    font_size=8,
    font_weight='bold', with_labels=True)
# networkx.draw_spring(G, with_labels=True)
image_name = f'network-graph.png'
plt.savefig(image_name)

logger.info(f"Made networks {networks}")
logger.info("Done")