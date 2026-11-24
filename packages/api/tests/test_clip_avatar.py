"""m-25112920: the avatar block of a Clip — a child `AVATAR_VIDEO` /
`ANIMATED_AVATAR_VIDEO` draft under a `local` Clip whose talking video enters the Clip's
recipe as a video stretch, behind two switches that are off everywhere.

Offline only: no BytePlus, OmniHuman, Seedream or Seed Speech is ever called — the vendors
are doubles (the local assembly's fails if it is called at all), the database is a set of
dicts and the videos are tiny files encoded here."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.creations import REQUEST_CLIP_AVATAR_BLOCK, weight_for
from qualify_creative.enums import (
    AvatarSource,
    ContentFormat,
    ContentKind,
    FailureReason,
    VideoEngine,
)
from qualify_creative.schemas import ContentBrief, MediaInputs, SourceSegment

from qualify_api.creative import clip_avatar as ca
from qualify_api.creative.creations import InMemoryCreationsLedger, NotEnoughCreations
from qualify_api.creative.fsm import APPROVED, DRAFTING, GENERATED
from qualify_api.creative.service import ContentService, DuplicateDraftRequest, check_part_link
from qualify_api.creative.video_pipeline import local

from . import test_video_pipeline_local as _local_tests
from .test_content_service import (
    BRAND_ID,
    TENANT_ID,
    USER_ID,
    FakeBrand,
    FakePricing,
    FakeRouter,
    FakeVoice,
    InMemoryRepository,
    RecordingDispatcher,
    StaticKeyResolver,
    copy_dict,
    make_brief,
    make_kit,
    make_voice,
    ok_outcome,
)
from .test_creative_media import BUDGET, COPY
from .test_video_pipeline_local import (
    PHOTO_KEY,
    ExplodingByteplus,
    ReadingStore,
    _branded_kit,
    _click_s,
    _png_bytes,
    _producer,
    _rms,
    _sound_of,
    _video_with_sound_bytes,
)

#: The local assembly's fixtures: the queue switch on, and (autouse) the sources' own
#: 9:16 size and no `normalize_local` job — as in its own suite.
queue_on = _local_tests.queue_on
assemble_at_the_sources_size = _local_tests.assemble_at_the_sources_size
no_normalize_jobs = _local_tests.no_normalize_jobs

av = pytest.importorskip("av")

PRESENTER_ON = {ca.PRESENTER_SWITCH: "on"}
ANIMATED_ON = {ca.ANIMATED_SWITCH: "1"}
BOTH_ON = {**PRESENTER_ON, **ANIMATED_ON}
SCRIPT = "Hola, soy Ana. Hoy te traigo la arepa de chócolo recién hecha."
OWN_VIDEO = f"uploads/{TENANT_ID}/mi-cocina.mp4"


def _presenter(**over: Any) -> ca.AvatarBlockRequest:
    return ca.AvatarBlockRequest(
        **{
            "kind": "presenter",
            "script": SCRIPT,
            "avatar_prompt": "Mujer latina de unos 30 años, sonriente",
            **over,
        }
    )


def _animated(**over: Any) -> ca.AvatarBlockRequest:
    return ca.AvatarBlockRequest(
        **{"kind": "animated", "script": SCRIPT, "avatar_prompt": "Una arepa con gafas", **over}
    )


def _local_clip(*segments: SourceSegment) -> ContentBrief:
    return make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(
            duration_seconds=5,
            clip_reference_mode="local",
            segments=segments or (SourceSegment(key=OWN_VIDEO, start_s=0, end_s=4, speed=2),),
            effects_pipeline_version=local.LOCAL_EFFECTS_PIPELINE_VERSION,
        ),
    )


# ---------------------------------------------------------------------------
# doubles: a repository with children, the store read from it


class BlockRepo(InMemoryRepository):
    """`InMemoryRepository` with what Postgres does for children: a parent and a slot
    (unique per parent, as migration 0119's index), a request key, a new brief."""

    def __init__(self) -> None:
        super().__init__()
        self.parents: dict[UUID, tuple[UUID, int]] = {}
        self.keys: dict[UUID, UUID] = {}
        self.inserts = 0

    def insert_brief_and_draft(  # type: ignore[override]
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        brief: ContentBrief,
        voice_profile_version: int,
        pipeline_version: str,
        request_key: UUID | None = None,
        parent_draft_id: UUID | None = None,
        part_index: int | None = None,
    ) -> UUID:
        from sqlalchemy.exc import IntegrityError

        check_part_link(brief, parent_draft_id, part_index)
        if request_key is not None and request_key in self.keys:
            raise DuplicateDraftRequest(self.keys[request_key])
        if parent_draft_id is not None and (parent_draft_id, part_index) in self.parents.values():
            raise IntegrityError("slot taken", {}, Exception("uq_content_drafts_part"))
        self.inserts += 1
        draft_id = super().insert_brief_and_draft(
            tenant_id=tenant_id,
            user_id=user_id,
            brief=brief,
            voice_profile_version=voice_profile_version,
            pipeline_version=pipeline_version,
        )
        if parent_draft_id is not None:
            assert part_index is not None
            self.parents[draft_id] = (parent_draft_id, part_index)
            self.drafts[draft_id] = replace(self.drafts[draft_id], parent_draft_id=parent_draft_id)
        if request_key is not None:
            self.keys[request_key] = draft_id
        return draft_id

    def draft_id_for_request(self, *, tenant_id: UUID, request_key: UUID) -> UUID | None:
        return self.keys.get(request_key)

    def replace_brief(
        self, *, tenant_id: UUID, draft_id: UUID, user_id: UUID, brief: ContentBrief
    ) -> UUID:
        brief_id = uuid4()
        self.briefs[brief_id] = brief
        self.drafts[draft_id] = replace(self.drafts[draft_id], brief_id=brief_id)
        return brief_id

    def bump_revision(self, *, tenant_id, draft_id, pipeline_version=None):  # type: ignore[override]  # noqa: ANN001, ANN201
        return super().bump_revision(tenant_id=tenant_id, draft_id=draft_id)


class RepoStore:
    """`ClipAvatarStore` read off a `BlockRepo` (what the Postgres store reads)."""

    def __init__(self, repo: BlockRepo, videos: dict[UUID, ca.BlockVideo] | None = None) -> None:
        self.repo = repo
        self.videos = videos if videos is not None else {}
        self.reads = 0

    def clip(self, *, tenant_id: UUID, clip_id: UUID) -> ca.ClipRow | None:
        self.reads += 1
        draft = self.repo.drafts.get(clip_id)
        if draft is None:
            return None
        return ca.ClipRow(
            id=draft.id,
            brand_id=draft.brand_id,
            brief_id=draft.brief_id,
            status=draft.status,
            revision=draft.revision,
            parent_draft_id=self.repo.parents.get(clip_id, (None, 0))[0],
        )

    def blocks_of(self, *, tenant_id: UUID, clip_id: UUID) -> tuple[ca.BlockRow, ...]:
        self.reads += 1
        rows = []
        for draft_id, (parent, slot) in self.repo.parents.items():
            brief = self.repo.briefs[self.repo.drafts[draft_id].brief_id]
            kind = ca.block_kind_of(brief)
            if parent != clip_id or kind is None:
                continue
            rows.append(
                ca.BlockRow(
                    id=draft_id,
                    slot=slot,
                    status=self.repo.drafts[draft_id].status,
                    kind=kind,
                    script_seconds=ca.script_seconds(brief.media.own_script),
                )
            )
        return tuple(sorted(rows, key=lambda row: row.slot))

    def block_video(self, *, tenant_id: UUID, block_id: UUID) -> ca.BlockVideo | None:
        return self.videos.get(block_id)

    def generated_sources(self, *, tenant_id: UUID, keys: Any) -> dict[str, ca.GeneratedSource]:
        found = {}
        for block_id, video in self.videos.items():
            if video.object_key in keys:
                found[video.object_key] = _source(
                    video.object_key, block_id, self.repo.parents[block_id][0], video.seconds
                )
        return found


def _source(key: str, block_id: UUID, clip_id: UUID | None, seconds: float) -> ca.GeneratedSource:
    """An avatar block's video as the lookup gives it."""
    return ca.GeneratedSource(
        object_key=key,
        block_id=block_id,
        clip_id=clip_id,
        kind="presenter",
        revision=1,
        asset_id=uuid4(),
        provider="omnihuman",
        model_id="omnihuman-1.5",
        model_revision="realman_avatar_picture_omni15_cv",
        seconds=seconds,
        pipeline_version="creative-v1",
    )


def _piece(key: str, *, provider: str, model_id: str, ai: bool = True) -> ca.GeneratedSource:
    """A file of another piece of the generator the owner chose (ADR 50 P3), as the
    lookup gives it: not a block, AI as its asset says."""
    return ca.GeneratedSource(
        object_key=key,
        block_id=uuid4(),
        clip_id=None,
        kind="clip",
        revision=1,
        asset_id=uuid4(),
        provider=provider,
        model_id=model_id,
        model_revision=None,
        seconds=4.0,
        pipeline_version="creative-v1",
        block=False,
        ai_generated=ai,
    )


def _block_key(block_id: UUID) -> str:
    return f"t/{TENANT_ID}/generated/{block_id}/r1/video.mp4"


def _wired(
    *,
    env: dict[str, str] | None = None,
    ledger: InMemoryCreationsLedger | None = None,
    clip_status: str = GENERATED,
    clip: ContentBrief | None = None,
    sources: Any = None,
) -> tuple[ca.ClipAvatarService, ContentService, BlockRepo, RepoStore, RecordingDispatcher, UUID]:
    repo, dispatcher = BlockRepo(), RecordingDispatcher()
    store = RepoStore(repo)
    content = ContentService(
        router=FakeRouter([ok_outcome(copy_dict()) for _ in range(3)]),  # type: ignore[arg-type]
        pricing=FakePricing(),
        credentials=StaticKeyResolver(),
        voice_service=FakeVoice(make_voice()),
        brand_service=FakeBrand(make_kit()),
        repository=repo,
        dispatcher=dispatcher,
        creations=ledger,
        clip_avatar_sources=sources
        or (lambda tenant, keys: store.generated_sources(tenant_id=tenant, keys=keys)),
    )
    clip_id = repo.seed_draft(clip or _local_clip(), status=clip_status)
    repo.inserts = 0  # the Clip itself
    service = ca.ClipAvatarService(
        content,
        store=store,
        env=env if env is not None else {},
        brand_avatar_key=lambda tenant, brand: f"t/{tenant}/brand/{brand}/avatar/a.jpg",
    )
    return service, content, repo, store, dispatcher, clip_id


# ---------------------------------------------------------------------------
# the switches


def test_both_switches_are_off_unless_turned_on() -> None:
    assert not ca.block_enabled("presenter", {}) and not ca.block_enabled("animated", {})
    assert not ca.any_block_enabled({})
    for value in ("off", "0", "", "yes", "encendido"):
        assert not ca.block_enabled("presenter", {ca.PRESENTER_SWITCH: value})
    for value in ("1", "on", "TRUE", " on "):
        assert ca.block_enabled("presenter", {ca.PRESENTER_SWITCH: value})
    # each kind has its own switch
    assert ca.block_enabled("animated", ANIMATED_ON) and not ca.block_enabled(
        "presenter", ANIMATED_ON
    )
    assert not ca.block_enabled("narrator", BOTH_ON)


@pytest.mark.parametrize(
    ("request_", "env"),
    [
        (_presenter(), {}),
        (_animated(), {}),
        (_presenter(), ANIMATED_ON),
        (_animated(), PRESENTER_ON),
    ],
)
def test_the_server_refuses_a_block_whose_kind_is_off_before_anything(
    request_: ca.AvatarBlockRequest, env: dict[str, str]
) -> None:
    ledger = InMemoryCreationsLedger()
    service, _, repo, store, dispatcher, clip_id = _wired(env=env, ledger=ledger)
    store.reads = 0
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        service.create_block(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=request_
        )
    assert refused.value.code == "switched_off"
    assert refused.value.owner_message == ca.SWITCHED_OFF_TEXT
    assert store.reads == 0 and repo.inserts == 0 and dispatcher.calls == []
    assert ledger.rows == {}


def test_the_env_files_keep_both_switches_off() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    for name in (".env.example", "deploy/.env.prod.example"):
        text = (root / name).read_text(encoding="utf-8")
        assert f"{ca.PRESENTER_SWITCH}=off" in text and f"{ca.ANIMATED_SWITCH}=off" in text


# ---------------------------------------------------------------------------
# creating a block


@pytest.mark.parametrize(
    ("request_", "kind", "source"),
    [
        (_presenter(), ContentKind.AVATAR_VIDEO, AvatarSource.AI),
        (_animated(), ContentKind.ANIMATED_AVATAR_VIDEO, AvatarSource.AI),
    ],
)
def test_a_block_is_a_child_of_its_clip_on_omnihuman_in_its_slot(
    request_: ca.AvatarBlockRequest, kind: ContentKind, source: AvatarSource
) -> None:
    ledger = InMemoryCreationsLedger()
    service, _, repo, _, dispatcher, clip_id = _wired(env=BOTH_ON, ledger=ledger)
    before = ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID)
    block = service.create_block(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=request_
    )
    assert repo.parents[block] == (clip_id, 1)
    assert repo.drafts[block].parent_draft_id == clip_id
    brief = repo.briefs[repo.drafts[block].brief_id]
    assert brief.kind is kind and brief.media.clip_avatar_block is True
    assert brief.media.video_engine is VideoEngine.OMNIHUMAN
    assert brief.media.avatar_source is source
    assert brief.media.own_script == SCRIPT and brief.media.part is None
    assert brief.format is ContentFormat.REELS_9_16 and brief.media.subtitles is False
    assert dispatcher.calls == [(TENANT_ID, block)]
    # nothing is charged when it is made: its seconds go with the Clip's approval
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID) == before
    assert weight_for(brief).request_kind == REQUEST_CLIP_AVATAR_BLOCK
    assert (weight_for(brief).weight, weight_for(brief).video_seconds) == (0, 0)
    # a second block takes the next slot
    other = service.create_block(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=request_
    )
    assert repo.parents[other] == (clip_id, 2)


