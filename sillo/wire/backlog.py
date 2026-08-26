"""Recent traffic per room, and where a reconnecting client left off.

A backlog is what turns a dropped connection into a gap a client can close. It
keeps the last N bytes of a room's envelopes and answers "everything after
sequence 42", which is the question a client actually has after reconnecting.

The memory implementation caps by *payload* bytes and evicts oldest-first.
Sizing a list of messages with :func:`sys.getsizeof` measures the list's
pointer array rather than the messages, so a "1 MB" cap set that way holds
whatever fits in 1 MB of pointers — a hundred times its stated limit — and
then, on tripping, discards the entire history rather than the oldest part of
it. Both of those are the bug this exists to not have.
"""

from __future__ import annotations

import typing
from collections import deque

from sillo.wire.envelope import Envelope

__all__ = ["Backlog", "MemoryBacklog", "NullBacklog"]

#: One mebibyte per room, which is a few thousand chat messages and a few
#: hundred sizeable JSON documents.
DEFAULT_CAPACITY_BYTES = 1_048_576


class Backlog(typing.Protocol):
    """What a hub needs from a message store.

    A protocol rather than a base class so a Redis or Postgres implementation
    does not have to import anything from here to satisfy it.
    """

    async def append(self, envelope: Envelope) -> None:
        """Record *envelope* against its room."""
        ...

    async def since(self, room: str, seq: int) -> list[Envelope]:
        """Every retained envelope for *room* newer than *seq*, oldest first."""
        ...

    async def latest(self, room: str, limit: int = 50) -> list[Envelope]:
        """The most recent *limit* envelopes for *room*, oldest first."""
        ...

    async def clear(self, room: str | None = None) -> None:
        """Forget one room's history, or all of it."""
        ...


class MemoryBacklog:
    """Per-room history in memory, capped by payload bytes.

    Args:
        capacity_bytes: How much payload to retain per room. Eviction is
            oldest-first, so the cap trims the tail of the history rather than
            emptying it.
    """

    __slots__ = ("_bytes", "_rooms", "capacity_bytes")

    def __init__(self, capacity_bytes: int = DEFAULT_CAPACITY_BYTES) -> None:
        if capacity_bytes < 1:
            raise ValueError("capacity_bytes must be at least 1")
        self.capacity_bytes = capacity_bytes
        self._rooms: dict[str, deque[Envelope]] = {}
        self._bytes: dict[str, int] = {}

    async def append(self, envelope: Envelope) -> None:
        """Record *envelope*, evicting oldest until the room fits its cap."""
        room = envelope.room
        entries = self._rooms.setdefault(room, deque())
        entries.append(envelope)
        self._bytes[room] = self._bytes.get(room, 0) + envelope.size()

        # A single envelope larger than the whole cap would loop forever if the
        # room could be emptied; stopping at one entry keeps the most recent
        # message retrievable, which is more useful than an empty room.
        while len(entries) > 1 and self._bytes[room] > self.capacity_bytes:
            self._bytes[room] -= entries.popleft().size()

    async def since(self, room: str, seq: int) -> list[Envelope]:
        """Everything retained for *room* after *seq*."""
        return [e for e in self._rooms.get(room, ()) if e.seq > seq]

    async def latest(self, room: str, limit: int = 50) -> list[Envelope]:
        """The last *limit* envelopes for *room*."""
        if limit <= 0:
            return []
        entries = self._rooms.get(room)
        if not entries:
            return []
        return list(entries)[-limit:]

    async def clear(self, room: str | None = None) -> None:
        """Forget *room*, or every room."""
        if room is None:
            self._rooms.clear()
            self._bytes.clear()
            return
        self._rooms.pop(room, None)
        self._bytes.pop(room, None)

    def usage(self, room: str) -> int:
        """Bytes currently retained for *room*.

        Exposed because a cap you cannot observe is a cap you cannot tune.
        """
        return self._bytes.get(room, 0)

    def rooms(self) -> list[str]:
        """Every room this backlog holds something for."""
        return list(self._rooms)
