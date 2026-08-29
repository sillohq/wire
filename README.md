# sillo-wire

Rooms, presence and fan-out for [Sillo](https://sillo.build) WebSockets.

```bash
pip install sillo-wire
```

Installs as `sillo-wire`, imports as `sillo.wire`.

```python
from sillo import SilloApp
from sillo.wire import Hub, Peer

app = SilloApp()
hub = Hub()

@app.ws_route("/ws/room/{name}")
async def room(socket, name: str):
    await socket.accept()
    peer = Peer(socket, identity=socket.query_params.get("user"))
    await hub.join(peer, name)
    try:
        async for message in socket.iter_json():
            await hub.broadcast(name, message)
    finally:
        await hub.disconnect(peer)
```

## Why this exists

Three things differ from the obvious implementation, and they are the whole
point of the package.

**A broadcast never blocks.** Writing straight to each socket in turn means the
slowest member of a room sets the pace for everyone else — a client that has
stopped reading fills its kernel buffer, the write blocks, and the rest of the
room waits behind it. Here every peer has a bounded queue and a writer task, so
a broadcast only ever enqueues:

```python
report = await hub.broadcast("lobby", {"msg": "hello"})
report.delivered   # 41
report.dropped     #  2   queues were full
report.failed      #  1   socket was already gone
```

You get a `DeliveryReport` rather than nothing, because a fan-out you cannot
measure is a fan-out you cannot operate.

**Nothing is global.** A `Hub` is an ordinary object. Two of them are two
independent worlds, so tests get a fresh one per case instead of remembering to
flush shared state, and a multi-tenant application keeps traffic apart without
a naming convention.

**History is replayable.** Every envelope carries a monotonic sequence, so a
client that reconnects asks for what it missed rather than for everything or
for nothing:

```python
await hub.replay(peer, "lobby", since=last_seq_the_client_saw)
```

## Slow consumers

When a peer's queue fills, what happens is a choice, not a default:

```python
from sillo.wire import Overflow, Peer

Peer(socket, overflow=Overflow.DROP_OLDEST)   # keep current — prices, cursors
Peer(socket, overflow=Overflow.DROP_NEWEST)   # keep order — reconcile later
Peer(socket, overflow=Overflow.CLOSE)         # disconnect and let it reconnect
```

## Presence

```python
@hub.on_join
async def joined(room, peer):
    await hub.broadcast(room, {"event": "joined", "who": peer.identity})

hub.identities("lobby")   # ["ada", "bob"] — people, not sockets
hub.count("lobby")        # 5 — subscriptions
```

Two peers can share an identity — the same person with a phone and two tabs —
and `send_to` reaches all of them:

```python
await hub.send_to("ada", {"notice": "your export is ready"})
```

## Consumers

`RoomConsumer` is the class-based form. It accepts the socket, builds the peer,
joins the rooms, pumps messages, and guarantees the peer is removed from every
room when the connection ends — including when a hook raises.

```python
from sillo.wire import Hub, RoomConsumer

hub = Hub()

class Chat(RoomConsumer):
    hub = hub

    async def identify(self, ctx):
        return ctx.query_params.get("user")

    async def rooms(self, ctx):
        return [ctx.path_params["room"]]

    async def on_message(self, data):
        await self.broadcast({"from": self.peer.identity, "text": data})

app.add_ws_route(path="/ws/{room}", handler=Chat.as_handler())
```

## Backlog

Retention is per room and capped by payload bytes, evicting oldest first:

```python
from sillo.wire import Hub, MemoryBacklog, NullBacklog

Hub(backlog=MemoryBacklog(capacity_bytes=4 * 1024 * 1024))
Hub(backlog=NullBacklog())    # keep nothing — typing indicators, telemetry
```

`Backlog` is a `Protocol`, so a Redis or Postgres store satisfies it without
importing anything from here.
