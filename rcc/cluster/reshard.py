'''Resharding tool

See this too https://github.com/projecteru/redis-trib.py

Copyright (c) 2020 Machine Zone, Inc. All rights reserved.
'''

import asyncio
import csv
import os
import sys
import logging

from rcc.client import RedisClient
from rcc.hash_slot import getHashSlot
from rcc.binpack import to_constant_bin_number
from rcc.cluster.info import getSlotsToNodesMapping, clusterCheck


def makeClientfromNode(node):
    url = f'redis://{node.ip}:{node.port}'
    return RedisClient(url, '')  # FIXME password


async def migrateSlot(masterNodes, slot, sourceNode, destinationNode, dry=False):
    '''Migrate a slot to a node'''
    logging.info(
        f'migrate from {sourceNode.node_id} to {destinationNode.node_id} slot [{slot}]'
    )

    if dry:
        src = f'redis://{sourceNode.ip}:{sourceNode.port}'
        dst = f'redis://{destinationNode.ip}:{destinationNode.port}'
        print(f'rcc migrate --src-addr {src} --dst-addr {dst} {slot}')
        return True

    sourceClient = makeClientfromNode(sourceNode)
    destinationClient = makeClientfromNode(destinationNode)

    # cmd = '/Users/bsergeant/sandbox/venv/bin/redis-trib.py migrate'
    # cmd += ' --src-addr ' + f'{sourceNode.ip}:{sourceNode.port}'
    # cmd += ' --dst-addr ' + f'{destinationNode.ip}:{destinationNode.port}'
    # cmd += ' '            + f'{slot}'
    # print(cmd)
    # ret = os.system(cmd)
    # return ret == 0

    # 1. Set the destination node slot to importing state using CLUSTER SETSLOT
    #    <slot> IMPORTING <source-node-id>.
    try:
        await destinationClient.send(
            'CLUSTER', 'SETSLOT', slot, 'IMPORTING', sourceNode.node_id
        )
    except Exception as e:
        logging.error(f'error with SETSLOT IMPORTING command: {e}')
        return False

    # 2. Set the source node slot to migrating state using CLUSTER SETSLOT
    #    <slot> MIGRATING <destination-node-id>.
    try:
        await sourceClient.send(
            'CLUSTER', 'SETSLOT', slot, 'MIGRATING', destinationNode.node_id
        )
    except Exception as e:
        logging.error(f'error with SETSLOT MIGRATING command: {e}')
        return False

    # 3. Get keys from the source node with CLUSTER GETKEYSINSLOT command and
    #    move them into the destination node using the MIGRATE command.
    # FIXME / we need to repeat this process / make this scalable etc...
    keys = await sourceClient.send('CLUSTER', 'GETKEYSINSLOT', slot, 1000)

    timeout = 5000  # 5 seconds
    db = 0
    if len(keys) > 0:
        print('migrating', len(keys), 'keys')
        host = destinationNode.ip
        port = destinationNode.port
        await sourceClient.send('MIGRATE', host, port, "", db, timeout, "KEYS", *keys)

    # 4. Use CLUSTER SETSLOT <slot> NODE <destination-node-id> in the source or
    #    destination.
    try:
        # set the slot owner for every node in the cluster
        for node in masterNodes:
            client = makeClientfromNode(node)
            await client.send(
                'CLUSTER', 'SETSLOT', slot, 'NODE', destinationNode.node_id
            )

    except Exception as e:
        logging.error(f'error with SETSLOT NODE command: {e}')
        return False

    return True


async def runClusterCheck(port):
    cmd = f'redis-cli --cluster check localhost:{port}'

    proc = await asyncio.create_subprocess_shell(cmd)
    stdout, stderr = await proc.communicate()


async def binPackingReshardCoroutine(redis_urls, weights, dry=False, nodeId=None):
    redisClient = RedisClient(redis_urls, '')
    nodes = await redisClient.cluster_nodes()

    # There will be as many bins as there are master nodes
    masterNodes = [node for node in nodes if node.role == 'master']
    binCount = len(masterNodes)

    # We need to know where each slots lives
    slotToNodes = {}
    for node in masterNodes:
        for slot in node.slots:
            slotToNodes[slot] = node

    # Run the bin packing algorithm
    bins = to_constant_bin_number(weights, binCount)

    slots = []

    for binIdx, b in enumerate(bins):
        binSlots = []

        for key in b:
            slot = getHashSlot(key)
            binSlots.append(slot)

        binSlots.sort()
        slots.append(binSlots)

    verbose = False

    totalMigratedSlots = 0

    for binSlots, node in zip(slots, masterNodes):

        print(f'== {node.node_id} / {node.ip}:{node.port} ==')
        migratedSlots = 0

        if nodeId is not None and node.node_id != nodeId:
            continue

        if verbose:
            print(binSlots)
            for slot in binSlots:
                sourceNode = slotToNodes[slot]
                print(f'{slot} owned by {sourceNode.node_id}')
            print()

        for slot in binSlots:
            slotToNodes = await getSlotsToNodesMapping(redis_urls)
            sourceNode = slotToNodes[slot]
            if sourceNode.node_id != node.node_id:

                ret = await migrateSlot(masterNodes, slot, sourceNode, node, dry)
                if not ret:
                    return False

                migratedSlots += 1

        print(f'migrated {migratedSlots} slots')
        totalMigratedSlots += migratedSlots

        #
        # This section is key.
        # We periodically make sure that all nodes in the cluster agree on their view
        # of the cluster, mostly on how slots are allocated
        #
        # Without this wait, if we try to keep on moving other slots
        # the cluster will become broken,
        # and commands such as redis-cli --cluste check will report it as inconsistent
        #
        # note that existing redis cli command do not migrate to multiple nodes at once
        # while this script does
        #
        print('Waiting for cluster view to be consistent...')
        while True:
            sys.stderr.write('.')
            sys.stderr.flush()

            ok = await clusterCheck(redis_urls)
            if ok:
                break

            await asyncio.sleep(0.5)

    print(f'total migrated slots: {migratedSlots}')
    return True


def binPackingReshard(redis_urls, path, dry=False, nodeId=None):
    if not os.path.exists(path):
        logging.error(f'{path} does not exists')
        return False

    with open(path) as csvfile:
        reader = csv.reader(csvfile)

        weights = {}
        try:
            for row in reader:
                key = row[0]
                weight = row[1]
                weights[key] = int(weight)

        except csv.Error as ex:
            logging.error(
                'error parsing csv file {}, line {}: {}'.format(
                    path, reader.line_num, ex
                )
            )
            return False

    return asyncio.run(binPackingReshardCoroutine(redis_urls, weights, dry, nodeId))