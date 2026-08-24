"""The unit of traffic, and the result of sending one.

An :class:`Envelope` is what a room stores and replays. It carries a monotonic
:attr:`~Envelope.seq` so a client that reconnects can say "everything after
42" rather than "everything" or "nothing" -- see :meth:`Backlog.since`.
"""

from __future__ import annotations

import enum
import itertools
import typing
from dataclasses import dataclass, field
from datetime import datetime, timezone

__all__ = ["DeliveryReport", "Encoding", "Envelope"]

#: Process-wide sequence source. Monotonic rather than time-based because two
#: envelopes created in the same microsecond must still order, and a clock that
#: steps backwards must not make a replay cursor skip.
_counter = itertools.count(1)


class Encoding(enum.Enum):
    """How a payload is written to the socket."""

    JSON = "json"
    TEXT = "text"
    BYTES = "bytes"


@dataclass(frozen=True, slots=True)
class Envelope:
    """One message, addressed to a room.

    Frozen because an envelope handed to a fan-out is shared by every peer in
    the room; a mutable one would let a slow peer observe an edit made after it
    was queued.
    """

    payload: typing.Any
    room: str = ""
    seq: int = field(default_factory=lambda: next(_counter))
    #: Factories rather than plain defaults: a plain default is evaluated once,
    #: at class definition, which would stamp every envelope in a backlog with
    #: the same import-time timestamp.
    sent_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    def size(self) -> int:
        """Roughly what this costs to hold, in bytes.

        Used by the backlog to enforce its cap. Exact for the encodings that
        have a length and estimated otherwise, which is the right trade for a
        limit whose purpose is to stop unbounded growth rather than to account
        precisely.
        """
        payload = self.payload
        if isinstance(payload, (bytes, bytearray, memoryview)):
            return len(payload)
        if isinstance(payload, str):
            return len(payload.encode("utf-8", "replace"))
        return len(repr(payload).encode("utf-8", "replace"))