def test_an_animated_block_may_speak_as_the_brands_own_avatar() -> None:
    service, _, repo, _, _, clip_id = _wired(env=ANIMATED_ON)
    block = service.create_block(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        clip_id=clip_id,
        request=_animated(use_brand_avatar=True, avatar_prompt=""),
    )
    media = repo.briefs[repo.drafts[block].brief_id].media
    assert media.avatar_source is AvatarSource.IMAGE and media.avatar_rights_confirmed
    assert media.avatar_image_key == f"t/{TENANT_ID}/brand/{BRAND_ID}/avatar/a.jpg"


def test_a_presenter_block_is_always_described() -> None:
    with pytest.raises(ValueError):
        _presenter(avatar_prompt="")
    with pytest.raises(ValueError):
        _presenter(use_brand_avatar=True)


def test_a_script_over_30_seconds_is_refused_before_anything() -> None:
    service, _, repo, store, _, clip_id = _wired(env=BOTH_ON)
    store.reads = 0
    long_script = "palabra " * 60  # 480 characters: ~32 s read aloud
    assert ca.script_seconds(long_script) > ca.AVATAR_BLOCK_MAX_SECONDS
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        service.create_block(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            clip_id=clip_id,
            request=_presenter(script=long_script),
        )
    assert refused.value.code == "too_long" and "30 segundos" in refused.value.owner_message
    assert store.reads == 0 and repo.inserts == 0
    # exactly 30 s goes on
    assert ca.script_seconds("a" * 450) == 30


