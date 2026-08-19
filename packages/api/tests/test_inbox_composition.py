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

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from qualify_shared.social.ig_shapes import COMMENTS_EDGE_PERMISSIONS, IGComment, IGCommentsPage

from qualify_api.inbox import composition
from qualify_api.inbox.composition import UnknownInboxConnection
from qualify_api.inbox.media_client import MediaReadError, MediaSummary
from qualify_api.inbox.repository import MemoryInboxRepository
from qualify_api.inbox.service import InboxService, MediaNotEligible, SyncSummary

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


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    media: dict[str, MediaSummary] | None = None,
    comments_by_media: dict[str, list[IGComment]] | None = None,
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
        return service

    monkeypatch.setattr(composition, "production_ig_user_id_for", ig_user_id_for)
    monkeypatch.setattr(composition, "production_inbox_service_for", service_for)
    return service, repository


@pytest.mark.asyncio
async def test_list_candidate_media_resolves_ig_user_id_before_calling_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(
        monkeypatch,
        media={"A": MediaSummary(id="A", timestamp=NOW, media_product_type="REELS")},
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
    _, repository = _wire(
        monkeypatch,
        media={"A": MediaSummary(id="A", timestamp=NOW - timedelta(days=1))},
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
