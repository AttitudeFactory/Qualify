"""m-25129408 (ADR 50 §13.4 with §12.4) and m-25128784 PR 3: a Clip with AI children —
character scenes and «parte con IA» — approved on ONE path (their seconds charged once,
their 1080p finals ordered, the Clip assembled again with them), and «Intentar de nuevo»
/ «Quitar escena» of a failed scene.

Offline only: no vendor is called; the repository, the ledger and the scenes' rows are
the in-memory doubles of the scene and AI-part suites."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.creations import weight_for

from qualify_api.creative import character_scene as cs
from qualify_api.creative import clip_final as cf
from qualify_api.creative.character_scene_actions import (
    SCENE_NOT_FAILED,
    SCENE_NOT_REMOVABLE,
    CharacterSceneActions,
)
from qualify_api.creative.clip_avatar import ClipAvatarRefused
from qualify_api.creative.creations import InMemoryCreationsLedger, NotEnoughCreations
from qualify_api.creative.draft_mode import draft_state
from qualify_api.creative.fsm import APPROVED, DRAFTING, FAILED, GENERATED
from qualify_api.creative.media import MediaOutcome, MediaWrite
from qualify_api.creative.service import ContentService, ImageRecord, VariantRecord
from qualify_api.mail import clip_avatar as mail_words

from . import test_clip_ai_parts as ai
from .test_character_scene import (
    NOW,
    SCENE_ON,
    Characters,
    SceneRows,
    SceneStore,
    _clip,
    _item,
)
from .test_clip_avatar import BlockRepo
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
    make_kit,
    make_voice,
    ok_outcome,
)


@pytest.fixture(autouse=True)
def _switches(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scene switch on (as the scene suite) and the creative queue on: a local Clip
    never runs inline (EF-06)."""
    from qualify_api.creative.video_pipeline.ai_parts import CLIP_AI_PARTS_SWITCH

    from .test_video_pipeline_local import SWITCH

    monkeypatch.setenv(cs.SCENE_SWITCH, "on")
    monkeypatch.setenv(SWITCH, "queue")
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "on")


# ---------------------------------------------------------------------------
# doubles


class FinalsDispatcher(RecordingDispatcher):
    """Records the generations AND the finals ordered (`dispatch_finalize`)."""

    def __init__(self) -> None:
        super().__init__()
        self.finals: list[UUID] = []

    def dispatch_finalize(self, *, tenant_id: UUID, draft_id: UUID) -> None:
        self.finals.append(draft_id)


def _wire_children(repo: Any) -> None:
    """What Postgres answers and the plain doubles lack: a parent's children without the
    removed ones (`parts_of`) and the draft block of a video (`set_video_draft`)."""
    if not hasattr(repo, "removed"):
        repo.removed = set()

    def parts_of(*, tenant_id: UUID, parent_id: UUID) -> tuple[Any, ...]:
        found = sorted(
            (slot, draft_id)
            for draft_id, (parent, slot) in repo.parents.items()
            if parent == parent_id and draft_id not in repo.removed
        )
        return tuple(repo.drafts[draft_id] for _, draft_id in found)

    def set_video_draft(*, tenant_id: UUID, asset_id: UUID, changes: Any) -> None:
        for draft_id, items in repo.media.items():
            repo.media[draft_id] = [
                replace(
                    item,
                    params={
                        **(item.params or {}),
                        "draft": {**(draft_state(item.params) or {}), **changes},
                    },
                )
                if item.id == asset_id
                else item
                for item in items
            ]

    repo.parts_of = parts_of
    repo.set_video_draft = set_video_draft


class SceneRepo(BlockRepo):
    def __init__(self) -> None:
        super().__init__()
        self.removed: set[UUID] = set()
        _wire_children(self)

    def mark_part_removed(self, *, tenant_id: UUID, draft_id: UUID, user_id: UUID) -> bool:
        if draft_id in self.removed:
            return False
        self.removed.add(draft_id)
        return True


