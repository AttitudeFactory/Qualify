"""EF-11 (m-25026585, ADR 50 §1.1 step 4): Seedance receives what was PREPARED — the
first frame of the first stretch of the owner's own video, upright and 9:16, as a
`data:` URL with `ratio: adaptive` — instead of the file as uploaded; an own video never
produces an `edit` request (D4); another business's file is never read; the frame and its
provenance are kept under the revision and reused on a retry. Offline: the generator's
fakes stand in for Seedance (nothing is paid, no network)."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.enums import ContentFormat, ContentKind, FailureReason
from qualify_creative.schemas import PartRef, SourceSegment

from qualify_api.creative.media import _Saver, generated_key
from qualify_api.creative.video_pipeline.prepared_frame import (
    PREPARED_FRAME_MANIFEST,
    PREPARED_FRAME_NAME,
    OwnVideoModeRefused,
    PreparedFrameFailed,
    prepared_first_frame,
    refuse_stretch_mode,
)
from qualify_api.creative.video_pipeline.recipe import unbuilt_recipe_problems

from .test_creative_media_byteplus import (
    TENANT_ID,
    FakeSeedance,
    MemoryStore,
    _brief,
    _produce,
    _producer,
)

av = pytest.importorskip("av")
Image = pytest.importorskip("PIL.Image")

V25 = "dreamina-seedance-2-5-260628"
V10 = "seedance-1-0-pro-250528"
FIXTURES = Path(__file__).parents[2] / "creative" / "tests" / "fixtures"
OWN = f"uploads/{TENANT_ID}/gopro.mp4"
OWN_PHOTO = f"uploads/{TENANT_ID}/foto.jpg"
OTHER_TENANT = "00000000-0000-4000-8000-000000000099"
FOREIGN = f"uploads/{OTHER_TENANT}/ajeno.mp4"
REEL = f"uploads/{TENANT_ID}/reel.mp4"


def _rotated(rotation: int = 90) -> bytes:
    """EF-01's phone fixture: 64×36 stored, a display matrix of `rotation`° CCW, a red
    band on the stored top edge and a blue one on the stored left edge."""
    return (FIXTURES / f"video-rotated-{rotation}.mp4").read_bytes()


def _is_red(pixel: tuple[int, ...]) -> bool:
    return pixel[0] > 160 and pixel[1] < 100 and pixel[2] < 100


def _is_blue(pixel: tuple[int, ...]) -> bool:
    return pixel[2] > 160 and pixel[0] < 100 and pixel[1] < 100


def _decoded(data_url: str) -> Any:
    head, _, body = data_url.partition(",")
    assert head == "data:image/jpeg;base64", head  # a data URL, never a public link
    return Image.open(io.BytesIO(base64.b64decode(body))).convert("RGB")


def _assert_upright_vertical(image: Any) -> None:
    """9:16 and turned the way a player shows the 90° fixture: red on the left, blue at
    the bottom."""
    width, height = image.size
    assert abs(width / height - 9 / 16) < 0.02, (width, height)
    assert _is_red(image.getpixel((1, height // 2))), image.getpixel((1, height // 2))
    assert _is_blue(image.getpixel((width // 2, height - 2))), image.getpixel(
        (width // 2, height - 2)
    )


class ReadLog(MemoryStore):
    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        super().__init__(files)
        self.reads: list[str] = []

    def read(self, key: str) -> bytes:
        self.reads.append(key)
        return super().read(key)


def _stretch(key: str = OWN, **fields: Any) -> SourceSegment:
    return SourceSegment(key=key, start_s=0.0, end_s=1.0, **fields)


def _clip(mode: str = "motion", *, segments: tuple[SourceSegment, ...] = (), **media: Any) -> Any:
    return _brief(
        ContentKind.CLIP,
        ContentFormat.REELS_9_16,
        duration_seconds=5,
        clip_reference_mode=mode,
        segments=segments or (_stretch(),),
        **media,
    )


def _part(mode: str, *, segments: tuple[SourceSegment, ...] = (), **media: Any) -> Any:
    reel: dict[str, Any] = {"analysis_id": uuid4(), "shot_indexes": (3,)} if mode == "edit" else {}
    part = PartRef(
        index=2,
        mode=mode,  # type: ignore[arg-type]
        seconds=4,
        segments=segments or (_stretch(),),
        **reel,
    )
    return _brief(
        ContentKind.CLIP,
        ContentFormat.REELS_9_16,
        part=part,
        duration_seconds=part.generation_seconds,
        clip_reference_mode={"edit": "edit", "extend": "extend"}.get(mode, "motion"),
        **media,
    )


def _setup(
    files: dict[str, bytes] | None = None, *, model: str = V25, reference: str | None = V25
) -> tuple[Any, ReadLog, FakeSeedance]:
    store = ReadLog({OWN: _rotated(90), **(files or {})})
    seedance = FakeSeedance()
    producer = _producer(store, seedance=seedance)
    producer._seedance_model = model
    producer._seedance_reference_model = reference
    return producer, store, seedance


# ---------------------------------------------------------------------------
# Criterion 1 — with `first_frame` the request carries `ratio: adaptive`, never «9:16»


def test_a_clip_from_own_video_opens_on_its_prepared_frame_with_an_adaptive_ratio() -> None:
    producer, store, seedance = _setup()
    draft_id = uuid4()
    outcome = _produce(producer, _clip(), draft_id)

    assert outcome.failure is None, outcome.detail
    (request,) = seedance.requests
    params = request.params
    assert params["ratio"] == "adaptive" and params["ratio"] != "9:16"
    assert params["model"] == V25
    assert str(params["first_frame"]).startswith("data:image/jpeg;base64,")
    # the uploaded file itself is never handed to the vendor: no video, no public link
    assert "reference_videos" not in params and "reference_images" not in params
    assert all(not str(value).startswith("http") for value in params.values())
    # the adapter's own body keeps it adaptive too (the frame role is there)
    from qualify_creative.adapters.byteplus_ark import _VideoSpec

    body = _VideoSpec.from_params(params, V25).body()
    assert body["ratio"] == "adaptive"
    assert [c.get("role") for c in body["content"]] == [None, "first_frame"]


def test_on_a_2_0_default_model_the_prepared_frame_is_still_adaptive() -> None:
    """2.0 takes `adaptive` but does not force it for a frame: the request asks for it."""
    from qualify_creative.adapters.byteplus_ark import _VideoSpec

    producer, _store, seedance = _setup(model="dreamina-seedance-2-0-260128", reference=None)
    outcome = _produce(producer, _clip(), uuid4())

    assert outcome.failure is None, outcome.detail
    (request,) = seedance.requests
    assert request.params["ratio"] == "adaptive"
    assert _VideoSpec.from_params(request.params, V25).body()["ratio"] == "adaptive"


def test_on_seedance_1_0_alone_a_prepared_frame_is_refused_before_any_spend() -> None:
    """1.0 takes no adaptive ratio: the frame is never sent with «9:16» — refused."""
    producer, _store, seedance = _setup(model=V10, reference=None)
    outcome = _produce(producer, _clip(), uuid4())

    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert seedance.requests == [] and outcome.usage == ()


def test_the_1_0_default_falls_to_the_reference_model_for_a_prepared_frame() -> None:
    producer, _store, seedance = _setup(model=V10, reference=V25)
    outcome = _produce(producer, _clip(), uuid4())

    assert outcome.failure is None, outcome.detail
    (request,) = seedance.requests
    assert (request.params["model"], request.params["ratio"]) == (V25, "adaptive")


def test_a_clip_without_stretches_keeps_its_frames_as_today() -> None:
    """Nothing changes for a Clip that has no own stretches (its opening frame as it was)."""
    first = f"uploads/{TENANT_ID}/first.jpg"
    out = io.BytesIO()
    Image.new("RGB", (400, 500), (200, 40, 40)).save(out, format="JPEG")
    producer, store, seedance = _setup({first: out.getvalue()}, model=V10, reference=None)
    brief = _brief(ContentKind.CLIP, duration_seconds=5, clip_first_frame_key=first)
    outcome = _produce(producer, brief, uuid4())

    assert outcome.failure is None, outcome.detail
    (request,) = seedance.requests
    assert request.params["ratio"] == "9:16" and "model" not in request.params
    assert "prepared_frame" not in outcome.media[0].params
    assert OWN not in store.reads


# ---------------------------------------------------------------------------
# Criterion 2 — the frame sent is 9:16 and upright (EF-01's rotation fixture)


def test_the_frame_sent_is_vertical_and_upright_with_the_rotation_fixture() -> None:
    producer, _store, seedance = _setup()
    outcome = _produce(producer, _clip(), uuid4())

    assert outcome.failure is None, outcome.detail
    (request,) = seedance.requests
    _assert_upright_vertical(_decoded(str(request.params["first_frame"])))


def test_the_owners_own_turn_is_applied_on_top_of_the_phones() -> None:
    """«Girar» 180° on the 90° fixture: red ends on the right, blue at the top."""
    producer, _store, seedance = _setup()
    outcome = _produce(producer, _clip(segments=(_stretch(rotate=180),)), uuid4())

    assert outcome.failure is None, outcome.detail
    image = _decoded(str(seedance.requests[0].params["first_frame"]))
    width, height = image.size
    assert abs(width / height - 9 / 16) < 0.02
    assert _is_red(image.getpixel((width - 2, height // 2)))
    assert _is_blue(image.getpixel((width // 2, 1)))


def test_a_landscape_photo_stretch_is_cropped_to_9_16() -> None:
    out = io.BytesIO()
    Image.new("RGB", (1600, 900), (20, 160, 40)).save(out, format="JPEG")
    producer, _store, seedance = _setup({OWN_PHOTO: out.getvalue()})
    photo = SourceSegment(key=OWN_PHOTO, start_s=0.0, end_s=3.0, kind="photo")
    outcome = _produce(producer, _clip(segments=(photo,)), uuid4())

    assert outcome.failure is None, outcome.detail
    image = _decoded(str(seedance.requests[0].params["first_frame"]))
    assert abs(image.size[0] / image.size[1] - 9 / 16) < 0.02


def test_the_helper_alone_prepares_the_fixture_upright_and_vertical(tmp_path: Path) -> None:
    from qualify_creative.video.opening_frame import prepared_opening_frame

    source = tmp_path / "source.mp4"
    source.write_bytes(_rotated(90))
    frame = prepared_opening_frame(source, key=OWN, start_s=0.0, end_s=1.0)
    image = Image.open(io.BytesIO(frame.jpeg)).convert("RGB")
    _assert_upright_vertical(image)
    assert (frame.width, frame.height) == image.size
    assert frame.params["turn"] == 90 and frame.params["at_s"] == 0.0


# ---------------------------------------------------------------------------
# Criterion 3 — an own video never produces an `edit` request (D4)


def test_an_own_video_clip_asked_as_edit_never_reaches_seedance() -> None:
    producer, store, seedance = _setup()
    edit = _clip("edit", clip_video_keys=(REEL,), clip_image_keys=(OWN_PHOTO,))
    outcome = _produce(producer, edit, uuid4())

    assert outcome.failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value
    assert seedance.requests == [] and outcome.usage == ()
    assert OWN not in store.reads  # refused before anything was read


@pytest.mark.parametrize("mode", ["edit", "extend"])
def test_an_own_video_part_asked_as_edit_or_extend_never_reaches_seedance(mode: str) -> None:
    producer, store, seedance = _setup()
    producer._part_windows = lambda **_: pytest.fail("no window is cut for an own video")
    part = _part(mode, clip_image_keys=(OWN_PHOTO,), clip_image_roles=("product",))
    outcome = _produce(producer, part, uuid4())

    assert outcome.failure == FailureReason.PART_FAILED.value
    assert seedance.requests == [] and outcome.usage == ()
    assert OWN not in store.reads


def test_d4_rule_and_recipe_gate_agree() -> None:
    stretches = (_stretch(),)
    for mode in ("edit", "extend"):
        with pytest.raises(OwnVideoModeRefused):
            refuse_stretch_mode(mode, stretches)
    for mode in ("motion", "reference", "local"):
        refuse_stretch_mode(mode, stretches)
    refuse_stretch_mode("edit", ())  # no own video: not this rule's
    # the creation gate: a `reference` Clip with stretches may be made; an `edit` one not
    assert unbuilt_recipe_problems(_clip()) == ()
    edit = _clip("edit", clip_video_keys=(REEL,), clip_image_keys=(OWN_PHOTO,))
    assert [(p.code, p.field) for p in unbuilt_recipe_problems(edit)] == [
        ("recipe_unavailable", "segments")
    ]


def test_a_reference_part_from_own_video_opens_on_the_prepared_frame() -> None:
    producer, _store, seedance = _setup()
    outcome = _produce(producer, _part("reference"), uuid4())

    assert outcome.failure is None, outcome.detail
    (request,) = seedance.requests
    params = request.params
    assert params.get("omni_reference_task_type") != "edit"
    assert params["ratio"] == "adaptive"
    _assert_upright_vertical(_decoded(str(params["first_frame"])))


# ---------------------------------------------------------------------------
# Criterion 4 — no byte of another business reaches the request (`owned_by`)


def test_another_business_stretch_is_never_read_nor_sent() -> None:
    producer, store, seedance = _setup({FOREIGN: _rotated(90)})
    outcome = _produce(producer, _clip(segments=(_stretch(FOREIGN),)), uuid4())

    assert outcome.failure is not None
    assert seedance.requests == [] and outcome.usage == ()
    assert FOREIGN not in store.reads


def test_the_helper_refuses_a_foreign_stretch_before_any_read() -> None:
    store = ReadLog({OWN: _rotated(90), FOREIGN: _rotated(90)})
    save = _Saver(store, TENANT_ID, uuid4(), 1)
    with pytest.raises(PreparedFrameFailed) as refused:
        prepared_first_frame(
            tenant_id=TENANT_ID,
            segments=(_stretch(), _stretch(FOREIGN)),
            store=store,
            save=save,
        )
    assert refused.value.failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value
    assert store.reads == []


# ---------------------------------------------------------------------------
# Provenance and idempotency


def test_the_asset_records_which_prepared_stretch_the_frame_came_from() -> None:
    producer, store, _seedance = _setup()
    draft_id = uuid4()
    outcome = _produce(producer, _clip(), draft_id)

    assert outcome.failure is None, outcome.detail
    (video,) = outcome.media
    provenance = video.params["prepared_frame"]
    assert provenance["segment"] == {
        "key": OWN,
        "start_s": 0.0,
        "end_s": 1.0,
        "rotate": 0,
        "kind": "video",
    }
    assert provenance["segment_index"] == 0
    assert provenance["frame"]["version"] == "opening-frame-v1"
    assert provenance["frame"]["prepare_version"].startswith("prepare-v")
    assert provenance["sent_as"] == "data_url"
    assert provenance["frame_key"] == generated_key(TENANT_ID, draft_id, PREPARED_FRAME_NAME)
    assert store.files[provenance["frame_key"]]
    manifest = json.loads(store.files[generated_key(TENANT_ID, draft_id, PREPARED_FRAME_MANIFEST)])
    assert manifest == provenance


def test_a_retry_of_the_same_revision_sends_the_same_frame_without_decoding_again() -> None:
    producer, store, seedance = _setup()
    draft_id = uuid4()
    first = _produce(producer, _clip(), draft_id)
    reads = store.reads.count(OWN)
    second = _produce(producer, _clip(), draft_id)

    assert first.failure is None and second.failure is None
    one, two = seedance.requests
    assert one.params["first_frame"] == two.params["first_frame"]
    assert store.reads.count(OWN) == reads  # the kept frame was reused, the video not reread
    assert (
        first.media[0].params["prepared_frame"]["sha256"]
        == second.media[0].params["prepared_frame"]["sha256"]
    )


def test_a_different_stretch_in_the_same_revision_is_prepared_again() -> None:
    producer, store, seedance = _setup()
    draft_id = uuid4()
    _produce(producer, _clip(), draft_id)
    _produce(producer, _clip(segments=(_stretch(rotate=180),)), draft_id)

    assert store.reads.count(OWN) == 2
    one, two = seedance.requests
    assert one.params["first_frame"] != two.params["first_frame"]


def test_a_stretch_gone_from_storage_fails_saying_so_before_any_spend() -> None:
    producer, store, seedance = _setup()
    del store.files[OWN]
    outcome = _produce(producer, _clip(), uuid4())

    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert "Ya no encontramos el video" in str(outcome.detail)
    assert seedance.requests == []


def test_an_unreadable_stretch_fails_before_any_spend() -> None:
    producer, _store, seedance = _setup({OWN: b"not a video"})
    outcome = _produce(producer, _clip(), uuid4())

    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert seedance.requests == []


# ---------------------------------------------------------------------------
# Review of 70bd652b: the source through `LocalSources` (normalized copy, or wait)


@pytest.fixture(autouse=True)
def no_normalize_jobs(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The `normalize_local` jobs in memory (offline), none to begin with."""
    from qualify_api.creative.video_pipeline import local_sources

    jobs = local_sources.InMemoryLocalSourceJobs()
    monkeypatch.setattr(local_sources, "default_jobs", lambda: jobs)
    return jobs


