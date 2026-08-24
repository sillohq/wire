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
