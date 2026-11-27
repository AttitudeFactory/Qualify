"""m-25128784 PR 2 (ADR 50 §12): a Clip with a «Personajes» track waits for its scenes,
then is assembled ONCE with each scene laid over its window; a scene that fails stamps
the Clip and stages the failure email of m-25120319; the owner's 72 h out fails the
Clip; a Clip with scenes is never approved before PR 3.

Offline only: no vendor is called — the scenes' rows are a double over the in-memory
repository, the email outbox the in-memory one, the videos tiny synthetic encodes."""

from __future__ import annotations

import io
from dataclasses import replace
from datetime import timedelta
from fractions import Fraction
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.creative import character_scene as cs
from qualify_api.creative.clip_avatar import ClipAvatarRefused, ClipBlocksWait
from qualify_api.creative.clip_avatar_mail import (
    SCENE_MAIL_KIND,
    ClipView,
    MemoryAvatarFailureOutbox,
    Recipient,
    send_pending,
)
from qualify_api.creative.fsm import DRAFTING, FAILED, GENERATED
from qualify_api.mail import clip_avatar as words

from .test_character_scene import (
    NOW,
    SCENE_ON,
    SceneRows,
    World,
    _clip,
    _create,
    _item,
    _own,
    _world,
)
from .test_content_service import BRAND_ID, TENANT_ID, USER_ID

AFTER = NOW + timedelta(minutes=5)


class Clock:
    def __init__(self) -> None:
        self.now = AFTER

    def __call__(self) -> Any:
        return self.now


def _scene_world(**kw: Any) -> tuple[World, Clock, MemoryAvatarFailureOutbox]:
    clock, outbox = Clock(), MemoryAvatarFailureOutbox()
    world = _world(clip_avatar_clock=clock, clip_failure_outbox=outbox, **kw)
    return world, clock, outbox


def _rows(world: World) -> SceneRows:
    store = world.content._character_scene_store  # noqa: SLF001
    assert isinstance(store, SceneRows)
    return store


def _set(world: World, draft_id: UUID, **change: Any) -> None:
    world.repo.drafts[draft_id] = replace(world.repo.drafts[draft_id], **change)


def _made(world: World, scene_id: UUID, key: str | None = None) -> None:
    _set(world, scene_id, status=GENERATED)
    _rows(world).videos[scene_id] = (
        uuid4(),
        key or f"t/{TENANT_ID}/generated/{scene_id}/scene.mp4",
        {
            "resolution": "480p",
            "prompt_version": cs.SCENE_PROMPT_VERSION,
            "character_scene": {"provider": "seedance", "model_id": cs.SCENE_MODEL},
        },
    )


def _run(world: World, clip_id: UUID) -> None:
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=clip_id)


def _clip_brief(world: World, clip_id: UUID) -> Any:
    return world.repo.briefs[world.repo.drafts[clip_id].brief_id]


@pytest.fixture(autouse=True)
def _scene_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """The emails read the switch from the environment (as in production), and a local
    Clip never runs inline (EF-06): the creative queue is on."""
    from .test_video_pipeline_local import SWITCH

    monkeypatch.setenv(cs.SCENE_SWITCH, "on")
    monkeypatch.setenv(SWITCH, "queue")


# ---------------------------------------------------------------------------
# the wait


def test_the_clip_waits_while_a_scene_is_being_made_and_writes_nothing() -> None:
    world, _, outbox = _scene_world()
    made = _create(world)
    brief_id = world.repo.drafts[made.clip_id].brief_id
    with pytest.raises(ClipBlocksWait):
        _run(world, made.clip_id)
    clip = world.repo.drafts[made.clip_id]
    assert clip.status == DRAFTING and clip.brief_id == brief_id
    assert outbox.rows == []