def test_a_source_over_4k_or_10_bit_waits_for_its_copy_and_nothing_is_decoded(
    monkeypatch: pytest.MonkeyPatch, no_normalize_jobs: Any
) -> None:
    from qualify_creative.video import prepare
    from qualify_creative.video.source_limits import SourceHeader

    from qualify_api.creative.queue_dispatch import CheckpointError
    from qualify_api.creative.video_pipeline import local_sources

    monkeypatch.setattr(
        local_sources,
        "_read_header",
        lambda _path: SourceHeader(width=5120, height=2880, pix_fmt="yuv420p10le"),
    )
    decoded: list[str] = []
    monkeypatch.setattr(prepare, "read_source", lambda source: decoded.append(str(source)))
    producer, _store, seedance = _setup()
    with pytest.raises(local_sources.LocalSourceNormalizing) as waited:
        _produce(producer, _clip(), uuid4())
    assert isinstance(waited.value, CheckpointError)  # the worker retries it later
    assert no_normalize_jobs.enqueued == [OWN]
    assert decoded == [] and seedance.requests == []


def test_a_normalized_copy_is_read_instead_of_the_original_and_recorded(
    no_normalize_jobs: Any,
) -> None:
    from qualify_api.creative.video_pipeline.local_sources import NormalizeJob, normalized_key

    copy = normalized_key(TENANT_ID, OWN)
    no_normalize_jobs.jobs[OWN] = NormalizeJob(
        status="done", normalized_key=copy, version="normalize-local-test"
    )
    # the original is 5K 10-bit: never opened; its copy is the phone fixture
    producer, store, seedance = _setup({OWN: b"too big to decode here", copy: _rotated(90)})
    outcome = _produce(producer, _clip(), uuid4())

    assert outcome.failure is None, outcome.detail
    assert OWN not in store.reads and copy in store.reads
    _assert_upright_vertical(_decoded(str(seedance.requests[0].params["first_frame"])))
    source = outcome.media[0].params["prepared_frame"]["source"]
    assert source["source_key"] == OWN
    assert (source["normalized_key"], source["normalizer_version"]) == (
        copy,
        "normalize-local-test",
    )


