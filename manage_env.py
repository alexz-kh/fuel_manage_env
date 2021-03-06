#!/usr/bin/python

####
# apt-get install python-yaml python-paramiko \
#  python-ipaddr python-proboscis python-keystoneclient
###

# ADDD:
'''
Script works at least with fuel 7\8
'''

import yaml
import os
import sys
import ipdb
import time
import pprint
import logging
from fuelweb_test.models.nailgun_client import NailgunClient
####

console = logging.StreamHandler()
console.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s %(filename)s:'
                              '%(lineno)d -- %(message)s')
console.setFormatter(formatter)
LOG = logging.getLogger(__name__)
LOG.addHandler(console)
pprinter = pprint.PrettyPrinter(indent=1, width=80, depth=None)

# Input params:
CLUSTER_CONFIG = os.environ.get("CLUSTER_CONFIG", "test_lab.yaml")

# optional
START_DEPLOYMENT = os.environ.get("START_DEPLOYMENT", "false")
UPLOAD_DEPLOYMENT_INFO = os.environ.get("UPLOAD_DEPLOYMENT_INFO", "false")
IPMI_CONFIGS = os.environ.get("IPMI_CONFIGS", "ipmi/netifnames.yaml")
# debug (don't use it!)
test_mode = False

LOG.info('Try load: %s' % (CLUSTER_CONFIG))
lab_config = yaml.load(open(CLUSTER_CONFIG))

client = NailgunClient(lab_config["fuel-master"])
##################################
# versions workaround
f_release = client.get_api_version()['release']
LOG.info('Fuel-version: \n%s' % pprinter.pformat(client.get_api_version()))
if float(f_release[:3]) < 6:
    api_cluster_id = "cluster_id"
else:
    api_cluster_id = "cluster"
###################################


def fetch_hw_data(config_yaml=IPMI_CONFIGS):
    """

    :param IPMI_CONFIGS:
    :return:
    """

    if os.path.isfile(config_yaml):
        with open(config_yaml, 'r') as f1:
            imported_yaml = yaml.load(f1)
            return imported_yaml.get('hw_server_list', None)
    else:
        return None


def remove_env(admin_node_ip, env_name, dont_wait_for_nodes=True):

    LOG.info('Removing cluster with name:{0}'.format(env_name))
    client = NailgunClient(admin_node_ip)
    cluster_id = client.get_cluster_id(env_name)
    all_nodes = []

    if cluster_id:
        cluster_nodes = client.list_cluster_nodes(cluster_id)
        if len(cluster_nodes) > 0:
            all_nodes = client.list_nodes()
        client.delete_cluster(cluster_id)
    else:
        LOG.info('Looks like cluster has not been created before.Okay')
        return "OK"

    # wait for cluster to disappear
    rerty_c = 120
    for i in range(rerty_c):
        cluster_id = client.get_cluster_id(env_name)
        LOG.info('Wait for cluster to disappear...try %s /%s' % (i, rerty_c))
        if cluster_id:
            time.sleep(10)
        else:
            break

    # fail if cluster is still around
    if cluster_id:
        return "Can't delete cluster"

    # wait for removed nodes to come back online
    if not dont_wait_for_nodes:
        for i in range(90):
            cur_nodes = client.list_nodes()
            if len(cur_nodes) < len(all_nodes):
                LOG.info('Wait for nodes to came back. Should be:{0} '
                         'Currently:{1} ...try {2}'.format(
                            len(all_nodes), len(cur_nodes), i))
                time.sleep(10)

    if len(client.list_nodes()) < len(all_nodes) and not dont_wait_for_nodes:
        return "Timeout while waiting for removed nodes ({}) to come back up".format(
            len(cluster_nodes))

    return "OK"


