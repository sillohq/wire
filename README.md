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
