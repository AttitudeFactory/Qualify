"""Offline tests for the inbox composition seam added for the Reflex vertical slice
(`list_candidate_media`/`set_media_monitored` — the inbox analogue of
`publishing/composition.py`'s `stage_and_start_publish`/`advance_publish`).

Fully offline: `production_inbox_service_for`/`production_ig_user_id_for` are
monkeypatched to return a real `InboxService` wired to in-memory/fake doubles, same
posture `test_publishing_composition.py` already establishes for its own seam. This file
proves the NEW seam wires `InboxService` correctly (ig_user_id resolved before Meta is
asked, an unknown connection is refused consistently by both entry points) — not
`InboxService`'s internal logic again (`test_inbox_service.py` already covers that).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from qualify_api.inbox import composition
from qualify_api.inbox.composition import UnknownInboxConnection
from qualify_api.inbox.media_client import MediaReadError, MediaSummary
from qualify_api.inbox.repository import MemoryInboxRepository
from qualify_api.inbox.service import InboxService, MediaNotEligible

TENANT = UUID("99999999-9999-4999-8999-999999999999")
CONNECTION = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
UNKNOWN_CONNECTION = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
IG_USER = "17840000000000009"
NOW = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)


class FakeCommentsClient:
    async def list_comments(self, *, ig_media_id: str, after: str | None = None):
        raise AssertionError("this slice never calls sync_comments")


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
    monkeypatch: pytest.MonkeyPatch, *, media: dict[str, MediaSummary] | None = None
) -> tuple[InboxService, MemoryInboxRepository]:
    repository = MemoryInboxRepository()
    service = InboxService(
        repository=repository,
        comments_client=FakeCommentsClient(),
        media_client=FakeMediaClient(media or {}),
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
