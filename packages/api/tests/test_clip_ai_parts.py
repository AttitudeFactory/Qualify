"""m-25129406 (ADR 50 §13, PR 2 «crear»): a Clip with «parte con IA» blocks, created.

The Clip and one child `CLIP` per AI block (a `media.part`, as a video by parts' child)
are born together; the children are made, the Clip WAITS for them (`ClipBlocksWait`, with
its sign of life) and is assembled ONCE from a brief with their videos as stretches.
Every rule refuses before anything is written and before any paid call; the same
`request_key` makes one Clip; the automatic assembly writes no charge row, so it never
counts in the day's 10 local builds.

Offline only: no BytePlus, Seedance or Claude is ever called — the copy vendor is a
double, the database a set of dicts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.schemas import (
    CLIP_MODE_OF_PART,
    ContentBrief,
    MediaInputs,
    PartRef,
    SourceSegment,
    VideoPartPlan,
    VideoTextLayer,
    ai_part_key,
)

from qualify_api.creative import clip_ai_parts as cap
from qualify_api.creative import clip_avatar as ca
from qualify_api.creative.creations import InMemoryCreationsLedger, NotEnoughCreations
from qualify_api.creative.fsm import DRAFTING, FAILED, GENERATED
from qualify_api.creative.local_cap import LocalDailyCapReached
from qualify_api.creative.media import _key_problems
from qualify_api.creative.part_extend import EXTEND_SWITCH
from qualify_api.creative.parts import PartsExtendUnavailable
from qualify_api.creative.service import ContentService, check_part_link
from qualify_api.creative.video_pipeline import local
from qualify_api.creative.video_pipeline.ai_parts import (
    CLIP_AI_PARTS_SWITCH,
    CLIP_EXTEND_OWN_VIDEO_SWITCH,
    ai_part_slots,
)
from qualify_api.creative.video_pipeline.recipe import RecipeRefused

from . import test_video_pipeline_local as _local_tests
from .test_clip_avatar import (
    OWN_VIDEO,
    BlockRepo,
    _assemble,
    _piece,
    _video_with_sound_bytes,
    assembly_files,
)
from .test_content_service import (
    BRAND_ID,
    TENANT_ID,
    USER_ID,
    FakeBrand,
    FakePricing,
    FakeRouter,
    FakeVoice,
    RecordingDispatcher,
    StaticKeyResolver,
    copy_dict,
    make_brief,
    make_kit,
    make_voice,
    ok_outcome,
)

queue_on = _local_tests.queue_on
__all__ = ["assembly_files", "queue_on"]  # fixtures used by name below

OTHER = f"uploads/{TENANT_ID}/otro.mp4"


@pytest.fixture(autouse=True)
def _switches(queue_on: None, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: PT004
    """The creative queue on, as production; the AI parts switch on (each test that
    needs it off says so)."""
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "on")
    monkeypatch.delenv(CLIP_EXTEND_OWN_VIDEO_SWITCH, raising=False)


# ---------------------------------------------------------------------------
# doubles


class PartsRepo(BlockRepo):
    """`BlockRepo` that counts the day's local builds as Postgres does (one charge row of
    kind `local_video` per draft and revision)."""

    ledger: InMemoryCreationsLedger | None = None
    cap_counting = True

    def local_builds_today(self, *, tenant_id: UUID) -> int:
        if self.ledger is None or not self.cap_counting:
            return 0
        return sum(
            1 for row in self.ledger.rows.values() if row.price.request_kind == "local_video"
        )


class PartsStore:
    """`AiPartsStore` read off a `PartsRepo` (what the Postgres store reads)."""

    def __init__(self, repo: PartsRepo) -> None:
        self.repo = repo
        self.videos: dict[UUID, cap.AiPartVideo] = {}
        self.settled: dict[UUID, datetime] = {}
        self.reads = 0

    def parts_of(self, *, tenant_id: UUID, clip_id: UUID) -> tuple[cap.AiPartRow, ...]:
        self.reads += 1
        rows = []
        for draft_id, (parent, slot) in self.repo.parents.items():
            brief = self.repo.briefs[self.repo.drafts[draft_id].brief_id]
            if parent != clip_id or brief.media.part is None:
                continue
            draft = self.repo.drafts[draft_id]
            rows.append(
                cap.AiPartRow(
                    id=draft_id,
                    slot=slot,
                    status=draft.status,
                    failure_reason=draft.failure_reason,
                    settled_at=self.settled.get(draft_id),
                )
            )
        return tuple(sorted(rows, key=lambda row: row.slot))

    def part_video(self, *, tenant_id: UUID, part_id: UUID) -> cap.AiPartVideo | None:
        return self.videos.get(part_id)


@dataclass
class World:
    service: cap.ClipAiPartsService
    content: ContentService
    repo: PartsRepo
    store: PartsStore
    dispatcher: RecordingDispatcher
    ledger: InMemoryCreationsLedger | None
    beats: list[tuple[UUID, UUID]]
    clock: list[datetime]


def _world(*, quota: bool = True, videos_used: int = 0, previews_used: int = 0) -> World:
    repo, dispatcher = PartsRepo(), RecordingDispatcher()
    store = PartsStore(repo)
    ledger = (
        InMemoryCreationsLedger(videos_used=videos_used, previews_used=previews_used)
        if quota
        else None
    )
    repo.ledger = ledger
    beats: list[tuple[UUID, UUID]] = []
    clock = [datetime(2026, 11, 27, 12, 0, tzinfo=UTC)]
    content = ContentService(
        router=FakeRouter([ok_outcome(copy_dict()) for _ in range(8)]),  # type: ignore[arg-type]
        pricing=FakePricing(),
        credentials=StaticKeyResolver(),
        voice_service=FakeVoice(make_voice()),
        brand_service=FakeBrand(make_kit()),
        repository=repo,
        dispatcher=dispatcher,
        creations=ledger,
        progress=lambda tenant, draft: beats.append((tenant, draft)),
        clip_ai_parts_store=store,
        clip_avatar_clock=lambda: clock[0],
        clip_avatar_sources=lambda tenant, keys: {},
    )
    service = cap.ClipAiPartsService(content, parts_store=store, store=object(), env={})
    return World(service, content, repo, store, dispatcher, ledger, beats, clock)


def _own(seconds: float = 4.0, key: str = OWN_VIDEO, **over: Any) -> SourceSegment:
    return SourceSegment(key=key, start_s=0, end_s=seconds, speed=over.pop("speed", 1), **over)


def _block(n: int, seconds: int = 5, **over: Any) -> SourceSegment:
    return SourceSegment(kind="ai_part", key=ai_part_key(n), start_s=0, end_s=seconds, **over)


def _entry(seconds: int = 5, **over: Any) -> VideoPartPlan:
    return VideoPartPlan(
        **{"mode": "reference", "seconds": seconds, "description": "Una arepa en la plancha"} | over
    )


def _clip(
    segments: tuple[SourceSegment, ...] | None = None,
    entries: tuple[VideoPartPlan, ...] | None = None,
    **media: Any,
) -> ContentBrief:
    """A local Clip: own video, an AI part, own video, an AI part (by default)."""
    if segments is None:
        segments = (_own(4.0), _block(1), _own(3.0, OTHER), _block(0, 4))
    if entries is None:
        entries = (_entry(4), _entry(5))
    return make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(
            duration_seconds=5,
            clip_reference_mode="local",
            segments=segments,
            ai_parts=entries,
            effects_pipeline_version=local.LOCAL_EFFECTS_PIPELINE_VERSION,
            **media,
        ),
    )


def _create(world: World, brief: ContentBrief | None = None, **kw: Any) -> cap.ClipWithAiParts:
    return world.service.create_clip_with_ai_parts(
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        user_id=USER_ID,
        brief=brief or _clip(),
        **kw,
    )


def _nothing_written(world: World) -> None:
    assert world.repo.drafts == {} and world.dispatcher.calls == []
    assert world.ledger is None or world.ledger.rows == {}


def _brief_of(world: World, draft_id: UUID) -> ContentBrief:
    return world.repo.briefs[world.repo.drafts[draft_id].brief_id]


def _made(world: World, part_id: UUID, seconds: float = 5.0, **params: Any) -> str:
    """The part came out: `generated`, its video kept (asset params as the producer
    writes them: its `part` meta)."""
    key = f"t/{TENANT_ID}/generated/{part_id}/r1/video.mp4"
    world.repo.drafts[part_id] = replace(world.repo.drafts[part_id], status=GENERATED)
    part = _brief_of(world, part_id).media.part
    assert part is not None
    meta = {
        "seconds": part.seconds,
        "generation_seconds": part.generation_seconds,
        "mode": part.mode,
        **params,
    }
    world.store.videos[part_id] = cap.AiPartVideo(
        asset_id=uuid4(),
        object_key=key,
        seconds=seconds,
        params={"duration_seconds": seconds, "part": meta},
    )
    return key


# ---------------------------------------------------------------------------
# creating: the Clip and its parts, born together


def test_a_clip_and_its_ai_parts_are_born_together_in_timeline_order() -> None:
    world = _world()
    made = _create(world)
    clip = world.repo.drafts[made.clip_id]
    assert clip.status == DRAFTING and clip.parent_draft_id is None
    assert len(made.part_ids) == 2
    # the child's place is its block's order on the timeline: ai_parts[1] comes first
    first, second = made.part_ids
    assert world.repo.parents[first] == (made.clip_id, 1)
    assert world.repo.parents[second] == (made.clip_id, 2)
    one, two = _brief_of(world, first), _brief_of(world, second)
    for child, slot, seconds in ((one, 1, 5), (two, 2, 4)):
        assert child.kind is ContentKind.CLIP and child.format is ContentFormat.REELS_9_16
        assert child.media.part is not None and child.media.part.index == slot
        assert child.media.part.seconds == seconds and child.media.part.mode == "reference"
        # never the Clip's AI plan, nor its timeline, texts or effects
        assert child.media.ai_parts == () and child.media.segments == ()
        assert child.media.clip_reference_mode == CLIP_MODE_OF_PART["reference"]
    # the Clip keeps its blocks as the owner made them
    assert _brief_of(world, made.clip_id).media.ai_parts == _clip().media.ai_parts
    # the parts are dispatched first, then the Clip that waits for them
    assert [d for _, d in world.dispatcher.calls] == [*made.part_ids, made.clip_id]


def test_check_part_link_takes_a_clip_as_the_parent() -> None:
    """§13.2: the child is the same child of today — under a Clip it passes as under a
    video by parts, and a part is still never loose."""
    world = _world()
    made = _create(world)
    child = _brief_of(world, made.part_ids[0])
    check_part_link(child, made.clip_id, 1)
    with pytest.raises(ValueError, match="part_index"):
        check_part_link(child, made.clip_id, 2)
    with pytest.raises(ValueError, match="parent"):
        check_part_link(child, None, None)


def test_one_vista_previa_per_part_and_the_clips_own_price_all_or_nothing() -> None:
    world = _world()
    made = _create(world)
    assert world.ledger is not None
    rows = {draft: row for (draft, _), row in world.ledger.rows.items()}
    assert set(rows) == {made.clip_id, *made.part_ids}
    for part_id in made.part_ids:
        assert rows[part_id].price.videos == 1  # one vista previa each
    assert rows[made.clip_id].price.request_kind == "local_video"


def test_without_vistas_previas_for_every_part_nothing_is_written() -> None:
    from qualify_creative.creations import load_weights

    world = _world(previews_used=load_weights().monthly_preview_quota - 1)
    with pytest.raises(NotEnoughCreations):
        _create(world)
    _nothing_written(world)


def test_with_the_switch_off_it_is_refused_before_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "off")
    world = _world()
    with pytest.raises(RecipeRefused) as refused:
        _create(world)
    assert {p.code for p in refused.value.problems} == {"switched_off"}
    _nothing_written(world)
    assert world.store.reads == 0


@pytest.mark.parametrize(
    ("segments", "entries", "code"),
    [
        # «Sigue a la anterior» first: nothing to continue
        ((_block(0), _own(4.0)), (_entry(mode="extend"),), "extend_needs_block_before"),
        # an AI block sped up
        ((_own(4.0), _block(0, speed=2)), (_entry(),), "ai_part_with_speed"),
        # «Igual al original» without the reel's cuts
        (
            (_own(4.0), _block(0)),
            (_entry(mode="edit", analysis_id=UUID(int=7)),),
            "edit_needs_reel_window",
        ),
        # the block does not last its entry's seconds
        ((_own(4.0), _block(0, 3)), (_entry(5),), "ai_part_length_mismatch"),
        # an entry without its block
        ((_own(4.0), _block(0)), (_entry(), _entry()), "ai_parts_mismatch"),
    ],
)
def test_every_rule_refuses_before_anything_is_written_or_paid(
    segments: tuple[SourceSegment, ...], entries: tuple[VideoPartPlan, ...], code: str
) -> None:
    world = _world()
    with pytest.raises(RecipeRefused) as refused:
        _create(world, _clip(segments, entries))
    assert code in {p.code for p in refused.value.problems}
    _nothing_written(world)


def test_too_many_ai_children_are_refused() -> None:
    world = _world()
    segments = (*(_block(n, 4) for n in range(7)), _own(3.0))
    with pytest.raises(Exception) as refused:  # noqa: PT011 — the type refuses 7 > 6 first
        _create(world, _clip(segments, tuple(_entry(4) for _ in range(7))))
    assert "too_many_ai_children" in str(refused.value) or "ai_parts" in str(refused.value)
    _nothing_written(world)


def test_a_part_with_nothing_to_make_it_from_is_refused() -> None:
    world = _world()
    with pytest.raises(cap.ClipAiPartsRefused) as refused:
        _create(world, _clip((_own(4.0), _block(0)), (_entry(description="  "),)))
    assert refused.value.code == cap.NEEDS_DESCRIPTION_CODE and refused.value.block == 1
    assert refused.value.owner_message == cap.NEEDS_DESCRIPTION_TEXT
    _nothing_written(world)


def test_a_clip_that_is_not_vertical_is_refused() -> None:
    world = _world()
    brief = _clip().model_copy(update={"format": ContentFormat.FEED_4_5})
    with pytest.raises((cap.ClipAiPartsRefused, RecipeRefused)):
        _create(world, brief)
    _nothing_written(world)


def test_todays_local_cap_is_checked_before_anything() -> None:
    world = _world()
    world.repo.cap_counting = True
    from qualify_api.creative.local_cap import local_daily_cap

    for _ in range(local_daily_cap()):
        assert world.ledger is not None
        world.ledger.charge(
            tenant_id=TENANT_ID,
            brand_id=BRAND_ID,
            draft_id=uuid4(),
            revision=1,
            price=world.content.new_draft_inputs(
                tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_own_only()
            ).price,
        )
    rows = dict(world.ledger.rows) if world.ledger else {}
    with pytest.raises(LocalDailyCapReached):
        _create(world)
    assert world.repo.drafts == {} and world.dispatcher.calls == []
    assert world.ledger is not None and world.ledger.rows == rows


def _own_only() -> ContentBrief:
    return _clip((_own(4.0),), ())


def test_the_same_create_twice_makes_one_clip_and_dispatches_once() -> None:
    world = _world()
    key = uuid4()
    first = _create(world, request_key=key)
    calls, drafts = list(world.dispatcher.calls), dict(world.repo.drafts)
    again = _create(world, request_key=key)
    assert again == first
    assert world.dispatcher.calls == calls and world.repo.drafts == drafts


def test_create_draft_never_makes_a_clip_with_ai_parts() -> None:
    """The contract (PR 1): only this service makes one; `create_draft` refuses it."""
    world = _world()
    with pytest.raises(RecipeRefused) as refused:
        world.content.create_draft(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_clip(), user_id=USER_ID
        )
    assert "recipe_unavailable" in {p.code for p in refused.value.problems}
    _nothing_written(world)


def test_a_part_without_photos_takes_the_clips_photos() -> None:
    """`clip_image_keys=None` on an entry means «the parent's photos»: in the single
    editor the parent is the Clip (`parts._child_brief`)."""
    photo = f"uploads/{TENANT_ID}/arepa.jpg"
    world = _world()
    made = _create(world, _clip(clip_image_keys=(photo,), clip_image_roles=("product",)))
    child = _brief_of(world, made.part_ids[0])
    assert child.media.clip_image_keys == (photo,)


# ---------------------------------------------------------------------------
# «Sigue a la anterior»


def test_extend_after_the_owners_video_stays_refused_with_its_switch_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(EXTEND_SWITCH, "draft")
    world = _world()
    with pytest.raises(RecipeRefused) as refused:
        _create(world, _clip((_own(4.0), _block(0)), (_entry(mode="extend"),)))
    assert {p.code for p in refused.value.problems} == {"extend_after_own_media"}
    _nothing_written(world)


def test_extend_after_the_owners_video_continues_it_with_its_switch_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(EXTEND_SWITCH, "draft")
    monkeypatch.setenv(CLIP_EXTEND_OWN_VIDEO_SWITCH, "on")
    world = _world()
    own = _own(4.0, transition_in=None)
    made = _create(world, _clip((own, _block(0)), (_entry(mode="extend"),)))
    part = _brief_of(world, made.part_ids[0]).media.part
    assert part is not None and part.mode == "extend"
    assert part.extend_own is not None and part.extend_own.key == OWN_VIDEO
    assert part.extend_own.end_s == 4.0


@pytest.mark.parametrize("own", [_own(1.5), _own(4.0, speed=2)])
def test_extend_after_a_short_or_sped_up_own_video_is_refused(
    own: SourceSegment, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EXTEND_SWITCH, "draft")
    monkeypatch.setenv(CLIP_EXTEND_OWN_VIDEO_SWITCH, "on")
    world = _world()
    with pytest.raises(RecipeRefused) as refused:
        _create(world, _clip((_own(3.0, OTHER), own, _block(0)), (_entry(mode="extend"),)))
    assert "extend_own_video_unfit" in {p.code for p in refused.value.problems}
    _nothing_written(world)


def test_extend_after_a_photo_is_never_continued(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EXTEND_SWITCH, "draft")
    monkeypatch.setenv(CLIP_EXTEND_OWN_VIDEO_SWITCH, "on")
    photo = SourceSegment(kind="photo", key=f"uploads/{TENANT_ID}/foto.jpg", start_s=0, end_s=3)
    world = _world()
    with pytest.raises(RecipeRefused) as refused:
        _create(world, _clip((photo, _block(0)), (_entry(mode="extend"),)))
    assert "extend_after_own_media" in {p.code for p in refused.value.problems}


def test_extend_with_its_switch_off_is_refused_before_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`QUALIFY_PARTS_EXTEND` off (today's production): «Sigue a la anterior» starts no
    new work, as in a video by parts."""
    monkeypatch.setenv(CLIP_EXTEND_OWN_VIDEO_SWITCH, "on")
    monkeypatch.delenv(EXTEND_SWITCH, raising=False)
    world = _world()
    with pytest.raises(PartsExtendUnavailable):
        _create(world, _clip((_own(4.0), _block(0)), (_entry(mode="extend"),)))
    _nothing_written(world)


