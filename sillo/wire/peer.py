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

    # ── lifecycle ────────────────────────────────────────────────────────

    @property
    def closed(self) -> bool:
        """Whether this peer has been closed, by either side."""
        return self._closed

    @property
    def pending(self) -> int:
        """Messages queued and not yet written."""
        return self._queue.qsize()

    def start(self) -> None:
        """Begin draining the queue.

        Idempotent, so a hub that joins the same peer to several rooms does not
        start several writers for it.
        """
        if self._writer is None and not self._closed:
            self._writer = asyncio.create_task(self._drain())

    async def close(self) -> None:
        """Stop the writer and close the socket.

        Safe to call twice, and safe to call on a socket that is already gone —
        a disconnect racing a cleanup is the normal case, not an error.
        """
        if self._closed:
            return
        self._closed = True

        if self._writer is not None:
            self._writer.cancel()
            with contextlib.suppress(BaseException):
                await self._writer
            self._writer = None

        # A socket that is already gone is the normal case here, not an error:
        # close() is what runs when the client hung up.
        with contextlib.suppress(Exception):
            await self.socket.close()

    # ── sending ──────────────────────────────────────────────────────────

    def offer(self, envelope: Envelope) -> bool:
        """Queue *envelope* without blocking. Returns whether it was accepted.

        This is what a fan-out calls. It never awaits and never raises, so one
        peer cannot affect the delivery of any other.
        """
        if self._closed:
            return False

        try:
            self._queue.put_nowait(envelope)
            return True
        except asyncio.QueueFull:
            return self._resolve_overflow(envelope)

    def _resolve_overflow(self, envelope: Envelope) -> bool:
        """Apply :attr:`overflow` to a message that did not fit."""
        if self.overflow is Overflow.DROP_NEWEST:
            return False

        if self.overflow is Overflow.CLOSE:
            # Closing is asynchronous, and this path must not await. Marking
            # it closed stops further offers immediately; the writer task sees
            # the flag and shuts the socket down.
            self._closed = True
            return False

        # DROP_OLDEST: make room by discarding the head, then retry once. The
        # retry cannot fail — nothing else consumes from this queue between the
        # two calls, because neither of them awaits.
        with contextlib.suppress(asyncio.QueueEmpty):
            self._queue.get_nowait()
        self._queue.put_nowait(envelope)
        return True

    async def send(self, payload: typing.Any) -> None:
        """Write *payload* to the socket now, bypassing the queue.

        For replies to that one peer, where the caller wants the failure. A
        broadcast uses :meth:`offer` instead.

        Raises:
            PeerGone: If the peer is closed, or the socket raises.
        """
        if self._closed:
            raise PeerGone(f"peer {self.id} is closed")
        try:
            await self._write(payload)
        except Exception as exc:
            raise PeerGone(f"peer {self.id} went away") from exc

    async def _write(self, payload: typing.Any) -> None:
        """Put one payload on the wire in this peer's encoding."""
        if self.encoding is Encoding.JSON:
            await self.socket.send_json(payload)
        elif self.encoding is Encoding.TEXT:
            await self.socket.send_text(payload)
        else:
            await self.socket.send_bytes(payload)
        self.last_sent_at = time.monotonic()

    async def _drain(self) -> None:
        """Write queued envelopes until cancelled or the socket fails."""
        while True:
            envelope = await self._queue.get()
            if self._closed:
                break
            try:
                await self._write(envelope.payload)
            except Exception:
                # The socket is gone. Stop the writer rather than spinning on a
                # dead connection; the hub notices through `closed` and evicts.
                self._closed = True
                break

    # ── health ───────────────────────────────────────────────────────────

    def is_idle(self, *, now: float | None = None) -> bool:
        """Whether nothing has been written for longer than :attr:`idle_timeout`.

        Distinct from a lifetime TTL on purpose: a connection that is being
        used should not be evicted for having existed a long time, and one that
        has gone quiet should be, however recently it connected.
        """
        if self.idle_timeout is None:
            return False
        moment = time.monotonic() if now is None else now
        return (moment - self.last_sent_at) > self.idle_timeout

    def __repr__(self) -> str:
        state = "closed" if self._closed else f"pending={self.pending}"
        return (
            f"<Peer {str(self.id)[:8]} {self.encoding.value} "
            f"identity={self.identity!r} {state}>"
        )