def test_no_paid_call_without_the_months_video_seconds() -> None:
    """The month must pay this block and the Clip's other live blocks at approval:
    otherwise nothing is created nor dispatched."""
    ledger = InMemoryCreationsLedger()
    service, _, repo, _, dispatcher, clip_id = _wired(env=BOTH_ON, ledger=ledger)
    balance = ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID)
    assert balance.video_in_seconds
    thirty = _presenter(script="a" * 450)  # a 30 s block
    room = balance.videos_left // ca.script_seconds(thirty.script)
    assert 0 < room < ca.AVATAR_BLOCK_SLOTS
    for _ in range(room):
        service.create_block(tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=thirty)
    made = repo.inserts
    with pytest.raises(NotEnoughCreations):
        service.create_block(tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=thirty)
    assert repo.inserts == made and len(dispatcher.calls) == made


@pytest.mark.parametrize(
    ("status", "clip", "code"),
    [
        (DRAFTING, None, "clip_not_ready"),
        (APPROVED, None, "clip_not_ready"),
        (GENERATED, make_brief(variants=1, kind=ContentKind.CLIP), "clip_not_local"),
    ],
)
def test_a_block_goes_only_into_an_own_video_clip_ready_to_show(
    status: str, clip: ContentBrief | None, code: str
) -> None:
    service, _, repo, _, _, clip_id = _wired(env=BOTH_ON, clip_status=status, clip=clip)
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        service.create_block(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=_presenter()
        )
    assert refused.value.code == code and repo.inserts == 0


