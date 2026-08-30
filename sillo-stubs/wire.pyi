"""Type stubs for ``sillo.wire``.

The runtime alias is installed by ``_sillo_wire_bootstrap`` via a ``.pth``, and
a type checker never runs import hooks — so without this file
``from sillo.wire import Hub`` type-checks as a missing module even though it
imports fine.

``py.typed`` next to this file contains the word ``partial`` (PEP 561), which
is what keeps these stubs additive: a checker uses them for ``sillo.wire`` and
falls back to the framework's own inline types for the rest of ``sillo``.
Without it, this directory would claim to describe all of ``sillo`` and hide
the types the framework ships.

Nothing is declared here. Everything is re-exported from ``sillo_wire``, whose
inline annotations are the single source of truth.
"""

from sillo_wire import Backlog as Backlog
from sillo_wire import DeliveryReport as DeliveryReport
from sillo_wire import Encoding as Encoding
from sillo_wire import Envelope as Envelope
from sillo_wire import Hub as Hub
from sillo_wire import MemoryBacklog as MemoryBacklog
from sillo_wire import NullBacklog as NullBacklog
from sillo_wire import Overflow as Overflow
from sillo_wire import Peer as Peer
from sillo_wire import PeerGone as PeerGone
from sillo_wire import RoomConsumer as RoomConsumer
from sillo_wire import RoomNotFound as RoomNotFound
from sillo_wire import WireError as WireError

__version__: str

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
]
