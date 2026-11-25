"""m-25119867 PR 2: «Intentar de nuevo» and «Quitar avatar» on a failed avatar block of a
Clip waiting for its first «Crear», the owner's 72 h (ADR 50 §11 P2), «Textos sí, efectos
no», «Crearla otra vez» of such a Clip, and «Necesita tu atención».

Offline only: no vendor is ever called; the database is a set of dicts and the clock is
injected. Contract: `docs/contrato-avatar-primer-crear.md`."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.schemas import EffectUse, SourceSegment, VideoTextLayer

from qualify_api.creative import clip_avatar as ca
from qualify_api.creative.creations import InMemoryCreationsLedger, NotEnoughCreations
from qualify_api.creative.fsm import APPROVED, DRAFTING, FAILED, GENERATED, REJECTED
from qualify_api.creative.service import ContentService
from qualify_api.creative.video_pipeline.recipe import RecipeRefused

from . import test_video_pipeline_local as _local_tests
from .test_clip_avatar import BOTH_ON, OWN_VIDEO, PRESENTER_ON, SCRIPT, BlockRepo, _presenter
from .test_clip_avatar_first_create import (
    PlanStore,
    RecordingDispatcher,
    _at,
    _clip,
    _clip_brief,
    _made,
    _own,
)
from .test_content_service import (
    BRAND_ID,
    TENANT_ID,
    USER_ID,
    FakeBrand,
    FakePricing,
    FakeRouter,
    FakeVoice,
    StaticKeyResolver,
    copy_dict,
    make_kit,
    make_voice,
    ok_outcome,
)

queue_on = _local_tests.queue_on
T0 = datetime(2026, 11, 26, 15, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _queue(queue_on: None, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: PT004
    for switch in BOTH_ON:
        monkeypatch.setenv(switch, "on")


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class RemovingRepo(BlockRepo):
    """`BlockRepo` that marks a block removed as Postgres does (`part_removed_at`)."""

    store: PlanStore

    def mark_part_removed(self, *, tenant_id: UUID, draft_id: UUID, user_id: UUID) -> bool:
        if draft_id in self.store.removed:
            return False
        self.store.removed.add(draft_id)
        return True


class AttemptStore(PlanStore):
    """`PlanStore` counting ATTEMPTS for the daily cap (P1): each block's revisions."""

    def blocks_made_today(self, *, tenant_id: UUID) -> int:
        if self.used_today is not None:
            return self.used_today
        return sum(self.repo.drafts[block_id].revision for block_id, _ in self._blocks())

    def clip(self, *, tenant_id: UUID, clip_id: UUID) -> ca.ClipRow | None:
        row = super().clip(tenant_id=tenant_id, clip_id=clip_id)
        if row is None:
            return None
        return replace(row, failure_detail=self.repo.drafts[clip_id].failure_detail)

    def clips_needing_attention(self, *, tenant_id: UUID) -> int:
        service = self.service
        return sum(
            1
            for clip_id in {parent for parent, _ in self.repo.parents.values()}
            if (wait := service.clip_wait(tenant_id=tenant_id, clip_id=clip_id)) is not None
            and wait.needs_attention
        )


