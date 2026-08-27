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