def check_for_name(mac, hw_dict=None, nic_schema='b_name', fancy=True):
    """Try to get real HW name by node mac

    :param mac:
    fancy: don't return False even name not exist
    :return:
    """
    if not hw_dict:
        hw_dict = fetch_hw_data()

    def check_if_exist(mac, hw_dict, fancy=fancy):
        """
        Check if mac in host['nics']
        Will stop on first founded
        :param ifs:
        :param hw_dict:
        :return:
        """
        for hw in hw_dict:
            for nic in hw_dict[hw]['nics']:
                if nic == mac:
                    s_check = hw_dict[hw]['nics'][mac].get(nic_schema, None)
                    if s_check:
                        LOG.info(
                            'Mac:"{0}" from node:"{1}" ifname:"{2}"'.format(
                                mac, hw, hw_dict[hw]['nics'][mac][nic_schema]))
                        return hw
        if fancy:
            return "discover_mac_was:" + mac
        LOG.warning(
            'MAC:{0} not assigned to any knowledgeable node!'.format(mac))
        return None

    if not hw_dict and fancy:
        return "discover_mac_was:" + mac

    if not hw_dict and not fancy:
        return None

    return check_if_exist(mac, hw_dict, fancy)


def wait_free_nodes(lab_config, should_be, timeout=120, ):
    """

    :param lab_config:
    :param timeout:
    :return:
    """
    actual_nodes_ids = None
    LOG.debug('Wait for:{0} free nodes..'.format(should_be))
    for i in range(timeout):
        all_nodes = client.list_nodes()
        actual_nodes_ids = []
        for node in all_nodes:
            if node['cluster'] in [None, cluster_id] and node['status'] == 'discover':
                actual_nodes_ids.append(node['id'])
        if len(actual_nodes_ids) < should_be:
            LOG.info(
                'Found {0} nodes in any status, from {1} needed. '
                'Sleep for 10s..try {2} from {3}'.format(
                    len(all_nodes), should_be, i, timeout))
            time.sleep(10)
            if i == timeout:
                LOG.error('Timeout awaiting nodes!'.format(
                    lab_config["cluster"]["name"]))
                sys.exit(1)
        else:
            break
    return actual_nodes_ids


def check_iface(node_interfaces, iface_for_check, node, test_mode=False):
    all_ifaces = []
    for i, val in enumerate(node_interfaces):
        all_ifaces.append(val['name'])

    if type(iface_for_check) is list:
        for iface_item in iface_for_check:
            if iface_item['name'] not in all_ifaces:
                if test_mode:
                    LOG.error(
                        'Iface %s not found on node %s !'
                        '\n Skip due test_mode=True' % (
                            iface_for_check, node))
                else:
                    LOG.error('Iface %s not found on node %s !' % (
                        iface_for_check, node))
                    sys.exit(1)
                return False

    if type(iface_for_check) is str:
        if iface_for_check not in all_ifaces:
            if test_mode:
                LOG.error(
                    'Iface %s not found on node %s !\n Skip due test_mode=True' % (
                        iface_for_check, node))
            else:
                LOG.error(
                    'Iface %s not found on node %s !' % (iface_for_check, node))
                sys.exit(1)
            return False
    return True


def update_netw_old():
    # wait while updating finished
    # this hack required only for fuel <8
    LOG.info('awaiting update_network task status...')
    task_id = client.update_network(cluster_id,
                                    networking_parameters=cluster_net[
                                        "networking_parameters"],
                                    networks=cluster_net["networks"])['id']

    for i in range(120):
        t_status = client.get_task(task_id)['status']
        if t_status == 'ready':
            LOG.info('update_network task %s in ready state' % (task_id))
            break

        if t_status == 'error' or i == 120:
            LOG.error(
                'update_network task %s in error state or awaitng timeout' % (
                    task_id))
            sys.exit(1)


