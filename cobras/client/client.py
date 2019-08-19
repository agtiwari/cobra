'''Client for a cobra server.

Copyright (c) 2018-2019 Machine Zone, Inc. All rights reserved.
'''

import logging
import asyncio
import functools
import itertools
import json

import click
import websockets

from cobras.client.connection import Connection, AuthException, HandshakeException, ActionException


async def client(url, creds, clientCallback, waitTime=None):
    '''Main client. Does authenticate then invoke the clientCallback which
    takes control.
    '''

    # Wait 1 second by default before retrying to connect after an error
    if waitTime is None:
        waitTime = 1

    while True:
        try:
            connection = Connection(url, creds)
            await connection.connect()
            return await clientCallback(connection)

        except TimeoutError as e:
            logging.error(e)
            await asyncio.sleep(waitTime)
            pass
        except ConnectionRefusedError as e:
            logging.error(e)
            await asyncio.sleep(waitTime)
            pass
        except ConnectionResetError as e:
            logging.error(e)
            await asyncio.sleep(waitTime)
            pass
        except websockets.exceptions.ConnectionClosedOK as e:
            logging.error(e)
            await asyncio.sleep(waitTime)
            pass
        except websockets.exceptions.ConnectionClosedError as e:
            logging.error(e)
            await asyncio.sleep(waitTime)
            pass
        except OSError as e:
            logging.error(e)
            await asyncio.sleep(waitTime)
            pass
        except AuthException as e:
            logging.error(e)
            await asyncio.sleep(waitTime)
            pass
        except ActionException as e:
            logging.error(e)
            await asyncio.sleep(waitTime)
            pass


async def subscribeHandler(connection, **args):
    channel = args['channel']
    position = args['position']
    fsqlFilter = args['fsqlFilter']
    messageHandlerClass = args['messageHandlerClass']
    messageHandlerArgs = args['messageHandlerArgs']
    subscriptionId = args.get('subscription_id', channel)
    messageHandlerArgs['subscription_id'] = subscriptionId

    return await connection.subscribe(channel,
                                      position,
                                      fsqlFilter,
                                      messageHandlerClass,
                                      messageHandlerArgs,
                                      subscriptionId)


async def subscribeClient(url, credentials, channel, position, fsqlFilter,
                          messageHandlerClass, messageHandlerArgs, waitTime=None):
    subscribeHandlerPartial = functools.partial(
        subscribeHandler,
        channel=channel,
        position=position,
        fsqlFilter=fsqlFilter,
        messageHandlerClass=messageHandlerClass,
        messageHandlerArgs=messageHandlerArgs)

    ret = await client(url, credentials, subscribeHandlerPartial, waitTime)
    return ret


async def unsafeSubcribeClient(url, credentials, channel, position, fsqlFilter,
                               messageHandlerClass, messageHandlerArgs):
    '''
    No retry or exception handling
    Used by the health check, where we want to die hard and fast if there's a problem
    '''
    connection = Connection(url, credentials)
    await connection.connect()
    message = await connection.subscribe(channel,
                                         position,
                                         fsqlFilter,
                                         messageHandlerClass,
                                         messageHandlerArgs,
                                         subscriptionId=channel)
    return message


async def readHandler(websocket, **args):
    position = args.get('position')
    channel = args.get('channel')
    handler = args.get('handler')

    readPdu = {
        "action": "rtm/read",
        "body": {
            "channel": channel,
        },
        "id": 3  # FIXME
    }

    if position is not None:
        readPdu['body']['position'] = position

    print(f"> {readPdu}")
    await websocket.send(json.dumps(readPdu))

    readResponse = await websocket.recv()
    print(f"< {readResponse}")

    data = json.loads(readResponse)
    msg = data['body']['message']  # FIXME data missing
    await handler(msg)


async def readClient(url, credentials, channel, position, handler):
    readHandlerPartial = functools.partial(readHandler,
                                           channel=channel,
                                           position=position,
                                           handler=handler)

    ret = await client(url, credentials, readHandlerPartial)
    return ret
