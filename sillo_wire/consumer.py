"""A class-based endpoint with the room plumbing already wired.

:class:`RoomConsumer` is the ergonomic layer over :class:`~sillo_wire.hub.Hub`
and :class:`~sillo_wire.peer.Peer`: it accepts the socket, builds the peer,
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

from sillo_wire.envelope import DeliveryReport, Encoding
from sillo_wire.hub import Hub
from sillo_wire.peer import Peer
from sillo_wire.policy import Overflow

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

    # ── registration ─────────────────────────────────────────────────────

    @classmethod
    def as_handler(cls, hub: Hub | None = None) -> typing.Callable[..., typing.Any]:
        """Build the coroutine to hand to ``@app.ws_route``.

        Path parameters arrive as keyword arguments, exactly as on an HTTP
        route, and are forwarded to :meth:`rooms` through the context rather
        than to the hooks — the hooks have a fixed shape so subclasses do not
        each have to declare them.
        """

        async def handler(ctx: typing.Any, **params: typing.Any) -> None:
            await cls(hub)(ctx)

        return handler

    # ── the loop ─────────────────────────────────────────────────────────

    async def __call__(self, ctx: typing.Any) -> None:
        """Run one connection to completion."""
        self.ctx = ctx
        await ctx.accept()

        self.peer = Peer(
            ctx,
            encoding=self.encoding,
            identity=await self.identify(ctx),
            capacity=self.capacity,
            overflow=self.overflow,
        )

        try:
            for room in await self.rooms(ctx):
                await self._hub.join(self.peer, room)
                self.joined.append(room)

            await self.on_connect()
            await self._pump()
        finally:
            # Runs on a clean close, a client disconnect, and an exception in a
            # hook alike. Leaving a peer subscribed after its socket is gone is
            # the leak this exists to prevent.
            await self.on_disconnect()
            await self._hub.disconnect(self.peer)

    async def _pump(self) -> None:
        """Read from the socket until it closes, dispatching each message."""
        iterator = {
            Encoding.JSON: "iter_json",
            Encoding.TEXT: "iter_text",
            Encoding.BYTES: "iter_bytes",
        }[self.encoding]

        async for message in getattr(self.ctx, iterator)():
            await self.on_message(message)

    # ── helpers ──────────────────────────────────────────────────────────

    async def broadcast(
        self, payload: typing.Any, room: str | None = None
    ) -> DeliveryReport:
        """Send *payload* to *room*, defaulting to the first room joined."""
        target = room if room is not None else (self.joined[0] if self.joined else None)
        if target is None:
            return DeliveryReport()
        return await self._hub.broadcast(target, payload)

    async def reply(self, payload: typing.Any) -> None:
        """Send *payload* to this connection alone."""
        if self.peer is not None:
            await self.peer.send(payload)

    async def join(self, room: str) -> bool:
        """Subscribe this connection to another room."""
        if self.peer is None:  # pragma: no cover - unreachable inside __call__
            return False
        added = await self._hub.join(self.peer, room)
        if added:
            self.joined.append(room)
        return added

    async def leave(self, room: str) -> bool:
        """Unsubscribe this connection from *room*."""
        if self.peer is None:  # pragma: no cover - unreachable inside __call__
            return False
        removed = await self._hub.leave(self.peer, room)
        if removed and room in self.joined:
            self.joined.remove(room)
        return removed

    # ── hooks ────────────────────────────────────────────────────────────

    async def identify(self, ctx: typing.Any) -> typing.Any:
        """Who this connection belongs to. ``None`` means anonymous.

        Called once, before any room is joined, so the identity is already set
        when presence listeners fire.
        """
        return None

    async def rooms(self, ctx: typing.Any) -> list[str]:
        """Which rooms to join on connect. Defaults to none."""
        return []

    async def on_connect(self) -> None:
        """Called once the peer is in its rooms."""

    async def on_message(self, data: typing.Any) -> None:
        """Called for each message received. Override this."""

    async def on_disconnect(self) -> None:
        """Called once as the connection ends, before the peer is removed."""