class Rows(SceneRows):
    """The scenes' rows, with the ones their owner removed marked."""

    def scene_rows(self, *, tenant_id: UUID, clip_id: UUID) -> tuple[cs.SceneRow, ...]:
        rows = super().scene_rows(tenant_id=tenant_id, clip_id=clip_id)
        return tuple(replace(row, removed=row.id in self.repo.removed) for row in rows)


@dataclass
class MemoryClipFinal:
    """`clip_final.ClipFinalStore` over the in-memory repository."""

    repo: Any
    opened: list[UUID] = field(default_factory=list)
    saved: list[Any] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def open(self, *, tenant_id: UUID, clip_id: UUID) -> None:
        self.opened.append(clip_id)

    def save(
        self, *, tenant_id: UUID, clip_id: UUID, asset_id: UUID, revision: int, write: Any
    ) -> bool:
        (video,) = [m for m in self.repo.media[clip_id] if m.id == asset_id]
        block = draft_state(video.params) or {}
        if block.get("status") != cf.CLIP_FINAL_PENDING:
            return False
        self.saved.append(write)
        self.repo.media[clip_id] = [
            replace(
                video, object_key=write.object_key, media_url=write.media_url, params=write.params
            )
        ]
        return True

    def fail(self, *, tenant_id: UUID, clip_id: UUID, asset_id: UUID, error: str) -> bool:
        self.failed.append(error)
        self.repo.set_video_draft(
            tenant_id=tenant_id,
            asset_id=asset_id,
            changes={"status": cf.CLIP_FINAL_FAILED, "error": error},
        )
        return True