def test_a_failed_scene_is_stamped_once_and_sends_one_failure_email() -> None:
    world, clock, outbox = _scene_world()
    made = _create(world)
    (scene_id,) = made.scene_ids
    _set(world, scene_id, status=FAILED, failure_reason="provider_error")
    with pytest.raises(ClipBlocksWait):
        _run(world, made.clip_id)
    brief = _clip_brief(world, made.clip_id)
    (item,) = brief.media.character_scenes
    assert item.failed_at == AFTER
    # provenance: the brief the owner sent stays, the new one points to it
    assert brief.media.derived_from_brief_id is not None
    (row,) = outbox.rows
    assert row.kind == words.BLOCK_FAILED and row.failed_at == AFTER
    assert row.block_ids == (scene_id,) and row.slots == (1,)
    # the next pass stamps nothing new and stages no second email
    clock.now = AFTER + timedelta(hours=1)
    with pytest.raises(ClipBlocksWait):
        _run(world, made.clip_id)
    assert len(outbox.rows) == 1
    assert world.repo.drafts[made.clip_id].status == DRAFTING


def test_no_email_while_the_scene_switch_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    world, _, outbox = _scene_world()
    made = _create(world)
    (scene_id,) = made.scene_ids
    _set(world, scene_id, status=FAILED, failure_reason="provider_error")
    monkeypatch.setenv(cs.SCENE_SWITCH, "off")
    with pytest.raises(ClipBlocksWait):
        _run(world, made.clip_id)
    assert outbox.rows == []


def test_the_owners_72_hours_out_fail_the_clip_and_give_back_what_was_not_delivered() -> None:
    world, clock, _ = _scene_world()
    made = _create(world)
    (scene_id,) = made.scene_ids
    assert world.ledger is not None
    _set(world, scene_id, status=FAILED, failure_reason="provider_error")
    with pytest.raises(ClipBlocksWait):
        _run(world, made.clip_id)
    clock.now = AFTER + timedelta(hours=72)
    _run(world, made.clip_id)
    clip = world.repo.drafts[made.clip_id]
    assert clip.status == FAILED and clip.failure_reason == cs.SCENE_FAILED
    assert clip.failure_detail == cs.SCENE_FAILED_TEXT
    balance = world.ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID)
    assert balance.previews_used == 0  # the scene the vendor never delivered


def test_a_scene_that_is_not_the_clips_fails_the_clip_at_once() -> None:
    world, _, outbox = _scene_world()
    made = _create(world)
    (scene_id,) = made.scene_ids
    _made(world, scene_id)
    # the child's scene was changed under the Clip: never assembled with another one
    child = world.repo.drafts[scene_id]
    other = world.repo.briefs[child.brief_id]
    changed = other.model_copy(
        update={
            "media": other.media.model_copy(update={"character_scenes": (_item(line="Otra cosa"),)})
        }
    )
    world.repo.briefs[child.brief_id] = changed
    _run(world, made.clip_id)
    clip = world.repo.drafts[made.clip_id]
    assert clip.status == FAILED and clip.failure_reason == cs.SCENE_BROKEN
    assert world.ledger is not None
    assert world.ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).previews_used == 0
    assert outbox.rows == []


def test_every_scene_made_assembles_the_clip_once_from_the_same_brief() -> None:
    from qualify_api.creative.media import MediaOutcome

    from .test_content_service import FakeMedia

    media = FakeMedia(MediaOutcome())
    world, _, _ = _scene_world(media=media)
    made = _create(world)
    (scene_id,) = made.scene_ids
    brief_id = world.repo.drafts[made.clip_id].brief_id
    _made(world, scene_id)
    _run(world, made.clip_id)
    clip = world.repo.drafts[made.clip_id]
    assert clip.status == GENERATED and clip.brief_id == brief_id
    (called,) = [brief for brief, _copy in media.calls if brief.media.character_scenes]
    assert called.media.character_scenes == _clip_brief(world, made.clip_id).media.character_scenes


def test_a_clip_with_scenes_is_never_approved_before_its_finals() -> None:
    from qualify_api.creative.media import MediaOutcome

    from .test_content_service import FakeMedia

    world, _, _ = _scene_world(media=FakeMedia(MediaOutcome()))
    made = _create(world)
    (scene_id,) = made.scene_ids
    _made(world, scene_id)
    _run(world, made.clip_id)
    variant = world.repo.variants_for(tenant_id=TENANT_ID, draft_id=made.clip_id)[0]
    with pytest.raises(ClipAvatarRefused) as refused:
        world.content.approve(
            tenant_id=TENANT_ID, draft_id=made.clip_id, variant_id=variant.id, user_id=USER_ID
        )
    assert refused.value.code == cs.APPROVE_UNAVAILABLE
    assert world.repo.drafts[made.clip_id].status == GENERATED


