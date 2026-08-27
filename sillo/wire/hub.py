"""Rooms, membership and fan-out.

A :class:`Hub` owns rooms and the peers in them. It is an ordinary object, not
a module of class methods over a global dict, so two hubs are two independent
worlds: a test gets a fresh one per case instead of remembering to flush shared
state, and an application that serves several tenants can keep their traffic
apart without a naming convention.

Fan-out is concurrent and non-blocking. Delivering to a room enqueues on every
peer at once and returns a :class:`~sillo.wire.envelope.DeliveryReport`; it
never waits on a socket, so one client that has stopped reading cannot hold up
the rest of the room.
"""

from __future__ import annotations

import inspect
import typing

from sillo.wire.backlog import Backlog, MemoryBacklog
from sillo.wire.envelope import DeliveryReport, Envelope
from sillo.wire.errors import RoomNotFound
from sillo.wire.peer import Peer

__all__ = ["Hub"]

#: Called as ``listener(room, peer)`` when membership changes. Sync or async.
PresenceListener = typing.Callable[[str, Peer], typing.Any]


class Hub:
    """A set of rooms and the peers subscribed to them.

    Args:
        backlog: Where delivered envelopes are retained for replay. Defaults to
            an in-memory one; pass :class:`~sillo.wire.backlog.NullBacklog` to
            keep nothing.
    """

    __slots__ = ("_backlog", "_on_join", "_on_leave", "_rooms")

    def __init__(self, backlog: Backlog | None = None) -> None:
        self._rooms: dict[str, set[Peer]] = {}
        self._backlog: Backlog = MemoryBacklog() if backlog is None else backlog
        self._on_join: list[PresenceListener] = []
        self._on_leave: list[PresenceListener] = []

    # ── membership ───────────────────────────────────────────────────────

    async def join(self, peer: Peer, room: str) -> bool:
        """Subscribe *peer* to *room*. Returns whether it was newly added.

        Starts the peer's writer if it is not already running, so a caller
        never has to remember to.
        """
        if not room:
            raise ValueError("room name must not be empty")

        members = self._rooms.setdefault(room, set())
        if peer in members:
            return False

        members.add(peer)
        peer.start()
        await self._announce(self._on_join, room, peer)
        return True

    async def leave(self, peer: Peer, room: str) -> bool:
        """Unsubscribe *peer* from *room*. Returns whether it was a member.

        Leaving a room that does not exist, or that the peer is not in, is not
        an error — a disconnect racing a cleanup produces both, routinely.
        """
        members = self._rooms.get(room)
        if members is None or peer not in members:
            return False

        members.discard(peer)
        if not members:
            del self._rooms[room]
        await self._announce(self._on_leave, room, peer)
        return True

    async def leave_all(self, peer: Peer) -> list[str]:
        """Remove *peer* from every room. Returns the rooms it was in."""
        left = [room for room, members in self._rooms.items() if peer in members]
        for room in left:
            await self.leave(peer, room)
        return left

    async def disconnect(self, peer: Peer) -> None:
        """Remove *peer* from every room and close its socket.

        The one call a consumer's disconnect path needs.
        """
        await self.leave_all(peer)
        await peer.close()

    # ── delivery ─────────────────────────────────────────────────────────

    async def broadcast(
        self,
        room: str,
        payload: typing.Any,
        *,
        retain: bool = True,
    ) -> DeliveryReport:
        """Deliver *payload* to every peer in *room*.

        Args:
            room: Which room to deliver to. An unknown room is an empty report,
                not an error — rooms come and go with their last member.
            payload: What to send.
            retain: Whether to record the envelope in the backlog for replay.

        Returns:
            What happened, per peer.
        """
        envelope = Envelope(payload=payload, room=room)
        if retain:
            await self._backlog.append(envelope)

        members = self._rooms.get(room)
        if not members:
            return DeliveryReport()

        report, stale = self._offer_all(members, envelope)
        if stale:
            members.difference_update(stale)
            if not members:
                del self._rooms[room]
        return report

    async def send_to(
        self, identity: typing.Any, payload: typing.Any
    ) -> DeliveryReport:
        """Deliver *payload* to every peer carrying *identity*.

        This is the "reach that user wherever they are" call — one person with
        a phone and two tabs is three peers, and all three get it. Nothing is
        retained: the message is addressed to a person, not to a room, so there
        is no room whose history it belongs in.
        """
        targets = {
            peer
            for members in self._rooms.values()
            for peer in members
            if peer.identity == identity
        }
        if not targets:
            return DeliveryReport()
        # Stale peers are not evicted here: a peer reached by identity may be
        # in several rooms, and removing it from all of them is `prune`'s job.
        report, _ = self._offer_all(targets, Envelope(payload=payload))
        return report