class Assembler:
    """The media producer's `assemble_clip_final`: records what it was asked."""

    def __init__(self, outcome: MediaOutcome | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.outcome = outcome

    def assemble_clip_final(self, **kw: Any) -> tuple[MediaOutcome, str | None]:
        self.calls.append(kw)
        if self.outcome is not None:
            return self.outcome, None
        key = f"t/{TENANT_ID}/generated/{kw['draft_id']}/r1/final-local.mp4"
        write = MediaWrite(
            position=0,
            media_type="video",
            media_url=key,
            object_key=key,
            width=1080,
            height=1920,
            aspect_ratio="9:16",
            model_id="local",
            provider="local",
            ai_generated=True,
            params={"local": {"recipe_version": 1}, "thumbnail_key": None},
        )
        return MediaOutcome(media=(write,)), "f" * 64


@dataclass
class World:
    content: ContentService
    actions: CharacterSceneActions
    repo: SceneRepo
    rows: Rows
    store: SceneStore
    dispatcher: FinalsDispatcher
    ledger: InMemoryCreationsLedger
    finals: MemoryClipFinal
    media: Assembler


def _world(*, videos_used: int = 0, media: Any = None) -> World:
    repo, dispatcher = SceneRepo(), FinalsDispatcher()
    store, rows = SceneStore(repo), Rows(repo)
    ledger = InMemoryCreationsLedger(videos_used=videos_used)
    finals = MemoryClipFinal(repo)
    assembler = media or Assembler()
    content = ContentService(
        router=FakeRouter([ok_outcome(copy_dict()) for _ in range(6)]),  # type: ignore[arg-type]
        pricing=FakePricing(),
        credentials=StaticKeyResolver(),
        voice_service=FakeVoice(make_voice()),
        brand_service=FakeBrand(make_kit()),
        repository=repo,
        dispatcher=dispatcher,
        creations=ledger,
        media=assembler,
        character_scene_store=rows,
        clip_final_store=finals,
        clip_avatar_clock=lambda: NOW,
    )
    actions = CharacterSceneActions(
        content, references=Characters(), store=store, rows=rows, env=SCENE_ON, clock=lambda: NOW
    )
    return World(content, actions, repo, rows, store, dispatcher, ledger, finals, assembler)


def _set(repo: Any, draft_id: UUID, **change: Any) -> None:
    repo.drafts[draft_id] = replace(repo.drafts[draft_id], **change)


def _variant(repo: Any, draft_id: UUID) -> UUID:
    variant_id = uuid4()
    repo.variants[variant_id] = VariantRecord(
        id=variant_id,
        draft_id=draft_id,
        ordinal=0,
        copy={"hook": "", "caption": "", "script": ""},
        edited_copy=None,
        fidelity={"passed": True, "hard_failures": []},
        model_id="none",
        model_revision=None,
    )
    return variant_id


def _video(key: str, params: dict[str, Any], asset_id: UUID | None = None) -> ImageRecord:
    return ImageRecord(
        id=asset_id or uuid4(),
        media_url=key,
        width=480,
        height=854,
        aspect_ratio="9:16",
        media_type="video",
        position=0,
        params=params,
        object_key=key,
    )


def _draft(**over: Any) -> dict[str, Any]:
    """A 480p draft block as `_with_draft` writes it (made now: not expired)."""
    return {
        "status": "draft",
        "task_id": "cgt-draft",
        "created_at": time.time(),
        "model": cs.SCENE_MODEL,
        "duration_seconds": 5,
        "finish": "video",
        **over,
    }


@dataclass
class SceneClip:
    clip_id: UUID
    scene_id: UUID
    variant_id: UUID
    scene_asset: UUID
    scene_key: str
    clip_key: str


def _made_scene_clip(world: World, *, duration: int = 5) -> SceneClip:
    """A Clip whose one scene came out (480p draft) and that was assembled with it."""
    made = world.actions.create_clip_with_scenes(
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        user_id=USER_ID,
        brief=_clip(_item(duration=duration)),
    )
    (scene_id,) = made.scene_ids
    repo = world.repo
    scene_asset = uuid4()
    scene_key = f"t/{TENANT_ID}/generated/{scene_id}/r1/scene.mp4"
    _set(repo, scene_id, status=GENERATED)
    _variant(repo, scene_id)
    repo.media[scene_id] = [
        _video(
            scene_key,
            {"prompt_version": cs.SCENE_PROMPT_VERSION, "draft": _draft(duration_seconds=duration)},
            scene_asset,
        )
    ]
    world.rows.videos[scene_id] = (scene_asset, scene_key, {"resolution": "480p"})
    clip_key = f"t/{TENANT_ID}/generated/{made.clip_id}/r1/local.mp4"
    _set(repo, made.clip_id, status=GENERATED)
    variant_id = _variant(repo, made.clip_id)
    repo.media[made.clip_id] = [
        _video(
            clip_key,
            {
                "local": {
                    "character_scenes": [{"draft_id": str(scene_id), "asset_id": str(scene_asset)}]
                }
            },
        )
    ]
    return SceneClip(made.clip_id, scene_id, variant_id, scene_asset, scene_key, clip_key)


def _approve(world: World, made: SceneClip) -> None:
    world.content.approve(
        tenant_id=TENANT_ID, draft_id=made.clip_id, variant_id=made.variant_id, user_id=USER_ID
    )


def _used(world: World) -> int:
    return world.ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).videos_used


def _block(world: World, draft_id: UUID) -> dict[str, Any]:
    (video,) = world.repo.media[draft_id]
    return dict(draft_state(video.params) or {})


def _scene_seconds(world: World, seconds: int) -> int:
    balance = world.ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID)
    return seconds if balance.video_in_seconds else 1


# ---------------------------------------------------------------------------
# approving a Clip with a character scene


def test_approving_charges_the_scene_seconds_once_and_orders_its_final() -> None:
    world = _world()
    made = _made_scene_clip(world, duration=7)
    before = _used(world)
    _approve(world, made)
    assert world.repo.drafts[made.clip_id].status == APPROVED
    assert world.repo.drafts[made.scene_id].status == APPROVED
    assert _used(world) - before == _scene_seconds(world, 7)
    # the scene's 1080p ordered, paid by the revision that was charged
    block = _block(world, made.scene_id)
    assert block["status"] in ("rendering", "final_scheduled")
    assert block["charge_revision"] == 1 and block["final_origin"] == "approval"
    assert world.dispatcher.finals == [made.scene_id]
    # the Clip waits for its final, out of the calendar meanwhile
    clip = _block(world, made.clip_id)
    assert clip["finish"] == cf.FINISH_CLIP_FINAL and clip["status"] == cf.CLIP_FINAL_PENDING
    assert clip["approved_revision"] == 1 and clip["preview_object_key"] == made.clip_key
    assert world.finals.opened == [made.clip_id]


