"""Helpers for testing code that uses :mod:`sillo.wire`.

Realtime code is awkward to test because the interesting behaviour is what a
*socket* received, and a socket is the one thing a unit test does not have.
:class:`FakeSocket` is that missing piece: it satisfies everything
:class:`~sillo.wire.peer.Peer` calls and records what it was given.

Nothing here is imported by the package itself, so it costs an application
nothing at run time.
"""

from __future__ import annotations

import asyncio
import typing

from sillo.wire.peer import Peer

__all__ = ["FakeSocket", "drain"]


class FakeSocket:
    """A stand-in for a WebSocket connection that records what it was sent.

    Args:
        delay: Seconds to sleep on each write. Non-zero simulates a client that
            is slow to read, which is the case worth testing and the hardest to
            reproduce with a real socket.
        fail: Raise on every write, simulating a connection that has gone away.
    """

    __slots__ = ("closed", "delay", "fail", "sent")

    def __init__(self, *, delay: float = 0.0, fail: bool = False) -> None:
        self.sent: list[typing.Any] = []
        self.delay = delay
        self.fail = fail
        self.closed = False

    async def _record(self, payload: typing.Any) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise ConnectionResetError("fake socket is closed")
        self.sent.append(payload)

    async def send_json(self, payload: typing.Any) -> None:
        """Record a JSON payload."""
        await self._record(payload)

    async def send_text(self, payload: str) -> None:
        """Record a text payload."""
        await self._record(payload)

    async def send_bytes(self, payload: bytes) -> None:
        """Record a bytes payload."""
        await self._record(payload)

    async def close(self, code: int = 1000) -> None:
        """Mark the socket closed."""
        self.closed = True

    async def accept(self) -> None:
        """Accept the connection."""
