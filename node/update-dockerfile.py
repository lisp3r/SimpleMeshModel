import yaml
from glob import glob

df = {
    'version': "3",
    'networks': {},
    'services': {}
    }

constant_service_fields = {'build': '.', 'command': 'python ./node.py'}

confs_nodes_files = glob('conf-*.yml')

networks = []
# services = {'services': {}}

for conf in confs_nodes_files:
    data = yaml.load(open(conf, 'r'), Loader=yaml.Loader)
    # print(data)
    node = {
        data['name']: {
            'container_name': data['name'],
            'volumes': [f'./{conf}:/node/config.yml'],
            'networks': data['networks'],
            **constant_service_fields
        }
    }
    networks += data['networks']
    df['services'].update(node)

networks = list(set(networks))
# df.update({'networks': dict.fromkeys(networks, {'driver': 'bridge'})})
for x in networks:
    df['networks'].update({x: {'driver': 'bridge'}})
# df.update(services)

with open('docker-compose.yml', 'w') as f:
    yaml.dump(df, f)

# print(df)

# dd = yaml.load(open('docker-compose.yml', 'r'), Loader=yaml.Loader)
# print(dd)


