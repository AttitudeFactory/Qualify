"""Offline tests for the inbox composition seam added for the Reflex vertical slice
(`list_candidate_media`/`set_media_monitored`/`sync_comments` — the inbox analogue of
`publishing/composition.py`'s `stage_and_start_publish`/`advance_publish`).

Fully offline: `production_inbox_service_for`/`production_ig_user_id_for` are
monkeypatched to return a real `InboxService` wired to in-memory/fake doubles, same
posture `test_publishing_composition.py` already establishes for its own seam. This file
proves the NEW seam wires `InboxService` correctly (ig_user_id resolved before Meta is
asked, an unknown connection is refused consistently across all three entry points) —
not `InboxService`'s internal logic again (`test_inbox_service.py` already covers that).
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from qualify_shared.social.ig_shapes import COMMENTS_EDGE_PERMISSIONS, IGComment, IGCommentsPage

from qualify_api.inbox import composition
from qualify_api.inbox.composition import InboxConnectionInactive, UnknownInboxConnection
from qualify_api.inbox.media_client import MediaReadError, MediaSummary
from qualify_api.inbox.repository import MemoryInboxRepository
from qualify_api.inbox.service import InboxService, MediaNotEligible, SyncSummary
from qualify_api.inbox.sync_guard import SyncAlreadyRunning, SyncGuard

# `sync_comments` fails closed without a granted scope (QUA-88) — this file's `_wire`
# always grants it, same posture `test_inbox_service.py`'s `GRANTED` establishes; the
# permission gate itself is `InboxService`'s job and is tested there, not re-tested here.
GRANTED = frozenset(COMMENTS_EDGE_PERMISSIONS)

TENANT = UUID("99999999-9999-4999-8999-999999999999")
CONNECTION = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
UNKNOWN_CONNECTION = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
IG_USER = "17840000000000009"
NOW = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)


class FakeCommentsClient:
    """Returns one fixed page per media id — same shape as `test_inbox_service.py`'s
    double, kept local rather than imported (that file's double is not part of any
    package's public surface)."""

    def __init__(self, comments_by_media: dict[str, list[IGComment]] | None = None) -> None:
        self._comments_by_media = comments_by_media or {}

    async def list_comments(self, *, ig_media_id: str, after: str | None = None):
        return IGCommentsPage(data=self._comments_by_media.get(ig_media_id, []))


class FakeMediaClient:
    def __init__(self, media_by_id: dict[str, MediaSummary]) -> None:
        self._media_by_id = media_by_id

    async def list_recent_media(self, *, ig_user_id: str, since: datetime):
        assert ig_user_id == IG_USER
        return tuple(m for m in self._media_by_id.values() if m.timestamp >= since)

    async def get_media(self, *, media_id: str) -> MediaSummary:
        media = self._media_by_id.get(media_id)
        if media is None:
            raise MediaReadError(f"no such media {media_id!r}")
        return media


@pytest.fixture(autouse=True)
def _in_memory_sync_guard(monkeypatch: pytest.MonkeyPatch, fake_async_redis) -> None:
    """`sync_comments` takes a per-connection lease in Redis; offline, that Redis is the
    in-memory one from `conftest.py` (CI's `test` job has none)."""

    @contextlib.asynccontextmanager
    async def _guard():
        yield SyncGuard(fake_async_redis)

    monkeypatch.setattr(composition, "_sync_guard", _guard)


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    media: dict[str, MediaSummary] | None = None,
    comments_by_media: dict[str, list[IGComment]] | None = None,
    status: str = "active",
    built: list[UUID] | None = None,
) -> tuple[InboxService, MemoryInboxRepository]:
    repository = MemoryInboxRepository()
    service = InboxService(
        repository=repository,
        comments_client=FakeCommentsClient(comments_by_media),
        media_client=FakeMediaClient(media or {}),
        granted_scopes=GRANTED,
    )

    def ig_user_id_for(*, tenant_id: UUID, connection_id: UUID) -> str:
        if (tenant_id, connection_id) != (TENANT, CONNECTION):
            raise UnknownInboxConnection(f"connection {connection_id} not visible")
        return IG_USER

    async def service_for(*, tenant_id: UUID, connection_id: UUID) -> InboxService:
        if (tenant_id, connection_id) != (TENANT, CONNECTION):
            raise UnknownInboxConnection(f"connection {connection_id} not visible")
        if built is not None:
            built.append(connection_id)
        return service

    def status_for(*, tenant_id: UUID, connection_id: UUID) -> str:
        if (tenant_id, connection_id) != (TENANT, CONNECTION):
            raise UnknownInboxConnection(f"connection {connection_id} not visible")
        return status

    monkeypatch.setattr(composition, "production_ig_user_id_for", ig_user_id_for)
    monkeypatch.setattr(composition, "production_connection_status_for", status_for)
    monkeypatch.setattr(composition, "production_inbox_service_for", service_for)
    return service, repository


