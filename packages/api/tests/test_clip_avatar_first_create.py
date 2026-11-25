"""m-25119867 (option B of m-25112920): the avatar chosen at the Clip's first «Crear».

The Clip and its avatar blocks are born together; the blocks are made, the Clip WAITS for
them (`ClipBlocksWait`, a `LocalVideoWait`: its run released not done, its sign of life
stamped) and is then made ONCE from a brief with their videos as stretches. Every rule of
ADR 50 §9 refuses before anything is written and before any paid call. Contract:
`docs/contrato-avatar-primer-crear.md`.

Offline only: no BytePlus, OmniHuman, Seedream, Seed Speech or Claude is ever called —
the copy vendor is a double, the database a set of dicts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentKind
from qualify_creative.schemas import (
    ClipAvatarSlot,
    ContentBrief,
    EffectUse,
    MediaInputs,
    SourceSegment,
    VideoTextLayer,
)

from qualify_api.creative import clip_avatar as ca
from qualify_api.creative.creations import InMemoryCreationsLedger, NotEnoughCreations
from qualify_api.creative.fsm import DRAFTING, FAILED, GENERATED
from qualify_api.creative.heavy_video import LocalVideoWait
from qualify_api.creative.queue_dispatch import CheckpointError
from qualify_api.creative.service import ContentService
from qualify_api.creative.video_pipeline.recipe import RecipeRefused

from . import test_video_pipeline_local as _local_tests
from .test_clip_avatar import (
    BOTH_ON,
    OWN_VIDEO,
    PRESENTER_ON,
    SCRIPT,
    BlockRepo,
    RepoStore,
    _animated,
    _local_clip,
    _presenter,
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

#: `create_clip_with_blocks` is the queue's only (EF-06: a local Clip never runs inline)
queue_on = _local_tests.queue_on


@pytest.fixture(autouse=True)
def _queue(queue_on: None, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: PT004
    """Every test here runs with the creative queue on, as production does, and both
    switches on in the WORKER's environment (the Clip's wait reads them there); the
    service's own `env` says what the «Crear» sees."""
    for switch in BOTH_ON:
        monkeypatch.setenv(switch, "on")


# ---------------------------------------------------------------------------
# doubles


class PlanStore(RepoStore):
    """`RepoStore` with what option B reads: each block's failure and removal, and P6 (a
    block of a FAILED Clip owes nothing)."""

    def __init__(self, repo: BlockRepo) -> None:
        super().__init__(repo)
        self.removed: set[UUID] = set()
        self.used_today: int | None = None

    def blocks_of(self, *, tenant_id: UUID, clip_id: UUID) -> tuple[ca.BlockRow, ...]:
        rows = super().blocks_of(tenant_id=tenant_id, clip_id=clip_id)
        return tuple(
            replace(
                row,
                removed=row.id in self.removed,
                failure_reason=self.repo.drafts[row.id].failure_reason,
                failure_detail=getattr(self.repo.drafts[row.id], "failure_detail", None),
            )
            for row in rows
        )

    def pending_block_seconds(self, *, tenant_id: UUID, brand_id: UUID) -> tuple[int, int]:
        live = [
            (draft_id, brief)
            for draft_id, brief in self._blocks()
            if brief.brand_id == brand_id
            and self.repo.drafts[draft_id].status != "failed"
            and draft_id not in self.removed
            and not self._charged(draft_id)
            and self.repo.drafts[self.repo.parents[draft_id][0]].status
            not in ("approved", "staged", "published", "failed")
        ]
        return len(live), sum(ca.script_seconds(b.media.own_script) for _, b in live)

    def blocks_made_today(self, *, tenant_id: UUID) -> int:
        if self.used_today is not None:
            return self.used_today
        return super().blocks_made_today(tenant_id=tenant_id)


@dataclass
class World:
    service: ca.ClipAvatarService
    content: ContentService
    repo: BlockRepo
    store: PlanStore
    dispatcher: RecordingDispatcher
    ledger: InMemoryCreationsLedger | None
    beats: list[tuple[UUID, UUID]]


