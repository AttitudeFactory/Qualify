"""m-24976891 — the seasonal library of stickers and short videos, offline: the standard
batch's shape, planning (idempotent, one job per new row, provenance on every row), the
worker's results (prefix-checked keys), the owner's approve / reject / archive / restore,
and what the chat may send (current season first)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from qualify_api.whatsapp.seasonal import (
    JOB_KIND,
    MAX_ATTEMPTS,
    SEASONAL_PIPELINE_VERSION,
    STANDARD_BATCH,
    STATUS_DELETED,
    AttemptsExhausted,
    MediaNotFound,
    MemorySeasonalRepository,
    MemorySourceReads,
    ModeNotAvailable,
    NothingToMake,
    ObjectKeyRefused,
    SeasonalMediaService,
    SeasonInvalid,
    StaleAttempt,
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
        self.deleted: list[tuple[UUID, UUID, list[str]]] = []
        self.service = SeasonalMediaService(
            self.repo,
            self.sources,
            clock=self.clock,
            delete_objects=lambda t, b, keys: self.deleted.append((t, b, keys)),
        )
        self.pieces = [uuid4() for _ in range(4)]
        self.sources.pieces[(TENANT, BRAND)] = list(self.pieces)
        self.sources.logos[(TENANT, BRAND)] = LOGO

    def plan(self, season: str = "navidad-2026", label: str = "Navidad 2026", mode="free"):
        return self.service.plan_batch(TENANT, BRAND, season, label, mode, USER)

    def key(self, media, attempt: int | None = None) -> str:
        ext = "webp" if media.kind == "sticker" else "mp4"
        n = attempt or self.repo.rows[media.id].attempt
        return f"seasonal/{TENANT}/{BRAND}/{media.season_key}/{media.id}-{n}.{ext}"

    def ready(self, media, attempt: int | None = None):
        n = attempt or self.repo.rows[media.id].attempt
        return self.service.mark_ready(
            tenant_id=TENANT,
            brand_id=BRAND,
            media_id=media.id,
            attempt=n,
            object_key=self.key(media, n),
            bytes=120_000,
            width=512,
            height=512,
            duration_ms=3000,
        )


@pytest.fixture
def world() -> World:
    return World()


def test_the_standard_batch_is_six_stickers_and_four_videos_per_mode() -> None:
    kinds = [s.kind for s in STANDARD_BATCH["free"]]
    assert (kinds.count("sticker"), kinds.count("video")) == (6, 4)
    for slots in STANDARD_BATCH.values():
        assert all(s.source_kind in ("piece", "logo", "text") for s in slots)
    # m-24976893: «Con IA» makes only videos, one approved photo each
    assert [s.recipe for s in STANDARD_BATCH["ai"]] == ["ai-seedance"] * 3
    assert all(s.kind == "video" and s.pieces == 1 for s in STANDARD_BATCH["ai"])
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
    assert job["kind"] == JOB_KIND and job["idempotency_key"] == f"seasonal:{rows[0].id}:1"
    assert set(job["payload"]) == {
        "media_id",
        "tenant_id",
        "brand_id",
        "kind",
        "recipe",
        "source_kind",
        "source_ref",
        "season_key",
        "attempt",
    }
    assert job["payload"]["attempt"] == 1


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
        f"seasonal/{TENANT}/{BRAND}/navidad-2026/{sticker.id}-1.mp4",
        f"seasonal/{TENANT}/{BRAND}/navidad-2026/{sticker.id}.webp",  # no attempt
        f"seasonal/{TENANT}/{BRAND}/navidad-2026/{sticker.id}-2.webp",  # not this attempt
        f"t/{TENANT}/generated/{sticker.id}/a.webp",
    ):
        with pytest.raises(ObjectKeyRefused):
            world.service.mark_ready(
                tenant_id=TENANT,
                brand_id=BRAND,
                media_id=sticker.id,
                attempt=1,
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
        tenant_id=TENANT, brand_id=BRAND, media_id=video.id, attempt=1, reason="ffmpeg_exit_1"
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
            tenant_id=OTHER_TENANT, brand_id=BRAND, media_id=media.id, attempt=1, reason="x"
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


def test_asking_for_another_reuses_the_row_with_a_new_job_and_a_new_key(world: World) -> None:
    sticker = next(r for r in world.plan() if r.kind == "sticker")
    first = world.ready(sticker)
    world.service.reject(TENANT, BRAND, sticker.id, USER)
    again = world.service.request_another(TENANT, BRAND, sticker.id, USER)
    assert again.id == sticker.id and again.attempt == 2 and again.status == "pending"
    assert (again.object_key, again.bytes, again.width, again.duration_ms) == (None,) * 4
    assert len(world.repo.rows) == 10  # the slot is still one row
    job = world.repo.jobs[-1]
    assert len(world.repo.jobs) == 11
    assert job["idempotency_key"] == f"seasonal:{sticker.id}:2"
    assert job["payload"]["attempt"] == 2
    assert world.deleted == [(TENANT, BRAND, [first.object_key])]
    second = world.ready(sticker)
    assert second.object_key == world.key(sticker, 2) != first.object_key
    # a failure can be asked again too; a pending or approved one cannot
    with pytest.raises(WrongState):
        world.service.request_another(TENANT, BRAND, rows_pending(world).id, USER)
    world.service.approve(TENANT, BRAND, [sticker.id], USER)
    with pytest.raises(WrongState):
        world.service.request_another(TENANT, BRAND, sticker.id, USER)


def rows_pending(world: World):
    return next(r for r in world.repo.rows.values() if r.status == "pending")


def test_a_late_result_of_an_earlier_attempt_is_refused(world: World) -> None:
    video = next(r for r in world.plan() if r.kind == "video")
    world.service.mark_failed(
        tenant_id=TENANT, brand_id=BRAND, media_id=video.id, attempt=1, reason="timeout"
    )
    world.service.request_another(TENANT, BRAND, video.id, USER)
    assert world.deleted == []  # a failure has no file to delete
    with pytest.raises(StaleAttempt):
        world.ready(video, attempt=1)
    with pytest.raises(StaleAttempt):
        world.service.mark_failed(
            tenant_id=TENANT, brand_id=BRAND, media_id=video.id, attempt=1, reason="late"
        )
    assert world.repo.rows[video.id].status == "pending"
    assert world.ready(video).attempt == 2


def test_another_has_no_owner_facing_cap_and_deletes_each_old_file(world: World) -> None:
    """m-25016851: the founder hit «Ya pediste otro tres veces»; «Pedir otro» goes on, and
    every new attempt deletes the previous file (no pile of files in R2)."""
    sticker = next(r for r in world.plan() if r.kind == "sticker")
    world.ready(sticker)
    for n in range(2, 8):
        before = world.repo.rows[sticker.id].object_key
        assert world.service.request_another(TENANT, BRAND, sticker.id, USER).attempt == n
        assert world.deleted[-1] == (TENANT, BRAND, [before])
        assert world.ready(sticker).object_key == world.key(sticker, n)
    assert len(world.deleted) == 6
    assert len({job["idempotency_key"] for job in world.repo.jobs}) == len(world.repo.jobs)


def test_another_stops_only_at_the_technical_ceiling_without_a_count(world: World) -> None:
    sticker = next(r for r in world.plan() if r.kind == "sticker")
    world.repo.rows[sticker.id] = replace(world.repo.rows[sticker.id], attempt=MAX_ATTEMPTS)
    world.ready(sticker)
    with pytest.raises(AttemptsExhausted) as refused:
        world.service.request_another(TENANT, BRAND, sticker.id, USER)
    assert MAX_ATTEMPTS == 99
    assert not any(ch.isdigit() for ch in refused.value.message)  # never a count
    assert "Elimínala" in refused.value.message
    assert world.repo.rows[sticker.id].status == "ready"


# --- «Eliminar» (m-25016851) -------------------------------------------------------------


def test_delete_keeps_the_row_for_provenance_clears_the_file_and_sweeps_every_attempt(
    world: World,
) -> None:
    sticker = next(r for r in world.plan() if r.kind == "sticker")
    world.ready(sticker)
    world.service.request_another(TENANT, BRAND, sticker.id, USER)
    world.ready(sticker)
    world.service.approve(TENANT, BRAND, [sticker.id], USER)
    world.deleted.clear()
    gone = world.service.delete(TENANT, BRAND, sticker.id, USER)
    assert gone.status == STATUS_DELETED and gone.attempt == 2
    assert (gone.object_key, gone.bytes, gone.width, gone.duration_ms) == (None,) * 4
    stored = world.repo.rows[sticker.id]  # provenance stays
    assert stored.recipe and stored.source_kind and stored.source_ref
    assert stored.pipeline_version == SEASONAL_PIPELINE_VERSION
    assert world.deleted == [(TENANT, BRAND, [world.key(sticker, 1), world.key(sticker, 2)])]
    # it leaves the library and the chat
    season = world.service.list_season(TENANT, BRAND, "navidad-2026")
    assert sticker.id not in {m.id for m in season}
    assert sticker.id not in {m.id for m in world.service.list_approved_for_chat(TENANT, BRAND)}
    counts = world.service.list_seasons(TENANT, BRAND)[0].counts
    assert STATUS_DELETED not in counts and sum(counts.values()) == 9
    # nothing else can be done with it
    for act in (
        lambda: world.service.approve(TENANT, BRAND, [sticker.id], USER),
        lambda: world.service.reject(TENANT, BRAND, sticker.id, USER),
        lambda: world.service.request_another(TENANT, BRAND, sticker.id, USER),
    ):
        with pytest.raises(WrongState):
            act()
    # planning the season again does not bring it back (the slot stays taken)
    jobs = len(world.repo.jobs)
    world.plan()
    assert world.repo.rows[sticker.id].status == STATUS_DELETED and len(world.repo.jobs) == jobs


def test_delete_is_idempotent_and_works_from_any_status(world: World) -> None:
    rows = world.plan()
    pending, failed = rows[0], rows[1]
    world.service.mark_failed(
        tenant_id=TENANT, brand_id=BRAND, media_id=failed.id, attempt=1, reason="x"
    )
    for media in (pending, failed):
        assert world.service.delete(TENANT, BRAND, media.id, USER).status == STATUS_DELETED
        again = world.service.delete(TENANT, BRAND, media.id, USER)
        assert again.status == STATUS_DELETED
    with pytest.raises(MediaNotFound):
        world.service.delete(TENANT, OTHER_BRAND, pending.id, USER)
    with pytest.raises(MediaNotFound):
        world.service.delete(OTHER_TENANT, BRAND, pending.id, USER)


def test_a_job_finishing_after_delete_is_refused_and_archive_skips_deleted(world: World) -> None:
    rows = world.plan()
    video = next(r for r in rows if r.kind == "video")
    world.service.delete(TENANT, BRAND, video.id, USER)
    with pytest.raises(WrongState):  # the job drops its result and deletes its file
        world.ready(video)
    with pytest.raises(WrongState):
        world.service.mark_failed(
            tenant_id=TENANT, brand_id=BRAND, media_id=video.id, attempt=1, reason="late"
        )
    world.service.archive(TENANT, BRAND, "navidad-2026")
    world.service.restore(TENANT, BRAND, "navidad-2026")
    assert world.repo.rows[video.id].status == STATUS_DELETED
    assert world.repo.rows[video.id].archived_at is None


def test_a_failed_file_delete_does_not_undo_the_delete(world: World) -> None:
    def boom(*_args) -> None:
        raise RuntimeError("r2 down")

    service = SeasonalMediaService(world.repo, world.sources, delete_objects=boom)
    sticker = next(r for r in world.plan() if r.kind == "sticker")
    world.ready(sticker)
    assert service.delete(TENANT, BRAND, sticker.id, USER).status == STATUS_DELETED


def test_a_season_with_everything_deleted_is_gone(world: World) -> None:
    for media in world.plan():
        world.service.delete(TENANT, BRAND, media.id, USER)
    assert world.service.list_seasons(TENANT, BRAND) == []


def test_a_failed_delete_of_the_old_file_does_not_undo_the_request(world: World) -> None:
    def boom(*_args) -> None:
        raise RuntimeError("r2 down")

    service = SeasonalMediaService(world.repo, world.sources, delete_objects=boom)
    sticker = next(r for r in world.plan() if r.kind == "sticker")
    world.ready(sticker)
    assert service.request_another(TENANT, BRAND, sticker.id, USER).attempt == 2


def test_a_stale_copy_never_overwrites_a_newer_attempt_or_state(world: World) -> None:
    sticker = next(r for r in world.plan() if r.kind == "sticker")
    world.ready(sticker)
    stale = world.repo.rows[sticker.id]  # what a slow approve / mark_ready read
    world.service.reject(TENANT, BRAND, sticker.id, USER)
    world.service.request_another(TENANT, BRAND, sticker.id, USER)
    with pytest.raises(StaleAttempt):
        world.repo.save(replace(stale, status="approved"), expected=stale)
    current = world.repo.rows[sticker.id]
    assert (current.attempt, current.status) == (2, "pending")
    world.ready(sticker)
    ready = world.repo.rows[sticker.id]
    world.service.archive(TENANT, BRAND, sticker.season_key)
    with pytest.raises(WrongState):  # archived meanwhile: the old copy is not approved
        world.repo.save(replace(ready, status="approved"), expected=ready)


def test_the_ai_mode_says_soon_until_its_recipes_ship(world: World) -> None:
    with pytest.raises(ModeNotAvailable) as refused:
        world.plan(mode="ai")
    assert refused.value.message.startswith("Pronto")
    assert world.repo.rows == {} and world.repo.jobs == []
    on = SeasonalMediaService(
        world.repo,
        world.sources,
        ai_mode=True,
        ai_video_estimate_usd=lambda: Decimal("0.0486"),
    )
    rows = on.plan_batch(
        TENANT,
        BRAND,
        "navidad-2026",
        "Navidad",
        "ai",
        USER,
        accepted_total_usd=Decimal("0.15"),
        accepted_draft_ids=[p.draft_id for p in on.quote_batch(TENANT, BRAND, "ai").photos],
    )
    assert rows and all(r.recipe == "ai-seedance" and r.kind == "video" for r in rows)


def test_a_multi_item_approval_is_all_or_nothing_against_a_concurrent_change(
    world: World,
) -> None:
    stickers = [r for r in world.plan() if r.kind == "sticker"][:3]
    for sticker in stickers:
        world.ready(sticker)
    real_get = world.repo.get
    calls = {"n": 0}

    def get_then_change(*, tenant_id, media_id):  # the third row changes after the read
        found = real_get(tenant_id=tenant_id, media_id=media_id)
        calls["n"] += 1
        if calls["n"] == 3:
            world.repo.rows[media_id] = replace(found, status="rejected")
        return found

    world.repo.get = get_then_change  # type: ignore[method-assign]
    with pytest.raises(WrongState):
        world.service.approve(TENANT, BRAND, [s.id for s in stickers], USER)
    world.repo.get = real_get  # type: ignore[method-assign]
    assert [world.repo.rows[s.id].status for s in stickers] == ["ready", "ready", "rejected"]
