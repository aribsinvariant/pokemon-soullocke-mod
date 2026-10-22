import asyncio
import unittest
from soullink.bridge.client import copy_relay, WrongRelayError


class Writer:
    def __init__(self):
        self.data = bytearray()

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        pass


class ConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_is_rejected_before_reaching_emulator(self):
        for response in (b'<!DOCTYPE HTML>\n', b'HTTP/1.1 400 Bad Request\r\n'):
            reader, writer = asyncio.StreamReader(), Writer()
            reader.feed_data(response)
            reader.feed_eof()
            with self.assertRaises(WrongRelayError):
                await copy_relay(reader, writer)
            self.assertEqual(writer.data, b'')

    async def test_fragmented_handshake_and_following_data_preserved(self):
        reader, writer = asyncio.StreamReader(), Writer()
        task = asyncio.create_task(copy_relay(reader, writer))
        reader.feed_data(b'STA')
        await asyncio.sleep(0)
        self.assertEqual(writer.data, b'')
        reader.feed_data(b'TE payload\nPOS 1 2 3 4 5 6 1\n')
        reader.feed_eof()
        await task
        self.assertEqual(writer.data, b'STATE payload\nPOS 1 2 3 4 5 6 1\n')

    async def test_relay_errors_are_forwarded(self):
        reader, writer = asyncio.StreamReader(), Writer()
        reader.feed_data(b'ERROR invalid credential\n')
        reader.feed_eof()
        await copy_relay(reader, writer)
        self.assertEqual(writer.data, b'ERROR invalid credential\n')
