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
