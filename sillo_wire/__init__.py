"""Rooms, presence and fan-out for Sillo WebSockets.

Install as ``sillo-wire``; import as ``sillo_wire``::

    from sillo import SilloApp
    from sillo_wire import Hub, Peer

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

Three things differ from a naive implementation, and they are the reason this
package exists:

* **A broadcast never blocks.** Peers have bounded queues and a writer each, so
  one client that has stopped reading cannot stall the room behind it.
* **Nothing is global.** A :class:`Hub` is an object. Two of them are two
  independent worlds, which is what makes tests and multi-tenancy simple.
* **History is replayable.** Envelopes carry a monotonic sequence, so a client
  that reconnects asks for what it missed rather than for everything.
"""

from sillo_wire.backlog import Backlog, MemoryBacklog, NullBacklog
from sillo_wire.consumer import RoomConsumer
from sillo_wire.envelope import DeliveryReport, Encoding, Envelope
from sillo_wire.errors import PeerGone, RoomNotFound, WireError
from sillo_wire.hub import Hub
from sillo_wire.peer import Peer
from sillo_wire.policy import Overflow

__version__ = "0.1.0"

__all__ = [
    "Backlog",
    "DeliveryReport",
    "Encoding",
    "Envelope",
    "Hub",
    "MemoryBacklog",
    "NullBacklog",
    "Overflow",
    "Peer",
    "PeerGone",
    "RoomConsumer",
    "RoomNotFound",
    "WireError",
    "__version__",
]