def test_approving_twice_charges_and_orders_nothing_more() -> None:
    world = _world()
    made = _made_scene_clip(world)
    _approve(world, made)
    used, rows = _used(world), dict(world.ledger.rows)
    _approve(world, made)
    assert _used(world) == used and world.ledger.rows == rows
    assert world.dispatcher.finals == [made.scene_id]


def test_without_the_seconds_nothing_is_written_nor_ordered() -> None:
    world = _world()
    made = _made_scene_clip(world, duration=5)
    # meanwhile another video took the month down to 4 seconds
    balance = world.ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID)
    assert balance.video_in_seconds
    world.ledger.charge_videos(
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        draft_id=uuid4(),
        revision=1,
        videos=1,
        seconds=balance.videos_left - 4,
    )
    before = _used(world)
    with pytest.raises(NotEnoughCreations):
        _approve(world, made)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    assert world.repo.drafts[made.scene_id].status == GENERATED
    assert _used(world) == before
    assert _block(world, made.clip_id) == {}
    assert _block(world, made.scene_id)["status"] == "draft"
    assert world.dispatcher.finals == []


def test_a_scene_the_clip_does_not_play_is_never_charged() -> None:
    world = _world()
    made = _made_scene_clip(world)
    # the scene was made again since the Clip was put together: another video row
    (video,) = world.repo.media[made.scene_id]
    world.repo.media[made.scene_id] = [replace(video, id=uuid4())]
    before = _used(world)
    with pytest.raises(ClipAvatarRefused) as refused:
        _approve(world, made)
    assert refused.value.code == cf.CHILDREN_CHANGED
    assert _used(world) == before and world.repo.drafts[made.clip_id].status == GENERATED


def test_a_scene_still_being_made_waits() -> None:
    world = _world()
    made = _made_scene_clip(world)
    _set(world.repo, made.scene_id, status=DRAFTING)
    with pytest.raises(ClipAvatarRefused) as refused:
        _approve(world, made)
    assert refused.value.code == cf.CHILDREN_NOT_READY
    assert world.ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).videos_used == 0