@pytest.mark.asyncio
async def test_list_candidate_media_resolves_ig_user_id_before_calling_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same class of bug already fixed below for `set_media_monitored`:
    # `composition.list_candidate_media` has no `now` passthrough (by design — see its
    # docstring), so `InboxService.list_candidate_media` computes `since` from
    # `datetime.now(UTC)` at call time, not from the fixed module-level `NOW`. A fixture
    # pinned to the fixed `NOW` rots the moment real time drifts `NOW` more than
    # `MONITORING_WINDOW` (14 days) into the past. Anchor to the real clock instead so
    # the fixture stays "recent enough" regardless of when the suite runs.
    _wire(
        monkeypatch,
        media={"A": MediaSummary(id="A", timestamp=datetime.now(UTC), media_product_type="REELS")},
    )

    candidates = await composition.list_candidate_media(tenant_id=TENANT, connection_id=CONNECTION)

    assert [c.external_media_id for c in candidates] == ["A"]


@pytest.mark.asyncio
async def test_list_candidate_media_propagates_unknown_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(monkeypatch)

    with pytest.raises(UnknownInboxConnection):
        await composition.list_candidate_media(tenant_id=TENANT, connection_id=UNKNOWN_CONNECTION)


@pytest.mark.asyncio
async def test_set_media_monitored_delegates_to_the_wired_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `composition.set_media_monitored` has no `now` passthrough (by design — the
    # production seam always re-verifies against the real clock, see its docstring),
    # so `InboxService.set_media_monitored` compares this fixture against
    # `datetime.now(UTC)` at call time, not against the fixed module-level `NOW`. A
    # fixture pinned to `NOW - 1 day` rots the moment real time drifts `NOW` more than
    # `MONITORING_WINDOW` (14 days) into the past — exactly what happened here. Anchor
    # to the real clock instead so "one day old" stays true regardless of when the
    # suite runs.
    _, repository = _wire(
        monkeypatch,
        media={"A": MediaSummary(id="A", timestamp=datetime.now(UTC) - timedelta(days=1))},
    )

    await composition.set_media_monitored(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="A", monitored=True
    )

    assert repository.list_monitored_media_ids(tenant_id=TENANT, connection_id=CONNECTION) == {"A"}


@pytest.mark.asyncio
async def test_set_media_monitored_refuses_an_unknown_connection_before_touching_meta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown connection must fail as `UnknownInboxConnection`, the same exception
    `list_candidate_media` raises for the identical condition — not a different,
    unexported `CredentialNotFound` leaking out of credential resolution."""
    _wire(monkeypatch)

    with pytest.raises(UnknownInboxConnection):
        await composition.set_media_monitored(
            tenant_id=TENANT,
            connection_id=UNKNOWN_CONNECTION,
            external_media_id="A",
            monitored=True,
        )


@pytest.mark.asyncio
async def test_set_media_monitored_propagates_media_not_eligible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(monkeypatch, media={})  # get_media will 404 -> MediaReadError -> MediaNotEligible

    with pytest.raises(MediaNotEligible):
        await composition.set_media_monitored(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            external_media_id="DOES_NOT_EXIST",
            monitored=True,
        )


@pytest.mark.asyncio
async def test_sync_comments_delegates_to_the_wired_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, repository = _wire(
        monkeypatch,
        comments_by_media={"A": [IGComment.model_validate({"id": "c1", "text": "hi"})]},
    )
    repository.set_media_monitored(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="A", monitored=True
    )

    summary = await composition.sync_comments(tenant_id=TENANT, connection_id=CONNECTION)

    assert summary == SyncSummary(media_checked=1, new_comments=1)


@pytest.mark.asyncio
async def test_sync_comments_is_idempotent_through_the_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same guarantee `test_inbox_service.py` already pins on `InboxService` directly —
    proven again here through the seam, since the seam is a new caller of it."""
    _, repository = _wire(
        monkeypatch,
        comments_by_media={"A": [IGComment.model_validate({"id": "c1", "text": "hi"})]},
    )
    repository.set_media_monitored(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="A", monitored=True
    )

    first = await composition.sync_comments(tenant_id=TENANT, connection_id=CONNECTION)
    second = await composition.sync_comments(tenant_id=TENANT, connection_id=CONNECTION)

    assert first.new_comments == 1
    assert second.new_comments == 0


@pytest.mark.asyncio
async def test_sync_comments_propagates_unknown_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same exception, checked the same way (`production_ig_user_id_for` first), as
    `list_candidate_media`/`set_media_monitored` — all three seam functions in this
    module now fail identically for an unknown connection."""
    _wire(monkeypatch)

    with pytest.raises(UnknownInboxConnection):
        await composition.sync_comments(tenant_id=TENANT, connection_id=UNKNOWN_CONNECTION)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["revoked", "degraded", "pending"])
async def test_sync_comments_refuses_a_connection_that_is_not_active(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    """B8: a disconnected (or degraded) account is never read. The refusal comes BEFORE
    the credential-resolved service is built, so no token is decrypted and no Meta call
    is made — `revoke.py` keeps the stored credential, so without this guard a sync of a
    revoked connection would still succeed."""
    built: list[UUID] = []
    _wire(monkeypatch, status=status, built=built)

    with pytest.raises(InboxConnectionInactive) as excinfo:
        await composition.sync_comments(tenant_id=TENANT, connection_id=CONNECTION)

    assert excinfo.value.status == status
    assert built == []


@pytest.mark.asyncio
async def test_sync_comments_of_another_tenant_never_reaches_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The seam takes the tenant from its caller (the session) and nothing else: a
    connection id the tenant cannot see is `UnknownInboxConnection`, never a sync."""
    built: list[UUID] = []
    _wire(monkeypatch, built=built)
    other_tenant = UUID("12121212-1212-4121-8121-121212121212")

    with pytest.raises(UnknownInboxConnection):
        await composition.sync_comments(tenant_id=other_tenant, connection_id=CONNECTION)

    assert built == []


# --- one pass per connection (sync_guard) -----------------------------------------------


@pytest.mark.asyncio
async def test_sync_holds_the_connection_lease_while_it_runs(
    monkeypatch: pytest.MonkeyPatch, fake_async_redis
) -> None:
    seen_during_pass: list[bool] = []
    service, repository = _wire(monkeypatch)
    real_sync = service.sync_comments

    async def observing_sync(**kwargs):
        seen_during_pass.append(
            await SyncGuard(fake_async_redis).is_running(
                tenant_id=TENANT, connection_id=CONNECTION, token="run-1"
            )
        )
        return await real_sync(**kwargs)

    monkeypatch.setattr(service, "sync_comments", observing_sync)

    await composition.sync_comments(tenant_id=TENANT, connection_id=CONNECTION, run_token="run-1")

    assert seen_during_pass == [True]
    guard = SyncGuard(fake_async_redis)
    assert not await guard.is_running(tenant_id=TENANT, connection_id=CONNECTION, token="run-1")
    assert (
        await guard.seconds_since_last_finished(
            tenant_id=TENANT, connection_id=CONNECTION, now=10**12
        )
        is not None
    )


@pytest.mark.asyncio
async def test_a_second_concurrent_sync_is_refused_before_meta(
    monkeypatch: pytest.MonkeyPatch, fake_async_redis
) -> None:
    built: list[UUID] = []
    _wire(monkeypatch, built=built)
    held = await SyncGuard(fake_async_redis).acquire(
        tenant_id=TENANT, connection_id=CONNECTION, token="someone-else"
    )

    with pytest.raises(SyncAlreadyRunning):
        await composition.sync_comments(tenant_id=TENANT, connection_id=CONNECTION)

    assert built == []  # no credential resolved, no Meta call
    await held.release()


@pytest.mark.asyncio
async def test_the_lease_is_released_when_the_pass_fails(
    monkeypatch: pytest.MonkeyPatch, fake_async_redis
) -> None:
    service, _ = _wire(monkeypatch)

    async def failing_sync(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "sync_comments", failing_sync)

    with pytest.raises(RuntimeError):
        await composition.sync_comments(
            tenant_id=TENANT, connection_id=CONNECTION, run_token="run-1"
        )

    assert not await SyncGuard(fake_async_redis).is_running(
        tenant_id=TENANT, connection_id=CONNECTION, token="run-1"
    )


@pytest.mark.asyncio
async def test_an_unreachable_lock_store_does_not_block_reading_comments(
    monkeypatch: pytest.MonkeyPatch, fake_async_redis
) -> None:
    """Idempotent pass + UNIQUE dedup: without Redis the pass still runs, unguarded."""
    _, repository = _wire(
        monkeypatch,
        comments_by_media={"A": [IGComment.model_validate({"id": "c1", "text": "hi"})]},
    )
    repository.set_media_monitored(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="A", monitored=True
    )
    fake_async_redis.fail_with = ConnectionError("redis down")

    summary = await composition.sync_comments(tenant_id=TENANT, connection_id=CONNECTION)

    assert summary.new_comments == 1


@pytest.mark.asyncio
async def test_liveness_is_conservative_when_the_lock_store_is_unreachable(
    fake_async_redis,
) -> None:
    """Unknown must never read as "dead": a pass that may still run is never reclaimed."""
    fake_async_redis.fail_with = ConnectionError("redis down")

    assert await composition.sync_in_progress(
        tenant_id=TENANT, connection_id=CONNECTION, token="run-1"
    )
    assert (
        await composition.seconds_since_last_sync(tenant_id=TENANT, connection_id=CONNECTION)
        is None
    )