def test_a_block_is_never_a_block_of_a_block() -> None:
    service, _, repo, _, _, clip_id = _wired(env=BOTH_ON)
    block = service.create_block(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=_presenter()
    )
    repo.drafts[block] = replace(repo.drafts[block], status=GENERATED)
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        service.create_block(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=block, request=_presenter()
        )
    assert refused.value.code == "clip_not_local"


def test_a_clip_has_at_most_six_slots() -> None:
    service, _, repo, _, _, clip_id = _wired(env=BOTH_ON)
    for _ in range(ca.AVATAR_BLOCK_SLOTS):
        service.create_block(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=_presenter()
        )
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        service.create_block(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=_presenter()
        )
    assert refused.value.code == "no_slot"
    assert sorted(slot for _, slot in repo.parents.values()) == [1, 2, 3, 4, 5, 6]


def test_the_same_request_key_makes_one_block() -> None:
    service, _, repo, _, dispatcher, clip_id = _wired(env=BOTH_ON)
    key = uuid4()
    first = service.create_block(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=_presenter(), request_key=key
    )
    again = service.create_block(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=_presenter(), request_key=key
    )
    assert first == again and repo.inserts == 1 and len(dispatcher.calls) == 1


def test_a_block_never_exists_loose_and_create_draft_refuses_one() -> None:
    brief = ca.block_brief(_local_clip(), _presenter())
    with pytest.raises(ValueError):
        check_part_link(brief, None, None)
    with pytest.raises(ValueError):
        check_part_link(brief, uuid4(), None)
    check_part_link(brief, uuid4(), 1)  # under its Clip, in a slot
    _, content, repo, _, _, _ = _wired(env=BOTH_ON)
    made = repo.inserts
    with pytest.raises(ValueError):
        content.create_draft(tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=brief, user_id=USER_ID)
    assert repo.inserts == made
    # an ordinary avatar video is untouched: no parent, no block
    plain = brief.model_copy(
        update={"media": brief.media.model_copy(update={"clip_avatar_block": False})}
    )
    check_part_link(plain, None, None)