def test_extend_own_only_on_an_extend_part_at_normal_speed() -> None:
    with pytest.raises(ValueError, match="Sigue a la anterior"):
        PartRef(index=1, mode="reference", seconds=5, extend_own=_own())
    with pytest.raises(ValueError, match="normal speed"):
        PartRef(index=1, mode="extend", seconds=5, extend_own=_own(speed=2))
    assert PartRef(index=1, mode="extend", seconds=5, extend_own=_own()).extend_own is not None


# ---------------------------------------------------------------------------
# the Clip waits for its parts, with a sign of life, and is assembled once


def test_the_clip_waits_with_a_heartbeat_and_writes_nothing_while_a_part_is_made() -> None:
    world = _world()
    made = _create(world)
    brief_before = world.repo.drafts[made.clip_id].brief_id
    for _ in range(3):
        with pytest.raises(ca.ClipBlocksWait):
            world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    clip = world.repo.drafts[made.clip_id]
    assert clip.status == DRAFTING and clip.brief_id == brief_before
    assert world.beats == [(TENANT_ID, made.clip_id)] * 3
    assert world.repo.variants_for(tenant_id=TENANT_ID, draft_id=made.clip_id) == ()


def test_with_its_parts_made_the_clip_is_assembled_once_from_their_videos() -> None:
    world = _world()
    made = _create(world)
    first = _made(world, made.part_ids[0], seconds=5.0)
    # a 4 s part asked at 4 s that came out 4.2 s: the join keeps its first 4 s
    second = _made(world, made.part_ids[1], seconds=4.2)
    asked_id = world.repo.drafts[made.clip_id].brief_id
    assert world.ledger is not None
    rows_before = dict(world.ledger.rows)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    clip = world.repo.drafts[made.clip_id]
    assert clip.status == GENERATED
    brief = _brief_of(world, made.clip_id)
    assert brief.media.derived_from_brief_id == asked_id
    assert brief.media.ai_parts == ()
    assert [s.key for s in brief.media.segments] == [OWN_VIDEO, first, OTHER, second]
    assert [s.kind for s in brief.media.segments] == ["video"] * 4
    assert [s.speed for s in brief.media.segments] == [1.0] * 4
    assert (brief.media.segments[1].start_s, brief.media.segments[1].end_s) == (0.0, 5.0)
    assert (brief.media.segments[3].start_s, brief.media.segments[3].end_s) == (0.0, 4.0)
    # the brief the owner sent stays as the record of what he asked for
    assert world.repo.briefs[asked_id].media.ai_parts
    # §13.5: the automatic assembly writes no charge row — never counted in the local cap
    assert world.ledger.rows == rows_before
    # a replay writes nothing again
    briefs = len(world.repo.briefs)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert len(world.repo.briefs) == briefs


