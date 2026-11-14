"""«Sigue a la anterior» (m-24880328 + VE-13 m-24921070): an `extend` part continues the
previous part's own vendor file, byte for byte; it WAITS (nothing captured, nothing paid)
until that part has a vista previa; what it continued is sticky per revision; the join
keeps only the new stretch whether the vendor returns it alone or after the input; a
changed previous part makes it «Hay que rehacerla»; a cut over 10 s is made `reference`
+ `extend`. All behind `QUALIFY_PARTS_EXTEND`. Offline: the clip tests' fakes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentFormat, ContentKind, FailureReason
from qualify_creative.schemas import PartRef

from qualify_api.creative.media import PART_EXTEND_PROMPT_VERSION, part_extend_prompt
from qualify_api.creative.part_extend import (
    EXTEND_MANIFEST,
    EXTEND_OUTPUT_SWITCH,
    EXTEND_SWITCH,
    SEGMENT,
    WHOLE,
    PreviousLookup,
    PreviousPart,
    SiblingPart,
    continued_key,
    extend_available,
    extend_is_stale,
    extend_offset,
    extend_output,
    pick_previous,
    source_key,
)
from qualify_api.creative.part_join import part_span

from .test_creative_clip import RecordingLinks
from .test_creative_media_byteplus import TENANT_ID, MemoryStore, _brief, _produce, _producer
from .test_creative_part_clip import V25, DraftSeedance, _jpeg, _mp4

ANALYSIS_ID = UUID("5e1f0000-0000-4000-8000-0000000000c1")
PHOTO = f"uploads/{TENANT_ID}/burger.jpg"
PREVIOUS = UUID("11111111-0000-4000-8000-000000000001")
ASSET = UUID("22222222-0000-4000-8000-000000000002")
RAW = f"t/{TENANT_ID}/generated/{PREVIOUS}/r1/queue-job-1.bin"
NOW = 1_800_000_000.0


@pytest.fixture
def extend_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EXTEND_SWITCH, "draft")
    monkeypatch.delenv(EXTEND_OUTPUT_SWITCH, raising=False)


# ---------------------------------------------------------------------------
# the switches


@pytest.mark.parametrize(
    ("value", "on"), [(None, False), ("off", False), ("draft", True), ("DRAFT", True), ("x", False)]
)
def test_extend_is_off_unless_switched_to_draft(
    monkeypatch: pytest.MonkeyPatch, value: str | None, on: bool
) -> None:
    if value is None:
        monkeypatch.delenv(EXTEND_SWITCH, raising=False)
    else:
        monkeypatch.setenv(EXTEND_SWITCH, value)
    assert extend_available() is on


def test_the_output_is_read_from_its_length_unless_the_switch_says(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(EXTEND_OUTPUT_SWITCH, raising=False)
    assert extend_output(output_s=5.04, input_s=5.0, asked_s=5) == SEGMENT
    assert extend_output(output_s=10.04, input_s=5.0, asked_s=5) == WHOLE
    assert extend_output(output_s=9.0, input_s=5.0, asked_s=4) == WHOLE
    assert extend_output(output_s=None, input_s=5.0, asked_s=5) == SEGMENT  # unreadable
    monkeypatch.setenv(EXTEND_OUTPUT_SWITCH, "whole")
    assert extend_output(output_s=5.0, input_s=5.0, asked_s=5) == WHOLE
    monkeypatch.setenv(EXTEND_OUTPUT_SWITCH, "segment")
    assert extend_output(output_s=10.0, input_s=5.0, asked_s=5) == SEGMENT


# ---------------------------------------------------------------------------
# the previous part (pure)


def _sibling(index: int, status: str = "generated", **kw: Any) -> SiblingPart:
    params = kw.pop("params", {"draft": {"created_at": NOW - 60}, "part": {"raw_key": RAW}})
    return SiblingPart(
        index=index, draft_id=kw.pop("draft_id", PREVIOUS), status=status, params=params, **kw
    )


def test_the_previous_part_with_a_vista_previa_is_continued() -> None:
    found = pick_previous(2, [_sibling(1, asset_id=ASSET)], now=NOW)
    assert found.state == "ready" and found.source is not None
    assert found.source.key == RAW and found.source.asset_id == ASSET


@pytest.mark.parametrize("status", ["drafting", "failed"])
def test_a_previous_part_still_being_made_or_failed_is_waited_for(status: str) -> None:
    assert pick_previous(2, [_sibling(1, status)], now=NOW).state == "waiting"


def test_a_previous_part_not_created_yet_is_waited_for() -> None:
    assert pick_previous(3, [_sibling(1)], now=NOW).state == "waiting"  # part 2 unmade


def test_an_expired_or_purged_previous_part_is_waited_for() -> None:
    old = _sibling(1, params={"draft": {"created_at": NOW - 8 * 86400}, "part": {"raw_key": RAW}})
    assert pick_previous(2, [old], now=NOW).state == "waiting"
    assert pick_previous(2, [_sibling(1, purged=True)], now=NOW).state == "waiting"


def test_a_removed_part_is_skipped_and_the_first_part_has_none() -> None:
    kept = _sibling(1)
    gone = _sibling(2, removed=True, draft_id=uuid4())
    assert pick_previous(3, [kept, gone], now=NOW).state == "ready"
    assert pick_previous(1, [], now=NOW).state == "missing"
    assert pick_previous(2, [_sibling(1, removed=True)], now=NOW).state == "missing"


def test_the_clean_file_is_continued_when_no_raw_file_was_kept() -> None:
    params = {"draft": {"created_at": NOW}, "part": {"raw_key": None, "clean_key": "x/clip.mp4"}}
    assert source_key(params) == "x/clip.mp4"
    assert source_key({"part": {}}) is None


# ---------------------------------------------------------------------------
# the request (m-24880328)


@dataclass
class FakePrevious:
    """`PreviousParts`: answers what the test sets; records every ask."""

    lookup: PreviousLookup
    calls: list[UUID] = field(default_factory=list)

    def __call__(self, *, tenant_id: UUID, draft_id: UUID) -> PreviousLookup:
        assert tenant_id == TENANT_ID
        self.calls.append(draft_id)
        return self.lookup


def _ready(key: str = RAW, draft_id: UUID = PREVIOUS) -> PreviousLookup:
    return PreviousLookup("ready", PreviousPart(draft_id, 1, ASSET, key, NOW - 60))


def _extend_brief(seconds: int = 5) -> Any:
    part = PartRef(
        index=2,
        mode="extend",
        seconds=seconds,
        analysis_id=ANALYSIS_ID,
        shot_indexes=(3,),
        description="La mano sirve la hamburguesa en el plato.",
    )
    brief = _brief(
        ContentKind.CLIP,
        ContentFormat.REELS_9_16,
        part=part,
        duration_seconds=part.generation_seconds,
        clip_reference_mode="extend",
        clip_image_keys=(PHOTO,),
        clip_image_roles=("product",),
    )
    return brief.model_copy(update={"product_ref": "Smash doble"})


def _setup(lookup: PreviousLookup, *, previous_seconds: int = 5, output: bytes | None = None):
    store = MemoryStore({PHOTO: _jpeg(), RAW: _mp4(previous_seconds)})
    seedance = DraftSeedance()
    producer = _producer(store, seedance=seedance)
    producer._seedance_reference_model = V25
    producer._seedance_model = V25
    links = RecordingLinks()
    producer._reference_links = links
    previous = FakePrevious(lookup)
    producer._previous_parts = previous
    if output is not None:
        producer._download = lambda url: output
    return producer, store, seedance, previous, links


def test_an_extend_part_continues_the_previous_file_byte_for_byte(extend_on: None) -> None:
    producer, store, seedance, previous, links = _setup(_ready())
    draft_id = uuid4()
    outcome = _produce(producer, _extend_brief(), draft_id)

    assert outcome.failure is None, outcome.detail
    assert previous.calls == [draft_id]
    (request,) = seedance.requests
    params = request.params
    assert params["omni_reference_task_type"] == "extend"
    assert params["ratio"] == "adaptive" and params["duration_seconds"] == 5
    assert params["draft"] is True and params["resolution"] == "480p"
    assert len(params["reference_videos"]) == 1
    assert params["reference_video_seconds"] == pytest.approx(5.0, abs=0.6)
    (sent, content_type), *_ = links.calls
    assert content_type == "video/mp4" and sent.endswith(f"extend-source-{ASSET}.mp4")
    assert f"/{draft_id}/" in sent and store.files[sent] == store.files[RAW]  # not re-encoded
    prompt = str(params["prompt"])
    assert prompt.startswith("Extend video @Video1: continue it seamlessly from its last frame")
    assert "@Image1" in prompt and "Smash doble" in prompt

    (write,) = outcome.media
    meta = write.params["part"]
    assert meta["mode"] == "extend" and write.params["reference_mode"] == "extend"
    assert meta["prompt_version"] == PART_EXTEND_PROMPT_VERSION
    extend = meta["extend"]
    assert extend["source_key"] == RAW and extend["source_draft_id"] == str(PREVIOUS)
    assert extend["source_asset_id"] == str(ASSET) and extend["sent_key"] == sent
    assert extend["output"] == SEGMENT and extend["draft"] is True
    assert continued_key(write.params) == RAW


def test_a_part_waits_without_a_paid_call_while_the_previous_has_no_preview(
    extend_on: None,
) -> None:
    producer, store, seedance, _previous, links = _setup(PreviousLookup("waiting"))
    before = dict(store.files)
    outcome = _produce(producer, _extend_brief(), uuid4())
    assert outcome.pending and outcome.failure is None and not outcome.media
    assert seedance.requests == [] and links.calls == [] and store.files == before


def test_what_a_revision_continued_is_sticky(extend_on: None) -> None:
    producer, store, seedance, previous, _links = _setup(_ready())
    draft_id = uuid4()
    _produce(producer, _extend_brief(), draft_id)
    manifest = next(k for k in store.files if k.endswith(EXTEND_MANIFEST))
    other = f"t/{TENANT_ID}/generated/{PREVIOUS}/r2/queue-job-2.bin"
    store.files[other] = _mp4(6)
    previous.lookup = _ready(other)  # the previous part changed meanwhile
    outcome = _produce(producer, _extend_brief(), draft_id)

    assert len(previous.calls) == 1  # the manifest answered: no second lookup
    assert json.loads(store.files[manifest])["source_key"] == RAW
    assert outcome.media[0].params["part"]["extend"]["source_key"] == RAW
    first, second = seedance.requests
    assert first.params["reference_video_seconds"] == second.params["reference_video_seconds"]


def test_a_whole_video_back_is_recorded_and_joined_from_the_new_stretch(extend_on: None) -> None:
    producer, *_ = _setup(_ready(), previous_seconds=5, output=_mp4(9))
    outcome = _produce(producer, _extend_brief(seconds=4), uuid4())
    extend = outcome.media[0].params["part"]["extend"]
    assert extend["output"] == WHOLE and extend["output_seconds"] == pytest.approx(9, abs=0.6)
    start, end = part_span(outcome.media[0].params)
    assert start == pytest.approx(extend["input_seconds"]) and end == pytest.approx(start + 4)


@pytest.mark.parametrize(
    "lookup",
    [
        PreviousLookup("missing"),
        _ready(f"t/00000000-0000-4000-8000-000000000099/generated/{PREVIOUS}/r1/q.bin"),
        _ready(f"t/{TENANT_ID}/generated/{uuid4()}/r1/queue-job-1.bin"),  # another part's
    ],
)
def test_no_previous_or_a_file_not_its_own_fails_before_any_spend(
    extend_on: None, lookup: PreviousLookup
) -> None:
    producer, store, seedance, _previous, links = _setup(lookup)
    store.files[lookup.source.key if lookup.source else "x"] = _mp4(5)
    outcome = _produce(producer, _extend_brief(), uuid4())
    assert outcome.failure == FailureReason.PART_FAILED.value
    assert seedance.requests == [] and links.calls == []


def test_a_previous_file_outside_two_to_thirty_seconds_fails_before_any_spend(
    extend_on: None,
) -> None:
    producer, store, seedance, *_ = _setup(_ready())
    store.files[RAW] = b"not a video"
    outcome = _produce(producer, _extend_brief(), uuid4())
    assert outcome.failure == FailureReason.PART_FAILED.value and seedance.requests == []


def test_switched_off_an_extend_part_is_never_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EXTEND_SWITCH, "off")
    producer, _store, seedance, previous, _links = _setup(_ready())
    outcome = _produce(producer, _extend_brief(), uuid4())
    assert outcome.failure == FailureReason.PART_FAILED.value
    assert seedance.requests == [] and previous.calls == []


def test_the_extend_prompt_asks_for_an_extension_with_the_brand_rules() -> None:
    from .test_creative_media_byteplus import _kit

    prompt = part_extend_prompt(brief=_extend_brief(), kit=_kit(), images=0, model=V25)
    assert "Extend video @Video1" in prompt and "5 more seconds" in prompt
    assert "La mano sirve la hamburguesa" in prompt
    assert "@Image" not in prompt


# ---------------------------------------------------------------------------
# the join never shows a frame twice (synthetic, both readings of the output)


FPS = 8
STEP = 7  # grey levels apart per frame (lossless encode: 32 frames fit in 0..217)


def _grey_clip(path: Path, levels: list[int]) -> Path:
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    with av.open(str(path), "w", format="mp4") as sink:
        stream = sink.add_stream("libx264", rate=FPS)
        stream.width, stream.height, stream.pix_fmt = 64, 112, "yuv420p"
        stream.options = {"crf": "0"}
        for i, level in enumerate(levels):
            frame = av.VideoFrame.from_ndarray(
                np.full((112, 64, 3), level, dtype=np.uint8), format="rgb24"
            )
            frame.pts = i
            frame.time_base = Fraction(1, FPS)
            for packet in stream.encode(frame):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    return path


def _levels(data_path: Path) -> list[int]:
    av = pytest.importorskip("av")
    with av.open(str(data_path)) as source:
        return [
            round(float(frame.to_ndarray(format="gray").mean()) / STEP)
            for frame in source.decode(video=0)
        ]


@pytest.mark.parametrize("output", [SEGMENT, WHOLE])
def test_the_join_does_not_duplicate_frames(tmp_path: Path, output: str) -> None:
    from qualify_creative.video import JoinClip, join_clips

    previous_frames = [STEP * i for i in range(2 * FPS)]  # 2 s: levels 0..15
    new_frames = [STEP * i for i in range(2 * FPS, 4 * FPS)]  # the next 2 s: 16..31
    first = _grey_clip(tmp_path / "p1.mp4", previous_frames)
    vendor = previous_frames + new_frames if output == WHOLE else new_frames
    second = _grey_clip(tmp_path / "p2.mp4", vendor)
    spans = [
        part_span({"part": {"mode": "reference", "seconds": 2, "generation_seconds": 2}}),
        part_span(
            {
                "part": {
                    "mode": "extend",
                    "seconds": 2,
                    "generation_seconds": 2,
                    "extend": {"output": output, "input_seconds": 2.0},
                }
            }
        ),
    ]
    clips = [JoinClip(first, *spans[0]), JoinClip(second, *spans[1])]
    out = tmp_path / "joined.mp4"
    join_clips(clips, out=out, size=(64, 112), fps=FPS)
    levels = _levels(out)
    assert len(levels) == 4 * FPS
    assert len(set(levels)) == len(levels), levels  # no frame of part 1 shown twice
    assert levels == sorted(levels)


# ---------------------------------------------------------------------------
# «Hay que rehacerla» (VE-13): the file it continued, not only the dates


def test_stale_when_the_previous_part_shows_another_file() -> None:
    assert extend_is_stale(continued="a", previous_source="b", own_made_at=2, previous_made_at=1)
    assert not extend_is_stale(
        continued="a", previous_source="a", own_made_at=1, previous_made_at=2
    )
    # made before the file was recorded: the newer vista previa decides, as before
    assert extend_is_stale(continued=None, previous_source="a", own_made_at=1, previous_made_at=2)
    assert not extend_is_stale(
        continued=None, previous_source=None, own_made_at=2, previous_made_at=1
    )


def test_extend_offset_is_zero_unless_the_whole_video_came_back() -> None:
    assert extend_offset({"mode": "extend", "extend": {"output": "segment"}}) == 0.0
    assert extend_offset({"mode": "extend", "extend": {"output": "whole", "input_seconds": 5}}) == 5
    assert extend_offset({"mode": "reference", "extend": {"output": "whole"}}) == 0.0
    assert part_span({"part": {"mode": "extend", "seconds": 5, "generation_seconds": 5}}) == (
        0.0,
        None,
    )


def test_an_unreadable_manifest_is_retried_never_chosen_again(extend_on: None) -> None:
    from qualify_api.creative.queue_dispatch import CheckpointError

    producer, store, seedance, previous, _links = _setup(_ready())
    draft_id = uuid4()
    _produce(producer, _extend_brief(), draft_id)
    manifest = next(k for k in store.files if k.endswith(EXTEND_MANIFEST))
    read = store.read

    def flaky(key: str) -> bytes:
        if key == manifest:
            raise RuntimeError("R2 down")
        return read(key)

    store.read = flaky  # type: ignore[method-assign]
    with pytest.raises(CheckpointError):
        _produce(producer, _extend_brief(), draft_id)
    assert len(previous.calls) == 1 and len(seedance.requests) == 1