# ---------------------------------------------------------------------------
# the producer's guards before OmniHuman


def test_a_block_is_capped_at_30_seconds_and_runs_on_omnihuman_15() -> None:
    block = ca.block_brief(_local_clip(), _presenter()).media
    plain = MediaInputs(video_engine=VideoEngine.OMNIHUMAN)
    assert ca.block_max_seconds(block, 59.0) == 30.0
    assert ca.block_max_seconds(plain, 59.0) == 59.0
    assert ca.block_model_problem(block, "realman_avatar_picture_omni15_cv") is None
    assert ca.block_model_problem(block, "realman_avatar_picture_omni20_cv") is not None
    assert ca.block_model_problem(plain, "realman_avatar_picture_omni20_cv") is None


def _block_produce(*, req_key: str, script: str) -> tuple[Any, Any, Any, Any]:
    from .test_creative_media_byteplus import (
        PUBLIC_VOICE,
        FakeLinks,
        FakeOmniHuman,
        FakeSeedream,
        FakeSpeech,
        _presenter,
        _produce,
        _store,
    )

    seedream, speech, omni = FakeSeedream(), FakeSpeech(), FakeOmniHuman()
    producer = _presenter(_store(), seedream=seedream, speech=speech, omni=omni, links=FakeLinks())
    producer._omnihuman_req_key = req_key  # what `composition` wires from the adapter
    brief = ca.block_brief(_local_clip(), _presenter_request(script, PUBLIC_VOICE))
    return _produce(producer, brief, uuid4()), seedream, speech, omni


def _presenter_request(script: str, voice: str) -> ca.AvatarBlockRequest:
    return _presenter(script=script, voice_id=voice)


def test_the_producer_refuses_a_block_on_another_omnihuman_before_any_spend() -> None:
    outcome, seedream, speech, omni = _block_produce(
        req_key="realman_avatar_picture_omni20_cv", script=SCRIPT
    )
    assert outcome.failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value
    assert outcome.detail == ca.BLOCK_MODEL_TEXT
    assert seedream.requests == speech.requests == omni.requests == [] and outcome.usage == ()


def test_a_block_whose_voice_lasts_over_30_seconds_never_reaches_omnihuman() -> None:
    script = "a" * 465  # 31 s read aloud: under OmniHuman's 59 s, over a block's 30 s
    outcome, _, speech, omni = _block_produce(
        req_key="realman_avatar_picture_omni15_cv", script=script
    )
    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert outcome.detail == ca.BLOCK_TOO_LONG_TEXT
    assert len(speech.requests) == 1 and omni.requests == []


def test_a_block_within_30_seconds_is_made_by_omnihuman_as_ai() -> None:
    outcome, _, _, omni = _block_produce(req_key="realman_avatar_picture_omni15_cv", script=SCRIPT)
    assert outcome.failure is None, outcome.detail
    (render,) = omni.requests
    assert render.params["audio_seconds"] <= ca.AVATAR_BLOCK_MAX_SECONDS
    (video,) = outcome.media
    assert video.ai_generated and video.provider == "omnihuman"


# ---------------------------------------------------------------------------
# the Clip assembled with its block


@pytest.fixture(scope="module")
def assembly_files() -> dict[str, bytes]:
    return {OWN_VIDEO: _video_with_sound_bytes(4.0, 1.5), PHOTO_KEY: _png_bytes()}