def test_a_source_read_as_it_is_records_the_header_it_passed() -> None:
    producer, _store, _seedance = _setup()
    outcome = _produce(producer, _clip(), uuid4())

    source = outcome.media[0].params["prepared_frame"]["source"]
    assert source["source_key"] == OWN and source["normalized_key"] is None
    assert source["header"]["width"] == 64  # the stored picture, read from the header only


# ---------------------------------------------------------------------------
# Review: a `reference` part with photos — the frame is «Image 1», the photos follow


PHOTO = f"uploads/{TENANT_ID}/burger.jpg"


@pytest.fixture(autouse=True)
def refs_switch_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """`QUALIFY_PARTS_PREPARED_FRAME_REFS` starts off in every test, whatever the shell
    exports; a test that wants it on sets it itself."""
    from qualify_api.creative.video_pipeline.prepared_frame import PREPARED_FRAME_REFS_SWITCH

    monkeypatch.delenv(PREPARED_FRAME_REFS_SWITCH, raising=False)


def _photo_jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (400, 500), (200, 40, 40)).save(out, format="JPEG")
    return out.getvalue()


def _photo_part(*, own: bool = True) -> Any:
    fields: dict[str, Any] = {"clip_image_keys": (PHOTO,), "clip_image_roles": ("product",)}
    if own:
        brief = _part("reference", **fields)
    else:
        part = PartRef(index=2, mode="reference", seconds=4)
        brief = _brief(
            ContentKind.CLIP,
            ContentFormat.REELS_9_16,
            part=part,
            duration_seconds=part.generation_seconds,
            clip_reference_mode="motion",
            **fields,
        )
    return brief.model_copy(update={"product_ref": "Smash doble"})


