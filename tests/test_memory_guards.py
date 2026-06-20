import struct
import sys
import types
import unittest
from collections import deque
from unittest.mock import AsyncMock, patch


_fake_aes = types.ModuleType("proxy._aes")
_fake_aes.Cipher = object
_fake_aes.algorithms = object
_fake_aes.modes = object
sys.modules.setdefault("proxy._aes", _fake_aes)

from proxy.bridge import MAX_MTPROTO_PACKET_SIZE, MsgSplitter  # noqa: E402
from proxy.pool import _WsPool  # noqa: E402
from proxy.raw_websocket import MAX_WS_FRAME_SIZE, RawWebSocket  # noqa: E402


class _IdentityCipher:
    def update(self, data):
        return data


def _splitter(proto):
    splitter = MsgSplitter.__new__(MsgSplitter)
    splitter._dec = _IdentityCipher()
    splitter._proto = proto
    splitter._cipher_buf = bytearray()
    splitter._plain_buf = bytearray()
    splitter._disabled = False
    return splitter


class MsgSplitterLimitsTest(unittest.TestCase):
    def test_rejects_oversized_intermediate_packet_before_buffering_body(self):
        splitter = _splitter(0xEEEEEEEE)
        header = struct.pack('<I', MAX_MTPROTO_PACKET_SIZE)

        with self.assertRaisesRegex(ValueError, "MTProto packet too large"):
            splitter.split(header)

        self.assertEqual(len(splitter._cipher_buf), len(header))
        self.assertEqual(len(splitter._plain_buf), len(header))

    def test_accepts_packet_at_limit(self):
        splitter = _splitter(0xEEEEEEEE)
        payload_len = MAX_MTPROTO_PACKET_SIZE - 4
        header = struct.pack('<I', payload_len)

        self.assertEqual(splitter.split(header), [])


class _Reader:
    def __init__(self, chunks):
        self._chunks = iter(chunks)

    async def readexactly(self, size):
        data = next(self._chunks)
        if len(data) != size:
            raise AssertionError(f"expected read of {size}, got {len(data)}")
        return data


class _HandshakeReader:
    def __init__(self):
        self._lines = iter((b"HTTP/1.1 400 Bad Request\r\n", b"\r\n"))

    async def readline(self):
        return next(self._lines)


class _Transport:
    def get_extra_info(self, _name):
        return None


class _Writer:
    def __init__(self):
        self.transport = _Transport()
        self.closed = False
        self.waited_closed = False

    def write(self, _data):
        pass

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        self.waited_closed = True


class RawWebSocketLimitsTest(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_oversized_frame_before_reading_payload(self):
        header = bytes((0x82, 127))
        length = struct.pack('>Q', MAX_WS_FRAME_SIZE + 1)
        ws = RawWebSocket(_Reader((header, length)), None)

        with self.assertRaisesRegex(ConnectionError,
                                    "WebSocket frame too large"):
            await ws._read_frame()

    async def test_failed_handshake_closes_writer(self):
        writer = _Writer()
        open_connection = AsyncMock(
            return_value=(_HandshakeReader(), writer)
        )

        with patch("proxy.raw_websocket.asyncio.open_connection",
                   open_connection):
            with self.assertRaisesRegex(Exception, "HTTP 400"):
                await RawWebSocket.connect("127.0.0.1", "example.com")

        self.assertTrue(writer.closed)
        self.assertTrue(writer.waited_closed)


class _PooledWebSocket:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class PoolCleanupTest(unittest.IsolatedAsyncioTestCase):
    async def test_reset_closes_idle_connections(self):
        pool = _WsPool()
        ws = _PooledWebSocket()
        pool._idle[(2, False)] = deque(((ws, 0.0),))

        await pool.reset()

        self.assertTrue(ws.closed)
        self.assertEqual(pool._idle, {})


if __name__ == '__main__':
    unittest.main()
