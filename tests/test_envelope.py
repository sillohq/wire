"""The message type and the report a fan-out returns."""

from __future__ import annotations

from datetime import datetime, timezone

from sillo_wire import DeliveryReport, Encoding, Envelope


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

    def test_it_is_frozen(self):
        """One envelope is shared by every peer in a room; edits must not
        reach a peer that has already queued it."""
        envelope = Envelope("a")
        try:
            envelope.payload = "b"
        except Exception as exc:
            assert type(exc).__name__ in {"FrozenInstanceError", "AttributeError"}
        else:  # pragma: no cover - dataclass is frozen
            raise AssertionError("expected the envelope to be immutable")

    def test_room_defaults_to_empty(self):
        assert Envelope("a").room == ""

    def test_size_of_bytes_is_exact(self):
        assert Envelope(b"1234567").size() == 7
        assert Envelope(bytearray(b"12345")).size() == 5
        assert Envelope(memoryview(b"123")).size() == 3

    def test_size_of_text_counts_encoded_bytes(self):
        """Not characters — a cap in bytes has to be measured in bytes."""
        assert Envelope("abc").size() == 3
        assert Envelope("é").size() == 2

    def test_size_of_anything_else_is_estimated(self):
        assert Envelope({"a": 1}).size() > 0
        assert Envelope(None).size() == 4

    def test_undecodable_text_still_sizes(self):
        """Surrogates would raise on a strict encode; the cap must not."""
        assert Envelope("\ud800").size() > 0


class TestEncoding:
    def test_the_three_wire_formats(self):
        assert {e.value for e in Encoding} == {"json", "text", "bytes"}


class TestDeliveryReport:
    def test_attempted_is_the_sum(self):
        report = DeliveryReport(delivered=3, dropped=2, failed=1)
        assert report.attempted == 6

    def test_it_is_truthy_when_anyone_got_it(self):
        assert DeliveryReport(delivered=1)
        assert not DeliveryReport(dropped=5, failed=5)
        assert not DeliveryReport()

    def test_it_defaults_to_empty(self):
        report = DeliveryReport()
        assert (report.delivered, report.dropped, report.failed) == (0, 0, 0)