def _world(*, env: dict[str, str] | None = None, quota: bool = True, videos_used: int = 0) -> World:
    repo, dispatcher = BlockRepo(), RecordingDispatcher()
    store = PlanStore(repo)
    ledger = InMemoryCreationsLedger(videos_used=videos_used) if quota else None
    beats: list[tuple[UUID, UUID]] = []
    content = ContentService(
        router=FakeRouter([ok_outcome(copy_dict()) for _ in range(6)]),  # type: ignore[arg-type]
        pricing=FakePricing(),
        credentials=StaticKeyResolver(),
        voice_service=FakeVoice(make_voice()),
        brand_service=FakeBrand(make_kit()),
        repository=repo,
        dispatcher=dispatcher,
        creations=ledger,
        progress=lambda tenant, draft: beats.append((tenant, draft)),
        clip_avatar_store=store,
        clip_avatar_sources=lambda tenant, keys: store.generated_sources(
            tenant_id=tenant, keys=keys
        ),
    )
    store.ledger = ledger
    service = ca.ClipAvatarService(
        content,
        store=store,
        env=env if env is not None else BOTH_ON,
        brand_avatar_key=lambda tenant, brand: f"t/{tenant}/brand/{brand}/avatar/a.jpg",
    )
    return World(service, content, repo, store, dispatcher, ledger, beats)


def _own(seconds: float = 4.0, key: str = OWN_VIDEO) -> SourceSegment:
    return SourceSegment(key=key, start_s=0, end_s=seconds, speed=1)


def _clip(*segments: SourceSegment, **media: Any) -> ContentBrief:
    brief = _local_clip(*(segments or (_own(4.0), _own(3.0, f"uploads/{TENANT_ID}/b.mp4"))))
    if not media:
        return brief
    return brief.model_copy(update={"media": brief.media.model_copy(update=media)})


def _at(request: ca.AvatarBlockRequest, at: int) -> ca.ClipAvatarPlacement:
    return ca.ClipAvatarPlacement(block=request, at=at)


def _create(world: World, *placements: ca.ClipAvatarPlacement, **kw: Any) -> ca.ClipWithBlocks:
    return world.service.create_clip_with_blocks(
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        user_id=USER_ID,
        brief=kw.pop("brief", None) or _clip(),
        blocks=placements or (_at(_presenter(), 0),),
        **kw,
    )


def _nothing_written(world: World) -> None:
    assert world.repo.drafts == {} and world.dispatcher.calls == []
    assert world.ledger is None or world.ledger.rows == {}


def _made(world: World, block_id: UUID, seconds: float = 4.0) -> str:
    """The block came out: `generated`, its video kept."""
    key = f"t/{TENANT_ID}/generated/{block_id}/r1/video.mp4"
    world.repo.drafts[block_id] = replace(world.repo.drafts[block_id], status=GENERATED)
    world.store.videos[block_id] = ca.BlockVideo(asset_id=uuid4(), object_key=key, seconds=seconds)
    return key


def _clip_brief(world: World, clip_id: UUID) -> ContentBrief:
    return world.repo.briefs[world.repo.drafts[clip_id].brief_id]


# ---------------------------------------------------------------------------
# creating: the Clip and its blocks, born together


def test_a_clip_and_its_blocks_are_born_together_and_the_blocks_go_first() -> None:
    world = _world()
    made = _create(world, _at(_presenter(), 0), _at(_animated(), 2))
    clip = world.repo.drafts[made.clip_id]
    assert clip.status == DRAFTING and clip.parent_draft_id is None
    plan = _clip_brief(world, made.clip_id).media.clip_avatar_plan
    assert [(e.slot, e.at, e.seconds_estimate) for e in plan] == [
        (1, 0, ca.script_seconds(SCRIPT)),
        (2, 2, ca.script_seconds(SCRIPT)),
    ]
    assert len(made.block_ids) == 2
    for slot, (block_id, kind) in enumerate(
        zip(
            made.block_ids,
            (ContentKind.AVATAR_VIDEO, ContentKind.ANIMATED_AVATAR_VIDEO),
            strict=True,
        ),
        1,
    ):
        assert world.repo.parents[block_id] == (made.clip_id, slot)
        block = world.repo.briefs[world.repo.drafts[block_id].brief_id]
        assert block.kind is kind and block.media.clip_avatar_block
        assert block.media.own_script == SCRIPT
    # the blocks are dispatched first, then the Clip that waits for them
    assert [d for _, d in world.dispatcher.calls] == [*made.block_ids, made.clip_id]
    # each block's charge row is of weight 0; the Clip's is its own price
    assert world.ledger is not None
    rows = {draft: row for (draft, _), row in world.ledger.rows.items()}
    assert set(rows) == {made.clip_id, *made.block_ids}
    assert all(rows[b].videos == 0 for b in made.block_ids)


