"""Exceptions raised by :mod:`sillo.wire`.

All of them derive from :class:`WireError`, so an application that wants to
treat "the realtime layer failed" as one case can catch that and nothing else.
"""

from __future__ import annotations

__all__ = ["PeerGone", "RoomNotFound", "WireError"]


class WireError(Exception):
    """Base class for every error this package raises."""


class PeerGone(WireError):
    """A peer's socket is closed, or closed while being written to.

    Raised only by the explicit single-peer sends. A broadcast never raises
    this — one dead subscriber is an ordinary event in a fan-out, and is
    reported through :class:`~sillo.wire.envelope.DeliveryReport` instead.
    """