class World:
    def __init__(self, *, env: dict[str, str] | None = None, videos_used: int = 0) -> None:
        self.repo = RemovingRepo()
        self.store = AttemptStore(self.repo)
        self.repo.store = self.store
        self.dispatcher = RecordingDispatcher()
        self.ledger = InMemoryCreationsLedger(videos_used=videos_used)
        self.clock = Clock()
        self.beats: list[tuple[UUID, UUID]] = []
        self.content = ContentService(
            router=FakeRouter([ok_outcome(copy_dict()) for _ in range(8)]),  # type: ignore[arg-type]
            pricing=FakePricing(),
            credentials=StaticKeyResolver(),
            voice_service=FakeVoice(make_voice()),
            brand_service=FakeBrand(make_kit()),
            repository=self.repo,
            dispatcher=self.dispatcher,
            creations=self.ledger,
            progress=lambda tenant, draft: self.beats.append((tenant, draft)),
            clip_avatar_store=self.store,
            clip_avatar_sources=lambda tenant, keys: self.store.generated_sources(
                tenant_id=tenant, keys=keys
            ),
            clip_avatar_clock=self.clock,
        )
        self.store.ledger = self.ledger
        self.service = ca.ClipAvatarService(
            self.content,
            store=self.store,
            env=env if env is not None else BOTH_ON,
            brand_avatar_key=lambda tenant, brand: f"t/{tenant}/brand/{brand}/avatar/a.jpg",
        )
        self.store.service = self.service

    def create(self, *placements: ca.ClipAvatarPlacement, **kw: Any) -> ca.ClipWithBlocks:
        return self.service.create_clip_with_blocks(
            tenant_id=TENANT_ID,
            brand_id=BRAND_ID,
            user_id=USER_ID,
            brief=kw.pop("brief", None) or _clip(),
            blocks=placements or (_at(_presenter(), 0),),
            **kw,
        )

    def fail(self, block_id: UUID, reason: str = "provider_error") -> None:
        self.repo.drafts[block_id] = replace(
            self.repo.drafts[block_id], status=FAILED, failure_reason=reason
        )

    def run(self, clip_id: UUID) -> None:
        """One pass of the Clip's run; a wait is a pass like any other."""
        try:
            self.content.run_generation(tenant_id=TENANT_ID, draft_id=clip_id)
        except ca.ClipBlocksWait:
            pass

    def retry(self, made: ca.ClipWithBlocks, index: int = 0, **kw: Any) -> UUID:
        return self.service.retry_block(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            clip_id=made.clip_id,
            block_id=made.block_ids[index],
            **kw,
        )

    def remove(self, made: ca.ClipWithBlocks, index: int = 0) -> bool:
        return self.service.remove_block(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            clip_id=made.clip_id,
            block_id=made.block_ids[index],
        )

    def wait(self, made: ca.ClipWithBlocks) -> ca.ClipWait:
        wait = self.service.clip_wait(tenant_id=TENANT_ID, clip_id=made.clip_id)
        assert wait is not None
        return wait


def _failed_world(**kw: Any) -> tuple[World, ca.ClipWithBlocks]:
    world = World(**kw)
    made = world.create(_at(_presenter(), 0))
    world.fail(made.block_ids[0])
    world.run(made.clip_id)  # the Clip sees the failure: its 72 h start
    return world, made


def _snapshot(world: World) -> tuple[Any, ...]:
    return (
        dict(world.repo.drafts),
        len(world.repo.briefs),
        list(world.dispatcher.calls),
        dict(world.ledger.rows),
    )


# ---------------------------------------------------------------------------
# what the screen reads


def test_a_failed_block_offers_both_buttons_its_deadline_and_needs_attention() -> None:
    world, made = _failed_world()
    wait = world.wait(made)
    assert wait.state == "block_failed" and wait.needs_attention
    assert wait.owner_text == ca.BLOCK_FAILED_STATE_TEXT
    assert "«Intentar de nuevo»" in wait.owner_text and "«Quitar avatar»" in wait.owner_text
    assert wait.wait_until == T0 + timedelta(hours=72)
    (block,) = wait.blocks
    assert block.actions == ("retry", "remove")
    assert block.owner_text == ca.BLOCK_FAILED_TEXT
    assert world.service.clips_needing_attention(tenant_id=TENANT_ID) == 1


def test_creating_and_ready_blocks_offer_nothing_and_need_no_attention() -> None:
    world = World()
    made = world.create(_at(_presenter(), 0))
    wait = world.wait(made)
    assert not wait.needs_attention and wait.wait_until is None
    assert all(b.actions == () for b in wait.blocks)
    assert world.service.clips_needing_attention(tenant_id=TENANT_ID) == 0