@pytest.mark.parametrize(
    ("env", "requests", "block"),
    [
        ({}, (_presenter(),), 0),
        (PRESENTER_ON, (_presenter(), _animated()), 1),
        ({ca.ANIMATED_SWITCH: "on"}, (_presenter(),), 0),
    ],
)
def test_a_kind_switched_off_is_refused_before_anything(
    env: dict[str, str], requests: tuple[ca.AvatarBlockRequest, ...], block: int
) -> None:
    world = _world(env=env)
    world.store.reads = 0
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        _create(world, *(_at(r, 0) for r in requests))
    assert refused.value.code == "switched_off" and refused.value.block == block
    assert refused.value.owner_message == ca.FIRST_CREATE_SWITCHED_OFF_TEXT
    assert world.store.reads == 0
    _nothing_written(world)


def test_a_script_over_30_seconds_is_refused_with_the_blocks_place() -> None:
    world = _world()
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        _create(world, _at(_presenter(), 0), _at(_presenter(script="a" * 600), 1))
    assert refused.value.code == "too_long" and refused.value.block == 1
    assert refused.value.owner_message == ca.TOO_LONG_TEXT
    _nothing_written(world)


def test_more_than_three_blocks_are_refused() -> None:
    world = _world()
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        _create(world, *(_at(_presenter(script="Hola."), 0) for _ in range(4)))
    assert refused.value.code == "too_many_blocks"
    assert refused.value.owner_message == ca.TOO_MANY_BLOCKS_TEXT
    _nothing_written(world)


def test_a_clip_of_avatars_alone_is_refused() -> None:
    """P5 (Deivid 2026-11-25): the owner's own photos and videos last 3 s or more."""
    world = _world()
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        _create(world, brief=_clip(_own(2.0)))
    assert refused.value.code == "avatar_needs_own_media"
    assert refused.value.owner_message == ca.NEEDS_OWN_MEDIA_TEXT
    _nothing_written(world)


def test_only_a_clip_of_the_owners_own_media_takes_blocks() -> None:
    world = _world()
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        _create(world, brief=make_brief(variants=1, kind=ContentKind.CLIP))
    assert refused.value.code == "clip_not_local"
    _nothing_written(world)


def test_the_recipe_with_the_blocks_estimated_length_is_checked() -> None:
    """30 s of the owner's video and two 30 s blocks would last 90 s: refused as the
    editor's recipe is, with the blocks counted at their estimated length."""
    world = _world()
    thirty = _presenter(script="a" * 450)
    with pytest.raises(RecipeRefused) as refused:
        _create(world, _at(thirty, 0), _at(thirty, 1), brief=_clip(_own(30.0)))
    assert refused.value.reason == "local_length_out_of_range"
    _nothing_written(world)


def test_a_text_over_a_planned_block_is_checked_on_the_estimated_timeline() -> None:
    """A text the owner put over the avatar (after his own 4 s) fits the estimated
    timeline — the stored recipe alone (4 s) would have refused it."""
    world = _world()
    text = VideoTextLayer(text="¡Pruébala!", start_s=5.0, end_s=7.0)
    made = _create(world, _at(_presenter(), 1), brief=_clip(_own(4.0), text_layers=(text,)))
    assert _clip_brief(world, made.clip_id).media.text_layers == (text,)


@pytest.mark.parametrize(
    ("used", "words"),
    [
        (3, "Ya creaste 3 avatares hoy. Mañana puedes crear más."),
        (2, "Hoy solo puedes crear 1 avatar más. Quita 2 para crear tu video."),
        (1, "Hoy solo puedes crear 2 avatares más. Quita 1 para crear tu video."),
    ],
)
def test_todays_cap_is_checked_for_every_block_of_the_create(used: int, words: str) -> None:
    world = _world()
    world.store.used_today = used
    with pytest.raises(ca.AvatarDailyCapReached) as refused:
        _create(world, *(_at(_presenter(script="Hola."), 0) for _ in range(3)))
    assert refused.value.code == ca.AVATAR_DAILY_CAP_CODE and refused.value.asking == 3
    assert refused.value.owner_message == words
    _nothing_written(world)


def test_the_daily_cap_words_at_the_first_create_are_section_9s() -> None:
    assert ca.FIRST_CREATE_DAILY_CAP_TEXT == "Ya creaste 3 avatares hoy. Mañana puedes crear más."


def test_more_stretches_than_a_clip_holds_are_refused_by_code() -> None:
    """8 stretches of the owner's and 1 avatar pass `SEGMENTS_MAX`: a stable code before
    anything is read — never a bare ValidationError from the recipe built with them."""
    world = _world()
    world.store.reads = 0
    eight = tuple(_own(1.0, f"uploads/{TENANT_ID}/{i}.mp4") for i in range(8))
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        _create(world, _at(_presenter(), 0), brief=_clip(*eight))
    assert refused.value.code == "too_many_segments"
    assert refused.value.owner_message == ca.TOO_MANY_SEGMENTS_TEXT
    assert world.store.reads == 0
    _nothing_written(world)


