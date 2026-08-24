"""One connected client, with a bounded outbound queue.

The queue is the point. Writing straight to a socket inside a fan-out means the
slowest member of a room sets the pace for every other member: a client that
has stopped reading fills its kernel buffer, the write blocks, and everyone
behind it waits. Here a broadcast only ever *enqueues*, which cannot block, and
a writer task per peer drains the queue at whatever rate that peer manages.

What happens when a queue fills is a policy rather than a default -- see
:class:`~sillo.wire.policy.Overflow`.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import typing
import uuid

from sillo.wire.envelope import Encoding, Envelope
from sillo.wire.errors import PeerGone
from sillo.wire.policy import Overflow

__all__ = ["Peer"]

#: Default queue depth. Deep enough to absorb a burst, shallow enough that a
#: client which has genuinely stopped reading is noticed within a second or two
#: rather than after megabytes have accumulated on its behalf.
DEFAULT_CAPACITY = 64


class Peer:
    """A socket, its identity, and its outbound queue.

    Args:
        socket: The connection to write to. Anything with the
            ``send_json`` / ``send_text`` / ``send_bytes`` trio works, which is
            what makes a peer testable without a server.
        encoding: How payloads are written.
        identity: Who this connection belongs to, if anyone. Two peers may
            share an identity — the same user with two tabs open — which is
            what :meth:`~sillo.wire.hub.Hub.send_to` relies on.
        capacity: Outbound queue depth.
        overflow: What to do when the queue is full.
        idle_timeout: Seconds of silence after which the peer is considered
            stale. ``None`` disables the check.
    """

    __slots__ = (
        "_closed",
        "_queue",
        "_writer",
        "capacity",
        "created_at",
        "encoding",
        "id",
        "identity",
        "idle_timeout",
        "last_sent_at",
        "overflow",
        "socket",
    )

    def __init__(
        self,
        socket: typing.Any,
        *,
        encoding: Encoding = Encoding.JSON,
        identity: typing.Any = None,
        capacity: int = DEFAULT_CAPACITY,
        overflow: Overflow = Overflow.DROP_OLDEST,
        idle_timeout: float | None = None,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")

        self.socket = socket
        self.encoding = encoding
        self.identity = identity
        self.capacity = capacity
        self.overflow = overflow
        self.idle_timeout = idle_timeout

        self.id = uuid.uuid4()
        self.created_at = time.monotonic()
        self.last_sent_at = self.created_at

        self._queue: asyncio.Queue[Envelope] = asyncio.Queue(maxsize=capacity)
        self._writer: asyncio.Task[None] | None = None
        self._closed = False
