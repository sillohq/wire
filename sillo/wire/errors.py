"""Exceptions raised by :mod:`sillo.wire`.

All of them derive from :class:`WireError`, so an application that wants to
treat "the realtime layer failed" as one case can catch that and nothing else.
"""

from __future__ import annotations

__all__ = ["PeerGone", "RoomNotFound", "WireError"]


class WireError(Exception):
    """Base class for every error this package raises."""