def test_scenes_and_ai_parts_together_stay_refused() -> None:
    from qualify_creative.schemas import SourceSegment, VideoPartPlan, ai_part_key

    from qualify_api.creative.clip_ai_parts import WITH_SCENES_CODE, ClipAiPartsRefused

    ai_block = SourceSegment(kind="ai_part", key=ai_part_key(1), start_s=0, end_s=5)
    plan = VideoPartPlan(mode="reference", seconds=5, description="Una arepa en la plancha")
    world, _, _ = _scene_world()
    with pytest.raises(ClipAiPartsRefused) as refused:
        _create(
            world,
            _clip(_item(), segments=(_own(10.0), ai_block, _own(10.0)), ai_parts=(plan,)),
        )
    assert refused.value.code == WITH_SCENES_CODE
    assert world.repo.drafts == {}


def test_a_failed_at_sent_by_the_editor_is_refused() -> None:
    world, _, _ = _scene_world()
    with pytest.raises(ValueError, match="server's"):
        _create(world, _clip(_item(failed_at=NOW)))
    assert world.repo.drafts == {}


# ---------------------------------------------------------------------------
# the email (m-25120319) for a scene


def _view(world: World, clip_id: UUID, status: str = DRAFTING) -> ClipView:
    rows = _rows(world).scene_rows(tenant_id=TENANT_ID, clip_id=clip_id)
    return ClipView(
        status=status,
        business="Bianki",
        timezone="America/Bogota",
        plan=(),
        blocks=(),
        scene_items=_clip_brief(world, clip_id).media.character_scenes,
        scene_rows=rows,
    )


class Mailer:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    def send(self, mail: Any) -> str:
        self.sent.append(mail)
        return "re_1"


def test_the_scene_email_goes_out_in_the_scenes_words() -> None:
    world, _, outbox = _scene_world()
    made = _create(world)
    (scene_id,) = made.scene_ids
    _set(world, scene_id, status=FAILED, failure_reason="provider_error")
    with pytest.raises(ClipBlocksWait):
        _run(world, made.clip_id)
    outbox.clips[(TENANT_ID, made.clip_id)] = _view(world, made.clip_id)
    outbox.recipients[(TENANT_ID, UUID(int=0))] = Recipient("dueno@example.com", uuid4())
    mailer = Mailer()
    sent = send_pending(
        outbox,
        TENANT_ID,
        mailer=mailer,  # type: ignore[arg-type]
        base_url="https://app.example",
        verify=lambda _u, email: email,
        now=AFTER,
        env=SCENE_ON,
    )
    assert sent == 1
    (mail,) = mailer.sent
    assert mail.subject == "Bianki: una escena con tu personaje no se pudo crear"
    assert "«Quitar escena»" in mail.text and "avatar" not in mail.text.lower()
    assert f"/drafts/{made.clip_id}" in mail.text


def test_the_scene_email_is_closed_when_the_switch_goes_off() -> None:
    world, _, outbox = _scene_world()
    made = _create(world)
    (scene_id,) = made.scene_ids
    _set(world, scene_id, status=FAILED, failure_reason="provider_error")
    with pytest.raises(ClipBlocksWait):
        _run(world, made.clip_id)
    outbox.clips[(TENANT_ID, made.clip_id)] = _view(world, made.clip_id)
    outbox.recipients[(TENANT_ID, UUID(int=0))] = Recipient("dueno@example.com", uuid4())
    mailer = Mailer()
    send_pending(
        outbox,
        TENANT_ID,
        mailer=mailer,  # type: ignore[arg-type]
        base_url="https://app.example",
        verify=lambda _u, email: email,
        now=AFTER,
        env={},
    )
    assert mailer.sent == [] and outbox.rows[0].closed_reason == "switched_off"