def _assemble(
    clip: ContentBrief,
    files: dict[str, bytes],
    *,
    clip_id: UUID,
    sources: dict[str, ca.GeneratedSource] | None,
) -> tuple[Any, ReadingStore, list[Any]]:
    store = ReadingStore(files)
    looked: list[Any] = []

    def resolver(tenant: UUID, keys: Any) -> dict[str, ca.GeneratedSource]:
        looked.append(list(keys))
        return dict(sources or {})

    producer = _producer(store, ExplodingByteplus())
    producer._clip_avatar_sources = resolver if sources is not None else None
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=clip_id,
        brief=clip,
        kit=_branded_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    return outcome, store, looked


def test_a_clip_with_its_block_keeps_the_voice_and_is_marked_ai(
    queue_on: None, assembly_files: dict[str, bytes]
) -> None:
    """The block's stretch at ×1 keeps its sound (the voice), the composed video is
    `ai_generated=True` and records the block; no vendor is called by the assembly."""
    clip_id, block_id = uuid4(), uuid4()
    key = _block_key(block_id)
    files = {**assembly_files, key: _video_with_sound_bytes(4.0, 1.5)}
    clip = _local_clip(
        SourceSegment(key=key, start_s=0, end_s=4.0, speed=1.0),
        SourceSegment(key=PHOTO_KEY, start_s=0, end_s=1.5, kind="photo"),
    )
    outcome, store, looked = _assemble(
        clip, files, clip_id=clip_id, sources={key: _source(key, block_id, clip_id, 4.0)}
    )
    assert outcome.failure is None, outcome.detail
    (video,) = outcome.media
    assert video.ai_generated is True and video.params["ai_generated"] is True
    (record,) = video.params["local"]["avatar_blocks"]
    assert record["block_id"] == str(block_id) and record["segment"] == 0
    assert record["provider"] == "omnihuman" and record["model_id"] == "omnihuman-1.5"
    assert record["clip_avatar_version"] == ca.CLIP_AVATAR_VERSION
    assert looked == [[key]]  # only the block's key was looked up
    sound = video.params["local"]["sound"]["segments"]
    assert sound[0] == {"segment": 0, "original_sound": True, "why": "kept"}
    _, samples = _sound_of(store.files[video.object_key])
    assert abs(_click_s(samples) - 1.5) <= 1 / 30  # the voice, where it was said
    assert _rms(samples, 0.1, 1.4) > 0.1
    assert video.params["local"]["cost_usd"] == "0.00"


@pytest.mark.parametrize(
    ("speed", "owner", "text"),
    [(1.25, "self", ca.SPEED_TEXT), (1.0, "other", ca.ELSEWHERE_TEXT)],
)
def test_a_block_at_another_speed_or_of_another_video_is_refused_before_any_read(
    queue_on: None, assembly_files: dict[str, bytes], speed: float, owner: str, text: str
) -> None:
    clip_id, block_id = uuid4(), uuid4()
    key = _block_key(block_id)
    files = {**assembly_files, key: _video_with_sound_bytes(4.0, 1.5)}
    clip = _local_clip(SourceSegment(key=key, start_s=0, end_s=4.0, speed=speed))
    belongs = clip_id if owner == "self" else uuid4()
    outcome, store, _ = _assemble(
        clip, files, clip_id=clip_id, sources={key: _source(key, block_id, belongs, 4.0)}
    )
    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert outcome.detail == text
    assert store.reads == []


def test_an_own_video_clip_looks_nothing_up_and_stays_not_ai(
    queue_on: None, assembly_files: dict[str, bytes]
) -> None:
    """Both switches off, an owner's recipe: no lookup, `ai_generated=False` as before."""
    outcome, _, looked = _assemble(
        _local_clip(SourceSegment(key=OWN_VIDEO, start_s=0, end_s=4.0, speed=1.0)),
        assembly_files,
        clip_id=uuid4(),
        sources={},
    )
    assert outcome.failure is None, outcome.detail
    assert looked == [] and outcome.media[0].ai_generated is False
    assert "avatar_blocks" not in outcome.media[0].params["local"]


def test_a_blocks_video_with_no_lookup_wired_fails_closed(
    queue_on: None, assembly_files: dict[str, bytes]
) -> None:
    """A file of the generator (a block or any piece) and no lookup wired: never made
    without knowing its «hecho con IA», with the avatar switches on or off."""
    key = _block_key(uuid4())
    outcome, store, _ = _assemble(
        _local_clip(SourceSegment(key=key, start_s=0, end_s=4.0, speed=1.0)),
        {**assembly_files, key: b""},
        clip_id=uuid4(),
        sources=None,
    )
    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert outcome.detail == local.LOCAL_SOURCE_FAILED_TEXT and store.reads == []


# ---------------------------------------------------------------------------
# placing the block and approving the Clip


