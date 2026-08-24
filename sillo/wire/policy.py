"""What to do when a peer cannot keep up.

A socket that is not being read drains into the kernel's send buffer, and once
that fills, a write blocks. In a fan-out that turns one slow client into a
stall for everybody behind it, so every peer gets a bounded queue and a policy
for what happens when the queue is full.
"""

from __future__ import annotations

import enum

__all__ = ["Overflow"]


class Overflow(enum.Enum):
    """What a peer does with a message it has no room for.

    There is no good universal answer, only a choice about which property
    matters more for the traffic in question.
    """

    DROP_OLDEST = "drop_oldest"
    """Discard the queued message at the front and enqueue the new one.

    Right for state that supersedes itself — a price tick, a cursor position, a
    progress percentage. The client sees a gap but always sees *current*.
    """

    DROP_NEWEST = "drop_newest"
    """Discard the message being sent and keep the queue as it is.

    Right when order matters more than recency and the client will reconcile
    from the backlog later.
    """

    CLOSE = "close"
    """Disconnect the peer.

    Right when a client that cannot keep up is a client that is broken, and
    letting it reconnect is cheaper than reasoning about what it missed.
    """