def test_approval_videos_announces_the_scene_seconds() -> None:
    world = _world()
    made = _made_scene_clip(world, duration=8)
    announced = world.content.approval_videos(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert announced is not None
    assert announced[0] == _scene_seconds(world, 8)


# ---------------------------------------------------------------------------
# a final that fails: its seconds back, «Intentar de nuevo»


def test_a_failed_final_gives_its_seconds_back_and_the_clip_waits_for_a_retry() -> None:
    world = _world()
    made = _made_scene_clip(world, duration=6)
    before = _used(world)
    _approve(world, made)
    # the vendor failed the scene's 1080p: what `_settle_final` does
    world.repo.set_video_draft(
        tenant_id=TENANT_ID, asset_id=made.scene_asset, changes={"status": "failed"}
    )
    world.content._refund_final_part(  # noqa: SLF001
        TENANT_ID, made.scene_id, "final_failed", (made.scene_asset,)
    )
    assert _used(world) == before
    view = world.content.clip_final_view(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert view.state == "failed" and view.can_retry
    assert view.failed_children == (made.scene_id,)
    assert "Intentar de nuevo" in view.owner_text
    # «Intentar de nuevo»: ordered again, never charged again
    world.content.retry_final(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.dispatcher.finals == [made.scene_id, made.scene_id]
    assert _used(world) == before
    assert _block(world, made.scene_id)["status"] in ("rendering", "final_scheduled")
    view = world.content.clip_final_view(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert view.state == "waiting"


# ---------------------------------------------------------------------------
# the Clip assembled again with the finals


def _scene_final_kept(world: World, made: SceneClip) -> str:
    """What `settle_final` writes for a scene: its final in place of the draft's file."""
    final_key = f"t/{TENANT_ID}/generated/{made.scene_id}/r1/scene-final-a.mp4"
    (video,) = world.repo.media[made.scene_id]
    world.repo.media[made.scene_id] = [
        replace(
            video,
            object_key=final_key,
            params={
                **(video.params or {}),
                "draft": {
                    **(draft_state(video.params) or {}),
                    "status": "final_ready",
                    "final_object_key": final_key,
                    "draft_object_key": made.scene_key,
                    "final_task_id": "cgt-final",
                    "final_cost_usd": "2.84",
                },
            },
        )
    ]
    return final_key


def test_nothing_is_assembled_while_a_final_is_on_its_way() -> None:
    world = _world()
    made = _made_scene_clip(world)
    _approve(world, made)
    assert world.content.run_clip_final(tenant_id=TENANT_ID, clip_id=made.clip_id) is False
    assert world.media.calls == [] and world.finals.saved == []


def test_every_final_kept_assembles_the_clip_again_with_their_provenance() -> None:
    world = _world()
    made = _made_scene_clip(world)
    _approve(world, made)
    final_key = _scene_final_kept(world, made)
    assert world.content.run_clip_final(tenant_id=TENANT_ID, clip_id=made.clip_id) is True
    (call,) = world.media.calls
    assert call["aliases"] == {} and call["revision"] == 1
    (write,) = world.finals.saved
    block = write.params["draft"]
    assert block["status"] == "final_ready" and block["final_sha256"] == "f" * 64
    assert block["preview_object_key"] == made.clip_key
    assert block["confirmed_by"] is None  # the owner reviews it before scheduling
    (child,) = write.params["clip_final"]["children"]
    assert child["kind"] == "scene" and child["final_object_key"] == final_key
    assert child["preview_object_key"] == made.scene_key
    assert child["final_task_id"] == "cgt-final"
    view = world.content.clip_final_view(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert view.state == "ready"
    # idempotent: assembled once
    assert world.content.run_clip_final(tenant_id=TENANT_ID, clip_id=made.clip_id) is False
    assert len(world.media.calls) == 1


def test_an_assembly_that_fails_keeps_the_preview_and_offers_a_retry() -> None:
    failed = MediaOutcome(failure="render_error", detail="x")
    world = _world(media=Assembler(failed))
    made = _made_scene_clip(world)
    _approve(world, made)
    _scene_final_kept(world, made)
    assert world.content.run_clip_final(tenant_id=TENANT_ID, clip_id=made.clip_id) is False
    (video,) = world.repo.media[made.clip_id]
    assert video.object_key == made.clip_key  # the preview stays
    assert world.finals.failed == [cf.CLIP_FINAL_FAILED_TEXT]
    view = world.content.clip_final_view(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert view.state == "failed" and view.can_retry
    world.content.retry_final(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert _block(world, made.clip_id)["status"] == cf.CLIP_FINAL_PENDING
    assert world.finals.opened[-1] == made.clip_id


# ---------------------------------------------------------------------------
# a Clip with «parte con IA» children: the same path


def test_approving_a_clip_with_ai_parts_charges_each_part_and_orders_its_final() -> None:
    world = ai._world()
    made = ai._create(world)
    keys = {part_id: ai._made(world, part_id) for part_id in made.part_ids}
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    _wire_children(world.repo)
    dispatcher = FinalsDispatcher()
    world.content.dispatcher = dispatcher
    world.content._clip_final_store = MemoryClipFinal(world.repo)  # noqa: SLF001
    for part_id, key in keys.items():
        _variant(world.repo, part_id)
        world.repo.media[part_id] = [_video(key, {"draft": _draft(finish="clip")})]
    world.repo.media[made.clip_id] = [_video(f"t/{TENANT_ID}/generated/c/r1/local.mp4", {})]
    (variant,) = world.repo.variants_for(tenant_id=TENANT_ID, draft_id=made.clip_id)[:1]
    assert world.ledger is not None
    before = world.ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).videos_used
    expected = 0
    for part_id in made.part_ids:
        price = weight_for(world.repo.briefs[world.repo.drafts[part_id].brief_id])
        balance = world.ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID)
        expected += price.video_seconds if balance.video_in_seconds else price.videos
    world.content.approve(
        tenant_id=TENANT_ID, draft_id=made.clip_id, variant_id=variant.id, user_id=USER_ID
    )
    after = world.ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).videos_used
    assert after - before == expected > 0
    assert sorted(dispatcher.finals) == sorted(made.part_ids)
    for part_id in made.part_ids:
        assert world.repo.drafts[part_id].status == APPROVED
    # twice: nothing more
    world.content.approve(
        tenant_id=TENANT_ID, draft_id=made.clip_id, variant_id=variant.id, user_id=USER_ID
    )
    assert world.ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).videos_used == after
    assert len(dispatcher.finals) == len(made.part_ids)


def test_the_final_brief_plays_each_parts_1080p_with_the_same_cut() -> None:
    preview = f"t/{TENANT_ID}/generated/p/r1/video.mp4"
    final = f"t/{TENANT_ID}/generated/p/r1/raw-1080.mp4"
    brief = ai._clip(segments=(ai._own(4.0), ai._own(3.0, preview)), entries=())
    swapped = cf.final_brief(
        brief,
        {
            preview: cf.ChildFinal(
                kind="ai_part",
                draft_id=uuid4(),
                slot=1,
                revision=1,
                asset_id=uuid4(),
                preview_key=preview,
                final_key=final,
                seconds=2.5,
            )
        },
    )
    own, part = swapped.media.segments
    assert own == brief.media.segments[0]
    assert part.key == final and part.start_s == 0 and part.end_s == 2.5  # ends with its file
    assert part.transition_in == brief.media.segments[1].transition_in


# ---------------------------------------------------------------------------
# the pure rules


def test_a_childs_final_state_reads_its_block() -> None:
    assert (
        cf.child_final_state({"draft": {"status": "part_final", "part_final_key": "k"}}) == "kept"
    )
    assert (
        cf.child_final_state({"draft": {"status": "final_ready", "final_object_key": "k"}})
        == "kept"
    )
    assert cf.child_final_state({"draft": {"status": "failed"}}) == "failed"
    rendering = {"draft": {"status": "rendering", "rendering_at": time.time()}}
    assert cf.child_final_state(rendering) == "waiting"
    assert (
        cf.child_final_key({"draft": {"status": "part_final", "part_final_key": "raw"}}, "p")
        == "raw"
    )
    assert cf.child_final_key({"draft": {"status": "final_ready"}}, "final") == "final"


def test_the_new_texts_are_plain_spanish() -> None:
    from qualify_api.creative import character_scene_actions as actions

    texts = [
        cf.CHILDREN_NOT_READY_TEXT,
        cf.CHILDREN_CHANGED_TEXT,
        cf.CLIP_FINAL_FAILED_TEXT,
        cf.WAITING_TEXT,
        cf.CHILD_FINAL_FAILED_TEXT,
        cf.READY_TEXT,
        actions.CLIP_NOT_WAITING_TEXT,
        actions.SCENE_NOT_FAILED_TEXT,
        actions.SCENE_NOT_REMOVABLE_TEXT,
    ]
    for text in texts:
        lowered = text.lower()
        for english in ("avatar", "clip", "draft", "preview", "seedance", "render", "scene"):
            assert english not in lowered, (english, text)


# ---------------------------------------------------------------------------
# «Intentar de nuevo» and «Quitar escena» of a failed scene (m-25128784 PR 3)


def _waiting_with_a_failed_scene(world: World, **failure: Any) -> tuple[UUID, UUID]:
    made = world.actions.create_clip_with_scenes(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, user_id=USER_ID, brief=_clip(_item())
    )
    (scene_id,) = made.scene_ids
    _set(
        world.repo,
        scene_id,
        status=FAILED,
        failure_reason=failure.get("reason", "provider_error"),
    )
    return made.clip_id, scene_id


def test_the_actions_carry_the_words_of_the_failure_email() -> None:
    from qualify_api.creative import character_scene_actions as actions

    assert f"«{actions.RETRY_LABEL}»" in mail_words.SCENE_LEAD
    assert f"«{actions.REMOVE_LABEL}»" in mail_words.SCENE_LEAD


def test_retrying_a_failed_scene_makes_a_new_attempt_with_one_vista_previa() -> None:
    world = _world()
    clip_id, scene_id = _waiting_with_a_failed_scene(world)
    clip_brief = world.repo.briefs[world.repo.drafts[clip_id].brief_id]
    stamped = clip_brief.model_copy(
        update={
            "media": clip_brief.media.model_copy(
                update={
                    "character_scenes": (
                        clip_brief.media.character_scenes[0].model_copy(update={"failed_at": NOW}),
                    )
                }
            )
        }
    )
    world.repo.briefs[world.repo.drafts[clip_id].brief_id] = stamped
    previews = world.ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).previews_used
    calls = len(world.dispatcher.calls)
    assert (
        world.actions.retry_scene(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, scene_id=scene_id
        )
        == scene_id
    )
    scene = world.repo.drafts[scene_id]
    assert scene.status == DRAFTING and scene.revision == 2
    assert (
        world.ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).previews_used == previews + 1
    )
    assert (scene_id, 2) in world.ledger.rows
    assert world.dispatcher.calls[calls:] == [(TENANT_ID, scene_id)]
    (item,) = world.repo.briefs[world.repo.drafts[clip_id].brief_id].media.character_scenes
    assert item.failed_at is None  # a new failure is stamped and mailed again
    # a double tap while it is being made: nothing more
    world.actions.retry_scene(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, scene_id=scene_id
    )
    assert (
        world.ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).previews_used == previews + 1
    )


