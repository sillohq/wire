"""A class-based endpoint with the room plumbing already wired.

:class:`RoomConsumer` is the ergonomic layer over :class:`~sillo.wire.hub.Hub`
and :class:`~sillo.wire.peer.Peer`: it accepts the socket, builds the peer,
joins the rooms, pumps messages into :meth:`~RoomConsumer.on_message`, and
guarantees the peer is removed from every room when the connection ends —
including when the handler raises.

Subclass it and override the hooks you need::

    class Chat(RoomConsumer):
        hub = my_hub

        async def rooms(self, ctx):
            return [ctx.path_params["room"]]

        async def on_message(self, data):
            await self.broadcast(data)
"""

from __future__ import annotations

import typing

from sillo.wire.envelope import DeliveryReport, Encoding
from sillo.wire.hub import Hub
from sillo.wire.peer import Peer
from sillo.wire.policy import Overflow

__all__ = ["RoomConsumer"]


class RoomConsumer:
    """One connection's lifecycle, from accept to cleanup.

    A fresh instance is created per connection, so ``self`` is a safe place to
    keep per-connection state — unlike the hub, which is shared.
    """

    #: The hub this consumer joins rooms on. Override per subclass, or pass one
    #: to :meth:`as_handler`.
    hub: typing.ClassVar[Hub | None] = None

    #: How payloads are written, and which ``iter_*`` the read loop uses.
    encoding: typing.ClassVar[Encoding] = Encoding.JSON

    #: Outbound queue depth per connection.
    capacity: typing.ClassVar[int] = 64

    #: What happens when a connection cannot keep up.
    overflow: typing.ClassVar[Overflow] = Overflow.DROP_OLDEST

    def __init__(self, hub: Hub | None = None) -> None:
        resolved = hub if hub is not None else self.hub
        if resolved is None:
            raise ValueError(
                f"{type(self).__name__} has no hub: set `hub` on the class or "
                f"pass one to as_handler()"
            )
        self._hub: Hub = resolved
        self.peer: Peer | None = None
        self.ctx: typing.Any = None
        self.joined: list[str] = []