def simple_pin_nodes_to_cluster(all_nodes, roller):
    """Pin random nodes to cluster

    :param all_nodes:
    :return:
    """
    nodes_data = []
    ctrl_counter = 0
    compute_counter = 0
    LOG.info('Simple(random) node assign to cluster chosen')
    for node in all_nodes:
        if node['cluster'] == None and (
                    ctrl_counter < roller['controller']['count']):
            node_data = {api_cluster_id: cluster_id,
                         'id': node['id'],
                         'pending_addition': True,
                         'pending_roles': roller['controller']['roles'],
                         'name': check_for_name(node['mac'])
                         }
            ctrl_counter += 1
            nodes_data.append(node_data)
        elif node['cluster'] == None and (
                    compute_counter < roller['compute']['count']):
            node_data = {api_cluster_id: cluster_id,
                         'id': node['id'],
                         'pending_addition': True,
                         'pending_roles': roller['compute']['roles'],
                         'name': check_for_name(node['mac'])
                         }
            compute_counter += 1
            nodes_data.append(node_data)
    return nodes_data


def simple_pin_nw_to_node(node_orig, node_ifs, roller):
    """
    :param node_orig:
    :param node_ifs:
    :param roller:
    :return:
    """
    node = node_orig.copy()
    # FIXME remove any client calls from func
    # TODO merge *_pin_nw_to_node in one
    nw_ids_dict = {network['name']: network['id'] for network in
                   client.get_networks(cluster_id)['networks']}
    role = []
    if 'compute' in node['pending_roles']:
        role = 'compute'
    elif 'controller' in node['pending_roles']:
        role = 'controller'
    l3_ifaces = roller[role]['l3_ifaces']
    phys_nic_map = l3_ifaces.get('phys_nic_map', None)
    virt_nic_map = l3_ifaces.get('virt_nic_map', None)

    def phys_assigh(phys_nic_map, ifs):
        LOG.info('Attempt to create phys nic assign')
        expect_nic_names = [nic for nic in phys_nic_map.keys()]

        for nic in ifs:
            if nic['name'] not in expect_nic_names:
                LOG.warning('Interface:{0} from node,'
                            'not found on phys-node-config:{1}'.format(
                    nic['name'], node['name']))
                # remove all networks from this IF. We hope, that someone push
                # them from config to other nic...otherwise - error will
                # be raised.
                nic['assigned_networks'] = []
            else:
                # we need to push { id : name } structure
                assigned_nws = []
                for assigned_nw in phys_nic_map[nic['name']].get(
                        'assigned_networks', []):
                    assigned_nws.append({'id': nw_ids_dict[assigned_nw],
                                         'name': assigned_nw})
                nic['assigned_networks'] = assigned_nws
        return ifs

    def virt_assigh(virt_nic_map, ifs):
        """

        :param virt_nic_map:
        :param ifs:
        :return:
        """
        LOG.info('Attempt to create virt nic assign')
        for bond in virt_nic_map:
            assigned_nws = []
            for assigned_nw in virt_nic_map[bond].get(
                    'assigned_networks', []):
                assigned_nws.append({'id': nw_ids_dict[assigned_nw],
                                     'name': assigned_nw})
            bond_dict = {
                'mode': virt_nic_map[bond]['mode'],
                'name': bond,
                'slaves': virt_nic_map[bond]['slaves'],
                'type': 'bond',
                'bond_properties': virt_nic_map[bond].get('bond_properties',
                                                          {}),
                'assigned_networks': assigned_nws}
            ifs.append(bond_dict)
        return ifs
    upd_ifs = phys_assigh(phys_nic_map, node_ifs)
    if virt_nic_map:
        upd_ifs = virt_assigh(virt_nic_map, upd_ifs)
    return upd_ifs


def get_nic_mapping_by_mac(mac, default_map=None):
    """

    :param mac:
    :param config_f:
    :return:
    """

    hw_name = check_for_name(node['mac'], fancy=False)

    if hw_name:
        LOG.info('NODE:{0} nic-MAC:{0} \n have nic-map:'.format())
    else:
        LOG.error('MAC:{0} not assigned to any knowledgeable node!')
        return None