def test_retrying_a_scene_that_did_not_fail_is_refused() -> None:
    world = _world()
    made = world.actions.create_clip_with_scenes(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, user_id=USER_ID, brief=_clip(_item())
    )
    (scene_id,) = made.scene_ids
    _set(world.repo, scene_id, status=GENERATED)
    with pytest.raises(ClipAvatarRefused) as refused:
        world.actions.retry_scene(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, scene_id=scene_id
        )
    assert refused.value.code == SCENE_NOT_FAILED


def test_a_scene_refused_as_a_real_face_is_not_tried_again() -> None:
    world = _world()
    clip_id, scene_id = _waiting_with_a_failed_scene(world, reason=cs.NEEDS_REDRAW)
    rows = dict(world.ledger.rows)
    with pytest.raises(ClipAvatarRefused) as refused:
        world.actions.retry_scene(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, scene_id=scene_id
        )
    assert refused.value.code == cs.NEEDS_REDRAW and world.ledger.rows == rows


def test_retrying_counts_in_the_days_scenes() -> None:
    world = _world()
    clip_id, scene_id = _waiting_with_a_failed_scene(world)
    world.store.used_today = cs.SCENE_DAILY_CAP
    with pytest.raises(ClipAvatarRefused) as refused:
        world.actions.retry_scene(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, scene_id=scene_id
        )
    assert refused.value.code == cs.SCENE_DAILY_CAP_CODE
    assert world.repo.drafts[scene_id].status == FAILED


