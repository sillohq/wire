"""The class-based endpoint, and the cleanup it guarantees."""

from __future__ import annotations

import pytest

from sillo.wire import Encoding, Hub, RoomConsumer
from sillo.wire.testing import FakeSocket, drain


class Socket(FakeSocket):
    """A FakeSocket that can also be read from."""

    def __init__(self, incoming=(), **kwargs):
        super().__init__(**kwargs)
        self.incoming = list(incoming)
        self.accepted = False
        self.path_params: dict = {}

    async def accept(self):
        self.accepted = True

    async def _iterate(self):
        for message in self.incoming:
            yield message

    def iter_json(self):
        return self._iterate()

    def iter_text(self):
        return self._iterate()

    def iter_bytes(self):
        return self._iterate()


class TestWiring:
    async def test_a_hub_is_required(self):
        with pytest.raises(ValueError, match="no hub"):
            RoomConsumer()

    async def test_the_class_attribute_is_used(self):
        hub = Hub()

        class Fixed(RoomConsumer):
            pass

        Fixed.hub = hub
        assert Fixed()._hub is hub

    async def test_an_explicit_hub_wins(self):
        class Anything(RoomConsumer):
            hub = Hub()

        mine = Hub()
        assert Anything(mine)._hub is mine

    async def test_as_handler_runs_a_fresh_instance(self):
        hub, seen = Hub(), []

        class Counting(RoomConsumer):
            async def on_connect(self):
                seen.append(self)

        handler = Counting.as_handler(hub)
        await handler(Socket())
        await handler(Socket())
        assert len(seen) == 2 and seen[0] is not seen[1]

    async def test_path_params_are_accepted_and_not_forwarded(self):
        """The hooks have a fixed shape, so a subclass reads params off the
        context rather than declaring them."""
        hub = Hub()
        handler = RoomConsumer.as_handler(hub)
        await handler(Socket(), room="lobby")


class TestLifecycle:
    async def test_it_accepts_joins_and_cleans_up(self):
        hub = Hub()
        events = []

        class Chat(RoomConsumer):
            async def rooms(self, ctx):
                return ["lobby"]

            async def on_connect(self):
                events.append("connect")

            async def on_message(self, data):
                events.append(("message", data))

            async def on_disconnect(self):
                events.append("disconnect")

        socket = Socket(incoming=[{"n": 1}, {"n": 2}])
        await Chat(hub)(socket)

        assert socket.accepted
        assert events == [
            "connect",
            ("message", {"n": 1}),
            ("message", {"n": 2}),
            "disconnect",
        ]
        assert hub.rooms() == []

    async def test_the_peer_is_removed_even_when_a_hook_raises(self):
        """Leaving a peer subscribed after its socket is gone is the leak
        this exists to prevent."""
        hub = Hub()

        class Exploding(RoomConsumer):
            async def rooms(self, ctx):
                return ["lobby"]

            async def on_message(self, data):
                raise RuntimeError("handler blew up")

        with pytest.raises(RuntimeError, match="blew up"):
            await Exploding(hub)(Socket(incoming=["boom"]))

        assert hub.rooms() == []
