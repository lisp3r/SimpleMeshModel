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
import argparse

from subprocess import check_call

logger = logging.getLogger('generator')
#logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)

logging.debug('Parse argumetns')
argparser = argparse.ArgumentParser(description='Generate docker-compose file and all required configuration for network using config.')
argparser.add_argument('--recreate',
    dest='recreate',
    action='store_true',
    help='Recreate configs from scratch, clean all')
argparser.add_argument('--no-recreate',
    dest='recreate',
    action='store_false',
    help='Save configs and just visualize current')
argparser.add_argument('--clean',
    dest='clean',
    action='store_true',
    help='Clean nodes artifacts')
args = argparser.parse_args()

swd = os.path.dirname(os.path.abspath(__file__))

config_file = os.path.join(swd, "config.yml")
node_config_file = os.path.join(swd, "node.conf.j2")
dc_template_file = os.path.join(swd, "dc.yml.j2")
node_temp_config_dest = os.path.join(swd, "node-configs")
dc_outfile = os.path.join(swd, "docker-compose.yml")
node_shared_artifacts_dir = os.path.normpath(os.path.join(swd, '..', 'artifacts'))

logger.info("Read tool config")
cfg = yaml.load(open(config_file), Loader=yaml.Loader)

if args.recreate:
    logger.info("Make dir for nodes config")
    if os.path.exists(node_temp_config_dest):
        shutil.rmtree(node_temp_config_dest)
    os.makedirs(node_temp_config_dest)
if args.recreate or args.clean:
    logger.info("Clean artifacts dir")
    if os.path.exists(node_shared_artifacts_dir):
        check_call(['sudo', 'rm', '-rf', node_shared_artifacts_dir])
    os.makedirs(node_shared_artifacts_dir)


logger.debug("Load templates")
with open(node_config_file, 'r') as f:
    node_j2_cfg_template = jinja2.Template(f.read())
with open(dc_template_file, 'r') as f:
    dc_j2_template = jinja2.Template(f.read())

networks = [f"network{nw_idx}" for nw_idx in range(cfg['networks count'])]
gateways_count = [0] * cfg['networks count']
nodes = []
if args.recreate:
    logger.info("Cook network")
    for nw_idx in range(cfg['networks count']):
        logger.info(f"Work on {nw_idx} network")
        nw_name = networks[nw_idx]
        networks.append(nw_name)
        logger.info(f"{nw_idx} | Make pure nodes")
        for n_idx in range(cfg['network peers']):
            n_name = f"nw{nw_idx}-n{n_idx}"
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
                gw_name = f"gw{len(nodes)}"
                gw_networks = [nw_name]
                gw_conn_cnt = random.randint(1, cfg['max gateway connectivity'])
                for _ in range(gw_conn_cnt):
                    # Here we need to select only "Free" networks, but it leads to parted graph
                    oth_nw_idx = random.choice(other_nw_idxs)
                    other_nw_idxs.remove(oth_nw_idx)
                    gw_networks.append(networks[oth_nw_idx])
                    gateways_count[oth_nw_idx] += 1
                nodes.append({
                    'name': gw_name,
                    'networks': gw_networks,
                    'cfgfile': os.path.join(node_temp_config_dest, gw_name)})
    logger.info(f"Made {len(nodes)} nodes to fulfill config")

    logger.debug("Write node configs")
    for node in nodes:
        output_text = node_j2_cfg_template.render(node)
        with open(node['cfgfile'], 'w') as f:
            f.write(output_text)

else:

    for n_cfg_fn in os.listdir(node_temp_config_dest):
        with open(os.path.join(node_temp_config_dest, n_cfg_fn)) as n_cfg_f:
            n_cfg = yaml.load(n_cfg_f, Loader=yaml.Loader)
            n_cfg['cfgfile'] = os.path.join(node_temp_config_dest, n_cfg_fn)
            nodes.append(n_cfg)
    logger.info(f"Read {len(nodes)} node configs")

logger.debug(f"(re)Dump docker-compose file '{dc_outfile}'")

with open(dc_outfile, 'w') as dc_file:
    dc_file.write(dc_j2_template.render({
        'networks': networks,
        'nodes': nodes,
        'node_shared_artifacts_dir': node_shared_artifacts_dir
    }))

logger.info("Visualize network just made")

edges = []
for nw_name in networks:
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
    node_size=100,
    node_color='lightblue',
    linewidths=1,
    font_size=8,
    font_weight='bold', with_labels=True)
# networkx.draw_spring(G, with_labels=True)
image_name = os.path.join(swd, 'network-graph.png')
plt.savefig(image_name)

logger.info(f"Made networks {networks}")
logger.info("Done")