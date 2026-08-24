"""The message type and the report a fan-out returns."""

from __future__ import annotations

from datetime import datetime, timezone

from sillo.wire import DeliveryReport, Encoding, Envelope


class TestEnvelope:
    def test_sequences_are_monotonic(self):
        """A replay cursor is only meaningful if sequences never go backwards."""
        first, second, third = Envelope("a"), Envelope("b"), Envelope("c")
        assert first.seq < second.seq < third.seq