def test_the_automatic_assembly_never_counts_in_the_days_local_builds() -> None:
    world = _world()
    made = _create(world)
    used = world.repo.local_builds_today(tenant_id=TENANT_ID)
    assert used == 1  # the owner's «Crear» counts once
    with pytest.raises(ca.ClipBlocksWait):
        world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    for part_id in made.part_ids:
        world.content.run_generation(tenant_id=TENANT_ID, draft_id=part_id)
        _made(world, part_id)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    assert world.repo.local_builds_today(tenant_id=TENANT_ID) == used


def test_a_failed_part_keeps_the_clip_waiting_72_hours_then_it_fails() -> None:
    world = _world()
    made = _create(world)
    failed_at = world.clock[0]
    world.repo.drafts[made.part_ids[0]] = replace(
        world.repo.drafts[made.part_ids[0]], status=FAILED, failure_reason="provider_error"
    )
    world.store.settled[made.part_ids[0]] = failed_at
    _made(world, made.part_ids[1])
    world.clock[0] = failed_at + timedelta(hours=71)
    with pytest.raises(ca.ClipBlocksWait):
        world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == DRAFTING
    world.clock[0] = failed_at + timedelta(hours=72)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    clip = world.repo.drafts[made.clip_id]
    assert clip.status == FAILED and clip.failure_reason == cap.AI_PART_FAILED