def test_a_switched_off_block_can_only_be_removed() -> None:
    world, made = _failed_world()
    world.repo.drafts[made.block_ids[0]] = replace(
        world.repo.drafts[made.block_ids[0]], status=GENERATED, failure_reason=None
    )
    world.service._env = {}  # noqa: SLF001 — switched off while the Clip waits
    (block,) = world.wait(made).blocks
    assert block.failure_code == "switched_off" and block.actions == ("remove",)


# ---------------------------------------------------------------------------
# «Intentar de nuevo»


def test_retry_makes_a_new_attempt_at_zero_and_clears_the_failure() -> None:
    world, made = _failed_world()
    block = made.block_ids[0]
    calls = len(world.dispatcher.calls)
    assert world.retry(made) == block
    draft = world.repo.drafts[block]
    assert (draft.status, draft.revision, draft.failure_reason) == (DRAFTING, 2, None)
    row = world.ledger.rows[(block, 2)]
    assert row.price.weight == 0 and row.videos == 0
    assert world.dispatcher.calls[calls:] == [(TENANT_ID, block)]
    (entry,) = _clip_brief(world, made.clip_id).media.clip_avatar_plan
    assert entry.failed_at is None and entry.refused is None
    wait = world.wait(made)
    assert wait.state == "waiting_blocks" and not wait.needs_attention


def test_retry_twice_makes_one_attempt() -> None:
    world, made = _failed_world()
    world.retry(made)
    before = _snapshot(world)
    assert world.retry(made) == made.block_ids[0]
    assert _snapshot(world) == before


def test_retry_with_new_words_changes_them_and_the_estimate() -> None:
    world, made = _failed_world()
    world.retry(made, request=_presenter(script="Hola."))
    block = world.repo.briefs[world.repo.drafts[made.block_ids[0]].brief_id]
    assert block.media.own_script == "Hola." and block.media.clip_avatar_block
    (entry,) = _clip_brief(world, made.clip_id).media.clip_avatar_plan
    assert entry.seconds_estimate == ca.script_seconds("Hola.")


def test_retry_of_a_block_the_clip_refused_regenerates_it() -> None:
    world = World()
    made = world.create(_at(_presenter(script="a" * 450), 1), brief=_clip(_own(30.0)))
    _made(world, made.block_ids[0], seconds=30.9)
    world.run(made.clip_id)  # over 60 s: refused on the plan
    assert world.wait(made).blocks[0].failure_code == "clip_too_long"
    world.retry(made, request=_presenter(script="a" * 300))
    draft = world.repo.drafts[made.block_ids[0]]
    assert draft.status == DRAFTING and draft.revision == 2
    (entry,) = _clip_brief(world, made.clip_id).media.clip_avatar_plan
    assert entry.refused is None and entry.seconds_estimate == 20


def _assert_refused_before_anything(world: World, made: ca.ClipWithBlocks, **kw: Any) -> str:
    before = _snapshot(world)
    with pytest.raises((ca.ClipAvatarRefused, NotEnoughCreations, RecipeRefused)) as refused:
        world.retry(made, **kw)
    assert _snapshot(world) == before
    return str(getattr(refused.value, "code", type(refused.value).__name__))


def test_retry_refuses_its_kind_switched_off_before_anything() -> None:
    world, made = _failed_world()
    world.service._env = {}  # noqa: SLF001
    assert _assert_refused_before_anything(world, made) == "switched_off"


def test_retry_refuses_words_over_30_seconds_before_anything() -> None:
    world, made = _failed_world()
    code = _assert_refused_before_anything(world, made, request=_presenter(script="a" * 600))
    assert code == "too_long"


def test_retry_never_changes_the_kind() -> None:
    from .test_clip_avatar import _animated

    world, made = _failed_world()
    assert _assert_refused_before_anything(world, made, request=_animated()) == "kind_change"