def test_the_scene_failure_codes_ride_as_one_group_per_pass() -> None:
    from qualify_api.creative.clip_avatar_mail import mail_groups

    world, _, _ = _scene_world()
    made = _create(world)
    (scene_id,) = made.scene_ids
    _set(world, scene_id, status=FAILED, failure_reason="character_needs_redraw")
    placed = cs.placed_scenes(
        _clip_brief(world, made.clip_id).media.character_scenes,
        _rows(world).scene_rows(tenant_id=TENANT_ID, clip_id=made.clip_id),
    )
    failures = cs.mailable_scene_failures(placed, AFTER, SCENE_ON)
    (failure,) = failures
    assert failure.block_kind == SCENE_MAIL_KIND and failure.code == "character_needs_redraw"
    (group,) = mail_groups(failures)
    assert group.scene and group.template_version == words.SCENE_TEMPLATE_VERSION


def test_the_new_texts_are_plain_spanish() -> None:
    texts = [
        cs.SCENE_FAILED_TEXT,
        cs.SCENE_BROKEN_TEXT,
        cs.APPROVE_UNAVAILABLE_TEXT,
        words.SCENE_SUBJECT,
        words.SCENE_HEADING,
        words.SCENE_LEAD,
        words.SCENE_WAIT,
        words.SCENE_SUBJECT_MANY,
        words.SCENE_HEADING_MANY,
        words.SCENE_LEAD_MANY,
        words.SCENE_WAIT_MANY,
        words.SCENE_FOOTER,
    ]
    for text in texts:
        lowered = text.lower()
        for english in ("avatar", "clip", "draft", "preview", "seedance", "byteplus", "scene"):
            assert english not in lowered, (english, text)


# ---------------------------------------------------------------------------
# the assembly: each scene laid over its window (real tiny encodes)

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

SIZE = (180, 320)


