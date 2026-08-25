"""The bounded queue, and what happens when it fills.

This is where the framework's original fan-out went wrong: it wrote straight to
each socket in turn, so one client that had stopped reading stalled the room.
Everything here is about that not being possible.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from sillo.wire import Encoding, Envelope, Overflow, Peer, PeerGone
from sillo.wire.testing import FakeSocket, drain


class TestConstruction:
    def test_capacity_must_be_positive(self):
        with pytest.raises(ValueError, match="at least 1"):
            Peer(FakeSocket(), capacity=0)

    def test_peers_get_distinct_ids(self):
        assert Peer(FakeSocket()).id != Peer(FakeSocket()).id

    def test_defaults(self):
        peer = Peer(FakeSocket())
        assert peer.encoding is Encoding.JSON
        assert peer.overflow is Overflow.DROP_OLDEST
        assert peer.identity is None
        assert peer.idle_timeout is None
        assert not peer.closed
        assert peer.pending == 0

    def test_repr_shows_state(self):
        peer = Peer(FakeSocket(), identity="ada")
        assert "ada" in repr(peer)
        assert "pending=0" in repr(peer)
        peer._closed = True
        assert "closed" in repr(peer)


class TestEncodings:
    @pytest.mark.parametrize(
        ("encoding", "payload"),
        [
            (Encoding.JSON, {"a": 1}),
            (Encoding.TEXT, "hello"),
            (Encoding.BYTES, b"hello"),
        ],
    )
    async def test_each_encoding_reaches_the_socket(self, encoding, payload):
        socket = FakeSocket()
        peer = Peer(socket, encoding=encoding)
        await peer.send(payload)
        assert socket.sent == [payload]


class TestDirectSend:
    async def test_send_raises_when_the_socket_is_gone(self):
        peer = Peer(FakeSocket(fail=True))
        with pytest.raises(PeerGone):
            await peer.send("x")

    async def test_send_raises_once_closed(self):
        peer = Peer(FakeSocket())
        await peer.close()
        with pytest.raises(PeerGone, match="closed"):
            await peer.send("x")

    async def test_send_updates_the_idle_clock(self):
        peer = Peer(FakeSocket())
        before = peer.last_sent_at
        await asyncio.sleep(0.01)
        await peer.send("x")
        assert peer.last_sent_at > before


class TestQueueing:
    async def test_offer_does_not_block(self):
        """The whole point: enqueueing is synchronous and cannot wait on a
        socket, however slow that socket is."""
        peer = Peer(FakeSocket(delay=10), capacity=4)
        started = time.perf_counter()
        for _ in range(4):
            assert peer.offer(Envelope("x"))
        assert time.perf_counter() - started < 0.05

    async def test_a_started_peer_drains_to_the_socket(self):
        socket = FakeSocket()
        peer = Peer(socket)
        peer.start()
        peer.offer(Envelope("one"))
        peer.offer(Envelope("two"))
        await drain(peer)
        assert socket.sent == ["one", "two"]

    async def test_start_is_idempotent(self):
        """A hub joins a peer to several rooms and must not spawn a writer
        per room."""
        peer = Peer(FakeSocket())
        peer.start()
        first = peer._writer
        peer.start()
        assert peer._writer is first
        await peer.close()

    async def test_a_closed_peer_refuses_offers(self):
        peer = Peer(FakeSocket())
        await peer.close()
        assert peer.offer(Envelope("x")) is False

    async def test_closed_peers_do_not_start(self):
        peer = Peer(FakeSocket())
        await peer.close()
        peer.start()
        assert peer._writer is None


class TestOverflow:
    async def test_drop_oldest_keeps_the_newest(self):
        socket = FakeSocket()
        peer = Peer(socket, capacity=2, overflow=Overflow.DROP_OLDEST)
        for n in range(4):
            assert peer.offer(Envelope(n))
        peer.start()
        await drain(peer)
        assert socket.sent == [2, 3]

    async def test_drop_newest_keeps_the_oldest(self):
        socket = FakeSocket()
        peer = Peer(socket, capacity=2, overflow=Overflow.DROP_NEWEST)
        assert peer.offer(Envelope(0))
        assert peer.offer(Envelope(1))
        assert peer.offer(Envelope(2)) is False
        peer.start()
        await drain(peer)
        assert socket.sent == [0, 1]

    async def test_close_disconnects_the_slow_peer(self):
        peer = Peer(FakeSocket(), capacity=1, overflow=Overflow.CLOSE)
        assert peer.offer(Envelope(0))
        assert peer.offer(Envelope(1)) is False
        assert peer.closed


class TestFailureHandling:
    async def test_a_writer_stops_when_the_socket_dies(self):
        peer = Peer(FakeSocket(fail=True))
        peer.start()
        peer.offer(Envelope("x"))
        for _ in range(20):
            await asyncio.sleep(0)
            if peer.closed:
                break
        assert peer.closed

    async def test_the_writer_exits_if_closed_mid_wait(self):
        """Closing while the writer is parked on an empty queue must end it,
        not leave it holding a socket that is already shut."""
        peer = Peer(FakeSocket())
        peer.start()
        await asyncio.sleep(0)
        peer._closed = True
        peer._queue.put_nowait(Envelope("ignored"))
        await asyncio.sleep(0)
        await peer.close()
        assert peer.closed
