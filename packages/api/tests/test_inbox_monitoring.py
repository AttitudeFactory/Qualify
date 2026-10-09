"""QUA-149: the 14-day monitoring rule (`qualify_api.inbox.monitoring`) and the in-memory
half of the repository that applies it. Offline — the Postgres half is exercised by the
`db`-marked tests in `test_inbox_repository.py`, against the same expectations."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from qualify_api.inbox import service as inbox_service
from qualify_api.inbox.models import MonitoredMedia
from qualify_api.inbox.monitoring import (
    MONITORING_WINDOW,
    MediaMetadata,
    MetadataFetchError,
    MonitoringState,
    effective_state,
    is_within_window,
    window_start,
)
from qualify_api.inbox.repository import MemoryInboxRepository

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
TENANT = uuid4()
CONNECTION = uuid4()


def _metadata(posted_at: datetime, caption: str | None = "a caption") -> MediaMetadata:
    return MediaMetadata(
        posted_at=posted_at,
        caption=caption,
        permalink="https://www.instagram.com/reel/x/",
        media_product_type="REELS",
    )


# --- the rule --------------------------------------------------------------------------


def test_the_window_is_fourteen_days() -> None:
    assert MONITORING_WINDOW == timedelta(days=14)
    assert window_start(NOW) == NOW - timedelta(days=14)


def test_the_service_reads_the_same_window_constant() -> None:
    """One definition: `service.MONITORING_WINDOW` is the shared object, not a copy."""
    assert inbox_service.MONITORING_WINDOW is MONITORING_WINDOW


def test_the_exact_boundary_is_still_inside_the_window() -> None:
    assert is_within_window(NOW - MONITORING_WINDOW, NOW)


def test_one_microsecond_past_the_boundary_is_outside() -> None:
    assert not is_within_window(NOW - MONITORING_WINDOW - timedelta(microseconds=1), NOW)


def test_a_fresh_media_is_inside() -> None:
    assert is_within_window(NOW - timedelta(days=1), NOW)


def test_effective_state_monitored_inside_the_window_is_active() -> None:
    state = effective_state(is_monitored=True, posted_at=NOW - timedelta(days=13), now=NOW)
    assert state is MonitoringState.ACTIVE


def test_effective_state_monitored_past_the_window_is_expired() -> None:
    state = effective_state(is_monitored=True, posted_at=NOW - timedelta(days=15), now=NOW)
    assert state is MonitoringState.EXPIRED


def test_effective_state_not_monitored_is_inactive_whatever_the_date() -> None:
    for posted_at in (None, NOW - timedelta(days=1), NOW - timedelta(days=30)):
        state = effective_state(is_monitored=False, posted_at=posted_at, now=NOW)
        assert state is MonitoringState.INACTIVE


def test_effective_state_unknown_date_is_active_because_it_is_still_synced() -> None:
    """A legacy row (monitored before 0046) is still synced until its date is read once,
    so the state must say so — never `EXPIRED` on a guess."""
    assert effective_state(is_monitored=True, posted_at=None, now=NOW) is MonitoringState.ACTIVE


def test_a_naive_now_is_refused() -> None:
    """Compared against `timestamptz`, a naive `now` would be read in the session's time
    zone and shift the window by hours — refused instead."""
    with pytest.raises(ValueError):
        window_start(datetime(2026, 10, 9, 12, 0))


def test_metadata_without_an_aware_publication_date_is_refused() -> None:
    with pytest.raises(ValueError):
        MediaMetadata(posted_at=datetime(2026, 10, 9, 12, 0))
    with pytest.raises(ValueError):
        MediaMetadata(posted_at=None)  # type: ignore[arg-type]


def _migration_0046():
    path = (
        Path(__file__).resolve().parents[3]
        / "migrations"
        / "postgres"
        / "versions"
        / "0046_monitored_media_metadata.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0046", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_metadata_error_values_agree_across_enum_migration_and_model() -> None:
    """The enum, the migration's CHECK and the ORM's CHECK spell the same four values —
    a value added to one only would be refused by Postgres at runtime."""
    enum_values = {e.value for e in MetadataFetchError}
    assert set(_migration_0046().METADATA_ERRORS) == enum_values
    model_check = next(
        str(c.sqltext)
        for c in MonitoredMedia.__table__.constraints
        if c.name == "ck_monitored_media_metadata_error"
    )
    for value in enum_values:
        assert f"'{value}'" in model_check


# --- MemoryInboxRepository -------------------------------------------------------------


def test_turning_on_with_metadata_stores_it_as_complete() -> None:
    repo = MemoryInboxRepository()
    repo.set_media_monitored(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id="m-1",
        monitored=True,
        metadata=_metadata(NOW - timedelta(days=2)),
        fetched_at=NOW,
    )

    row = repo.get_monitored_media(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="m-1"
    )
    assert row is not None
    assert row.is_monitored
    assert row.media_posted_at == NOW - timedelta(days=2)
    assert row.caption == "a caption"
    assert row.permalink == "https://www.instagram.com/reel/x/"
    assert row.media_product_type == "REELS"
    assert row.metadata_fetched_at == NOW
    assert row.metadata_error is None
    assert row.state(NOW) is MonitoringState.ACTIVE


def test_turning_off_keeps_the_metadata() -> None:
    repo = MemoryInboxRepository()
    repo.set_media_monitored(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id="m-1",
        monitored=True,
        metadata=_metadata(NOW - timedelta(days=2)),
        fetched_at=NOW,
    )
    repo.set_media_monitored(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="m-1", monitored=False
    )

    row = repo.get_monitored_media(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="m-1"
    )
    assert row is not None
    assert not row.is_monitored
    assert row.caption == "a caption"
    assert row.media_posted_at == NOW - timedelta(days=2)
    assert row.state(NOW) is MonitoringState.INACTIVE


def test_list_media_to_sync_never_returns_an_expired_media() -> None:
    repo = MemoryInboxRepository()
    for media_id, age_days in (("active", 3), ("expired", 20)):
        repo.set_media_monitored(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            external_media_id=media_id,
            monitored=True,
            metadata=_metadata(NOW - timedelta(days=age_days)),
            fetched_at=NOW,
        )

    to_sync = repo.list_media_to_sync(tenant_id=TENANT, connection_id=CONNECTION, now=NOW)

    assert [m.external_media_id for m in to_sync] == ["active"]
    assert not to_sync[0].needs_metadata
    # Expired is still known, still readable — only no longer synced.
    expired = repo.get_monitored_media(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="expired"
    )
    assert expired is not None and expired.state(NOW) is MonitoringState.EXPIRED


def test_list_media_to_sync_includes_a_legacy_row_flagged_for_metadata() -> None:
    repo = MemoryInboxRepository()
    repo.set_media_monitored(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="legacy", monitored=True
    )

    to_sync = repo.list_media_to_sync(tenant_id=TENANT, connection_id=CONNECTION, now=NOW)

    assert [(m.external_media_id, m.needs_metadata) for m in to_sync] == [("legacy", True)]


def test_list_media_to_sync_skips_monitoring_off_and_other_connections() -> None:
    repo = MemoryInboxRepository()
    other_connection = uuid4()
    repo.set_media_monitored(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="off", monitored=False
    )
    repo.set_media_monitored(
        tenant_id=TENANT, connection_id=other_connection, external_media_id="other", monitored=True
    )

    assert repo.list_media_to_sync(tenant_id=TENANT, connection_id=CONNECTION, now=NOW) == ()


def test_list_media_to_sync_is_ordered_by_media_id() -> None:
    repo = MemoryInboxRepository()
    for media_id in ("m-3", "m-1", "m-2"):
        repo.set_media_monitored(
            tenant_id=TENANT, connection_id=CONNECTION, external_media_id=media_id, monitored=True
        )

    to_sync = repo.list_media_to_sync(tenant_id=TENANT, connection_id=CONNECTION, now=NOW)

    assert [m.external_media_id for m in to_sync] == ["m-1", "m-2", "m-3"]


def test_a_failed_metadata_read_is_recorded_without_touching_anything_else() -> None:
    repo = MemoryInboxRepository()
    repo.set_media_monitored(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="legacy", monitored=True
    )

    repo.record_media_metadata_failure(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id="legacy",
        error=MetadataFetchError.RATE_LIMITED,
        attempted_at=NOW,
    )

    row = repo.get_monitored_media(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="legacy"
    )
    assert row is not None
    assert row.is_monitored  # a failure never turns monitoring off
    assert row.metadata_fetched_at is None
    assert row.metadata_error is MetadataFetchError.RATE_LIMITED
    assert row.metadata_attempted_at == NOW
    to_sync = repo.list_media_to_sync(tenant_id=TENANT, connection_id=CONNECTION, now=NOW)
    assert to_sync[0].needs_metadata
    assert to_sync[0].metadata_error is MetadataFetchError.RATE_LIMITED


def test_a_failure_after_a_success_keeps_the_stored_metadata() -> None:
    repo = MemoryInboxRepository()
    repo.set_media_monitored(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id="m-1",
        monitored=True,
        metadata=_metadata(NOW - timedelta(days=2)),
        fetched_at=NOW,
    )

    repo.record_media_metadata_failure(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id="m-1",
        error=MetadataFetchError.TRANSIENT,
        attempted_at=NOW + timedelta(hours=1),
    )

    row = repo.get_monitored_media(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="m-1"
    )
    assert row is not None
    assert row.caption == "a caption"
    assert row.metadata_fetched_at == NOW


def test_backfill_completes_a_legacy_row_and_clears_the_failure() -> None:
    repo = MemoryInboxRepository()
    repo.set_media_monitored(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="legacy", monitored=True
    )
    repo.record_media_metadata_failure(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id="legacy",
        error=MetadataFetchError.TRANSIENT,
        attempted_at=NOW,
    )

    repo.record_media_metadata(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id="legacy",
        metadata=_metadata(NOW - timedelta(days=30), caption=None),
        fetched_at=NOW + timedelta(minutes=5),
    )

    row = repo.get_monitored_media(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="legacy"
    )
    assert row is not None
    assert row.is_monitored
    assert row.caption is None  # no caption on Instagram is a real, complete answer
    assert row.metadata_fetched_at == NOW + timedelta(minutes=5)
    assert row.metadata_error is None
    assert row.state(NOW) is MonitoringState.EXPIRED
    # Now known to be expired: no longer offered to the sync.
    assert repo.list_media_to_sync(tenant_id=TENANT, connection_id=CONNECTION, now=NOW) == ()


def test_metadata_writes_on_a_missing_row_are_no_ops() -> None:
    repo = MemoryInboxRepository()
    repo.record_media_metadata(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id="ghost",
        metadata=_metadata(NOW),
        fetched_at=NOW,
    )
    repo.record_media_metadata_failure(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id="ghost",
        error=MetadataFetchError.UNKNOWN,
        attempted_at=NOW,
    )

    assert (
        repo.get_monitored_media(
            tenant_id=TENANT, connection_id=CONNECTION, external_media_id="ghost"
        )
        is None
    )
