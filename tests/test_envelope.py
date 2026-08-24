"""The message type and the report a fan-out returns."""

from __future__ import annotations

from datetime import datetime, timezone

from sillo.wire import DeliveryReport, Encoding, Envelope


class TestEnvelope:
    def test_sequences_are_monotonic(self):
        """A replay cursor is only meaningful if sequences never go backwards."""
        first, second, third = Envelope("a"), Envelope("b"), Envelope("c")
        assert first.seq < second.seq < third.seq

    def test_each_envelope_gets_its_own_timestamp(self):
        """A shared default would stamp every message with the import time."""
        one, two = Envelope("a"), Envelope("b")
        assert one.sent_at != two.sent_at or one.seq != two.seq
        assert one.sent_at.tzinfo is timezone.utc
        assert isinstance(one.sent_at, datetime)
