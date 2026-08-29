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

    async def test_identity_is_set_before_presence_fires(self):
        hub, seen = Hub(), []

        @hub.on_join
        def watch(room, peer):
            seen.append(peer.identity)

        class Known(RoomConsumer):
            async def identify(self, ctx):
                return "ada"

            async def rooms(self, ctx):
                return ["lobby"]

        await Known(hub)(Socket())
        assert seen == ["ada"]

    async def test_no_rooms_by_default(self):
        hub = Hub()
        await RoomConsumer(hub)(Socket())
        assert hub.rooms() == []


class TestHelpers:
    async def test_broadcast_defaults_to_the_first_room(self):
        hub = Hub()
        listener_socket = Socket()

        class Echo(RoomConsumer):
            async def rooms(self, ctx):
                return ["lobby"]

            async def on_message(self, data):
                await self.broadcast(data)

        # A second peer already in the room to receive the echo.
        from sillo.wire import Peer

        listener = Peer(listener_socket)
        await hub.join(listener, "lobby")

        await Echo(hub)(Socket(incoming=["hello"]))
        await drain(listener)
        assert listener_socket.sent == ["hello"]

    async def test_broadcast_with_no_rooms_delivers_nothing(self):
        hub = Hub()
        consumer = RoomConsumer(hub)
        assert (await consumer.broadcast("x")).attempted == 0

    async def test_broadcast_to_a_named_room(self):
        hub = Hub()
        from sillo.wire import Peer

        target = Peer(Socket())
        await hub.join(target, "other")

        class Sender(RoomConsumer):
            async def rooms(self, ctx):
                return ["lobby"]

            async def on_message(self, data):
                await self.broadcast(data, room="other")

        await Sender(hub)(Socket(incoming=["ping"]))
        await drain(target)
        assert target.socket.sent == ["ping"]

    async def test_reply_goes_only_to_this_connection(self):
        hub = Hub()

        class Replier(RoomConsumer):
            async def on_message(self, data):
                await self.reply({"echo": data})

        socket = Socket(incoming=["hi"])
        await Replier(hub)(socket)
        assert socket.sent == [{"echo": "hi"}]

    async def test_reply_before_a_peer_exists_is_a_no_op(self):
        await RoomConsumer(Hub()).reply("x")

    async def test_joining_and_leaving_mid_connection(self):
        hub = Hub()
        recorded = []

        class Mover(RoomConsumer):
            async def rooms(self, ctx):
                return ["lobby"]

            async def on_message(self, data):
                recorded.append(await self.join("extra"))
                recorded.append(await self.join("extra"))
                recorded.append(sorted(self.joined))
                recorded.append(await self.leave("extra"))
                recorded.append(await self.leave("never"))
                recorded.append(sorted(self.joined))

        await Mover(hub)(Socket(incoming=["go"]))
        assert recorded == [True, False, ["extra", "lobby"], True, False, ["lobby"]]


class TestEncodings:
    @pytest.mark.parametrize(
        ("encoding", "message"),
        [
            (Encoding.JSON, {"a": 1}),
            (Encoding.TEXT, "plain"),
            (Encoding.BYTES, b"raw"),
        ],
    )
    async def test_each_encoding_picks_the_matching_iterator(self, encoding, message):
        hub, seen = Hub(), []

        class Typed(RoomConsumer):
            pass

        Typed.encoding = encoding

        class Recording(Typed):
            async def on_message(self, data):
                seen.append(data)

        await Recording(hub)(Socket(incoming=[message]))
        assert seen == [message]

    async def test_queue_settings_reach_the_peer(self):
        hub, seen = Hub(), []

        class Tuned(RoomConsumer):
            capacity = 8

            async def on_connect(self):
                seen.append((self.peer.capacity, self.peer.overflow))

        await Tuned(hub)(Socket())
        assert seen[0][0] == 8
