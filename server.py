import os
import json
import sys
import logging

import etcd
from docker import Client

cli = Client(base_url='unix:///var/run/docker.sock')

events = cli.events(decode=True)

logging.basicConfig(level=logging.DEBUG)

etcd_hostname = 'etcd'
etcd_client = etcd.Client(host=etcd_hostname)

def get_container(message):
    container = message.get('Actor')
    container['Attributes']['ID'] = container['ID']
    return container['Attributes']

def get_envvar(container, to_find):
    container_details = cli.inspect_container(container['ID'])
    env = container_details['Config']['Env']
    for envvar in env:
      if envvar.startswith(to_find + '='):
       return envvar.split('=')[1]
    return None

def get_container_hostname(container):
    return container['name'] + '.weave.local'

def create_backend(backend_name):
    key = '/vulcand/backends/%s/backend' % backend_name
    try:
        etcd_client.read(key)
        return True
    except etcd.EtcdKeyNotFound:
        value = '{"Type": "http"}'
        etcd_client.write(key, value)
        logging.info('Created backend : %s' % key)
        return False

def create_frontend(backend_name, ROUTE):
    key = '/vulcand/frontends/%s/frontend' % backend_name
    try:
        etcd_client.read(key)
        return True
    except etcd.EtcdKeyNotFound:
        # NOTE : Route could be passed as a raw string.
        #        More flexible but not needed
        value = '{"Type": "http", "BackendId": "%s", "Route": "PathRegexp(`%s.*`)"}'\
                % (backend_name, ROUTE)
        etcd_client.write(key, value)
        logging.info('Created frontend : %s' % key)
        return False

def remove_frontend(backend_name):
    key = '/vulcand/frontends/%s/frontend' % backend_name
    try:
        etcd_client.read(key)
        return True
    except etcd.EtcdKeyNotFound:
        etcd_client.delete(key)
        logging.info('Removed frontend : %s' % key)
        return False

def add_container(container):
    server_name = container['name']

    ROUTE = '/' + server_name

    backend_name = server_name
    create_backend(backend_name)

    HOSTNAME = get_container_hostname(container)
    PORT = get_envvar(container, 'PORT')
    ROUTE = get_envvar(container, 'ROUTE')

    logging.info('Adding: %s:%s%s' % (HOSTNAME, PORT, ROUTE))

    if PORT:
        if not ROUTE:
          logging.info('No route could be found for this container' + server_name)
          return

        key = '/vulcand/backends/%s/servers/%s' % (backend_name, server_name)
        value = '{"URL": "http://%s:%s"}' % (HOSTNAME, PORT)

        etcd_client.write(key, value)
        logging.info('Added server: %s = %s on route %s' % (key, value, ROUTE))
        create_frontend(backend_name, ROUTE)
    else:
        logging.info('No port could be found for this container' + server_name)

def remove_container(container):
    server_name = container['name']
    backend_name = server_name

    key = '/vulcand/backends/%s/servers/%s' % (backend_name, server_name)
    try:
        etcd_client.delete(key)
        logging.info('Removed server: %s' % key)
        remove_frontend(backend_name)
    except etcd.EtcdKeyNotFound as e:
        logging.error(e)

def create_listener(name, protocol, address):
    key = '/vulcand/listeners/%s' % name
    try:
        etcd_client.read(key)
    except etcd.EtcdKeyNotFound:
        value = '{"Protocol":"%s", "Address":{"Network":"tcp", "Address":"%s"}}' % (protocol, address)
        etcd_client.write(key, value)

create_listener('http', 'http', "0.0.0.0:80")

for event in events:
	print(event)
	action = event['Action']
	container = get_container(event)

	if action == 'stop':
            logging.info('Stopped')
            remove_container(container)
	elif action == 'start':
            logging.info('Started')
            add_container(container)
	else:
	    pass
