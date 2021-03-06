'''Copyright (c) 2019 Machine Zone, Inc. All rights reserved.'''

import asyncio
import tempfile
import os
import random

from cobras.common.apps_config import AppsConfig
from cobras.server.app import AppRunner

import coloredlogs
import pytest

coloredlogs.install(level='INFO')


def getFreePort():
    return random.randint(9000, 16000)


def makeRunner(debugMemory=False, enableStats=False, redisUrls=None):
    host = 'localhost'
    port = getFreePort()
    redisPassword = None
    redisCluster = False
    maxSubscriptions = -1
    idleTimeout = 10  # after 10 seconds it's a lost cause / FIXME(unused)

    if redisUrls is None:
        redisUrls = 'redis://localhost'

    appsConfigPath = tempfile.mktemp()
    appsConfig = AppsConfig(appsConfigPath)
    appsConfig.generateDefaultConfig()
    os.environ['COBRA_APPS_CONFIG'] = appsConfigPath

    runner = AppRunner(
        host,
        port,
        redisUrls,
        redisPassword,
        redisCluster,
        appsConfigPath,
        debugMemory,
        enableStats,
        maxSubscriptions,
        idleTimeout,
    )
    asyncio.get_event_loop().run_until_complete(runner.setup())
    return runner, appsConfigPath


@pytest.fixture()
def runner():
    runner, appsConfigPath = makeRunner(debugMemory=False)
    yield runner

    runner.terminate()
    os.unlink(appsConfigPath)


@pytest.fixture()
def redisDownRunner():
    redisUrls = 'redis://localhost:9999'
    runner, appsConfigPath = makeRunner(
        debugMemory=False, enableStats=False, redisUrls=redisUrls
    )
    yield runner

    runner.terminate()
    os.unlink(appsConfigPath)