def test_switch_off_a_reference_part_with_photos_and_own_video_is_refused_as_on_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review F1: with `QUALIFY_PARTS_PREPARED_FRAME_REFS` off (the default) a `reference`
    part with own stretches AND photos is refused as on main (`recipe_unavailable` at
    the recipe gate; before the copy and before any vendor call in the producer) — never
    made ignoring the owner's video. Nothing is read nor decoded."""
    from qualify_creative.video import prepare

    from qualify_api.creative.brand_references import BrandReferenceError
    from qualify_api.creative.video_pipeline.prepared_frame import (
        STRETCHES_WITH_REFERENCES_TEXT,
    )

    decoded: list[str] = []
    real = prepare.read_source
    monkeypatch.setattr(
        prepare, "read_source", lambda source: decoded.append(str(source)) or real(source)
    )
    assert [(p.code, p.field) for p in unbuilt_recipe_problems(_photo_part())] == [
        ("recipe_unavailable", "segments")
    ]
    producer, store, seedance = _setup({PHOTO: _photo_jpeg()})
    with pytest.raises(BrandReferenceError) as refused:
        producer.prepare_reference_videos(
            tenant_id=TENANT_ID, draft_id=uuid4(), brief=_photo_part()
        )
    assert refused.value.detail == STRETCHES_WITH_REFERENCES_TEXT
    outcome = _produce(producer, _photo_part(), uuid4())
    assert outcome.failure == FailureReason.PART_FAILED.value
    assert outcome.detail == STRETCHES_WITH_REFERENCES_TEXT
    assert seedance.requests == [] and outcome.usage == ()
    assert OWN not in store.reads and decoded == []
    # the same part without own stretches is made as always
    assert _produce(producer, _photo_part(own=False), uuid4()).failure is None