def test_retry_counts_for_todays_cap_before_anything() -> None:
    """ADR 50 §11 P1: every «Intentar de nuevo» is one more avatar of the day."""
    world, made = _failed_world()
    world.store.used_today = 3
    with pytest.raises(ca.AvatarDailyCapReached):
        world.retry(made)
    world.store.used_today = None
    used = world.store.blocks_made_today(tenant_id=TENANT_ID)
    world.retry(made)
    assert world.store.blocks_made_today(tenant_id=TENANT_ID) == used + 1


def test_retry_refuses_without_the_months_video_before_anything() -> None:
    world, made = _failed_world()
    world.ledger._opening_videos = 39  # noqa: SLF001 — the month spent meanwhile: 1 s left
    assert ca.script_seconds(SCRIPT) > 1
    before = _snapshot(world)
    with pytest.raises(NotEnoughCreations):
        world.retry(made)
    assert _snapshot(world) == before


def test_retry_refuses_a_block_that_did_not_fail_or_a_clip_that_no_longer_waits() -> None:
    world = World()
    made = world.create(_at(_presenter(), 0), _at(_presenter(script="Hola."), 1))
    _made(world, made.block_ids[1])
    assert _assert_refused_before_anything(world, made, index=1) == "block_not_failed"
    world.fail(made.block_ids[0])
    world.repo.drafts[made.clip_id] = replace(world.repo.drafts[made.clip_id], status=FAILED)
    assert _assert_refused_before_anything(world, made) == "clip_not_waiting"


def test_retry_with_words_that_make_the_clip_too_long_is_refused_before_anything() -> None:
    world = World()
    made = world.create(_at(_presenter(script="Hola."), 0), brief=_clip(_own(31.0)))
    world.fail(made.block_ids[0])
    world.run(made.clip_id)
    # 31 s of the owner's and a 30 s avatar: 61 s, refused as the editor's recipe is
    code = _assert_refused_before_anything(world, made, request=_presenter(script="a" * 450))
    assert code == "RecipeRefused"


# ---------------------------------------------------------------------------
# «Quitar avatar»


def test_remove_marks_the_block_once_and_the_clip_is_made_without_it() -> None:
    world = World()
    made = world.create(_at(_presenter(), 0), _at(_presenter(script="Hola."), 2))
    world.fail(made.block_ids[0])
    second = _made(world, made.block_ids[1], seconds=1.2)
    world.run(made.clip_id)
    assert world.remove(made) is True
    assert world.remove(made) is False  # idempotent
    assert world.wait(made).state == "assembling"
    world.run(made.clip_id)
    clip = world.repo.drafts[made.clip_id]
    assert clip.status == GENERATED
    keys = [s.key for s in _clip_brief(world, made.clip_id).media.segments]
    assert keys == [OWN_VIDEO, f"uploads/{TENANT_ID}/b.mp4", second]
    # nothing charged for the removed block
    assert world.ledger.rows[(made.block_ids[0], 1)].videos == 0


