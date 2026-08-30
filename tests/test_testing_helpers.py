"""The helpers this package ships for other people's tests."""

from __future__ import annotations

import asyncio

import pytest

from sillo_wire import Envelope, Peer
from sillo_wire.testing import FakeSocket, drain


class TestFakeSocket:
    async def test_it_records_each_encoding(self):
        socket = FakeSocket()
        await socket.send_json({"a": 1})
        await socket.send_text("b")
        await socket.send_bytes(b"c")
        assert socket.sent == [{"a": 1}, "b", b"c"]

    async def test_close_marks_it(self):
        socket = FakeSocket()
        assert not socket.closed
        await socket.close()
        assert socket.closed

    async def test_accept_is_available(self):
        await FakeSocket().accept()

    async def test_fail_simulates_a_dead_connection(self):
        socket = FakeSocket(fail=True)
        with pytest.raises(ConnectionResetError):
            await socket.send_json("x")
        assert socket.sent == []

    async def test_delay_simulates_a_slow_reader(self):
        socket = FakeSocket(delay=0.02)
        started = asyncio.get_running_loop().time()
        await socket.send_text("x")
        assert asyncio.get_running_loop().time() - started >= 0.015


class TestDrain:
    async def test_it_waits_for_the_queue_to_empty(self):
        socket = FakeSocket()
        peer = Peer(socket)
        peer.start()
        for n in range(5):
            peer.offer(Envelope(n))
        await drain(peer)
        assert socket.sent == [0, 1, 2, 3, 4]

    async def test_it_handles_several_peers(self):
        peers = [Peer(FakeSocket()) for _ in range(3)]
        for peer in peers:
            peer.start()
            peer.offer(Envelope("x"))
        await drain(*peers)
        assert all(p.socket.sent == ["x"] for p in peers)

    async def test_an_empty_queue_returns_at_once(self):
        await drain(Peer(FakeSocket()))

    async def test_a_stuck_writer_times_out(self):
        """A queue that never empties is a bug, and the helper says so rather
        than hanging the suite."""
        peer = Peer(FakeSocket(delay=10))
        peer.start()
        peer.offer(Envelope("x"))
        peer.offer(Envelope("y"))
        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            await drain(peer, timeout=0.05)
        await peer.close()