def _made_block(
    service: ca.ClipAvatarService, repo: BlockRepo, store: RepoStore, clip_id: UUID
) -> tuple[UUID, str]:
    block = service.create_block(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=_presenter()
    )
    repo.drafts[block] = replace(repo.drafts[block], status=GENERATED)
    key = _block_key(block)
    store.videos[block] = ca.BlockVideo(asset_id=uuid4(), object_key=key, seconds=4.2)
    return block, key


def test_placing_a_block_puts_its_video_at_x1_and_makes_the_clips_next_version() -> None:
    service, _, repo, store, dispatcher, clip_id = _wired(env=PRESENTER_ON)
    block, key = _made_block(service, repo, store, clip_id)
    old_brief = repo.drafts[clip_id].brief_id
    revision = repo.drafts[clip_id].revision
    dispatcher.calls.clear()
    service.place_block(tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, block_id=block, at=0)
    draft = repo.drafts[clip_id]
    assert draft.brief_id != old_brief and draft.revision == revision + 1
    assert draft.status == DRAFTING and dispatcher.calls == [(TENANT_ID, clip_id)]
    segments = repo.briefs[draft.brief_id].media.segments
    assert segments[0] == SourceSegment(key=key, start_s=0, end_s=4.2, speed=1.0)
    assert segments[1].key == OWN_VIDEO
    # the brief the version shown was made from is kept as it was
    assert repo.briefs[old_brief].media.segments[0].key == OWN_VIDEO
    # twice is refused
    repo.drafts[clip_id] = replace(repo.drafts[clip_id], status=GENERATED)
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        service.place_block(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, block_id=block, at=5
        )
    assert refused.value.code == "already_placed"


def test_placing_is_refused_while_the_block_is_not_made_or_its_switch_is_off() -> None:
    service, content, repo, store, _, clip_id = _wired(env=PRESENTER_ON)
    block = service.create_block(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=_presenter()
    )
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        service.place_block(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, block_id=block, at=0
        )
    assert refused.value.code == "block_not_ready"
    off = ca.ClipAvatarService(content, store=store, env={})
    with pytest.raises(ca.ClipAvatarRefused) as refused:
        off.place_block(tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, block_id=block, at=0)
    assert refused.value.code == "switched_off"
    assert repo.drafts[clip_id].status == GENERATED


def test_approving_the_clip_charges_its_blocks_seconds_once() -> None:
    """Deivid: the block's seconds come off the month's video when the Clip is approved
    (4.2 s plays as 5 whole seconds); the owner's own stretches still use nothing."""
    ledger = InMemoryCreationsLedger()
    service, content, repo, store, _, clip_id = _wired(env=PRESENTER_ON, ledger=ledger)
    block, key = _made_block(service, repo, store, clip_id)
    clip = _local_clip(
        SourceSegment(key=key, start_s=0, end_s=4.2, speed=1.0),
        SourceSegment(key=OWN_VIDEO, start_s=0, end_s=4.0, speed=2.0),
    )
    repo.drafts[clip_id] = replace(
        repo.drafts[clip_id],
        brief_id=repo.replace_brief(
            tenant_id=TENANT_ID, draft_id=clip_id, user_id=USER_ID, brief=clip
        ),
    )
    variant = uuid4()
    from qualify_api.creative.service import VariantRecord

    repo.variants[variant] = VariantRecord(
        id=variant,
        draft_id=clip_id,
        ordinal=1,
        copy=copy_dict(),
        edited_copy=None,
        fidelity={"passed": True},
        model_id="claude",
        model_revision="r",
    )
    before = ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID)
    used, _ = content.approval_videos(tenant_id=TENANT_ID, draft_id=clip_id) or (0, None)
    assert used == 5
    content.approve(tenant_id=TENANT_ID, draft_id=clip_id, variant_id=variant, user_id=USER_ID)
    after = ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID)
    assert before.videos_left - after.videos_left == 5
    assert repo.drafts[clip_id].status == APPROVED
    assert ca.charged_seconds(()) == 0
    assert block in repo.parents


def test_a_block_is_never_made_again_on_its_own_past_the_quota_check() -> None:
    """«Pedir otra versión» of a block would order OmniHuman again with no charge and no
    quota check: refused before the FSM, the charge or the dispatch."""
    service, content, repo, _, dispatcher, clip_id = _wired(env=PRESENTER_ON)
    block = service.create_block(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=clip_id, request=_presenter()
    )
    repo.drafts[block] = replace(repo.drafts[block], status=GENERATED)
    dispatcher.calls.clear()
    with pytest.raises(ValueError):
        content.reject(
            tenant_id=TENANT_ID, draft_id=block, reason="otra", user_id=USER_ID, regenerate=True
        )
    assert repo.drafts[block].status == GENERATED and dispatcher.calls == []