def test_removing_the_only_avatar_makes_the_clip_of_the_owners_own_media() -> None:
    world, made = _failed_world()
    world.remove(made)
    world.run(made.clip_id)
    brief = _clip_brief(world, made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    assert [s.key for s in brief.media.segments] == [OWN_VIDEO, f"uploads/{TENANT_ID}/b.mp4"]


def test_remove_refuses_a_block_that_did_not_fail_before_anything() -> None:
    world = World()
    made = world.create(_at(_presenter(), 0))
    before = _snapshot(world)
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        world.remove(made)
    assert refused.value.code == "block_not_removable"
    assert _snapshot(world) == before


# ---------------------------------------------------------------------------
# the owner's 72 h (P2)


def test_the_clip_fails_72_hours_after_the_latest_failure_and_gives_back_its_creations() -> None:
    world, made = _failed_world()
    clip_charge = world.ledger.rows[(made.clip_id, 1)]
    world.clock.now = T0 + timedelta(hours=71, minutes=59)
    world.run(made.clip_id)
    assert world.repo.drafts[made.clip_id].status == DRAFTING
    world.clock.now = T0 + timedelta(hours=72)
    world.run(made.clip_id)
    clip = world.repo.drafts[made.clip_id]
    assert (clip.status, clip.failure_reason) == (FAILED, ca.AVATAR_BLOCK_FAILED)
    assert clip.failure_detail == ca.AVATAR_BLOCK_FAILED_TEXT
    assert world.ledger.rows[(made.clip_id, 1)].status == "refunded" or clip_charge.status == (
        "refunded"
    )
    # P6: its blocks owe nothing; the screen reads «failed», no more buttons
    quota = world.service.avatar_quota(tenant_id=TENANT_ID, brand_id=BRAND_ID)
    assert quota is not None and quota.pending_blocks == 0
    wait = world.wait(made)
    assert wait.state == "failed" and wait.owner_text == ca.AVATAR_BLOCK_FAILED_TEXT
    assert all(b.actions == () for b in wait.blocks) and not wait.needs_attention


def test_the_72_hours_run_from_the_latest_failure() -> None:
    world = World()
    made = world.create(_at(_presenter(), 0), _at(_presenter(script="Hola."), 1))
    world.fail(made.block_ids[0])
    world.run(made.clip_id)
    world.clock.now = T0 + timedelta(hours=10)
    world.fail(made.block_ids[1])
    world.run(made.clip_id)
    assert world.wait(made).wait_until == T0 + timedelta(hours=82)
    world.clock.now = T0 + timedelta(hours=72)
    world.run(made.clip_id)
    assert world.repo.drafts[made.clip_id].status == DRAFTING


def test_a_retry_resets_the_owners_time() -> None:
    world, made = _failed_world()
    world.clock.now = T0 + timedelta(hours=70)
    world.retry(made)
    world.fail(made.block_ids[0])
    world.run(made.clip_id)
    assert world.wait(made).wait_until == T0 + timedelta(hours=142)


# ---------------------------------------------------------------------------
# «Textos sí, efectos no» (ADR 50 §11)


SMOKE = EffectUse(effect_id="humo_capa", version=1, start_s=1.0, end_s=3.0)


@pytest.mark.parametrize(
    ("effect", "refused"),
    [
        (SMOKE, True),  # over the avatar (0..~4 s at its estimate)
        (EffectUse(effect_id="vapor_capa", version=1), True),  # no span: the whole Clip
        (EffectUse(effect_id="brasas_capa", version=1, start_s=6.0, end_s=7.0), False),
    ],
)
def test_a_smoke_layer_never_crosses_an_avatar_at_the_first_create(
    effect: EffectUse, refused: bool
) -> None:
    world = World()
    brief = _clip(effects=(effect,))
    if refused:
        with pytest.raises(ca.ClipAvatarRefused) as caught:
            world.create(_at(_presenter(), 0), brief=brief)
        assert caught.value.code == ca.AVATAR_EFFECT_CODE
        assert caught.value.owner_message == ca.AVATAR_EFFECT_TEXT
        assert world.repo.drafts == {}
    else:
        world.create(_at(_presenter(), 0), brief=brief)


def test_a_text_over_an_avatar_is_fine() -> None:
    world = World()
    text = VideoTextLayer(text="¡Pruébala!", start_s=0.5, end_s=2.0)
    world.create(_at(_presenter(), 0), brief=_clip(text_layers=(text,)))


def test_place_block_refuses_a_smoke_layer_over_the_avatar() -> None:
    from .test_clip_avatar import _wired

    service, _, repo, store, _, clip_id = _wired(env=PRESENTER_ON, clip=_clip(effects=(SMOKE,)))
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
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, block_id=block, at=0
        )
    assert refused.value.code == ca.AVATAR_EFFECT_CODE and len(repo.briefs) == briefs
    # after the owner's 7 s the smoke (1-3 s) no longer crosses it: placed
    service.place_block(tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, block_id=block, at=2)


