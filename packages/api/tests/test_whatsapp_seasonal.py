"""m-24976891 — the seasonal library of stickers and short videos, offline: the standard
batch's shape, planning (idempotent, one job per new row, provenance on every row), the
worker's results (prefix-checked keys), the owner's approve / reject / archive / restore,
and what the chat may send (current season first)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from qualify_api.whatsapp.seasonal import (
    JOB_KIND,
    SEASONAL_PIPELINE_VERSION,
    STANDARD_BATCH,
    MediaNotFound,
    MemorySeasonalRepository,
    MemorySourceReads,
    NothingToMake,
    ObjectKeyRefused,
    SeasonalMediaService,
    SeasonInvalid,
    WrongState,
)

NOW = datetime(2026, 11, 8, 15, 0, tzinfo=UTC)
TENANT = UUID("a0000000-0000-4000-8000-000000976891")
OTHER_TENANT = UUID("b0000000-0000-4000-8000-000000976891")
BRAND = UUID("c0000000-0000-4000-8000-000000976891")
OTHER_BRAND = UUID("c1000000-0000-4000-8000-000000976891")
USER = UUID("e0000000-0000-4000-8000-000000976891")
LOGO = f"t/{TENANT}/brand/{BRAND}/logo.png"


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class World:
    def __init__(self) -> None:
        self.repo = MemorySeasonalRepository()
        self.sources = MemorySourceReads()
        self.clock = Clock()
        self.service = SeasonalMediaService(self.repo, self.sources, clock=self.clock)
        self.pieces = [uuid4() for _ in range(4)]
        self.sources.pieces[(TENANT, BRAND)] = list(self.pieces)
        self.sources.logos[(TENANT, BRAND)] = LOGO

    def plan(self, season: str = "navidad-2026", label: str = "Navidad 2026", mode="free"):
        return self.service.plan_batch(TENANT, BRAND, season, label, mode, USER)

    def ready(self, media):
        ext = "webp" if media.kind == "sticker" else "mp4"
        return self.service.mark_ready(
            tenant_id=TENANT,
            brand_id=BRAND,
            media_id=media.id,
            object_key=f"seasonal/{TENANT}/{BRAND}/{media.season_key}/{media.id}.{ext}",
            bytes=120_000,
            width=512,
            height=512,
            duration_ms=3000,
        )


@pytest.fixture
def world() -> World:
    return World()


def test_the_standard_batch_is_six_stickers_and_four_videos_per_mode() -> None:
    for mode, slots in STANDARD_BATCH.items():
        kinds = [s.kind for s in slots]
        assert (kinds.count("sticker"), kinds.count("video")) == (6, 4), mode
        assert all(s.source_kind in ("piece", "logo", "text") for s in slots)
    assert any(s.recipe == "ai-seedance" for s in STANDARD_BATCH["ai"])
    assert not any(s.recipe.startswith("ai-") for s in STANDARD_BATCH["free"])


def test_planning_makes_pending_rows_with_provenance_and_one_job_each(world: World) -> None:
    rows = world.plan()
    assert len(rows) == 10 and all(r.status == "pending" for r in rows)
    for row in rows:
        assert row.recipe and row.source_kind and row.source_ref
        assert row.pipeline_version == SEASONAL_PIPELINE_VERSION
        assert row.cost_usd == Decimal("0") and row.created_by == USER
    logo_rows = [r for r in rows if r.source_kind == "logo"]
    assert all(r.source_ref == LOGO for r in logo_rows)
    texts = {r.source_ref for r in rows if r.source_kind == "text"}
    assert texts == {"¡Feliz Navidad 2026!", "¡Gracias por tu pedido!"}
    xfade = next(r for r in rows if r.recipe == "b-xfade")
    assert len(xfade.source_ref.split(",")) == 3
    assert len(world.repo.jobs) == 10
    job = world.repo.jobs[0]
    assert job["kind"] == JOB_KIND and job["idempotency_key"] == f"seasonal:{rows[0].id}"
    assert set(job["payload"]) == {
        "media_id",
        "tenant_id",
        "brand_id",
        "kind",
        "recipe",
        "source_kind",
        "source_ref",
        "season_key",
    }


def test_planning_twice_makes_nothing_new(world: World) -> None:
    first = world.plan()
    again = world.plan()
    assert {r.id for r in again} == {r.id for r in first}
    assert len(world.repo.rows) == 10 and len(world.repo.jobs) == 10


def test_missing_sources_skip_their_slots_and_nothing_at_all_is_refused(world: World) -> None:
    world.sources.pieces[(TENANT, BRAND)] = []
    rows = world.plan()
    assert rows and all(r.source_kind != "piece" for r in rows)
    world.sources.logos.clear()
    with pytest.raises(NothingToMake):
        world.plan(season="madres-2027", label="Día de la Madre")


@pytest.mark.parametrize(
    ("season", "label"),
    [("Navidad 2026", "Navidad"), ("navidad-2026", ""), ("x", "Y"), ("navidad-2026", "x" * 25)],
)
def test_a_bad_season_is_refused(world: World, season: str, label: str) -> None:
    with pytest.raises(SeasonInvalid):
        world.plan(season=season, label=label)


def test_the_worker_can_only_store_the_file_where_it_belongs(world: World) -> None:
    sticker = next(r for r in world.plan() if r.kind == "sticker")
    for bad in (
        f"seasonal/{TENANT}/{OTHER_BRAND}/navidad-2026/{sticker.id}.webp",
        f"seasonal/{TENANT}/{BRAND}/madres-2027/{sticker.id}.webp",
        f"seasonal/{TENANT}/{BRAND}/navidad-2026/{sticker.id}.mp4",
        f"t/{TENANT}/generated/{sticker.id}/a.webp",
    ):
        with pytest.raises(ObjectKeyRefused):
            world.service.mark_ready(
                tenant_id=TENANT,
                brand_id=BRAND,
                media_id=sticker.id,
                object_key=bad,
                bytes=1,
                width=1,
                height=1,
                duration_ms=1,
            )
    ready = world.ready(sticker)
    assert ready.status == "ready" and ready.bytes == 120_000
    with pytest.raises(WrongState):
        world.ready(sticker)


def test_a_failure_can_be_retried_by_the_worker(world: World) -> None:
    video = next(r for r in world.plan() if r.kind == "video")
    failed = world.service.mark_failed(
        tenant_id=TENANT, brand_id=BRAND, media_id=video.id, reason="ffmpeg_exit_1"
    )
    assert failed.status == "failed" and failed.fail_reason == "ffmpeg_exit_1"
    assert world.ready(video).status == "ready"


def test_only_ready_media_can_be_approved_and_all_or_nothing(world: World) -> None:
    rows = world.plan()
    ready = world.ready(rows[0])
    with pytest.raises(WrongState):
        world.service.approve(TENANT, BRAND, [ready.id, rows[1].id], USER)  # rows[1] pending
    assert world.repo.rows[ready.id].status == "ready"
    (approved,) = world.service.approve(TENANT, BRAND, [ready.id], USER)
    assert approved.status == "approved" and approved.approved_at == NOW
    rejected = world.service.reject(TENANT, BRAND, approved.id, USER)
    assert rejected.status == "rejected"


def test_another_tenant_or_business_cannot_touch_a_medium(world: World) -> None:
    media = world.plan()[0]
    with pytest.raises(MediaNotFound):
        world.service.mark_failed(
            tenant_id=OTHER_TENANT, brand_id=BRAND, media_id=media.id, reason="x"
        )
    with pytest.raises(MediaNotFound):
        world.service.reject(TENANT, OTHER_BRAND, media.id, USER)
    assert world.service.list_season(OTHER_TENANT, BRAND, "navidad-2026") == []


def test_archive_hides_a_season_from_the_chat_and_restore_brings_it_back(world: World) -> None:
    rows = world.plan()
    for row in rows[:2]:
        world.ready(row)
    world.service.approve(TENANT, BRAND, [rows[0].id, rows[1].id], USER)
    assert len(world.service.list_approved_for_chat(TENANT, BRAND)) == 2
    world.service.archive(TENANT, BRAND, "navidad-2026")
    assert world.service.list_approved_for_chat(TENANT, BRAND) == []
    assert world.repo.rows[rows[0].id].status == "archived"
    assert world.repo.rows[rows[5].id].status == "pending"  # not approved: only stamped
    (season,) = world.service.list_seasons(TENANT, BRAND)
    assert season.archived and season.season_label == "Navidad 2026"
    world.service.restore(TENANT, BRAND, "navidad-2026")
    assert len(world.service.list_approved_for_chat(TENANT, BRAND)) == 2
    with pytest.raises(WrongState):  # an archived season's ready rows cannot be approved
        world.service.archive(TENANT, BRAND, "navidad-2026")
        world.ready(rows[2])
        world.service.approve(TENANT, BRAND, [rows[2].id], USER)


def test_the_chat_gets_the_current_season_first_with_what_its_card_needs(world: World) -> None:
    old = world.plan(season="halloween-2026", label="Halloween")
    world.ready(old[0])
    world.service.approve(TENANT, BRAND, [old[0].id], USER)
    world.clock.now = NOW + timedelta(days=30)
    new = world.plan()
    video = next(r for r in new if r.kind == "video")
    sticker = next(r for r in new if r.kind == "sticker")
    for row in (video, sticker):
        world.ready(row)
    world.service.approve(TENANT, BRAND, [video.id, sticker.id], USER)
    chat = world.service.list_approved_for_chat(TENANT, BRAND)
    assert [m.id for m in chat] == [sticker.id, video.id, old[0].id]
    first = chat[0]
    assert (first.kind, first.season_label, first.bytes, first.width, first.duration_ms) == (
        "sticker",
        "Navidad 2026",
        120_000,
        512,
        3000,
    )
    assert first.object_key.startswith(f"seasonal/{TENANT}/{BRAND}/navidad-2026/")
    assert first.approved_at == NOW + timedelta(days=30)


def test_the_worker_door_is_used_when_asked(world: World) -> None:
    calls: list[tuple[UUID, UUID]] = []

    def reader(tenant_id: UUID, brand_id: UUID):
        calls.append((tenant_id, brand_id))
        return []

    service = SeasonalMediaService(world.repo, world.sources, worker_reader=reader)
    assert service.list_approved_for_chat(TENANT, BRAND, as_worker=True) == []
    assert calls == [(TENANT, BRAND)]
