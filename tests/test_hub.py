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


class TestSendTo:
    async def test_every_connection_that_identity_has(self):
        """One person with a phone and two tabs is three peers."""
        hub = Hub()
        phone = make_peer(identity="ada")
        tab_one = make_peer(identity="ada")
        tab_two = make_peer(identity="ada")
        other = make_peer(identity="bob")
        for peer in (phone, tab_one, tab_two, other):
            await hub.join(peer, "room")

        report = await hub.send_to("ada", "just for you")
        await drain(phone, tab_one, tab_two, other)

        assert report.delivered == 3
        assert other.socket.sent == []

    async def test_an_unknown_identity_delivers_nothing(self):
        hub = Hub()
        await hub.join(make_peer(identity="ada"), "room")
        assert (await hub.send_to("nobody", "x")).attempted == 0

    async def test_it_reaches_across_rooms(self):
        hub = Hub()
        peer = make_peer(identity="ada")
        await hub.join(peer, "one")
        await hub.join(peer, "two")
        assert (await hub.send_to("ada", "x")).delivered == 1


class TestReplay:
    async def test_a_reconnecting_client_gets_only_what_it_missed(self):
        hub = Hub()
        first = make_peer()
        await hub.join(first, "room")
        await hub.broadcast("room", "one")
        await hub.broadcast("room", "two")
        cursor = (await hub.history("room"))[-1].seq
        await hub.broadcast("room", "three")

        returning = make_peer()
        await hub.join(returning, "room")
        sent = await hub.replay(returning, "room", since=cursor)
        await drain(returning)

        assert sent == 1
        assert returning.socket.sent == ["three"]

    async def test_replaying_from_zero_gives_everything(self):
        hub = Hub()
        await hub.join(make_peer(), "room")
        for n in range(3):
            await hub.broadcast("room", n)
        peer = make_peer()
        await hub.join(peer, "room")
        assert await hub.replay(peer, "room") == 3

    async def test_replay_respects_a_limit(self):
        hub = Hub()
        await hub.join(make_peer(), "room")
        for n in range(5):
            await hub.broadcast("room", n)
        peer = make_peer()
        assert await hub.replay(peer, "room", limit=2) == 2
        assert await hub.replay(peer, "room", limit=0) == 0

    async def test_replay_counts_only_what_was_accepted(self):
        hub = Hub()
        await hub.join(make_peer(), "room")
        for n in range(5):
            await hub.broadcast("room", n)
        peer = Peer(FakeSocket(delay=5), capacity=2, overflow=Overflow.DROP_NEWEST)
        assert await hub.replay(peer, "room") == 2

    async def test_history_and_clearing_it(self):
        hub = Hub()
        await hub.join(make_peer(), "room")
        await hub.broadcast("room", "x")
        assert len(await hub.history("room")) == 1
        await hub.clear_history("room")
        assert await hub.history("room") == []
        await hub.broadcast("room", "y")
        await hub.clear_history()
        assert await hub.history("room") == []

    async def test_a_null_backlog_retains_nothing(self):
        hub = Hub(backlog=NullBacklog())
        await hub.join(make_peer(), "room")
        await hub.broadcast("room", "x")
        assert await hub.history("room") == []

    async def test_a_backlog_can_be_supplied(self):
        backlog = MemoryBacklog(capacity_bytes=64)
        hub = Hub(backlog=backlog)
        await hub.join(make_peer(), "room")
        await hub.broadcast("room", "x")
        assert backlog.usage("room") > 0


class TestPresence:
    async def test_join_and_leave_listeners_fire(self):
        hub, seen = Hub(), []

        @hub.on_join
        def joined(room, peer):
            seen.append(("join", room))

        @hub.on_leave
        async def left(room, peer):
            seen.append(("leave", room))

        peer = make_peer()
        await hub.join(peer, "room")
        await hub.leave(peer, "room")
        assert seen == [("join", "room"), ("leave", "room")]

    async def test_a_listener_is_returned_so_it_decorates(self):
        hub = Hub()

        def listener(room, peer): ...

        assert hub.on_join(listener) is listener
        assert hub.on_leave(listener) is listener

    async def test_identities_are_the_roster(self):
        hub = Hub()
        await hub.join(make_peer(identity="ada"), "room")
        await hub.join(make_peer(identity="ada"), "room")
        await hub.join(make_peer(identity="bob"), "room")
        await hub.join(make_peer(), "room")
        assert sorted(hub.identities("room")) == ["ada", "bob"]

    async def test_asking_about_a_room_that_does_not_exist(self):
        with pytest.raises(RoomNotFound):
            Hub().identities("ghost")


class TestIntrospection:
    async def test_counts(self):
        hub = Hub()
        peer = make_peer()
        await hub.join(peer, "one")
        await hub.join(peer, "two")
        await hub.join(make_peer(), "one")
        assert hub.count("one") == 2
        assert hub.count("missing") == 0
        # Subscriptions, not connections: the shared peer counts in both rooms.
        assert hub.count() == 3

    async def test_members_of_an_unknown_room_is_empty(self):
        assert Hub().members("nope") == []

    async def test_repr(self):
        hub = Hub()
        await hub.join(make_peer(), "room")
        assert "rooms=1" in repr(hub)
        assert "peers=1" in repr(hub)


class TestPruning:
    async def test_it_evicts_closed_peers(self):
        hub, alive, dead = Hub(), make_peer(), make_peer()
        await hub.join(alive, "room")
        await hub.join(dead, "room")
        await dead.close()
        assert await hub.prune() == [dead]
        assert hub.members("room") == [alive]

    async def test_it_evicts_idle_peers(self):
        hub = Hub()
        stale = Peer(FakeSocket(), idle_timeout=0.01)
        await hub.join(stale, "room")
        await asyncio.sleep(0.02)
        assert await hub.prune() == [stale]

    async def test_a_peer_in_two_rooms_is_reported_once(self):
        hub, peer = Hub(), make_peer()
        await hub.join(peer, "one")
        await hub.join(peer, "two")
        await peer.close()
        assert await hub.prune() == [peer]

    async def test_nothing_to_prune(self):
        hub = Hub()
        await hub.join(make_peer(), "room")
        assert await hub.prune() == []
        await hub.close()


class TestIsolation:
    async def test_two_hubs_do_not_see_each_other(self):
        """The reason this is an object and not a module of class methods
        over a global dict."""
        one, two = Hub(), Hub()
        await one.join(make_peer(), "room")
        assert two.rooms() == []
        assert two.count() == 0

    async def test_close_shuts_everything(self):
        hub = Hub()
        peers = [make_peer() for _ in range(3)]
        for peer in peers:
            await hub.join(peer, "room")
        await hub.close()
        assert hub.rooms() == []
        assert all(p.closed for p in peers)