def test_switch_on_the_recipe_gate_lets_the_part_with_photos_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.creative.video_pipeline.prepared_frame import PREPARED_FRAME_REFS_SWITCH

    monkeypatch.setenv(PREPARED_FRAME_REFS_SWITCH, "on")
    assert unbuilt_recipe_problems(_photo_part()) == ()


def test_the_recipe_gate_reads_a_parents_plan_entries_the_same_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parent's `reference` entry with own stretches inherits the parent's photos when
    it names none: refused while the switch is off, let through when it is on; an entry
    that deliberately uses no photo is let through either way."""
    from qualify_creative.schemas import VideoPartPlan

    from qualify_api.creative.video_pipeline.prepared_frame import PREPARED_FRAME_REFS_SWITCH

    def parent(**entry: Any) -> Any:
        plan = VideoPartPlan(seconds=4, description="Uno.", segments=(_stretch(),), **entry)
        return _brief(ContentKind.SHOT_VIDEO, clip_image_keys=(PHOTO,), parts=(plan,))

    assert [(p.code, p.field) for p in unbuilt_recipe_problems(parent())] == [
        ("recipe_unavailable", "segments")
    ]
    assert unbuilt_recipe_problems(parent(clip_image_keys=())) == ()
    monkeypatch.setenv(PREPARED_FRAME_REFS_SWITCH, "on")
    assert unbuilt_recipe_problems(parent()) == ()


# ---------------------------------------------------------------------------
# Review F2 and F4a: the reference-image limit; a passing read failure is retried


def test_the_prepared_frame_counts_against_the_reference_image_limit() -> None:
    from qualify_api.creative.brand_references import BrandReferenceError

    photos = tuple(f"uploads/{TENANT_ID}/p{i}.jpg" for i in range(9))
    producer, store, _seedance = _setup()
    brief = _clip(clip_image_keys=photos, clip_image_roles=("product",) * 9)
    with pytest.raises(BrandReferenceError) as refused:
        producer.prepare_reference_videos(tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief)
    assert "caben hasta 8 fotos" in refused.value.detail
    assert store.reads == []  # refused before anything is read or paid


def test_no_room_left_for_photos_says_so_without_a_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A limit the frame alone fills: its own text, never «caben hasta 0 fotos»."""
    from qualify_api.creative import media as media_module
    from qualify_api.creative.brand_references import BrandReferenceError

    monkeypatch.setattr(media_module, "CLIP_MAX_IMAGES", 1)
    producer, store, _seedance = _setup()
    brief = _clip(clip_image_keys=(PHOTO,), clip_image_roles=("product",))
    with pytest.raises(BrandReferenceError) as refused:
        producer.prepare_reference_videos(tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief)
    assert refused.value.detail == (
        "Con tu video no caben fotos de referencia. Quítalas y vuelve a crear el video."
    )
    assert store.reads == []


