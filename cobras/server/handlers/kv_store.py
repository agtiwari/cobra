'''Key Value store operations (set, get, delete),
but that are using streams for storage

Copyright (c) 2019 Machine Zone, Inc. All rights reserved.

FIXME: missing delete
'''

import asyncio
import rapidjson as json
import logging
from typing import Dict, Optional

from cobras.common.cobra_types import JsonDict
from cobras.server.connection_state import ConnectionState


async def kvStoreRead(redis, stream: str, position: Optional[str], logger):
    if position is None:
        # Get the last entry written to a stream
        end = '-'
        start = '+'
    else:
        start = position
        end = start

    try:
        results = await redis.send('XREVRANGE', stream, start, end, b'COUNT', 1)

        if not results:
            return None

        result = results[0]
        position = result[0]
        msg = result[1]
        data = msg[b'json']

        msg = json.loads(data)
        return msg

    except asyncio.CancelledError:
        logger('Cancelling redis subscription')
        raise


# FIXME error handling
async def handleRead(
    state: ConnectionState, ws, app: Dict, pdu: JsonDict, serializedPdu: bytes
):

    connection = None
    body = pdu.get('body', {})
    position = body.get('position')
    channel = body.get('channel')

    appkey = state.appkey
    appChannel = '{}::{}'.format(appkey, channel)

    # We need to create a new connection as reading from it will be blocking
    redis = app['redis_clients'].makeRedisClient()

    try:
        # Handle read
        message = await kvStoreRead(redis, appChannel, position, state.log)
    except Exception as e:
        errMsg = f'write: cannot connect to redis {e}'
        logging.warning(errMsg)
        response = {
            "action": "rtm/read/error",
            "id": pdu.get('id', 1),
            "body": {"error": errMsg},
        }
        await state.respond(ws, response)
        return
    finally:
        # When finished, close the connection.
        if connection is not None:
            connection.close()

    app['stats'].updateReads(state.role, len(serializedPdu))

    # Correct path
    response = {
        "action": "rtm/read/ok",
        "id": pdu.get('id', 1),
        "body": {"message": message},
    }
    await state.respond(ws, response)


async def handleWrite(
    state: ConnectionState, ws, app: Dict, pdu: JsonDict, serializedPdu: bytes
):
    # Missing message
    message = pdu.get('body', {}).get('message')
    if message is None:
        errMsg = 'write: empty message'
        logging.warning(errMsg)
        response = {
            "action": "rtm/write/error",
            "id": pdu.get('id', 1),
            "body": {"error": errMsg},
        }
        await state.respond(ws, response)
        return

    # Missing channel
    channel = pdu.get('body', {}).get('channel')
    if channel is None:
        errMsg = 'write: missing channel field'
        logging.warning(errMsg)
        response = {
            "action": "rtm/write/error",
            "id": pdu.get('id', 1),
            "body": {"error": errMsg},
        }
        await state.respond(ws, response)
        return

    # Extract the message. This is what will be published
    message = pdu['body']['message']

    appkey = state.appkey
    redis = app['redis_clients'].getRedisClient(appkey)

    try:
        appChannel = '{}::{}'.format(appkey, channel)

        serializedPdu = json.dumps(message)
        streamId = await redis.send(
            'XADD', appChannel, 'MAXLEN', '~', 1, b'*', 'json', serializedPdu
        )

    except Exception as e:
        errMsg = f'write: cannot connect to redis {e}'
        logging.warning(errMsg)
        response = {
            "action": "rtm/write/error",
            "id": pdu.get('id', 1),
            "body": {"error": errMsg},
        }
        await state.respond(ws, response)
        return

    # Stats
    app['stats'].updateWrites(state.role, len(serializedPdu))

    response = {
        "action": f"rtm/write/ok",
        "id": pdu.get('id', 1),
        "body": {"stream": streamId},
    }
    await state.respond(ws, response)


async def handleDelete(
    state: ConnectionState, ws, app: Dict, pdu: JsonDict, serializedPdu: bytes
):
    # Missing channel
    channel = pdu.get('body', {}).get('channel')
    if channel is None:
        errMsg = 'delete: missing channel field'
        logging.warning(errMsg)
        response = {
            "action": "rtm/delete/error",
            "id": pdu.get('id', 1),
            "body": {"error": errMsg},
        }
        await state.respond(ws, response)
        return

    appkey = state.appkey
    appChannel = '{}::{}'.format(appkey, channel)
    redis = app['redis_clients'].getRedisClient(appkey)

    try:
        await redis.send('DEL', appChannel)
    except Exception as e:
        errMsg = f'delete: cannot connect to redis {e}'
        logging.warning(errMsg)
        response = {
            "action": "rtm/delete/error",
            "id": pdu.get('id', 1),
            "body": {"error": errMsg},
        }
        await state.respond(ws, response)
        return

    response = {"action": f"rtm/delete/ok", "id": pdu.get('id', 1), "body": {}}
    await state.respond(ws, response)
