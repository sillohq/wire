"""Rooms, fan-out, presence and replay."""

from __future__ import annotations

import asyncio
import time

import pytest

from sillo.wire import (
    Encoding,
    Envelope,
    Hub,
    MemoryBacklog,
    NullBacklog,
    Overflow,
    Peer,
    RoomNotFound,
)
from sillo.wire.testing import FakeSocket, drain


def make_peer(**kwargs) -> Peer:
    return Peer(FakeSocket(**kwargs.pop("socket", {})), **kwargs)


class TestMembership:
    async def test_joining_and_leaving(self):
        hub, peer = Hub(), make_peer()
        assert await hub.join(peer, "room") is True
        assert hub.members("room") == [peer]
        assert await hub.leave(peer, "room") is True
        assert hub.rooms() == []

    async def test_joining_twice_is_a_no_op(self):
        hub, peer = Hub(), make_peer()
        assert await hub.join(peer, "room") is True
        assert await hub.join(peer, "room") is False
        assert hub.count("room") == 1

    async def test_an_empty_room_name_is_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            await Hub().join(make_peer(), "")

    async def test_leaving_what_you_never_joined(self):
        """A disconnect racing a cleanup produces exactly this, routinely."""
        hub, peer = Hub(), make_peer()
        assert await hub.leave(peer, "nowhere") is False
        await hub.join(make_peer(), "room")
        assert await hub.leave(peer, "room") is False

    async def test_the_room_disappears_with_its_last_member(self):
        hub, one, two = Hub(), make_peer(), make_peer()
        await hub.join(one, "room")
        await hub.join(two, "room")
        await hub.leave(one, "room")
        assert hub.rooms() == ["room"]
        await hub.leave(two, "room")
        assert hub.rooms() == []

    async def test_joining_starts_the_writer(self):
        hub, peer = Hub(), make_peer()
        await hub.join(peer, "room")
        assert peer._writer is not None
        await hub.close()

    async def test_leave_all_reports_what_it_left(self):
        hub, peer = Hub(), make_peer()
        await hub.join(peer, "one")
        await hub.join(peer, "two")
        assert sorted(await hub.leave_all(peer)) == ["one", "two"]
        assert hub.rooms() == []

    async def test_disconnect_removes_and_closes(self):
        hub, peer = Hub(), make_peer()
        await hub.join(peer, "room")
        await hub.disconnect(peer)
        assert hub.rooms() == []
        assert peer.closed


class TestBroadcast:
    async def test_everyone_in_the_room_gets_it(self):
        hub = Hub()
        peers = [make_peer() for _ in range(3)]
        for peer in peers:
            await hub.join(peer, "room")

        report = await hub.broadcast("room", {"hello": True})
        await drain(*peers)

        assert report.delivered == 3
        assert report.attempted == 3
        for peer in peers:
            assert peer.socket.sent == [{"hello": True}]

    async def test_an_unknown_room_is_an_empty_report_not_an_error(self):
        report = await Hub().broadcast("nobody-here", "x")
        assert report.attempted == 0
        assert not report

    async def test_one_stalled_peer_does_not_hold_up_the_room(self):
        """The bug this package exists to not have: the original fan-out
        awaited each socket in turn, so a single slow client serialised
        everybody behind it."""
        hub = Hub()
        slow = Peer(FakeSocket(delay=5), capacity=4)
        quick = [make_peer() for _ in range(5)]
        for peer in (slow, *quick):
            await hub.join(peer, "room")

        started = time.perf_counter()
        report = await hub.broadcast("room", "ping")
        elapsed = time.perf_counter() - started

        assert elapsed < 0.05
        assert report.delivered == 6
        await drain(*quick)
        assert all(p.socket.sent == ["ping"] for p in quick)
        await hub.close()

    async def test_a_closed_peer_counts_as_failed_and_is_evicted(self):
        hub = Hub()
        alive, dead = make_peer(), make_peer()
        await hub.join(alive, "room")
        await hub.join(dead, "room")
        await dead.close()

        report = await hub.broadcast("room", "x")
        assert report.delivered == 1
        assert report.failed == 1
        assert hub.members("room") == [alive]

    async def test_evicting_the_last_peer_removes_the_room(self):
        hub, peer = Hub(), make_peer()
        await hub.join(peer, "room")
        await peer.close()
        await hub.broadcast("room", "x")
        assert hub.rooms() == []

    async def test_a_full_queue_is_dropped_not_failed(self):
        hub = Hub()
        peer = Peer(FakeSocket(delay=5), capacity=1, overflow=Overflow.DROP_NEWEST)
        await hub.join(peer, "room")
        # Fill the queue directly rather than through the hub: whether the
        # writer has already dequeued a message is a race, and the behaviour
        # under test is what happens once the queue is genuinely full.
        while peer.pending < peer.capacity:
            peer.offer(Envelope("filler"))

        report = await hub.broadcast("room", "overflow")
        assert report.dropped == 1
        assert report.delivered == 0
        await hub.close()

    async def test_close_policy_evicts_on_overflow(self):
        hub = Hub()
        peer = Peer(FakeSocket(delay=5), capacity=1, overflow=Overflow.CLOSE)
        await hub.join(peer, "room")
        while peer.pending < peer.capacity:
            peer.offer(Envelope("filler"))

        report = await hub.broadcast("room", "overflow")
        assert report.dropped == 1
        assert peer.closed
        # The policy closed the peer as it refused the message, so the same
        # fan-out evicts it — and it was the room's only member.
        assert hub.rooms() == []

    async def test_retain_false_skips_the_backlog(self):
        hub = Hub()
        await hub.join(make_peer(), "room")
        await hub.broadcast("room", "kept")
        await hub.broadcast("room", "transient", retain=False)
        assert [e.payload for e in await hub.history("room")] == ["kept"]