def test_room_for_one_photo_says_one_photo(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.creative import media as media_module
    from qualify_api.creative.brand_references import BrandReferenceError

    monkeypatch.setattr(media_module, "CLIP_MAX_IMAGES", 2)
    producer, _store, _seedance = _setup()
    photos = (PHOTO, f"uploads/{TENANT_ID}/otra.jpg")
    brief = _clip(clip_image_keys=photos, clip_image_roles=("product", "product"))
    with pytest.raises(BrandReferenceError) as refused:
        producer.prepare_reference_videos(tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief)
    assert refused.value.detail == (
        "Con tu video cabe 1 foto de referencia. Quita las que sobren y vuelve a crear el video."
    )


def test_room_for_several_photos_says_how_many() -> None:
    from qualify_api.creative.brand_references import BrandReferenceError

    photos = tuple(f"uploads/{TENANT_ID}/p{i}.jpg" for i in range(9))
    producer, _store, _seedance = _setup()
    brief = _clip(clip_image_keys=photos, clip_image_roles=("product",) * 9)
    with pytest.raises(BrandReferenceError) as refused:
        producer.prepare_reference_videos(tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief)
    assert refused.value.detail == (
        "Con tu video caben hasta 8 fotos de referencia. Quita las que sobren y vuelve a "
        "crear el video."
    )


def test_a_passing_read_failure_is_retried_not_failed() -> None:
    from qualify_api.creative.queue_dispatch import CheckpointError

    class Flaky(ReadLog):
        def read(self, key: str) -> bytes:
            if key == OWN:
                raise ConnectionError("R2 timed out")
            return super().read(key)

    store = Flaky({OWN: _rotated(90)})
    save = _Saver(store, TENANT_ID, uuid4(), 1)
    with pytest.raises(CheckpointError):
        prepared_first_frame(tenant_id=TENANT_ID, segments=(_stretch(),), store=store, save=save)

    producer, _store, seedance = _setup()
    producer._store = Flaky({OWN: _rotated(90)})
    with pytest.raises(CheckpointError):
        _produce(producer, _clip(), uuid4())
    assert seedance.requests == []


def test_switch_off_a_clip_and_a_part_without_photos_still_open_on_the_frame() -> None:
    producer, _store, seedance = _setup()
    assert _produce(producer, _clip(), uuid4()).failure is None
    assert _produce(producer, _part("reference"), uuid4()).failure is None
    assert all(str(r.params["first_frame"]).startswith("data:") for r in seedance.requests)


def test_an_unknown_switch_value_reads_as_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.creative.video_pipeline.prepared_frame import (
        PREPARED_FRAME_REFS_SWITCH,
        prepared_frame_with_references,
    )

    monkeypatch.setenv(PREPARED_FRAME_REFS_SWITCH, "si")
    assert prepared_frame_with_references() is False
    monkeypatch.setenv(PREPARED_FRAME_REFS_SWITCH, " ON ")
    assert prepared_frame_with_references() is True


def test_a_reference_part_with_photos_names_the_prepared_frame_image_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Switch on: the prepared frame is reference «Image 1», prompt version 6."""
    from qualify_api.creative.media import PART_PREPARED_FRAME_PROMPT_VERSION
    from qualify_api.creative.video_pipeline.prepared_frame import PREPARED_FRAME_REFS_SWITCH

    monkeypatch.setenv(PREPARED_FRAME_REFS_SWITCH, "on")
    producer, _store, seedance = _setup({PHOTO: _photo_jpeg()})
    outcome = _produce(producer, _photo_part(), uuid4())

    assert outcome.failure is None, outcome.detail
    (request,) = seedance.requests
    params = request.params
    # ModelArk takes no `first_frame` beside references: the frame is the first image
    assert "first_frame" not in params and len(params["reference_images"]) == 2
    _assert_upright_vertical(_decoded(str(params["reference_images"][0])))
    prompt = str(params["prompt"])
    assert "The opening frame is Image 1" in prompt
    assert "Image 2" in prompt and "Image 1: the client" not in prompt
    video = outcome.media[0]
    assert video.params["part"]["prompt_version"] == PART_PREPARED_FRAME_PROMPT_VERSION
    (frame,) = [m for m in video.params["reference_manifest"] if m["role"] == "opening_frame"]
    assert frame["source_key"] == OWN


def test_a_reference_part_without_the_flag_keeps_its_prompt_text() -> None:
    """The prompt change is only for a part opening on its prepared frame."""
    from qualify_api.creative.media import part_reference_prompt

    from .test_creative_media_byteplus import _kit

    photo = f"uploads/{TENANT_ID}/burger.jpg"
    part = PartRef(index=2, mode="reference", seconds=4)
    brief = _brief(
        ContentKind.CLIP,
        ContentFormat.REELS_9_16,
        part=part,
        duration_seconds=part.generation_seconds,
        clip_image_keys=(photo,),
        clip_image_roles=("product",),
    )
    plain = part_reference_prompt(brief=brief, kit=_kit(), images=1)
    flagged = part_reference_prompt(brief=brief, kit=_kit(), images=1, opening_frame=True)
    assert "opening frame" not in plain and "Image 1" in plain
    assert "The opening frame is Image 1" in flagged and "Image 2" in flagged


# ---------------------------------------------------------------------------
# Review: spending order — refused before the copy is paid


def _service_prepare(producer: Any, brief: Any, draft_id: Any) -> None:
    producer.prepare_reference_videos(tenant_id=TENANT_ID, draft_id=draft_id, brief=brief)


def test_no_2x_model_is_refused_before_the_copy_is_paid() -> None:
    from qualify_api.creative.brand_references import BrandReferenceError

    producer, store, _seedance = _setup(model=V10, reference=None)
    with pytest.raises(BrandReferenceError):
        _service_prepare(producer, _clip(), uuid4())
    assert OWN not in store.reads  # the model is checked before the file is read


def test_a_stretch_gone_is_refused_before_the_copy_is_paid() -> None:
    from qualify_api.creative.brand_references import BrandReferenceError

    producer, store, _seedance = _setup()
    del store.files[OWN]
    with pytest.raises(BrandReferenceError) as refused:
        _service_prepare(producer, _clip(), uuid4())
    assert "Ya no encontramos el video" in str(refused.value.detail)


def test_d4_is_refused_before_the_copy_is_paid() -> None:
    from qualify_api.creative.brand_references import BrandReferenceError

    producer, store, _seedance = _setup()
    edit = _clip("edit", clip_video_keys=(REEL,), clip_image_keys=(OWN_PHOTO,))
    with pytest.raises(BrandReferenceError):
        _service_prepare(producer, edit, uuid4())
    assert store.reads == []


def test_the_frame_made_before_the_copy_is_the_one_the_clip_sends() -> None:
    producer, store, seedance = _setup()
    draft_id = uuid4()
    _service_prepare(producer, _clip(), draft_id)
    assert store.reads.count(OWN) == 1
    outcome = _produce(producer, _clip(), draft_id)

    assert outcome.failure is None, outcome.detail
    assert store.reads.count(OWN) == 1  # read back, not prepared again
    assert seedance.requests[0].params["first_frame"]


def test_a_local_clip_needs_no_prepared_frame_before_the_copy() -> None:
    producer, store, _seedance = _setup(model=V10, reference=None)
    _service_prepare(producer, _clip("local"), uuid4())
    assert store.reads == []


# ---------------------------------------------------------------------------
# Review: sha256 of the bytes sent; a photo kept at most 1080×1920; a bad manifest


def test_the_manifest_records_the_sha256_of_the_bytes_sent() -> None:
    import hashlib

    producer, _store, seedance = _setup()
    outcome = _produce(producer, _clip(), uuid4())

    sent = base64.b64decode(str(seedance.requests[0].params["first_frame"]).partition(",")[2])
    provenance = outcome.media[0].params["prepared_frame"]
    assert provenance["sent_sha256"] == hashlib.sha256(sent).hexdigest()
    assert provenance["sent_sha256"] != provenance["sha256"]  # q90 sent, q92 kept


def test_a_big_photo_stretch_is_kept_at_most_1080_by_1920() -> None:
    out = io.BytesIO()
    Image.new("RGB", (4000, 3000), (20, 160, 40)).save(out, format="JPEG")
    producer, store, _seedance = _setup({OWN_PHOTO: out.getvalue()})
    photo = SourceSegment(key=OWN_PHOTO, start_s=0.0, end_s=3.0, kind="photo")
    outcome = _produce(producer, _clip(segments=(photo,)), uuid4())

    assert outcome.failure is None, outcome.detail
    key = outcome.media[0].params["prepared_frame"]["frame_key"]
    kept = Image.open(io.BytesIO(store.files[key]))
    assert kept.size[0] <= 1080 and kept.size[1] <= 1920
    assert abs(kept.size[0] / kept.size[1] - 9 / 16) < 0.02


def test_a_manifest_whose_frame_is_not_a_dict_is_made_again() -> None:
    store = ReadLog({OWN: _rotated(90)})
    draft_id = uuid4()
    save = _Saver(store, TENANT_ID, draft_id, 1)
    made = prepared_first_frame(tenant_id=TENANT_ID, segments=(_stretch(),), store=store, save=save)
    assert made is not None
    key = generated_key(TENANT_ID, draft_id, PREPARED_FRAME_MANIFEST)
    broken = json.loads(store.files[key])
    broken["frame"] = "not a dict"
    store.files[key] = json.dumps(broken).encode()
    again = prepared_first_frame(
        tenant_id=TENANT_ID, segments=(_stretch(),), store=store, save=save
    )
    assert again is not None and store.reads.count(OWN) == 2