def test_removing_a_failed_scene_takes_it_out_of_the_clip() -> None:
    world = _world()
    clip_id, scene_id = _waiting_with_a_failed_scene(world)
    rows = dict(world.ledger.rows)
    assert (
        world.actions.remove_scene(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, scene_id=scene_id
        )
        is True
    )
    assert scene_id in world.repo.removed and world.ledger.rows == rows
    brief = world.repo.briefs[world.repo.drafts[clip_id].brief_id]
    assert brief.media.character_scenes == ()
    assert brief.media.derived_from_brief_id is not None
    # again: nothing more
    assert (
        world.actions.remove_scene(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, scene_id=scene_id
        )
        is False
    )


def test_a_scene_that_did_not_fail_cannot_be_removed() -> None:
    world = _world()
    made = world.actions.create_clip_with_scenes(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, user_id=USER_ID, brief=_clip(_item())
    )
    (scene_id,) = made.scene_ids
    with pytest.raises(ClipAvatarRefused) as refused:
        world.actions.remove_scene(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, scene_id=scene_id
        )
    assert refused.value.code == SCENE_NOT_REMOVABLE
    assert scene_id not in world.repo.removed


def test_the_other_scenes_keep_their_child_after_one_is_removed() -> None:
    first, second, third = (_item(start=float(s)) for s in (0, 6, 12))
    rows = tuple(
        cs.SceneRow(id=uuid4(), slot=slot, status="generated", revision=1, item=item)
        for slot, item in enumerate((first, second, third), 1)
    )
    removed = (rows[0], replace(rows[1], removed=True), rows[2])
    placed = cs.placed_scenes((first, third), removed)
    assert [(p.item, p.row) for p in placed] == [(first, rows[0]), (third, rows[2])]
    assert [p.slot for p in placed] == [1, 3]


