'''rcc redis client

Copyright (c) 2020 Machine Zone, Inc. All rights reserved.
'''

from urllib.parse import urlparse

from rcc.client import RedisClient


class RedisClientRcc(object):
    def __init__(self, url, password, cluster, library):
        self.url = url
        self.password = password
        self.cluster = cluster
        self.library = library

        netloc = urlparse(url).netloc
        host, _, port = netloc.partition(':')
        if port:
            port = int(port)
        else:
            port = 6379

        self.redis = RedisClient(self.url, self.password)

        self.host = host

    def __del__(self):
        self.close()

    def close(self):
        pass

    async def connect(self):
        pass

    async def getClientId(self):
        return await self.redis.send('CLIENT', 'ID')

    async def getHostForKey(self, key):
        if not self.redis.cluster:
            return f'{self.redis.host}:{self.redis.port}'

        slot = await self.redis.send('CLUSTER', 'KEYSLOT', key)
        slots = await self.redis.send('CLUSTER', 'SLOTS')

        for slotInfo in slots:
            if slotInfo[0] <= slot <= slotInfo[1]:
                host = slotInfo[2][0].decode()
                port = slotInfo[2][1]
                return f'{host}:{port}'

        return 'unknown-host'

    async def ping(self):
        return await self.redis.send('PING')

    async def xadd(self, stream, field, data, maxLen):
        return await self.redis.send(
            'XADD', stream, 'MAXLEN', '~', maxLen, b'*', field, data
        )

    async def exists(self, key):
        return await self.redis.send('EXISTS', key)

    async def xread(self, streams):
        args = ['XREAD', 'BLOCK', b'0', b'STREAMS']
        for item in streams.items():
            args.append(item[0])
            args.append(item[1])

        result = await self.redis.send(*args)
        return result

    async def delete(self, key):
        return await self.redis.send('DEL', key)

    async def xrevrange(self, stream, start, end, count):
        return await self.redis.send('XREVRANGE', stream, start, end, b'COUNT', count)