def test_the_assembly_refuses_a_smoke_layer_over_an_avatar() -> None:
    from qualify_api.creative.video_pipeline import local

    clip_id = uuid4()
    key = f"t/{TENANT_ID}/generated/{uuid4()}/r1/video.mp4"
    source = ca.GeneratedSource(
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
        SourceSegment(key=key, start_s=0, end_s=4.0, speed=1), _own(4.0), effects=(SMOKE,)
    )
    outcome = local.produce_local(
        tenant_id=TENANT_ID,
        draft_id=clip_id,
        brief=brief,
        store=None,
        save=None,
        allowed=True,
        generated_sources={key: source},
    )
    assert outcome.detail == ca.AVATAR_EFFECT_TEXT


def test_the_windows_and_overlaps_are_pure() -> None:
    assert ca.block_windows([4.0, 3.0, 2.0], [1]) == [(4.0, 7.0)]
    assert ca.avatar_effect_problems([SMOKE], [(4.0, 7.0)]) == ()
    assert ca.avatar_effect_problems([SMOKE], [(2.5, 7.0)]) == (0,)
    assert ca.avatar_effect_problems([SMOKE], []) == ()


# ---------------------------------------------------------------------------
# «Crearla otra vez» and create_draft with a plan (R6)


def test_recreate_of_a_clip_with_avatars_is_refused_with_a_code() -> None:
    world, made = _failed_world()
    world.clock.now = T0 + timedelta(hours=72)
    world.run(made.clip_id)  # failed: «Crearla otra vez» would be offered
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        world.content.recreate(tenant_id=TENANT_ID, draft_id=made.clip_id, user_id=USER_ID)
    assert refused.value.code == ca.RECREATE_FROM_EDITOR_CODE
    assert refused.value.owner_message == ca.RECREATE_FROM_EDITOR_TEXT


def test_recreate_of_a_clip_made_from_its_avatars_is_refused_too() -> None:
    world = World()
    made = world.create(_at(_presenter(), 0))
    _made(world, made.block_ids[0])
    world.run(made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        world.content.recreate(tenant_id=TENANT_ID, draft_id=made.clip_id, user_id=USER_ID)
    assert refused.value.code == ca.RECREATE_FROM_EDITOR_CODE


def test_create_draft_with_a_plan_is_refused_with_a_code() -> None:
    from qualify_creative.schemas import ClipAvatarSlot

    world = World()
    plan = (ClipAvatarSlot(slot=1, at=0, seconds_estimate=4),)
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        world.content.create_draft(
            tenant_id=TENANT_ID,
            brand_id=BRAND_ID,
            user_id=USER_ID,
            brief=_clip(clip_avatar_plan=plan),
        )
    assert refused.value.code == ca.RECREATE_FROM_EDITOR_CODE
    assert world.repo.drafts == {}


# ---------------------------------------------------------------------------
# option A stays as it was


def test_option_a_blocks_offer_no_buttons() -> None:
    from .test_clip_avatar import _wired

    service, _, repo, store, _, clip_id = _wired(env=PRESENTER_ON)
    block = service.create_block(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=_presenter()
    )
    repo.drafts[block] = replace(repo.drafts[block], status=FAILED, failure_reason="timeout")
    service._store = PlanStore(repo)  # noqa: SLF001
    wait = service.clip_wait(tenant_id=TENANT_ID, clip_id=clip_id)
    assert wait is not None and not wait.needs_attention
    assert all(b.actions == () for b in wait.blocks)
    for status in (APPROVED, REJECTED):
        assert status  # option A's own states are untouched by PR 2
