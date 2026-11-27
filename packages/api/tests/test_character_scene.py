"""m-25128784 (ADR 50 §12): the character's scene in a Clip — the «Personajes» track,
its checks before anything is written or paid, the Clip and its scenes born together,
the vista previa each scene takes, and the 480p draft on Seedance 2.5.

Offline only: no BytePlus, Seedance, Seedream or Claude is ever called — the vendor is a
double, the database a set of dicts, the saved character a double of the port m-25129385
implements (`CharacterReferenceSource`)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from qualify_creative.creations import REQUEST_CHARACTER_SCENE, weight_for
from qualify_creative.enums import ContentKind, FailureReason
from qualify_creative.schemas import (
    CharacterSceneBackground,
    CharacterSceneItem,
    CharacterSceneProduct,
    ContentBrief,
    EffectUse,
    MediaInputs,
    SourceSegment,
    character_line_max_chars,
)

from qualify_api.creative import character_scene as cs
from qualify_api.creative.clip_avatar import ClipAvatarRefused
from qualify_api.creative.creations import InMemoryCreationsLedger, NotEnoughCreations
from qualify_api.creative.fsm import DRAFTING
from qualify_api.creative.service import ContentService, check_part_link

from . import test_video_pipeline_local as _local_tests
from .test_clip_avatar import OWN_VIDEO, BlockRepo, _local_clip
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

queue_on = _local_tests.queue_on
SCENE_ON = {cs.SCENE_SWITCH: "on"}
NOW = datetime(2026, 11, 26, 15, 0, tzinfo=UTC)
CHARACTER_ID = UUID("c4a2c7e2-0000-4000-8000-000000000001")
PRODUCT_ID = UUID("9f000000-0000-4000-8000-000000000001")
PRODUCT_KEY = f"uploads/{TENANT_ID}/super-smash.jpg"
PLACE_KEY = f"uploads/{TENANT_ID}/local.jpg"
#: A PNG's first bytes: the drawing must travel exactly as it was kept.
DRAWING = b"\x89PNG\r\n\x1a\n" + bytes(range(64))


@pytest.fixture(autouse=True)
def _queue(queue_on: None) -> None:  # noqa: PT004
    """A local Clip never runs inline (EF-06): the creative queue is on, as in production."""


def _item(**over: Any) -> CharacterSceneItem:
    data: dict[str, Any] = {
        "character_id": CHARACTER_ID,
        "product": CharacterSceneProduct(product_id=PRODUCT_ID, photo_key=PRODUCT_KEY),
        "background": CharacterSceneBackground(key=PLACE_KEY, source="photo"),
        "line": "¡Mira esta super smash!",
        "start": 0.0,
        "duration": 5,
    }
    data.update(over)
    return CharacterSceneItem(**data)


def _own(seconds: float, key: str = OWN_VIDEO, join: EffectUse | None = None) -> SourceSegment:
    return SourceSegment(key=key, start_s=0, end_s=seconds, speed=1, transition_in=join)


def _clip(
    *scenes: CharacterSceneItem, segments: tuple[SourceSegment, ...] = (), **media: Any
) -> ContentBrief:
    brief = _local_clip(*(segments or (_own(10.0), _own(10.0, f"uploads/{TENANT_ID}/b.mp4"))))
    return brief.model_copy(
        update={"media": brief.media.model_copy(update={"character_scenes": scenes, **media})}
    )


# ---------------------------------------------------------------------------
# doubles


@dataclass
class Characters:
    """The port m-25129385 implements: one saved character, byte for byte."""

    drawn_at: datetime = NOW - timedelta(days=2)
    known: set[UUID] = field(default_factory=lambda: {CHARACTER_ID})
    calls: int = 0

    def scene_character(
        self, *, tenant_id: UUID, brand_id: UUID, character_id: UUID
    ) -> cs.CharacterReference | None:
        self.calls += 1
        if character_id not in self.known:
            return None
        return cs.CharacterReference(
            character_id=character_id,
            image=DRAWING,
            content_type="image/png",
            drawn_at=self.drawn_at,
            provenance={"provider": "seedream", "model_id": "dola-seedream-5-0-pro-260628"},
        )


class SceneStore:
    def __init__(self, repo: BlockRepo) -> None:
        self.repo = repo
        self.used_today = 0
        self.pending = (0, 0)

    def scenes_of(self, *, tenant_id: UUID, clip_id: UUID) -> tuple[UUID, ...]:
        found = [(slot, d) for d, (parent, slot) in self.repo.parents.items() if parent == clip_id]
        return tuple(d for _, d in sorted(found))

    def scenes_made_today(self, *, tenant_id: UUID) -> int:
        return self.used_today + len(self.repo.parents)

    def pending_scene_seconds(self, *, tenant_id: UUID, brand_id: UUID) -> tuple[int, int]:
        return self.pending


class SceneRows:
    """`character_scene.SceneRowsStore` over the in-memory repository: each scene child
    with its own scene and, once a test says it is made (`videos`), its kept video."""

    def __init__(self, repo: BlockRepo) -> None:
        self.repo = repo
        self.videos: dict[UUID, tuple[UUID, str, dict[str, Any]]] = {}
        self.reads = 0

    def scene_rows(self, *, tenant_id: UUID, clip_id: UUID) -> tuple[cs.SceneRow, ...]:
        self.reads += 1
        found = []
        for draft_id, (parent, slot) in self.repo.parents.items():
            if parent != clip_id:
                continue
            record = self.repo.drafts[draft_id]
            brief = self.repo.briefs[record.brief_id]
            video = self.videos.get(draft_id)
            found.append(
                cs.SceneRow(
                    id=draft_id,
                    slot=slot,
                    status=record.status,
                    revision=record.revision,
                    item=brief.media.character_scenes[0] if brief.media.character_scenes else None,
                    failure_reason=record.failure_reason,
                    asset_id=video[0] if video else None,
                    object_key=video[1] if video else None,
                    params=video[2] if video else {},
                    model_id=cs.SCENE_MODEL,
                    provider="seedance",
                )
            )
        return tuple(sorted(found, key=lambda row: row.slot))


@dataclass
class World:
    service: cs.CharacterSceneService
    content: ContentService
    repo: BlockRepo
    store: SceneStore
    dispatcher: RecordingDispatcher
    ledger: InMemoryCreationsLedger | None
    characters: Characters


def _world(
    *,
    env: dict[str, str] | None = None,
    quota: bool = True,
    previews_used: int = 0,
    videos_used: int = 0,
    media: Any = None,
    **content_kw: Any,
) -> World:
    repo, dispatcher = BlockRepo(), RecordingDispatcher()
    store = SceneStore(repo)
    ledger = (
        InMemoryCreationsLedger(previews_used=previews_used, videos_used=videos_used)
        if quota
        else None
    )
    # PR 2: the scenes a Clip waits for, read off the in-memory repository
    content_kw.setdefault("character_scene_store", SceneRows(repo))
    content = ContentService(
        **content_kw,
        router=FakeRouter([ok_outcome(copy_dict()) for _ in range(6)]),  # type: ignore[arg-type]
        pricing=FakePricing(),
        credentials=StaticKeyResolver(),
        voice_service=FakeVoice(make_voice()),
        brand_service=FakeBrand(make_kit()),
        repository=repo,
        dispatcher=dispatcher,
        creations=ledger,
        media=media,
    )
    characters = Characters()
    service = cs.CharacterSceneService(
        content,
        references=characters,
        store=store,
        env=env if env is not None else SCENE_ON,
        clock=lambda: NOW,
    )
    return World(service, content, repo, store, dispatcher, ledger, characters)


def _create(world: World, brief: ContentBrief | None = None, **kw: Any) -> cs.ClipWithScenes:
    return world.service.create_clip_with_scenes(
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        user_id=USER_ID,
        brief=brief or _clip(_item()),
        **kw,
    )


def _nothing_written(world: World) -> None:
    assert world.repo.drafts == {} and world.dispatcher.calls == []
    assert world.ledger is None or world.ledger.rows == {}


# ---------------------------------------------------------------------------
# the «Personajes» track in the brief (the schema's own rules)


def test_the_brief_takes_a_personajes_track_with_every_field() -> None:
    brief = _clip(_item(start=2.0, duration=8, line="Crujiente por fuera y jugosa por dentro."))
    (scene,) = brief.media.character_scenes
    assert scene.character_id == CHARACTER_ID
    assert scene.product.product_id == PRODUCT_ID and scene.product.photo_key == PRODUCT_KEY
    assert scene.background.key == PLACE_KEY
    assert (scene.start, scene.duration, scene.end) == (2.0, 8, 10.0)
    # it round-trips through the stored JSON
    again = ContentBrief.model_validate(brief.model_dump(mode="json"))
    assert again.media.character_scenes == brief.media.character_scenes


@pytest.mark.parametrize("duration", [4, 11, 0, 30])
def test_a_duration_out_of_5_to_10_seconds_is_refused_with_clear_words(duration: int) -> None:
    with pytest.raises(ValidationError) as refused:
        _item(duration=duration)
    (error,) = refused.value.errors()
    assert error["type"] == "character_scene_duration"
    assert cs.schema_problem_text(error["type"]) == cs.DURATION_TEXT
    assert "de 5 a 10 segundos" in cs.DURATION_TEXT


def test_a_duration_is_whole_seconds() -> None:
    with pytest.raises(ValidationError):
        _item(duration=7.5)


def test_a_fourth_scene_in_the_same_video_is_refused() -> None:
    scenes = tuple(_item(start=float(s)) for s in (0, 5, 10, 15))
    with pytest.raises(ValidationError) as refused:
        MediaInputs(character_scenes=scenes)
    (error,) = refused.value.errors()
    assert error["type"] == "too_many_character_scenes"
    assert cs.schema_problem_text(error["type"]) == cs.TOO_MANY_TEXT
    # three are fine
    assert len(MediaInputs(character_scenes=scenes[:3]).character_scenes) == 3


def test_two_scenes_that_cross_in_time_are_refused() -> None:
    with pytest.raises(ValidationError) as refused:
        MediaInputs(character_scenes=(_item(start=0.0, duration=6), _item(start=5.0)))
    (error,) = refused.value.errors()
    assert error["type"] == "character_scenes_overlap"
    assert cs.schema_problem_text(error["type"]) == cs.OVERLAP_TEXT
    # one right after the other only touches
    MediaInputs(character_scenes=(_item(start=0.0), _item(start=5.0)))


@pytest.mark.parametrize(("duration", "limit"), [(5, 37), (8, 82), (10, 112)])
def test_the_line_fits_its_scene(duration: int, limit: int) -> None:
    assert character_line_max_chars(duration) == limit
    _item(duration=duration, line="a" * limit)
    with pytest.raises(ValidationError) as refused:
        _item(duration=duration, line="a" * (limit + 1))
    (error,) = refused.value.errors()
    assert error["type"] == "character_line_too_long"
    words = cs.schema_problem_text(error["type"], error.get("ctx"))
    assert words == cs.line_too_long_text(duration) and f"{limit} letras" in words


def test_scenes_only_go_in_a_local_clip() -> None:
    from .test_content_service import make_brief

    with pytest.raises(ValidationError, match="character_scene_not_local|local Clip"):
        make_brief(
            variants=1,
            kind=ContentKind.CLIP,
            media=MediaInputs(character_scenes=(_item(),)),
        )


def test_a_scene_brief_holds_exactly_its_scene_and_lives_under_its_clip() -> None:
    brief = cs.scene_brief(_clip(_item()), _item())
    assert brief.kind is ContentKind.CHARACTER_SCENE and len(brief.media.character_scenes) == 1
    check_part_link(brief, uuid4(), 1)
    with pytest.raises(ValueError, match="under its Clip"):
        check_part_link(brief, None, None)
    assert not ContentKind.CHARACTER_SCENE.is_offered
    assert ContentKind.CHARACTER_SCENE.requires_ai_disclosure
    assert not ContentKind.CHARACTER_SCENE.is_video  # never the presenter's path


def test_a_scene_uses_one_vista_previa_and_its_seconds_at_approval() -> None:
    price = weight_for(cs.scene_brief(_clip(_item(duration=8)), _item(duration=8)))
    assert price.request_kind == REQUEST_CHARACTER_SCENE
    assert (price.weight, price.videos, price.video_seconds) == (0, 1, 8)


# ---------------------------------------------------------------------------
# the recipe on the Clip's timeline (pure)


def test_a_scene_that_ends_after_the_main_video_is_refused() -> None:
    problems = cs.scene_problems([_item(start=16.0)], clip_seconds=20.0)
    assert [p.code for p in problems] == [cs.PAST_END]
    assert cs.scene_problems([_item(start=15.0)], clip_seconds=20.0) == ()


def test_the_owner_keeps_3_seconds_of_their_own_in_view() -> None:
    problems = cs.scene_problems([_item(duration=10)], clip_seconds=12.0)
    assert [p.code for p in problems] == [cs.NEEDS_OWN_MEDIA]
    assert cs.scene_problems([_item(duration=10)], clip_seconds=13.0) == ()


def test_smoke_over_a_scene_is_refused_but_texts_and_effects_elsewhere_are_not() -> None:
    smoke = SimpleNamespace(effect_id="humo_capa", start_s=4.0, end_s=6.0)
    away = SimpleNamespace(effect_id="humo_capa", start_s=10.0, end_s=12.0)
    whole = SimpleNamespace(effect_id="vapor_capa", start_s=None, end_s=None)
    zoom = SimpleNamespace(effect_id="zoom_suave", start_s=0.0, end_s=5.0)
    scene = [_item(start=0.0)]
    assert [p.code for p in cs.scene_problems(scene, clip_seconds=20, effects=[smoke])] == [
        cs.SCENE_EFFECT
    ]
    assert [p.code for p in cs.scene_problems(scene, clip_seconds=20, effects=[whole])] == [
        cs.SCENE_EFFECT
    ]
    assert cs.scene_problems(scene, clip_seconds=20, effects=[away, zoom]) == ()


def test_the_joins_of_the_owners_stretches_on_the_output_timeline() -> None:
    # 10 s, then a 0.5 s blend into the next 10 s: it starts at 9.5
    joins = cs.stretch_joins([10.0, 10.0, 5.0], [0.0, 0.5, 0.0])
    assert joins == (cs.Join(index=1, start=9.5, end=10.0),)


def test_a_scene_leaves_only_with_a_cut_but_comes_in_with_any_transition() -> None:
    blend_at = cs.Join(index=1, start=9.5, end=10.0)
    # a scene ending where the blend starts (9.5), or inside it (9.7): the blend plays
    # right at its exit and eats its last word
    for start in (4.5, 4.7):
        leaving = cs.scene_problems([_item(start=start)], clip_seconds=20.0, joins=[blend_at])
        assert [p.code for p in leaving] == [cs.EXIT_CUT_ONLY]
    # the scene starting at 9.5: the blend brings it in — fine (any transition in)
    entering = cs.scene_problems([_item(start=9.5)], clip_seconds=20.0, joins=[blend_at])
    assert entering == ()
    # a blend wholly under the scene (5-10 s, or 8-14 s) is never seen — fine
    for start, duration in ((5.0, 5), (8.0, 6)):
        under = cs.scene_problems(
            [_item(start=start, duration=duration)], clip_seconds=20.0, joins=[blend_at]
        )
        assert under == ()
    # the scene's own way in takes any library transition
    fade = EffectUse(effect_id="fundido", version=2, params={"duration_s": 0.5})
    assert _item(transition_in=fade).transition_in == fade
    assert _item(transition_in=EffectUse(effect_id="corte", version=1)).transition_in is None


# ---------------------------------------------------------------------------
# «Crear»: the Clip and its scenes, born together


def test_crear_makes_the_clip_and_its_scenes_and_charges_one_vista_previa_each() -> None:
    world = _world()
    brief = _clip(_item(start=0.0), _item(start=12.0, duration=8))
    made = _create(world, brief)
    clip = world.repo.drafts[made.clip_id]
    assert clip.status == DRAFTING and clip.parent_draft_id is None
    assert len(made.scene_ids) == 2
    for slot, scene_id in enumerate(made.scene_ids, 1):
        assert world.repo.parents[scene_id] == (made.clip_id, slot)
        scene_brief = world.repo.briefs[world.repo.drafts[scene_id].brief_id]
        assert scene_brief.kind is ContentKind.CHARACTER_SCENE
    # the scenes go first, then the Clip that waits for them
    assert [d for _, d in world.dispatcher.calls] == [*made.scene_ids, made.clip_id]
    # «Crear» takes 1 vista previa per scene and NO video seconds (those wait for approval)
    assert world.ledger is not None
    rows = {d: row for (d, _), row in world.ledger.rows.items()}
    for scene_id in made.scene_ids:
        assert rows[scene_id].price.request_kind == REQUEST_CHARACTER_SCENE
        assert rows[scene_id].price.videos == 1  # the vista previa
        assert rows[scene_id].videos == 0 and rows[scene_id].video_seconds == 0
    balance = world.ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID)
    assert balance.previews_used == 2 and balance.videos_used == 0


def test_the_same_crear_again_makes_and_charges_nothing_twice() -> None:
    world = _world()
    key = uuid4()
    first = _create(world, request_key=key)
    rows, calls, drafts = (
        dict(world.ledger.rows),
        list(world.dispatcher.calls),
        len(world.repo.drafts),
    )  # type: ignore[union-attr]
    again = _create(world, request_key=key)
    assert again == first
    assert world.ledger.rows == rows  # type: ignore[union-attr]
    assert world.dispatcher.calls == calls and len(world.repo.drafts) == drafts


def test_the_switch_off_refuses_before_anything_is_read() -> None:
    world = _world(env={})
    with pytest.raises(ClipAvatarRefused) as refused:
        _create(world)
    assert refused.value.code == cs.SWITCHED_OFF
    assert refused.value.owner_message == cs.SWITCHED_OFF_TEXT
    assert world.characters.calls == 0
    _nothing_written(world)


def test_a_scene_past_the_end_of_the_video_is_refused_before_anything_is_written() -> None:
    world = _world()
    with pytest.raises(ClipAvatarRefused) as refused:
        _create(world, _clip(_item(start=18.0)))
    assert refused.value.code == cs.PAST_END and refused.value.owner_message == cs.past_end_text(1)
    _nothing_written(world)


def test_a_blend_at_a_scenes_exit_is_refused_before_anything_is_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.creative.video_pipeline.recipe import CLIP_BLOCK_TRANSITIONS_SWITCH

    monkeypatch.setenv(CLIP_BLOCK_TRANSITIONS_SWITCH, "on")
    world = _world()
    fade = EffectUse(effect_id="fundido", version=2, params={"duration_s": 0.5})
    segments = (_own(10.0), _own(10.0, f"uploads/{TENANT_ID}/b.mp4", join=fade))
    # the blend plays 9.5-10.0; a scene from 4.5 to 9.5 ends right where it starts
    with pytest.raises(ClipAvatarRefused) as refused:
        _create(world, _clip(_item(start=4.5), segments=segments))
    assert refused.value.code == cs.EXIT_CUT_ONLY
    _nothing_written(world)


def test_the_fourth_scene_of_the_day_is_refused_with_clear_words() -> None:
    world = _world()
    world.store.used_today = 3
    with pytest.raises(ClipAvatarRefused) as refused:
        _create(world)
    assert refused.value.code == cs.SCENE_DAILY_CAP_CODE
    assert refused.value.owner_message == cs.DAILY_CAP_TEXT
    assert "Hoy ya usaste tus 3 creaciones con tu personaje" in cs.DAILY_CAP_TEXT
    _nothing_written(world)


def test_two_scenes_with_one_left_today_say_how_many_fit() -> None:
    world = _world()
    world.store.used_today = 2
    with pytest.raises(ClipAvatarRefused) as refused:
        _create(world, _clip(_item(start=0.0), _item(start=10.0)))
    assert refused.value.owner_message == cs.daily_left_text(1, 2)
    assert "Hoy te queda 1 creación con tu personaje" in refused.value.owner_message
    _nothing_written(world)


def test_no_vista_previa_left_refuses_before_any_paid_call() -> None:
    world = _world(previews_used=20)
    with pytest.raises(NotEnoughCreations) as refused:
        _create(world)
    assert refused.value.missing_previews == 1
    _nothing_written(world)


def test_the_months_video_must_pay_every_uncharged_scene() -> None:
    world = _world(videos_used=36)  # Básico: 40 s, 4 left
    world.store.pending = (0, 0)
    with pytest.raises(NotEnoughCreations) as refused:
        _create(world)  # a 5 s scene
    assert refused.value.video_in_seconds and refused.value.missing_videos == 1
    _nothing_written(world)


def test_a_missing_character_is_refused() -> None:
    world = _world()
    world.characters.known = set()
    with pytest.raises(ClipAvatarRefused) as refused:
        _create(world)
    assert refused.value.code == cs.CHARACTER_MISSING
    _nothing_written(world)


def test_a_character_drawn_30_days_ago_needs_a_new_drawing() -> None:
    world = _world()
    world.characters.drawn_at = NOW - timedelta(days=30)
    with pytest.raises(ClipAvatarRefused) as refused:
        _create(world)
    assert refused.value.code == FailureReason.CHARACTER_NEEDS_REDRAW.value
    assert refused.value.owner_message.startswith("Tu personaje necesita un dibujo nuevo")
    _nothing_written(world)


def test_a_file_of_another_business_is_refused() -> None:
    world = _world()
    foreign = _item(background=CharacterSceneBackground(key=f"uploads/{uuid4()}/x.jpg"))
    with pytest.raises(ClipAvatarRefused) as refused:
        _create(world, _clip(foreign))
    assert refused.value.code == cs.FILE_NOT_OWNED
    _nothing_written(world)


def test_a_plain_create_draft_never_takes_a_personajes_track() -> None:
    world = _world()
    with pytest.raises(ValueError, match="own service"):
        world.content.create_draft(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, user_id=USER_ID, brief=_clip(_item())
        )
    _nothing_written(world)


# ---------------------------------------------------------------------------
# the 480p draft on Seedance 2.5 (the producer's part)


class _Failed(Exception):
    def __init__(self, failure: str, detail: str, raw: str = "") -> None:
        super().__init__(raw or detail)
        self.failure, self.detail, self.raw = failure, detail, raw


class FakeProducer:
    """What `produce_scene` uses of the media producer; `_run` stands for the router (the
    price guard and the vendor task record), recorded and answered here."""

    def __init__(self, *, refuse: str | None = None) -> None:
        self._character_references = Characters()
        self._catalog = SimpleNamespace(
            products_for=lambda **_: (SimpleNamespace(name="Super smash"),)
        )
        self._brand_names = lambda **_: "Nibbles' Burgers"
        self.files = {PRODUCT_KEY: _jpeg(), PLACE_KEY: _jpeg()}
        self.requests: list[Any] = []
        self.refuse = refuse
        self.saved: dict[str, bytes] = {}

    def _read(self, key: str | None) -> bytes | None:
        return self.files.get(key or "")

    def _run(self, **kw: Any) -> Any:
        from qualify_api.creative import media as m

        self.requests.append(kw["request"])
        assert kw["link"] == m.SEEDANCE
        if self.refuse:
            raise m._MediaFailed(FailureReason.PROVIDER_ERROR.value, "x", raw=self.refuse)
        return SimpleNamespace(
            payload={
                "task_id": "cgt-scene-1",
                "created_at": 1764169200,
                "draft": True,
                "resolution": "480p",
                "duration_seconds": 5,
                "generate_audio": True,
                "seed": 7,
            },
            provider="seedance",
            model_id=cs.SCENE_MODEL,
            model_revision="260628",
            media_url="https://vendor.example/scene.mp4",
            usage=SimpleNamespace(output_tokens=48_600, media_seconds=4.96),
        )

    def _seedance_usage(self, result: Any, resolution: str, usage: list[Any]) -> Decimal:
        usage.append(("seedance", resolution, result.usage.output_tokens, Decimal("0.52")))
        return Decimal("0.52")

    def _download(self, url: str) -> bytes:
        return b"mp4-bytes"


def _jpeg() -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 30, 30)).save(out, format="JPEG")
    return out.getvalue()


def _produce(producer: FakeProducer, now: datetime = NOW) -> tuple[list[Any], list[Any]]:
    usage: list[Any] = []
    saved = producer.saved

    def save(name: str, data: bytes, content_type: str) -> str:
        key = f"t/{TENANT_ID}/generated/scene/r1/{name}"
        saved[key] = data
        return key

    media = cs.produce_scene(
        producer,
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=cs.scene_brief(_clip(_item()), _item()),
        kit=make_kit().model_copy(
            update={"palette_rgb": ("#305046", "#da2220"), "font_heading": "Baloo 2"}
        ),
        budget=None,
        usage=usage,
        save=save,
        now=now,
    )
    return media, usage


def test_the_draft_is_one_omni_task_at_480p_with_the_three_references() -> None:
    import base64

    producer = FakeProducer()
    media, usage = _produce(producer)
    (request,) = producer.requests
    params = request.params
    assert params["model"] == cs.SCENE_MODEL == "dreamina-seedance-2-5-260628"
    assert params["draft"] is True and params["resolution"] == "480p"
    assert params["omni_reference_task_type"] == "reference"
    assert params["generate_audio"] is True and params["duration_seconds"] == 5
    assert params["dialogue"] == "¡Mira esta super smash!"
    character, product, place = params["reference_images"]
    # the saved drawing travels byte for byte, with its own content type
    assert character == "data:image/png;base64," + base64.b64encode(DRAWING).decode()
    assert product.startswith("data:image/jpeg;base64,")
    assert place.startswith("data:image/jpeg;base64,")
    # brand fidelity: the product's and brand's names and the palette go in the prompt
    assert '"Super smash" from Nibbles\' Burgers' in params["prompt"]
    assert "Brand colors" in params["prompt"]
    # its usage is recorded with its cost, and the video kept with its provenance
    assert usage and usage[0][-1] == Decimal("0.52")
    (write,) = media
    assert write.media_type == "video" and write.ai_generated and write.provider == "seedance"
    assert (write.width, write.height) == (480, 854)
    record = write.params["character_scene"]
    assert record["prompt_version"] == cs.SCENE_PROMPT_VERSION == "personaje-escena-v1"
    assert record["model_id"] == cs.SCENE_MODEL and record["provider"] == "seedance"
    assert record["character_id"] == str(CHARACTER_ID)
    assert record["character"]["model_id"] == "dola-seedream-5-0-pro-260628"
    assert record["request_digest"] == cs.scene_digest(_item())
    assert record["draft_task_id"] == "cgt-scene-1" and record["draft_cost_usd"] == "0.52"
    # what the 1080p final needs at approval (§12.4)
    assert write.params["draft"]["task_id"] == "cgt-scene-1"
    assert write.params["draft"]["audio"] is True


def test_a_character_past_30_days_is_refused_before_any_paid_call() -> None:
    from qualify_api.creative import media as m

    producer = FakeProducer()
    producer._character_references.drawn_at = NOW - timedelta(days=31)
    with pytest.raises(m._MediaFailed) as failed:
        _produce(producer)
    assert failed.value.failure == FailureReason.CHARACTER_NEEDS_REDRAW.value
    assert producer.requests == []


def test_the_vendor_refusing_the_character_as_a_real_face_asks_for_a_new_drawing() -> None:
    from qualify_api.creative import media as m

    producer = FakeProducer(refuse="OutputImageSensitiveContentDetected.PrivacyInformation")
    with pytest.raises(m._MediaFailed) as failed:
        _produce(producer)
    assert failed.value.failure == FailureReason.CHARACTER_NEEDS_REDRAW.value
    assert failed.value.detail == cs.NEEDS_REDRAW_TEXT


def test_no_character_source_wired_fails_before_any_paid_call() -> None:
    from qualify_api.creative import media as m

    producer = FakeProducer()
    producer._character_references = None  # type: ignore[assignment]
    with pytest.raises(m._MediaFailed) as failed:
        _produce(producer)
    assert failed.value.detail == cs.UNAVAILABLE_TEXT
    assert producer.requests == []


def test_the_scene_draft_is_quoted_from_the_versioned_table() -> None:
    from qualify_creative.pricing import JsonPricingTable

    table = JsonPricingTable("v10")
    assert cs.scene_quote_usd(table, 5) == Decimal("0.514007")  # AVESC-001 measured US$0.52
    assert cs.model_problem(cs.SCENE_MODEL) is None
    assert cs.model_problem("seedance-1-0-pro-250528") is not None


def test_the_digest_is_the_same_for_the_same_scene_wherever_it_goes() -> None:
    assert cs.scene_digest(_item(start=0.0)) == cs.scene_digest(_item(start=9.0))
    assert cs.scene_digest(_item()) != cs.scene_digest(_item(line="Otra línea."))
    assert cs.scene_request_key(TENANT_ID, _item()) == cs.scene_request_key(TENANT_ID, _item())


def test_the_scene_texts_are_plain_spanish() -> None:
    texts = [
        cs.SWITCHED_OFF_TEXT,
        cs.DAILY_CAP_TEXT,
        cs.DURATION_TEXT,
        cs.TOO_MANY_TEXT,
        cs.OVERLAP_TEXT,
        cs.past_end_text(1),
        cs.NEEDS_OWN_MEDIA_TEXT,
        cs.effect_text(1),
        cs.exit_cut_text(2),
        cs.transition_unavailable_text(1),
        cs.NEEDS_REDRAW_TEXT,
        cs.CHARACTER_MISSING_TEXT,
        cs.FILE_NOT_OWNED_TEXT,
        cs.NOT_LOCAL_TEXT,
        cs.UNAVAILABLE_TEXT,
        cs.WAITING_TEXT,
        cs.line_too_long_text(5),
        cs.daily_left_text(1, 2),
    ]
    for text in texts:
        lowered = text.lower()
        for english in ("avatar", "clip", "draft", "preview", "seedance", "byteplus"):
            assert english not in lowered, (english, text)


# ---------------------------------------------------------------------------
# the Clip waits for its scenes; a scene is never made again on its own


def test_the_clip_waits_for_its_scenes_and_is_never_assembled_without_them() -> None:
    from qualify_api.creative.clip_avatar import ClipBlocksWait

    world = _world()
    made = _create(world)
    brief_before = world.repo.drafts[made.clip_id].brief_id
    with pytest.raises(ClipBlocksWait):
        world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    clip = world.repo.drafts[made.clip_id]
    assert clip.status == DRAFTING and clip.brief_id == brief_before


def test_a_scene_is_never_regenerated_on_its_own() -> None:
    from qualify_api.creative.fsm import GENERATED

    world = _world()
    made = _create(world)
    (scene_id,) = made.scene_ids
    world.repo.drafts[scene_id] = replace(world.repo.drafts[scene_id], status=GENERATED)
    with pytest.raises(ValueError, match="not made again on its own"):
        world.content.reject(
            tenant_id=TENANT_ID, draft_id=scene_id, user_id=USER_ID, reason="x", regenerate=True
        )


# ---------------------------------------------------------------------------
# the contract with m-25129385 (the saved characters)


def test_the_adapter_over_the_saved_characters_sends_the_drawing_byte_for_byte() -> None:
    import io

    found = SimpleNamespace(
        character_id=CHARACTER_ID,
        object_key=f"t/{TENANT_ID}/characters/{CHARACTER_ID}.png",
        content_type="image/png",
        drawn_at=NOW - timedelta(days=1),
        source="seedream",
        style="animado",
        model_id="dola-seedream-5-0-pro-260628",
        model_revision=None,
        prompt_version="personaje-v1",
    )
    asked: list[tuple[Any, ...]] = []

    class Service:
        def character_reference(self, tenant_id: UUID, brand_id: UUID, character_id: UUID) -> Any:
            asked.append((tenant_id, brand_id, character_id))
            if character_id != CHARACTER_ID:
                raise ValueError("not_found")  # `CharacterRefused` is a ValueError
            return found

    source = cs.business_character_source(Service(), lambda t, b, k: io.BytesIO(DRAWING))
    reference = source.scene_character(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, character_id=CHARACTER_ID
    )
    assert reference is not None and reference.image == DRAWING
    assert reference.content_type == "image/png" and reference.provenance["prompt_version"]
    assert asked == [(TENANT_ID, BRAND_ID, CHARACTER_ID)]
    assert (
        source.scene_character(tenant_id=TENANT_ID, brand_id=BRAND_ID, character_id=uuid4()) is None
    )


def test_a_drawing_with_no_date_needs_a_new_one() -> None:
    reference = cs.CharacterReference(CHARACTER_ID, DRAWING, "image/png", None)
    assert reference.too_old(NOW)


def test_the_brief_names_the_character_where_the_in_use_check_reads_it() -> None:
    """m-25129385's `PostgresCharacterUsage` reads `media.character_scenes[*].character_id`
    as a string from the stored brief."""
    stored = _clip(_item()).model_dump(mode="json")
    assert stored["media"]["character_scenes"][0]["character_id"] == str(CHARACTER_ID)
    scene = cs.scene_brief(_clip(_item()), _item()).model_dump(mode="json")
    assert scene["media"]["character_scenes"][0]["character_id"] == str(CHARACTER_ID)


# ---------------------------------------------------------------------------
# review of cbbfbe77


def test_a_scene_way_in_other_than_a_cut_is_refused_until_the_assembly_draws_it() -> None:
    world = _world()
    fade = EffectUse(effect_id="fundido", version=2, params={"duration_s": 0.5})
    brief = _clip(_item(start=0.0), _item(start=10.0, transition_in=fade))
    with pytest.raises(cs.CharacterSceneRefused) as refused:
        _create(world, brief)
    assert refused.value.code == cs.TRANSITION_UNAVAILABLE and refused.value.block == 1
    assert refused.value.owner_message == cs.transition_unavailable_text(2)
    assert "bloque" not in refused.value.owner_message
    _nothing_written(world)


def test_the_cut_only_refusal_numbers_the_scene_and_offers_to_change_it() -> None:
    blend_at = cs.Join(index=1, start=9.5, end=10.0)
    (problem,) = cs.scene_problems(
        [_item(start=0.0), _item(start=4.5)], clip_seconds=20.0, joins=[blend_at]
    )
    assert problem.scene == 1 and problem.action == cs.CUT_ACTION
    assert problem.text.startswith("Después de la escena 2")
    assert "«Cambiar a Corte»" in problem.text
    with pytest.raises(cs.CharacterSceneRefused) as refused:
        cs.refuse_scene_problems([problem])
    assert refused.value.action == cs.CUT_ACTION


def test_a_failed_scene_gives_its_vista_previa_back() -> None:
    from qualify_api.creative.fsm import FAILED
    from qualify_api.creative.media import MediaOutcome

    from .test_content_service import FakeMedia

    media = FakeMedia(MediaOutcome(failure="provider_error", detail="No salió."))
    world = _world(media=media)
    made = _create(world)
    (scene_id,) = made.scene_ids
    assert world.ledger is not None
    assert world.ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).previews_used == 1
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=scene_id)
    assert world.repo.drafts[scene_id].status == FAILED
    assert world.ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).previews_used == 0