def test_texts_move_to_the_parts_real_length() -> None:
    """A text over the own video after a part that came out shorter keeps its place over
    that video; one past the new end is cut."""
    texts = (
        VideoTextLayer(text="sobre mi video", start_s=6.0, end_s=8.0),
        VideoTextLayer(text="hasta el final", start_s=1.0),
    )
    brief = _clip((_block(0, 5), _own(4.0)), (_entry(5),), text_layers=texts)
    video = cap.AiPartVideo(
        asset_id=uuid4(),
        object_key=f"t/{TENANT_ID}/generated/{uuid4()}/r1/video.mp4",
        seconds=4.5,
        params={"duration_seconds": 4.5, "part": {"seconds": 5, "generation_seconds": 5}},
    )
    resolved = cap.resolve(brief, {0: video})
    over_own, to_end = resolved.brief.media.text_layers
    assert (over_own.start_s, over_own.end_s) == (5.5, 7.5)
    assert to_end.start_s == 0.9 and to_end.end_s is None  # its place inside the part
    assert resolved.moved == 2 and resolved.dropped == 0


def test_a_part_plays_the_interval_the_join_keeps() -> None:
    """A 2 s part asked at 4 s (Seedance's minimum) plays its first 2 s; an explicit trim
    of the plan wins."""
    segment = _block(0, 2)
    video = cap.AiPartVideo(
        asset_id=uuid4(),
        object_key=f"t/{TENANT_ID}/generated/{uuid4()}/r1/video.mp4",
        seconds=4.0,
        params={"duration_seconds": 4.0, "part": {"seconds": 2, "generation_seconds": 4}},
    )
    stretch = cap.part_stretch(segment, video)
    assert (stretch.start_s, stretch.end_s, stretch.speed) == (0.0, 2.0, 1.0)
    trimmed = replace(
        video,
        params={
            "duration_seconds": 4.0,
            "part": {"seconds": 2, "generation_seconds": 4, "trim_start_s": 1.0, "trim_end_s": 3.0},
        },
    )
    assert (
        cap.part_stretch(segment, trimmed).start_s,
        cap.part_stretch(segment, trimmed).end_s,
    ) == (
        1.0,
        3.0,
    )


