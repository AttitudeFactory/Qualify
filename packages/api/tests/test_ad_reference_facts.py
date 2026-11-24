"""Reference facts cutoff (m-25091393): nothing is recorded without a valid date."""

from datetime import UTC, datetime
from uuid import uuid4

from qualify_api.ads import reference_facts


def test_cutoff_parses_dates_and_refuses_empty_or_invalid(monkeypatch):
    monkeypatch.delenv(reference_facts.CUTOFF_ENV, raising=False)
    assert reference_facts.cutoff() is None
    for raw in ("", "  ", "mañana", "2026-13-01"):
        monkeypatch.setenv(reference_facts.CUTOFF_ENV, raw)
        assert reference_facts.cutoff() is None
    monkeypatch.setenv(reference_facts.CUTOFF_ENV, "2026-12-01")
    assert reference_facts.cutoff() == datetime(2026, 12, 1, tzinfo=UTC)
    monkeypatch.setenv(reference_facts.CUTOFF_ENV, "2026-12-01T05:00:00-05:00")
    assert reference_facts.cutoff() == datetime(2026, 12, 1, 10, tzinfo=UTC)


def test_without_cutoff_no_database_is_touched(monkeypatch):
    monkeypatch.delenv(reference_facts.CUTOFF_ENV, raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("no session without a cutoff")

    monkeypatch.setattr(reference_facts, "tenant_session", forbidden)
    assert reference_facts.record_reference_facts(tenant_id=uuid4()) == 0