def test_the_blocks_brief_length_is_one_the_brief_accepts() -> None:
    assert [ca.block_duration(s) for s in (1, 5, 6, 11, 16, 30, 31)] == [5, 5, 10, 15, 30, 30, 30]
    short = ca.block_brief(_local_clip(), _presenter(script="Hola."))
    assert short.media.duration_seconds == 5


def test_with_both_switches_off_a_seedance_piece_the_owner_chose_now_says_ai(
    queue_on: None, assembly_files: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    """INTENTIONAL change of behaviour with both avatar switches off (Deivid, 2026-11-24,
    ADR 50 §9): before m-25112920 a Seedance piece of the generator the owner chose as a
    stretch (ADR 50 P3) came out `ai_generated=False`. The label is now read from what
    was made — the asset's provider —, so the video says «hecho con IA». Everything
    else stays as before: no block, nothing charged, nothing else read."""
    monkeypatch.delenv(ca.PRESENTER_SWITCH, raising=False)
    monkeypatch.delenv(ca.ANIMATED_SWITCH, raising=False)
    key = _block_key(uuid4())
    piece = _piece(key, provider="seedance", model_id="seedance-2-0")
    outcome, _, looked = _assemble(
        _local_clip(SourceSegment(key=key, start_s=0, end_s=4.0, speed=1.0)),
        {**assembly_files, key: _video_with_sound_bytes(4.0, 1.5)},
        clip_id=uuid4(),
        sources={key: piece},
    )
    assert outcome.failure is None, outcome.detail
    (video,) = outcome.media
    assert video.ai_generated is True and video.params["ai_generated"] is True
    (record,) = video.params["local"]["ai_sources"]
    assert record["provider"] == "seedance" and record["avatar_block"] is False
    assert record["asset_id"] == str(piece.asset_id) and record["segment"] == 0
    assert "avatar_blocks" not in video.params["local"]
    assert looked == [[key]]


def test_a_seedream_photo_among_own_videos_makes_the_clip_ai(
    queue_on: None, assembly_files: dict[str, bytes]
) -> None:
    key = f"t/{TENANT_ID}/generated/{uuid4()}/r1/scene.png"
    outcome, _, _ = _assemble(
        _local_clip(
            SourceSegment(key=OWN_VIDEO, start_s=0, end_s=4.0, speed=1.0),
            SourceSegment(key=key, start_s=0, end_s=1.5, kind="photo"),
        ),
        {**assembly_files, key: _png_bytes()},
        clip_id=uuid4(),
        sources={key: _piece(key, provider="seedream", model_id="seedream-5-0")},
    )
    assert outcome.failure is None, outcome.detail
    assert outcome.media[0].ai_generated is True
    (record,) = outcome.media[0].params["local"]["ai_sources"]
    assert record["segment"] == 1 and record["provider"] == "seedream"


def test_a_generator_file_that_is_not_ai_keeps_the_clip_not_ai(
    queue_on: None, assembly_files: dict[str, bytes]
) -> None:
    """A piece of the generator made only from the owner's files (a local video of
    before: its asset says `ai_generated` False) does not turn the label on."""
    key = _block_key(uuid4())
    outcome, _, _ = _assemble(
        _local_clip(SourceSegment(key=key, start_s=0, end_s=4.0, speed=1.0)),
        {**assembly_files, key: _video_with_sound_bytes(4.0, 1.5)},
        clip_id=uuid4(),
        sources={key: _piece(key, provider="local", model_id="local_video", ai=False)},
    )
    assert outcome.failure is None, outcome.detail
    assert outcome.media[0].ai_generated is False
    assert "ai_sources" not in outcome.media[0].params["local"]


@pytest.mark.parametrize(
    ("provider", "params_ai", "draft", "expected"),
    [
        ("seedance", None, False, True),
        ("Seedance", None, False, True),  # some writers capitalize
        ("seedream", None, False, True),
        ("omnihuman", None, False, True),
        ("local", False, False, False),  # its own record wins
        ("local", True, False, True),  # a local video that played a block
        ("qualify_join", True, False, True),  # a join of AI parts says so itself
        ("qualify", None, True, True),  # our composition over a Seedream scene
        ("qualify", None, False, False),  # our composition of the owner's photos
        ("remotion", None, False, False),
    ],
)
def test_an_asset_is_ai_by_its_own_record_then_its_vendor_then_its_draft(
    provider: str, params_ai: bool | None, draft: bool, expected: bool
) -> None:
    assert (
        ca.asset_is_ai(provider=provider, params_ai=params_ai, draft_requires_disclosure=draft)
        is expected
    )
