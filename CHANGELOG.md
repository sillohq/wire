# Changelog

## Unreleased

### Removed

- **The `sillo.wire` import alias.** `sillo_wire` is now the only import path:

  ```python
  from sillo_wire import Hub, Peer     # was: from sillo.wire import ...
  ```

  The alias was a meta-path finder registered by a `.pth` at interpreter
  startup, plus PEP 561 stubs under `sillo-stubs/` to serve type checkers,
  which never run import hooks. It read as part of the framework, but it cost a
  `.pth` executing on every interpreter start in every environment the package
  was installed in, a second set of stubs to keep in step with the real
  package, and a name that static analysis only resolved because a second set
  of files said so. A plain top-level package needs none of that.

  `_sillo_wire_bootstrap.py`, `sillo_wire.pth` and `sillo-stubs/` are gone, and
  so are the `force-include` blocks that shipped them. Inline types in
  `sillo_wire` are now the single source of truth for type checkers.

## 0.1.0.dev1

Development pre-release for testing. Install with
`pip install --pre sillo-wire==0.1.0.dev1`.

First cut. Extracted from `sillo.websockets.channels` and rebuilt around
three things the original could not do.

### Added

- `Hub` — rooms, membership and fan-out as an object rather than class methods
  over a process-global dict. Two hubs are independent, which is what makes
  tests and multi-tenancy straightforward.
- `Peer` — a connection with a bounded outbound queue and its own writer task.
- `Overflow` — `DROP_OLDEST`, `DROP_NEWEST` or `CLOSE` when a queue fills.
- `DeliveryReport` — what a fan-out actually did, per peer.
- `Envelope` — an immutable message carrying a monotonic sequence.
- `Backlog` protocol, with `MemoryBacklog` and `NullBacklog`.
- `Hub.replay` — send a reconnecting client only what it missed.
- `Hub.send_to` — reach every connection an identity has open.
- Presence: `on_join` / `on_leave` listeners, and `identities()` as a roster.
- `RoomConsumer` — class-based endpoint with guaranteed cleanup.
- `Hub.close` empties its rooms before awaiting anything and closes every peer
  concurrently, so shutdown is not paced by the slowest socket.
- `sillo.wire.testing` — `FakeSocket` and `drain` for testing realtime code.
- Importable as both `sillo.wire` and `sillo_wire`. The alias is a
  meta-path finder registered by a `.pth`, with PEP 561 partial stubs for
  type checkers; nothing is written into the framework's own package.

### Fixed, relative to the code this replaces

- **A broadcast no longer blocks on the slowest client.** The previous fan-out
  awaited each socket in turn, so one client that had stopped reading stalled
  every other member of the group.
- **The history cap now measures messages.** It previously sized the *list
  object* with `sys.getsizeof`, so a 1 MB cap retained around 128 MB, and on
  tripping discarded the entire history rather than the oldest part of it.
- **Expiry distinguishes idle from lifetime.** Sending reset the creation time,
  so a documented TTL behaved as an idle timeout without saying so.