def strict_pin_nw_to_node(node_orig, node_ifs, lab_config):
    """
    1)Looks for exact config by name
    2)use default config from lab_config

    :param node_id:
    :param nw:
    :return:
    """
    node = node_orig.copy()
    # FIXME remove any client calls from func
    nw_ids_dict = {network['name']: network['id'] for network in
                   client.get_networks(cluster_id)['networks']}
    l3_ifaces = lab_config['nodes'][node['name']]['l3_ifaces']
    phys_nic_map = l3_ifaces.get('phys_nic_map', None)
    virt_nic_map = l3_ifaces.get('virt_nic_map', None)

    def phys_assigh(phys_nic_map, ifs):
        LOG.info('Attempt to create phys nic assign')
        expect_nic_names = [nic for nic in phys_nic_map.keys()]

        for nic in ifs:
            if nic['name'] not in expect_nic_names:
                LOG.warning('Interface:{0} from node,'
                            'not found on phys-node-config:{1}'.format(
                    nic['name'], node['name']))
                # remove all networks from this IF. We hope, that someone push
                # them from config to other nic...otherwise - error will
                # be raised.
                nic['assigned_networks'] = []
            else:
                # we need to push { id : name } structure
                assigned_nws = []
                for assigned_nw in phys_nic_map[nic['name']].get(
                        'assigned_networks', []):
                    assigned_nws.append({'id': nw_ids_dict[assigned_nw],
                                         'name': assigned_nw})
                nic['assigned_networks'] = assigned_nws
        return ifs

    def virt_assigh(virt_nic_map, ifs):
        """

        :param virt_nic_map:
        :param ifs:
        :return:
        """
        LOG.info('Attempt to create virt nic assign')
        for bond in virt_nic_map:
            assigned_nws = []
            for assigned_nw in virt_nic_map[bond].get(
                    'assigned_networks', []):
                assigned_nws.append({'id': nw_ids_dict[assigned_nw],
                                     'name': assigned_nw})
            bond_dict = {
                'mode': virt_nic_map[bond]['mode'],
                'name': bond,
                'slaves': virt_nic_map[bond]['slaves'],
                'type': 'bond',
                'bond_properties': virt_nic_map[bond].get('bond_properties',
                                                          {}),
                'assigned_networks': assigned_nws}
            ifs.append(bond_dict)
        return ifs
    upd_ifs = phys_assigh(phys_nic_map, node_ifs)
    if virt_nic_map:
        upd_ifs = virt_assigh(virt_nic_map, upd_ifs)
    return upd_ifs


def strict_pin_node_to_cluster(node_orig, lab_config):
    """
    :param all_nodes:
    :return:
    """
    node = node_orig.copy()
    cluster = {'cluster_id': cluster_id, 'name': lab_config['cluster']['name']}
    e_nodes = lab_config.get('nodes', None)

    if not e_nodes:
        LOG.warning(
            'Unable to find nodes list,which should be pinned to cluster')
        return None

    LOG.info('Strict node assign for cluster has been chosen')
    LOG.info('Expected hardware nodes:{0}'.format(e_nodes.keys()))

    hw_name = check_for_name(node['mac'], fancy=False)
    if node['cluster'] is None and hw_name in e_nodes.keys():
        LOG.info('Node ID:{0} should be in cluster:{1}\n'
                 'with name:{2}'.format(node['id'], cluster['cluster_id'],
                                        hw_name))
        new_data = {'cluster': cluster['cluster_id'],
                    'id': node['id'],
                    'pending_addition': True,
                    'pending_roles': e_nodes[hw_name]['roles'],
                    'name': hw_name
                    }
        node.update(new_data)
        # facepalm fix
        del node['group_id']
        return node
    elif node['cluster'] is None:
        LOG.info(
            'Skipping node ID:{0} not from cluster:{2},ID{1}'.format(
                node['id'], cluster['cluster_id'], cluster['name']))
        return None

############################################################
############################################################