def _encode(
    seconds: float,
    colour: tuple[int, int, int],
    size: tuple[int, int],
    fps: int,
    tone: float | None,
) -> bytes:
    out = io.BytesIO()
    with av.open(out, mode="w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=fps)
        video.width, video.height, video.pix_fmt = *size, "yuv420p"
        video.options = {"preset": "ultrafast", "crf": "20"}
        track = None
        if tone is not None:
            track = sink.add_stream("aac", rate=48_000)
            track.layout = "stereo"
        pixels = np.zeros((size[1], size[0], 3), dtype=np.uint8)
        pixels[:, :] = colour
        for index in range(round(seconds * fps)):
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = index, Fraction(1, fps)
            for packet in video.encode(frame):
                sink.mux(packet)
        if track is not None:
            total = round(seconds * 48_000)
            wave = (tone * np.sin(2 * np.pi * 1000 * np.arange(total) / 48_000)).astype(np.float32)
            for start in range(0, total, 1024):
                chunk = np.tile(wave[start : start + 1024], (2, 1))
                frame = av.AudioFrame.from_ndarray(chunk, format="fltp", layout="stereo")
                frame.sample_rate, frame.pts = 48_000, start
                frame.time_base = Fraction(1, 48_000)
                for packet in track.encode(frame):
                    sink.mux(packet)
            for packet in track.encode():
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    return out.getvalue()


@pytest.fixture
def small_assembly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assembled at the sources' 9:16 size (as `test_video_pipeline_local` does), offline
    normalize jobs, the creative queue on."""
    from qualify_creative.video import prepare

    from qualify_api.creative.video_pipeline import local_sources

    from .test_video_pipeline_local import SWITCH

    monkeypatch.setattr(prepare, "TARGET_SIZE", SIZE)
    jobs = local_sources.InMemoryLocalSourceJobs()
    monkeypatch.setattr(local_sources, "default_jobs", lambda: jobs)
    monkeypatch.setenv(SWITCH, "queue")


def _source(slot: int, key: str, start: float, duration: int) -> cs.SceneSource:
    return cs.SceneSource(
        slot=slot,
        draft_id=uuid4(),
        revision=1,
        asset_id=uuid4(),
        object_key=key,
        start_s=start,
        duration_s=duration,
        provider="seedance",
        model_id=cs.SCENE_MODEL,
        params={
            "resolution": "480p",
            "character_scene": {
                "provider": "seedance",
                "model_id": cs.SCENE_MODEL,
                "prompt_version": cs.SCENE_PROMPT_VERSION,
                "line": "¡Mira esta super smash!",
                "draft_task_id": "cgt-1",
            },
        },
    )


def test_the_assembly_lays_the_scene_over_its_window_and_records_it(
    small_assembly: None,
) -> None:
    from qualify_api.creative.video_pipeline.local import produce_local

    from .test_video_pipeline_local import ReadingStore

    own_key = f"uploads/{TENANT_ID}/mi-cocina.mp4"
    scene_key = f"t/{TENANT_ID}/generated/escena.mp4"
    store = ReadingStore(
        {
            own_key: _encode(8.0, (20, 200, 40), SIZE, 30, None),
            # 4.9 s delivered for a 5 s scene (AVESC-001): its last frame is held
            scene_key: _encode(4.9, (220, 20, 20), (90, 160), 24, 0.05),
        }
    )
    brief = _clip(
        _item(start=2.0, duration=5),
        segments=(_own(8.0, own_key),),
    )
    brief = brief.model_copy(
        update={"media": brief.media.model_copy(update={"effects_pipeline_version": 1})}
    )
    saved: dict[str, bytes] = {}

    class Save:
        def __call__(self, name: str, data: bytes, content_type: str) -> str:
            key = f"t/{TENANT_ID}/out/{name}"
            saved[key] = data
            return key

        def optional(self, name: str, data: bytes, content_type: str) -> str:
            return self(name, data, content_type)

    outcome = produce_local(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        store=store,
        save=Save(),
        scenes=(_source(1, scene_key, 2.0, 5),),
    )
    assert outcome.failure is None, outcome.detail
    (write,) = outcome.media
    assert write.ai_generated is True
    local = write.params["local"]
    assert local["steps"]["scene_overlay"] == "scene-overlay-v1"
    (scene,) = local["character_scenes"]
    assert scene["slot"] == 1 and scene["seconds_requested"] == 5
    assert scene["model_id"] == cs.SCENE_MODEL and scene["line"] == "¡Mira esta super smash!"
    assert scene["laid"]["held_frames"] >= 2 and scene["laid"]["sound"] is True
    assert {"kind": "character_scene"}.items() <= local["ai_sources"][-1].items()
    assert scene_key in store.reads
    with av.open(io.BytesIO(saved[write.object_key])) as container:
        frames = [
            f.to_ndarray(format="rgb24") for f in container.decode(container.streams.video[0])
        ]
    assert len(frames) == 240  # 8 s at 30 fps: the Clip keeps its length
    red = [i for i, f in enumerate(frames) if f[..., 0].mean() > 170 and f[..., 1].mean() < 80]
    assert red == list(range(60, 210))  # [2, 7) s, cut in and cut out


def test_the_assembly_refuses_a_clip_whose_scenes_did_not_all_arrive(
    small_assembly: None,
) -> None:
    from qualify_api.creative.video_pipeline.local import produce_local

    from .test_video_pipeline_local import ReadingStore

    store = ReadingStore({})
    outcome = produce_local(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_clip(_item(start=2.0), segments=(_own(8.0),)),
        store=store,
        save=None,
        scenes=(),
    )
    assert outcome.failure is not None and store.reads == []


def test_the_producer_never_assembles_without_a_scene_lookup(small_assembly: None) -> None:
    from .test_video_pipeline_local import ExplodingByteplus, ReadingStore, _producer

    producer = _producer(ReadingStore({}), ExplodingByteplus())
    assert producer._clip_scenes(TENANT_ID, uuid4(), _clip(_item())) is None  # noqa: SLF001
    assert producer._clip_scenes(TENANT_ID, uuid4(), _clip()) == ()  # noqa: SLF001


def test_the_saved_characters_are_wired_and_read_nothing_while_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.creative import composition

    monkeypatch.setenv(cs.SCENE_SWITCH, "off")
    source = composition._character_references()  # noqa: SLF001
    found = source.scene_character(tenant_id=TENANT_ID, brand_id=BRAND_ID, character_id=uuid4())
    assert found is None
