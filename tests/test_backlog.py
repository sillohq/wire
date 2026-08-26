"""Retention, eviction and the replay cursor."""

from __future__ import annotations

import pytest

from sillo.wire import Envelope, MemoryBacklog, NullBacklog


class TestMemoryBacklog:
    def test_capacity_must_be_positive(self):
        with pytest.raises(ValueError, match="at least 1"):
            MemoryBacklog(capacity_bytes=0)

    async def test_it_keeps_what_it_is_given(self):
        backlog = MemoryBacklog()
        await backlog.append(Envelope("a", room="r"))
        await backlog.append(Envelope("b", room="r"))
        assert [e.payload for e in await backlog.latest("r")] == ["a", "b"]

    async def test_the_cap_counts_payload_bytes(self):
        """The bug this replaces sized the *list object*, so a 1 KB cap held
        128 KB of messages."""
        backlog = MemoryBacklog(capacity_bytes=1000)
        for _ in range(50):
            await backlog.append(Envelope("x" * 100, room="r"))
        assert backlog.usage("r") <= 1000
        assert len(await backlog.latest("r", limit=999)) == 10