if __name__ == '__main__':

    assign_method = lab_config.get('assign_method', 'simple')

    # remove cluster, and create new
    remove_env(lab_config["fuel-master"], lab_config["cluster"]["name"])
    LOG.info('Creating cluster with:{0}'.format(
        pprinter.pformat(lab_config["cluster"])))
    client.create_cluster(data=lab_config["cluster"])

    # update network and attributes
    cluster_id = client.get_cluster_id(lab_config["cluster"]["name"])
    if cluster_id is None:
        LOG.error(
            'Cluster with name %s not found!' % (lab_config["cluster"]["name"]))
        sys.exit(1)

    cluster_attributes = client.get_cluster_attributes(cluster_id)
    cluster_net = client.get_networks(cluster_id)

    for network in cluster_net["networks"]:
        network_name = network["name"]
        if network_name in lab_config["nets"]:
            for value in lab_config["nets"][network_name]:
                network[value] = lab_config["nets"][network_name][value]

    cluster_net["networking_parameters"].update(
        lab_config["networking_parameters"])

    for section in lab_config["attributes"]:
        attr = lab_config["attributes"][section]
        for option in attr:
            cluster_attributes['editable'][section][option]['value'] = \
                lab_config["attributes"][section][option]

    # push extra info
    # update common part
    if "common" in lab_config:
        cluster_attributes['editable']['common'].update(lab_config["common"])

    # create extra part
    if "custom_attributes" in lab_config:
        cluster_attributes['editable']['custom_attributes'] = lab_config[
            "custom_attributes"]

    # replace repos
    try:
        cluster_attributes['editable']['repo_setup']['repos']['value'] = \
            lab_config['repos']['value']
        LOG.info('Section: repos was successfully replaced with \n%s\n ' % \
                 pprinter.pformat(lab_config['repos']['value']))
    except KeyError as e:
        LOG.warn('Section: %s not found in %s ' % (e.message, CLUSTER_CONFIG))

    client.update_cluster_attributes(cluster_id, cluster_attributes)

    if float(f_release[:3]) < 8:
        update_netw_old()
    else:
        LOG.info('Update cluster networks..its can take some time...')
        # FIXME
        client.update_network(cluster_id, networking_parameters=cluster_net[
            "networking_parameters"], networks=cluster_net["networks"])

    # add nodes into cluster and set roles

    # simple check for enough nodes count
    # FIXME
    if assign_method == 'hw_pin':
        should_be_nodes = len(lab_config['nodes'].keys())
    else:
        should_be_nodes = lab_config['roller']['controller']['count'] + \
                          lab_config['roller']['compute']['count']
    wait_free_nodes(lab_config, should_be_nodes)

    # add nodes to cluster
    LOG.info("StageX:START Assign nodes to cluster")
    if assign_method == 'hw_pin':
        while len(client.list_cluster_nodes(cluster_id)) < should_be_nodes:
            for node in client.list_nodes():
                node_new = strict_pin_node_to_cluster(node, lab_config)
                if node_new:
                    client.update_node(node['id'], node_new)
            # FIXME add at least timeout
            time.sleep(5)
    else:
        client.update_nodes(simple_pin_nodes_to_cluster(client.list_nodes(),
                                                        lab_config['roller']))
    LOG.info("StageX: END Assign nodes to cluster")

    # assign\create network role to nic per node
    LOG.info("StageX: Assign network role to nic per node")
    if assign_method == 'hw_pin':
        for node in client.list_cluster_nodes(cluster_id):
            upd_ifs = strict_pin_nw_to_node(node, client.get_node_interfaces(
                node['id']), lab_config)
            if upd_ifs:
                client.put_node_interfaces(
                    [{'id': node['id'],
                      'interfaces': upd_ifs}])
    else:
        for node in client.list_cluster_nodes(cluster_id):
            upd_ifs = simple_pin_nw_to_node(node, client.get_node_interfaces(
                node['id']), lab_config.get('roller'))
            if upd_ifs:
                client.put_node_interfaces(
                    [{'id': node['id'],
                      'interfaces': upd_ifs}])
    LOG.info("StageX: END Assign network role to nic per node")

    if START_DEPLOYMENT.lower() == 'true':
        client.deploy_cluster_changes(cluster_id)
        LOG.info('Deployment started!')
