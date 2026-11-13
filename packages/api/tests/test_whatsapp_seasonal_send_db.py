"""m-24976894 against the compose Postgres: the outbox sender's re-check reads the
library row as `qualify_app` under `tenant_session` (the whatsapp-worker's door — no
webhook-worker grant involved), sees the current attempt and status, and another
tenant's sender cannot see the row at all."""

from __future__ import annotations

from uuid import uuid4

import pytest
from packages.api.tests.test_creative_retention_db import TENANT_A, TENANT_B, _provision

from qualify_api.whatsapp.seasonal import (
    MemorySourceReads,
    PostgresSeasonalRepository,
    SeasonalMediaService,
)
from qualify_api.whatsapp.seasonal_send import SeasonalSendGuard

pytestmark = pytest.mark.db


def _guard(repo: PostgresSeasonalRepository) -> SeasonalSendGuard:
    def never(*_: object) -> bytes:
        raise AssertionError("no file read in this test")

    return SeasonalSendGuard(lambda t, m: repo.get(tenant_id=t, media_id=m), never)


def test_the_sender_door_reads_the_current_state_and_only_its_tenant() -> None:
    brand, user, _ = _provision(TENANT_A, "A")
    repo = PostgresSeasonalRepository()
    sources = MemorySourceReads()
    sources.logos[(TENANT_A, brand)] = f"t/{TENANT_A}/brand/{brand}/logo.png"
    library = SeasonalMediaService(repo, sources)
    season = f"navidad-{uuid4().hex[:6]}"
    media = next(
        m
        for m in library.plan_batch(TENANT_A, brand, season, "Navidad", "free", user)
        if m.kind == "sticker"
    )
    key = f"seasonal/{TENANT_A}/{brand}/{season}/{media.id}-1.webp"
    library.mark_ready(
        tenant_id=TENANT_A,
        brand_id=brand,
        media_id=media.id,
        attempt=1,
        object_key=key,
        bytes=10,
        width=512,
        height=512,
        duration_ms=None,
    )
    library.approve(TENANT_A, brand, [media.id], user)
    attachment = {
        "seasonal_media_id": str(media.id),
        "attempt": 1,
        "object_key": key,
        "brand_id": str(brand),
    }
    guard = _guard(repo)
    assert guard.refusal(TENANT_A, attachment) is None
    assert guard.refusal(TENANT_B, attachment) == "attachment_refused"
    library.archive(TENANT_A, brand, season)
    assert guard.refusal(TENANT_A, attachment) == "seasonal_withdrawn"
