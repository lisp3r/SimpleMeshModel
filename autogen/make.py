#!/usr/bin/env python3
import yaml
import os
import jinja2
import shutil
import logging
import random


swd = os.path.dirname(__file__)

config_file = os.path.join(swd, "config.yml")
node_config_file = os.path.join(swd, "node.conf.j2")
dc_template_file = os.path.join(swd, "dc.yml.j2")
node_temp_config_dest = os.path.join(swd, "node-configs")

logging.info("Read tool config")
cfg = yaml.load(open(config_file), Loader=yaml.Loader)

logging.info("Make dir for nodes config")
if os.path.exists(node_temp_config_dest):
    shutil.rmtree(node_temp_config_dest)
os.makedirs(node_temp_config_dest)

logging.info("Read templates")
with open(node_config_file, 'r') as f:
    node_j2_cfg_template = jinja2.Template(f.read())
with open(dc_template_file, 'r') as f:
    dc_j2_template = jinja2.Template(f.read())


logging.info("Make networks")
networks = []
for i in range(cfg['networks count']):
    networks.append(f"network{i}")

logging.info("Make nodes")
nodes = []
for i in range(cfg['nodes count']):
    n_cfg = {
        'name': f"node{i}",
        'networks': random.sample(
            networks,
            random.randint(1, int(cfg['networks count'] * cfg['connectivity']))),
        'cfgfile': os.path.join(node_temp_config_dest, f"node{i}.yml")
    }
    nodes.append(n_cfg)
    # j2_environment = jinja2.Environment(loader=jinja2.FileSystemLoader(swd))
    output_text = node_j2_cfg_template.render(n_cfg)
    with open(n_cfg['cfgfile'], 'w') as f:
        f.write(output_text)

logging.info("Make docker-compose file")
with open(os.path.join(swd, "docker-compose.yml"), 'w') as dc_file:
    dc_file.write(dc_j2_template.render({
        'networks': networks,
        'nodes': nodes
    }))

