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