def test_the_switches_say_not_before_pr_2() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    for name in (".env.example", "deploy/.env.prod.example"):
        assert "NO encender antes del PR 2 de m-25119867" in (root / name).read_text(
            encoding="utf-8"
        )


def test_no_paid_call_without_the_months_video_for_every_block() -> None:
    world = _world()
    assert world.ledger is not None
    left = world.ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).videos_left
    half = _presenter(script="a" * (15 * (left // 2 + 1)))  # two of them pass the month
    assert ca.plan_seconds([half, half]) > left >= ca.plan_seconds([half])
    with pytest.raises(NotEnoughCreations):
        _create(world, _at(half, 0), _at(half, 1), brief=_clip(_own(3.0)))
    _nothing_written(world)


def test_plan_seconds_is_what_the_quota_check_adds() -> None:
    """The screen's cost before «Crear» is the same sum the check refuses with: the
    blocks fit exactly when `plan_seconds` is at most `avatar_quota().free`."""
    world = _world(videos_used=20)
    quota = world.service.avatar_quota(tenant_id=TENANT_ID, brand_id=BRAND_ID)
    assert quota is not None and quota.free is not None and quota.pending_seconds == 0
    assert quota.free == quota.left == 20
    fits = _presenter(script="a" * (15 * quota.free))
    assert ca.plan_seconds([fits]) == quota.free
    _create(world, _at(fits, 0))
    after = world.service.avatar_quota(tenant_id=TENANT_ID, brand_id=BRAND_ID)
    assert after is not None and after.pending_seconds == quota.free and after.free == 0
    with pytest.raises(NotEnoughCreations):
        _create(world, _at(_presenter(script="Hola."), 0))


def test_a_foreign_file_of_a_block_is_refused() -> None:
    world = _world()
    foreign = _animated(
        avatar_image_key=f"uploads/{uuid4()}/gato.png", avatar_rights_confirmed=True
    )
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        _create(world, _at(foreign, 0))
    assert refused.value.code == "avatar_file_not_owned" and refused.value.block == 0
    _nothing_written(world)


def test_the_same_create_twice_makes_one_clip() -> None:
    world = _world()
    key = uuid4()
    first = _create(world, _at(_presenter(), 0), request_key=key)
    calls = list(world.dispatcher.calls)
    again = _create(world, _at(_presenter(), 0), request_key=key)
    assert again == first and world.dispatcher.calls == calls


def test_create_draft_refuses_a_brief_with_a_plan() -> None:
    world = _world()
    plan = (ClipAvatarSlot(slot=1, at=0, seconds_estimate=4),)
    with pytest.raises(ValueError, match="planned by their own service"):
        world.content.create_draft(
            tenant_id=TENANT_ID,
            brand_id=BRAND_ID,
            user_id=USER_ID,
            brief=_clip(clip_avatar_plan=plan),
        )
    _nothing_written(world)


def test_only_a_local_clip_may_carry_a_plan() -> None:
    plan = (ClipAvatarSlot(slot=1, at=0, seconds_estimate=4),)
    with pytest.raises(ValueError, match="only in a local Clip"):
        make_brief(variants=1, kind=ContentKind.CLIP, media=MediaInputs(clip_avatar_plan=plan))
    with pytest.raises(ValueError, match="its own slot"):
        MediaInputs(clip_avatar_plan=plan * 2)


# ---------------------------------------------------------------------------
# the Clip waits for its blocks


def test_the_clip_waits_with_a_heartbeat_and_writes_nothing_while_a_block_is_made() -> None:
    world = _world()
    made = _create(world, _at(_presenter(), 0))
    brief_before = world.repo.drafts[made.clip_id].brief_id
    with pytest.raises(ca.ClipBlocksWait):
        world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    clip = world.repo.drafts[made.clip_id]
    assert clip.status == DRAFTING and clip.brief_id == brief_before
    assert world.beats == [(TENANT_ID, made.clip_id)]
    assert world.repo.variants == {}  # no text asked for, nothing paid


def test_the_wait_is_a_local_video_wait_retried_within_a_minute() -> None:
    """The worker releases the run NOT done and holds it `retry_after_s` (a
    `LocalVideoWait`, a `CheckpointError`): with a pass every 2 s, the sign of life is
    stamped well within 60 s."""
    assert issubclass(ca.ClipBlocksWait, LocalVideoWait)
    assert issubclass(ca.ClipBlocksWait, CheckpointError)
    assert 0 < ca.ClipBlocksWait.retry_after_s <= 45


def test_the_wait_is_the_same_after_a_restart() -> None:
    """A restart loses only the worker's hold: the next pass derives the same wait from
    the rows, and the Clip is made exactly once when its blocks are."""
    world = _world()
    made = _create(world, _at(_presenter(), 0))
    for _ in range(3):
        with pytest.raises(ca.ClipBlocksWait):
            world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert len(world.beats) == 3 and world.repo.drafts[made.clip_id].status == DRAFTING
    _made(world, made.block_ids[0])
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    briefs = len(world.repo.briefs)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)  # a replay
    assert len(world.repo.briefs) == briefs


def test_with_its_blocks_made_the_clip_is_made_once_from_their_videos() -> None:
    world = _world()
    made = _create(world, _at(_presenter(), 0), _at(_presenter(script="Hola."), 2))
    first = _made(world, made.block_ids[0], seconds=4.4)
    second = _made(world, made.block_ids[1], seconds=1.2)
    asked = _clip_brief(world, made.clip_id)
    asked_id = world.repo.drafts[made.clip_id].brief_id
    assert asked.media.derived_from_brief_id is None
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    # provenance: the derived brief points to the one the owner sent
    assert _clip_brief(world, made.clip_id).media.derived_from_brief_id == asked_id
    clip = world.repo.drafts[made.clip_id]
    assert clip.status == GENERATED
    brief = _clip_brief(world, made.clip_id)
    assert brief.media.clip_avatar_plan == ()
    assert [s.key for s in brief.media.segments] == [
        first,
        OWN_VIDEO,
        f"uploads/{TENANT_ID}/b.mp4",
        second,
    ]
    assert [s.speed for s in brief.media.segments] == [1.0] * 4
    assert brief.media.segments[0].end_s == 4.4 and brief.media.segments[3].end_s == 1.2
    # the brief the owner sent stays as the record of what he asked for
    assert asked in world.repo.briefs.values() and asked.media.clip_avatar_plan


def test_a_block_made_too_long_is_refused_and_the_clip_waits_for_the_owner() -> None:
    world = _world()
    made = _create(world, _at(_presenter(script="a" * 450), 1), brief=_clip(_own(30.0)))
    _made(world, made.block_ids[0], seconds=30.9)  # 30 s + 30.9 s > 60 s
    with pytest.raises(ca.ClipBlocksWait):
        world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    (entry,) = _clip_brief(world, made.clip_id).media.clip_avatar_plan
    assert entry.refused == "clip_too_long"
    wait = world.service.clip_wait(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert wait is not None and wait.state == "block_failed"
    (block,) = wait.blocks
    assert block.state == "failed" and block.failure_code == "clip_too_long"
    assert block.owner_text == ca.CLIP_TOO_LONG_TEXT
    # the next pass waits without writing again
    briefs = len(world.repo.briefs)
    with pytest.raises(ca.ClipBlocksWait):
        world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert len(world.repo.briefs) == briefs


def test_a_failed_block_keeps_the_clip_waiting_never_failed_by_itself() -> None:
    world = _world()
    made = _create(world, _at(_presenter(), 0))
    world.repo.drafts[made.block_ids[0]] = replace(
        world.repo.drafts[made.block_ids[0]], status=FAILED, failure_reason="timeout"
    )
    with pytest.raises(ca.ClipBlocksWait):
        world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == DRAFTING and world.beats


def test_a_kind_switched_off_while_waiting_is_never_placed() -> None:
    world = _world()
    made = _create(world, _at(_presenter(), 0))
    _made(world, made.block_ids[0])
    world.service._env = {}  # noqa: SLF001 — switched off after the «Crear»
    gate = ca.plan_gate(
        tenant_id=TENANT_ID,
        clip_id=made.clip_id,
        brief=_clip_brief(world, made.clip_id),
        store=world.store,
        env={},
    )
    assert isinstance(gate, ca.PlanWait) and gate.reason == "block_failed"


# ---------------------------------------------------------------------------
# P3: a block of option B has no text of its own


def test_a_block_made_before_its_clip_has_a_text_takes_an_empty_one() -> None:
    world = _world()
    made = _create(world, _at(_presenter(), 0))
    block_id = made.block_ids[0]
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=block_id)
    assert world.repo.drafts[block_id].status == GENERATED
    (variant,) = world.repo.variants_for(tenant_id=TENANT_ID, draft_id=block_id)
    assert variant.copy["hook"] == "" and variant.copy["caption"] == ""
    assert variant.copy["script"] == SCRIPT
    assert variant.fidelity["clip_avatar_block_without_text"] is True
    assert variant.fidelity["inherited_from"] is None


# ---------------------------------------------------------------------------
# moving texts and effects to the blocks' real length (pure)


def _plan(*entries: tuple[int, int, int]) -> tuple[ClipAvatarSlot, ...]:
    return tuple(ClipAvatarSlot(slot=s, at=a, seconds_estimate=e) for s, a, e in entries)


def _video(seconds: float) -> ca.BlockVideo:
    return ca.BlockVideo(
        asset_id=uuid4(), object_key=f"t/{TENANT_ID}/generated/x/{seconds}.mp4", seconds=seconds
    )


def test_texts_and_effects_move_to_the_blocks_real_length() -> None:
    plan = _plan((1, 0, 5))  # a 5 s estimate that came out 7 s, before 4 s of own video
    texts = (
        VideoTextLayer(text="dentro", start_s=1.0, end_s=4.0),  # inside the block
        VideoTextLayer(text="despues", start_s=6.0, end_s=8.0),  # over the own video
        VideoTextLayer(text="hasta el final", start_s=5.0),
    )
    effects = (EffectUse(effect_id="humo_capa", version=1, start_s=5.5, end_s=9.0),)
    brief = _clip(_own(4.0), text_layers=texts, effects=effects, clip_avatar_plan=plan)
    fit = ca.fit_plan(brief, {1: _video(7.0)}, keep=plan)
    assert fit.brief is not None
    moved = fit.brief.media.text_layers
    assert (moved[0].start_s, moved[0].end_s) == (1.4, 5.6)  # scaled inside the block
    assert (moved[1].start_s, moved[1].end_s) == (8.0, 10.0)  # +2 s after it
    assert (moved[2].start_s, moved[2].end_s) == (7.0, None)
    (effect,) = fit.brief.media.effects
    assert (effect.start_s, effect.end_s) == (7.5, 11.0)
    assert fit.moved == 4 and fit.dropped == 0


def test_a_text_past_the_new_end_is_cut_or_dropped() -> None:
    plan = _plan((1, 0, 6))  # estimated 6 s, came out 3 s: the Clip ends 3 s earlier
    texts = (
        VideoTextLayer(text="corta", start_s=8.0, end_s=10.0),  # over the own video
        VideoTextLayer(text="fuera", start_s=10.0),  # starts at the estimated end
    )
    brief = _clip(_own(4.0), text_layers=texts, clip_avatar_plan=plan)
    fit = ca.fit_plan(brief, {1: _video(3.0)}, keep=plan)
    assert fit.brief is not None
    (cut,) = fit.brief.media.text_layers
    assert (cut.start_s, cut.end_s) == (5.0, 7.0)
    assert fit.dropped == 1


def test_over_60_seconds_names_the_block_that_passes_them() -> None:
    plan = _plan((1, 0, 20), (2, 1, 20))
    brief = _clip(_own(25.0), clip_avatar_plan=plan)
    fit = ca.fit_plan(brief, {1: _video(20.0), 2: _video(15.5)}, keep=plan)
    assert fit.brief is None and fit.too_long == 2


# ---------------------------------------------------------------------------
# what the screen reads


def test_clip_wait_says_what_the_clip_waits_for() -> None:
    world = _world()
    made = _create(world, _at(_presenter(), 0), _at(_presenter(script="Hola."), 1))
    wait = world.service.clip_wait(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert wait is not None and wait.state == "waiting_blocks"
    assert wait.owner_text == ca.WAITING_MANY_TEXT and wait.clip_status == DRAFTING
    assert [(b.slot, b.at, b.state) for b in wait.blocks] == [
        (1, 0, "creating"),
        (2, 1, "creating"),
    ]
    assert all(b.actions == () for b in wait.blocks)  # «Intentar de nuevo» comes with PR 2
    _made(world, made.block_ids[0], seconds=4.4)
    world.repo.drafts[made.block_ids[1]] = replace(
        world.repo.drafts[made.block_ids[1]], status=FAILED, failure_reason="timeout"
    )
    wait = world.service.clip_wait(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert wait is not None and wait.state == "block_failed"
    assert wait.owner_text == ca.BLOCK_FAILED_STATE_TEXT
    ready, failed = wait.blocks
    assert (ready.state, ready.seconds) == ("ready", 4.4)
    assert (failed.state, failed.failure_code, failed.owner_text) == (
        "failed",
        "timeout",
        ca.BLOCK_TIMEOUT_TEXT,
    )
    world.repo.drafts[made.block_ids[1]] = replace(
        world.repo.drafts[made.block_ids[1]], status=DRAFTING, failure_reason=None
    )
    _made(world, made.block_ids[1])
    wait = world.service.clip_wait(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert wait is not None and wait.state == "assembling"
    assert wait.owner_text == ca.ASSEMBLING_WITH_BLOCKS_TEXT
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    wait = world.service.clip_wait(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert wait is not None and wait.state == "ready" and wait.owner_text == ca.READY_TEXT


def test_one_block_reads_in_the_singular_and_a_clip_without_blocks_reads_nothing() -> None:
    world = _world()
    made = _create(world, _at(_presenter(), 0))
    wait = world.service.clip_wait(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert wait is not None and wait.owner_text == ca.WAITING_ONE_TEXT
    plain = world.repo.seed_draft(_clip(), status=GENERATED)
    assert world.service.clip_wait(tenant_id=TENANT_ID, clip_id=plain) is None
    assert world.service.clip_wait(tenant_id=TENANT_ID, clip_id=uuid4()) is None


def test_clip_wait_reads_option_a_blocks_as_their_rows_say() -> None:
    """A Clip with no plan (option A's blocks): each block's state is its row's — being
    made, failed with its own words, made — never assumed `ready`."""
    from .test_clip_avatar import _wired

    service, _, repo, store, _, clip_id = _wired(env=PRESENTER_ON)
    store.capped = False
    making = service.create_block(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=_presenter()
    )
    broken = service.create_block(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=_presenter()
    )
    done = service.create_block(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=_presenter()
    )
    repo.drafts[broken] = replace(
        repo.drafts[broken], status=FAILED, failure_reason="timeout", failure_detail=None
    )
    repo.drafts[done] = replace(repo.drafts[done], status=GENERATED)
    service._store = PlanStore(repo)  # noqa: SLF001 — the double that reads failures
    wait = service.clip_wait(tenant_id=TENANT_ID, clip_id=clip_id)
    assert wait is not None
    states = {b.block_id: (b.state, b.failure_code, b.owner_text) for b in wait.blocks}
    assert states[making] == ("creating", None, None)
    assert states[broken] == ("failed", "timeout", ca.BLOCK_TIMEOUT_TEXT)
    assert states[done][0] == "ready"


def test_the_free_reads_before_create() -> None:
    world = _world(env=PRESENTER_ON)
    assert ca.avatar_kind_enabled("presenter", PRESENTER_ON)
    assert not ca.avatar_kind_enabled("animated", PRESENTER_ON)
    assert world.service.avatar_daily_left(tenant_id=TENANT_ID) == (0, ca.AVATAR_DAILY_CAP)
    _create(world, _at(_presenter(), 0))
    assert world.service.avatar_daily_left(tenant_id=TENANT_ID) == (1, ca.AVATAR_DAILY_CAP)
    assert world.service.brand_avatar_ready(tenant_id=TENANT_ID, brand_id=BRAND_ID)
    assert _world(quota=False).service.avatar_quota(tenant_id=TENANT_ID, brand_id=BRAND_ID) is None


def test_a_failed_clips_blocks_owe_nothing() -> None:
    """P6 (Deivid 2026-11-25): from the moment the Clip fails, its blocks free the month."""
    world = _world()
    made = _create(world, _at(_presenter(), 0))
    before = world.service.avatar_quota(tenant_id=TENANT_ID, brand_id=BRAND_ID)
    assert before is not None and before.pending_blocks == 1
    world.repo.drafts[made.clip_id] = replace(world.repo.drafts[made.clip_id], status=FAILED)
    after = world.service.avatar_quota(tenant_id=TENANT_ID, brand_id=BRAND_ID)
    assert after is not None and after.pending_blocks == 0 and after.pending_seconds == 0


# ---------------------------------------------------------------------------
# a join next to an avatar is only «Corte» (Deivid, 2026-11-25)


FADE = EffectUse(effect_id="fundido", version=2, params={"duration_s": 0.5})
CUT = EffectUse(effect_id="corte", version=1)
OTHER = f"uploads/{TENANT_ID}/b.mp4"


def _joined(seconds: float, join: EffectUse | None, key: str = OWN_VIDEO) -> SourceSegment:
    """An owner's stretch with its join to the one before it (ADR 50 §10)."""
    return SourceSegment(key=key, start_s=0, end_s=seconds, speed=1, transition_in=join)


def test_a_blending_join_next_to_a_block_is_found() -> None:
    stretches = [
        _joined(3, None),
        _joined(3, None, OTHER),
        _joined(3, FADE),
        _joined(3, FADE, OTHER),
        _joined(3, FADE),
    ]
    # a block at 1: its own join (a cut) and the next one's (a fade)
    assert ca.avatar_join_problems(stretches, [1]) == (2,)
    # a block at 3: its own fade and the next one's
    assert ca.avatar_join_problems(stretches, [3]) == (3, 4)
    # «Corte» named explicitly is no blend; a block not made yet (None) always cuts
    assert ca.avatar_join_problems([_joined(3, None), _joined(3, CUT, OTHER)], [0]) == ()
    assert ca.avatar_join_problems([None, _joined(3, None)], [0]) == ()
    assert ca.avatar_join_problems(stretches, []) == ()
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        ca.refuse_avatar_joins(stretches, [3])
    assert refused.value.code == ca.AVATAR_JOIN_CODE == "avatar_join_cut_only"
    assert refused.value.owner_message == ca.AVATAR_JOIN_TEXT


@pytest.fixture(params=["off", "on"], ids=["transitions_off", "transitions_on"])
def block_transitions(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """The rule holds with ADR 50 §10's switch off AND on: it is the condition to turn it
    on, so it never depends on it (and it answers before the switch's own refusal)."""
    from qualify_api.creative.video_pipeline.recipe import CLIP_BLOCK_TRANSITIONS_SWITCH

    monkeypatch.setenv(CLIP_BLOCK_TRANSITIONS_SWITCH, request.param)
    return str(request.param)


@pytest.mark.parametrize(
    ("stretches", "at"),
    [
        # the owner's stretch right after the avatar blends into it
        ((_joined(4.0, None), _joined(3.0, FADE, OTHER)), 1),
        # the avatar first: the stretch after it is the first, blending into the avatar
        ((_joined(4.0, FADE), _joined(3.0, None, OTHER)), 0),
    ],
    ids=["after_the_avatar", "avatar_first"],
)
def test_the_first_create_refuses_a_blend_next_to_an_avatar(
    block_transitions: str, stretches: tuple[SourceSegment, ...], at: int
) -> None:
    world = _world()
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        _create(world, _at(_presenter(), at), brief=_clip(*stretches))
    assert refused.value.code == ca.AVATAR_JOIN_CODE
    _nothing_written(world)


def test_the_first_create_takes_a_cut_next_to_an_avatar(block_transitions: str) -> None:
    world = _world()
    stretches = (_joined(4.0, None), _joined(3.0, CUT, OTHER))
    made = _create(world, _at(_presenter(), 1), brief=_clip(*stretches))
    assert made.clip_id in world.repo.drafts


def test_place_block_refuses_a_blend_into_an_avatar(block_transitions: str) -> None:
    from .test_clip_avatar import _wired

    stretches = (_joined(4.0, None), _joined(3.0, FADE, OTHER))
    service, _, repo, store, _, clip_id = _wired(env=PRESENTER_ON, clip=_clip(*stretches))
    block = service.create_block(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=_presenter()
    )
    repo.drafts[block] = replace(repo.drafts[block], status=GENERATED)
    store.videos[block] = ca.BlockVideo(
        asset_id=uuid4(), object_key=f"t/{TENANT_ID}/generated/{block}/r1/v.mp4", seconds=4.0
    )
    briefs = len(repo.briefs)
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        service.place_block(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, block_id=block, at=1
        )
    assert refused.value.code == ca.AVATAR_JOIN_CODE
    assert len(repo.briefs) == briefs  # nothing written


def test_the_assembly_refuses_a_blend_next_to_an_avatar_whatever_path_put_it_there(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The local assembly's own check (`produce_local`): a recipe that reached it with a
    fade next to a block is failed before anything is read — with the switch ON, where
    the recipe's own rules let the fade through (off, they refuse it first)."""
    from qualify_api.creative.video_pipeline import local
    from qualify_api.creative.video_pipeline.recipe import CLIP_BLOCK_TRANSITIONS_SWITCH

    monkeypatch.setenv(CLIP_BLOCK_TRANSITIONS_SWITCH, "on")

    clip_id = uuid4()
    key = f"t/{TENANT_ID}/generated/{uuid4()}/r1/video.mp4"
    block = ca.GeneratedSource(
        object_key=key,
        block_id=uuid4(),
        clip_id=clip_id,
        kind="presenter",
        revision=1,
        asset_id=uuid4(),
        provider="omnihuman",
        model_id="omnihuman-1.5",
        model_revision=None,
        seconds=4.0,
        pipeline_version="creative-v1",
    )
    brief = _clip(
        _joined(4.0, None),
        SourceSegment(key=key, start_s=0, end_s=4.0, speed=1),
        _joined(3.0, FADE, OTHER),
    )
    outcome = local.produce_local(
        tenant_id=TENANT_ID,
        draft_id=clip_id,
        brief=brief,
        store=None,
        save=None,
        beat=None,
        allowed=True,
        generated_sources={key: block},
    )
    assert outcome.detail == ca.AVATAR_JOIN_TEXT