def test_slots_follow_the_timeline() -> None:
    assert ai_part_slots((_block(2), _own(), _block(0), _block(1))) == {2: 1, 0: 2, 1: 3}


# ---------------------------------------------------------------------------
# the part itself, and what is not built yet


def test_a_part_of_a_clip_takes_an_empty_text() -> None:
    world = _world()
    made = _create(world)
    part_id = made.part_ids[0]
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=part_id)
    assert world.repo.drafts[part_id].status == GENERATED
    (variant,) = world.repo.variants_for(tenant_id=TENANT_ID, draft_id=part_id)
    assert variant.copy["hook"] == "" and variant.copy["caption"] == ""
    assert variant.fidelity["clip_ai_part_without_text"] is True


def test_a_clip_with_ai_parts_is_not_approved_until_pr4() -> None:
    world = _world()
    made = _create(world)
    for part_id in made.part_ids:
        _made(world, part_id)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    (variant,) = world.repo.variants_for(tenant_id=TENANT_ID, draft_id=made.clip_id)[:1]
    with pytest.raises(cap.ClipAiPartsRefused) as refused:
        world.content.approve(
            tenant_id=TENANT_ID, draft_id=made.clip_id, variant_id=variant.id, user_id=USER_ID
        )
    assert refused.value.code == cap.APPROVE_UNAVAILABLE_CODE
    assert world.repo.drafts[made.clip_id].status == GENERATED