def test_a_child_whose_draft_expired_is_given_back_once_and_never_retried() -> None:
    world = _world()
    made = _made_scene_clip(world, duration=6)
    before = _used(world)
    _approve(world, made)
    # the final never left (inline ordering lost) and, days later, the draft expired
    world.repo.set_video_draft(
        tenant_id=TENANT_ID,
        asset_id=made.scene_asset,
        changes={"status": "draft", "created_at": time.time() - 30 * 86400},
    )
    # not given back yet: never «te devolvimos», and the tap that settles it is offered
    view = world.content.clip_final_view(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert view.state == "expired" and view.can_retry
    assert view.owner_text == cf.CHILD_EXPIRED_UNSETTLED_TEXT
    assert _used(world) - before == _scene_seconds(world, 6)
    world.content.retry_final(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert _used(world) == before  # its seconds back
    assert world.dispatcher.finals == [made.scene_id]  # never ordered again
    block = _block(world, made.scene_id)
    assert block["status"] == "failed" and block["error"] == cf.DRAFT_EXPIRED_TEXT
    # again: nothing more given back nor ordered
    world.content.retry_final(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert _used(world) == before and world.dispatcher.finals == [made.scene_id]
    view = world.content.clip_final_view(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert view.state == "expired" and view.owner_text == cf.CHILD_EXPIRED_TEXT


def test_a_final_that_never_left_does_not_claim_a_refund() -> None:
    view = cf.final_view(
        {"finish": cf.FINISH_CLIP_FINAL, "status": cf.CLIP_FINAL_PENDING},
        {uuid4(): ({"draft": {"status": "draft", "created_at": time.time()}},)},
    )
    assert view is not None and view.state == "failed"
    assert view.owner_text == cf.CHILD_FINAL_STUCK_TEXT


def test_the_childs_provenance_names_its_vendor_and_model() -> None:
    final = cf.ChildFinal(
        kind="scene",
        draft_id=uuid4(),
        slot=1,
        revision=1,
        asset_id=uuid4(),
        preview_key="p",
        final_key="f",
        params={
            "prompt_version": cs.SCENE_PROMPT_VERSION,
            "draft": {
                "model": cs.SCENE_MODEL,
                "raw_final": {"provider": "seedance", "model_id": cs.SCENE_MODEL},
                "final_task_id": "cgt-final",
                "final_cost_usd": "2.84",
            },
        },
    ).provenance()
    assert final["provider"] == "seedance" and final["model_id"] == cs.SCENE_MODEL
    assert final["prompt_version"] == cs.SCENE_PROMPT_VERSION
    assert final["final_task_id"] == "cgt-final" and final["final_cost_usd"] == "2.84"


def test_a_child_made_without_a_vendor_draft_needs_no_final() -> None:
    world = _world()
    made = _made_scene_clip(world)
    (video,) = world.repo.media[made.scene_id]
    world.repo.media[made.scene_id] = [replace(video, params={"resolution": "1080p"})]
    before = _used(world)
    _approve(world, made)
    assert world.repo.drafts[made.clip_id].status == APPROVED
    assert _used(world) - before == _scene_seconds(world, 5)
    assert world.dispatcher.finals == [] and world.finals.opened == []
    assert _block(world, made.clip_id) == {}  # the approved Clip is its final