def test_key_problems_skip_ai_blocks_and_check_the_entries_files() -> None:
    foreign = f"uploads/{uuid4()}/ajeno.mp4"
    brief = _clip(entries=(_entry(4), _entry(5, clip_video_keys=(foreign,))))
    malformed, refused = _key_problems(TENANT_ID, brief, make_kit())
    assert malformed == [] and refused == [foreign]


# ---------------------------------------------------------------------------
# the assembly: never an unresolved block; provenance of every part played


def test_the_assembly_refuses_an_unresolved_ai_block(
    queue_on: None, assembly_files: dict[str, bytes]
) -> None:
    outcome, store, _ = _assemble(_clip(), assembly_files, clip_id=uuid4(), sources={})
    assert outcome.failure is not None
    assert store.reads == [] if hasattr(store, "reads") else True


def test_the_assembly_records_each_ai_part_it_plays(
    queue_on: None, assembly_files: dict[str, bytes]
) -> None:
    part_id = uuid4()
    key = f"t/{TENANT_ID}/generated/{part_id}/r1/video.mp4"
    piece = replace(
        _piece(key, provider="seedance", model_id="dreamina-seedance-2-0"),
        ai_part={"mode": "reference", "mode_reason": "no_source", "seconds": 4},
        prompt_version="part-reference-v6",
        task_id="cgt-123",
        cost_usd="0.21",
    )
    clip = _clip((_own(4.0), SourceSegment(key=key, start_s=0, end_s=4.0, speed=1.0)), ())
    outcome, _, _ = _assemble(
        clip,
        {**assembly_files, key: _video_with_sound_bytes(4.0, 1.5)},
        clip_id=uuid4(),
        sources={key: piece},
    )
    assert outcome.failure is None, outcome.detail
    (video,) = outcome.media
    assert video.ai_generated is True
    (source,) = video.params["local"]["ai_sources"]
    assert source["ai_part"] is True and source["avatar_block"] is False
    (record,) = video.params["local"]["ai_parts"]
    assert record["segment"] == 1 and record["mode"] == "reference"
    assert record["mode_reason"] == "no_source" and record["seconds_asked"] == 4
    assert record["prompt_version"] == "part-reference-v6" and record["task_id"] == "cgt-123"
    assert record["cost_usd"] == "0.21" and record["provider"] == "seedance"
