"""VE-10b (m-24921068) offline: the rules of approving a video by parts whole, a part's
final kept as it came (`part_final`) and the 1080p final join — no database, no vendor.

The database side (charges, approval, the worker's phases, the lists) is
`test_creative_part_final_db.py`."""

from __future__ import annotations

import hashlib
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.schemas import ContentBrief, PartRef
from qualify_creative.video.join import JoinClip, JoinError, concat_segments, encode_segment
from qualify_creative.video.join_child import join_in_child, segment_in_child

from qualify_api.creative import part_final
from qualify_api.creative.draft_mode import draft_pending
from qualify_api.creative.fsm import (
    APPROVED,
    GENERATED,
    PUBLISHED,
    DraftTrigger,
    InvalidTransition,
    apply_transition,
)
from qualify_api.creative.part_final import (
    EXPIRED,
    JOIN_FINAL_PENDING,
    NOT_READY,
    STALE,
    approval_problem,
    final_parts,
    join_final,
    join_final_fingerprint,
    part_final_media,
    preview_fingerprint,
)
from qualify_api.creative.part_join import (
    PART_FINAL,
    PartPreview,
    PartsToJoin,
    io_failure,
    ready_parts,
)
from qualify_api.creative.service import ImageRecord

from .test_creative_media_byteplus import BUDGET, COPY, TENANT_ID, _kit
from .test_creative_part_join import PARENT, TENANT, Joiner, Store, _params
from .test_creative_part_join_review import LOGO_KEY, _clip, _frames, _logo_png
from .test_creative_seedance_draft import (
    DraftSeedance,
    RecordingFitter,
    _finalize,
    _producer,
    _record,
    _store,
)
from .test_creative_seedance_draft import _clip as _clip_brief


def _raw(draft: UUID, revision: int = 1) -> dict[str, Any]:
    return {
        "key": f"t/{TENANT}/generated/{draft}/r{revision}/clip-final-raw.mp4",
        "task_id": "cgt-final",
        "model_id": "seedance-2-5",
        "resolution": "1080p",
        "cost_usd": "1.17",
    }


def _part(
    index: int,
    *,
    status: str = GENERATED,
    block: str = "draft",
    raw: bool = False,
    seconds: int = 4,
    generation: int = 5,
    created_at: float | None = None,
) -> PartPreview:
    draft = uuid4()
    params = _params(seconds=seconds, generation=generation, created_at=created_at, status=block)
    if raw:
        params["draft"]["raw_final"] = _raw(draft)
    return PartPreview(
        draft_id=draft,
        part_index=index,
        status=status,
        revision=1,
        version_id=uuid4(),
        object_key=f"t/{TENANT}/generated/{draft}/r1/clip.mp4",
        params=params,
    )


def _final(index: int, **kwargs: Any) -> PartPreview:
    return _part(index, status=APPROVED, block=PART_FINAL, raw=True, **kwargs)


def _snapshot(
    *parts: PartPreview,
    status: str = GENERATED,
    block: dict[str, Any] | None = None,
    logo_key: str | None = None,
) -> PartsToJoin:
    shown = block
    if shown is None:
        fingerprint = preview_fingerprint(parts, {"logo": "sin logo"})
        shown = {
            "finish": "join",
            "status": "join_preview",
            "fingerprint": fingerprint,
            "parent_revision": 1,
            "logo": "sin logo",
        }
    return PartsToJoin(
        parent_id=PARENT,
        revision=1,
        planned=len(parts),
        parts=parts,
        joined_fingerprint=shown.get("fingerprint"),
        logo_key=logo_key,
        status=status,
        joined_asset_id=uuid4(),
        joined_object_key=f"t/{TENANT}/generated/{PARENT}/join-x.mp4",
        joined_block=shown,
    )


def _approved(snapshot: PartsToJoin) -> PartsToJoin:
    block = {
        **dict(snapshot.joined_block or {}),
        "status": JOIN_FINAL_PENDING,
        "approved_fingerprint": snapshot.joined_fingerprint,
    }
    return replace(snapshot, status=APPROVED, joined_block=block)


class FinalJoins:
    """A `PartFinalStore` double: one snapshot; records saves and failures."""

    def __init__(self, snapshot: PartsToJoin) -> None:
        self.snapshot = snapshot
        self.failed: list[str] = []

    def read(self, *, tenant_id: UUID, parent_id: UUID) -> PartsToJoin | None:
        return self.snapshot if parent_id == self.snapshot.parent_id else None

    def save_final(self, **_: Any) -> bool:
        return True

    def fail_final(self, *, tenant_id: UUID, parent_id: UUID, error: str) -> bool:
        self.failed.append(error)
        return True


def _raw_files(*parts: PartPreview) -> dict[str, bytes]:
    return {str(part_final.raw_key(p)): f"raw-{p.part_index}".encode() for p in parts}


# ---------------------------------------------------------------------------
# approving the whole video (pure)


def test_the_shown_preview_of_the_active_versions_can_be_approved() -> None:
    snapshot = _snapshot(_part(1), _part(2), _part(3))
    assert approval_problem(snapshot, TENANT) is None


def test_a_part_missing_or_still_being_made_is_not_ready() -> None:
    assert approval_problem(None, TENANT) == NOT_READY
    parts = (_part(1), _part(2))
    snapshot = _snapshot(*parts)
    assert approval_problem(replace(snapshot, planned=3), TENANT) == NOT_READY
    drafting = replace(parts[1], status="drafting")
    assert approval_problem(replace(snapshot, parts=(parts[0], drafting)), TENANT) == NOT_READY
    assert approval_problem(replace(snapshot, joined_block=None), TENANT) == NOT_READY


def test_a_preview_that_is_not_the_join_of_the_active_versions_is_stale() -> None:
    parts = (_part(1), _part(2))
    snapshot = _snapshot(*parts)
    another = replace(parts[1], version_id=uuid4())  # «Crear otra versión», not joined yet
    assert approval_problem(replace(snapshot, parts=(parts[0], another)), TENANT) == STALE
    assert approval_problem(replace(snapshot, revision=2), TENANT) == STALE  # a new text


def test_a_part_whose_preview_expired_is_reported_as_expired() -> None:
    old = time.time() - 8 * 86_400
    snapshot = _snapshot(_part(1), _part(2, created_at=old))
    assert approval_problem(snapshot, TENANT) == EXPIRED


def test_an_approved_part_with_its_1080p_kept_is_still_ready_for_another_preview() -> None:
    # «Pedir otra versión» of part 2 after the final: parts 1 and 3 keep their raw final
    parts = (_final(1), _part(2), _final(3))
    assert ready_parts(_snapshot(*parts), TENANT) == parts
    # a final on its way is not (its preview is being replaced in the block)
    rendering = _part(1, status=APPROVED, block="rendering")
    assert ready_parts(_snapshot(rendering, _part(2)), TENANT) is None
    # the part keeps its preview's file: the preview fingerprint does not change
    a = _part(1)
    kept = replace(
        a,
        status=APPROVED,
        params=part_final_media(_asset(a), a.params["draft"], _raw(a.draft_id), 1).params,
    )
    assert preview_fingerprint((kept,), {}) == preview_fingerprint((a,), {})


def test_part_changed_sends_an_approved_parent_back_and_refuses_a_published_one() -> None:
    assert apply_transition(APPROVED, DraftTrigger.PART_CHANGED) == GENERATED
    with pytest.raises(InvalidTransition):
        apply_transition(PUBLISHED, DraftTrigger.PART_CHANGED)


# ---------------------------------------------------------------------------
# a part's final (pure, and the producer's branch)


def _asset(part: PartPreview) -> ImageRecord:
    return ImageRecord(
        id=uuid4(),
        media_url=part.object_key,
        width=480,
        height=854,
        aspect_ratio="9:16",
        media_type="video",
        position=0,
        params=part.params,
        object_key=part.object_key,
    )


def test_a_part_final_keeps_its_preview_file_and_the_raw_1080p() -> None:
    part = _part(1)
    raw = _raw(part.draft_id)
    write = part_final_media(_asset(part), part.params["draft"], raw, 1)
    block = write.params["draft"]
    assert write.object_key == part.object_key and write.media_url == part.object_key
    assert (write.width, write.height) == (480, 854)
    assert block["status"] == PART_FINAL and block["raw_final"] == raw
    assert block["part_final_key"] == raw["key"] and block["final_task_id"] == "cgt-final"
    assert "final_sha256" not in block and "final_object_key" not in block
    assert draft_pending(write.params)  # never publishable on its own


def _part_brief() -> ContentBrief:
    brief = _clip_brief()
    part = PartRef(index=1, seconds=5, description="La arepa sobre la mesa.")
    media = {**brief.media.model_dump(), "part": part.model_dump(), "duration_seconds": 5}
    return ContentBrief.model_validate({**brief.model_dump(), "media": media})


def test_the_producer_keeps_a_parts_paid_1080p_without_fitting_it() -> None:
    store, seedance, fitter, draft_id = _store(), DraftSeedance(), RecordingFitter(), uuid4()
    producer = _producer(store, seedance, fitter)
    (draft,) = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        brief=_clip_brief(),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    ).media
    asset = _record(draft)
    fitted_before = len(fitter.calls)

    outcome = _finalize(producer, _part_brief(), asset, draft_id)

    assert outcome.failure is None and outcome.media is not None
    assert len(fitter.calls) == fitted_before  # no H.264 fit, no logo: the join's job
    block = outcome.media.params["draft"]
    assert block["status"] == PART_FINAL
    assert store.files[block["raw_final"]["key"]] == b"hevc-bytes"  # kept as it came
    assert outcome.media.object_key == asset.object_key  # still shows its preview

    # a retry after the last write never landed: the kept 1080p, never paid again
    paid = sum(1 for r in seedance.requests if "draft_task_id" in r.params)
    again = {**asset.params["draft"], "raw_final": block["raw_final"], "status": "rendering"}
    retried = _finalize(
        producer, _part_brief(), replace(asset, params={**asset.params, "draft": again}), draft_id
    )
    assert retried.media is not None and retried.media.params["draft"]["status"] == PART_FINAL
    assert sum(1 for r in seedance.requests if "draft_task_id" in r.params) == paid


# ---------------------------------------------------------------------------
# the final join


def test_final_parts_need_every_part_approved_with_its_raw_final() -> None:
    parts = (_final(1), _final(2))
    assert final_parts(_snapshot(*parts), TENANT) == parts
    assert (
        final_parts(_snapshot(_final(1), _part(2, status=APPROVED, block="rendering")), TENANT)
        is None
    )
    foreign = _final(2)
    foreign.params["draft"]["raw_final"]["key"] = f"t/{uuid4()}/generated/x/raw.mp4"
    assert final_parts(_snapshot(_final(1), foreign), TENANT) is None


def test_the_final_fingerprint_is_the_raw_files_and_the_logo() -> None:
    parts = (_final(1), _final(2))
    spans = [(0.0, 4.0), (0.0, 4.0)]
    base = join_final_fingerprint(parts, spans, None)
    assert join_final_fingerprint(parts, spans, LOGO_KEY) != base
    moved = replace(
        parts[1],
        params={
            **parts[1].params,
            "draft": {**parts[1].params["draft"], "raw_final": _raw(uuid4())},
        },
    )
    assert join_final_fingerprint((parts[0], moved), spans, None) != base


def test_the_final_join_reads_the_raw_finals_at_1080p_and_lays_the_logo_once() -> None:
    parts = (_final(1), _final(2), _final(3))
    shown = {
        "finish": "join",
        "status": "join_preview",
        "fingerprint": preview_fingerprint(parts, {"logo": {"key": LOGO_KEY}}),
        "parent_revision": 1,
        "logo": {"key": LOGO_KEY, "sha256": "x"},
    }
    snapshot = _approved(_snapshot(*parts, block=shown, logo_key=LOGO_KEY))
    store = Store({**_raw_files(*parts), LOGO_KEY: _logo_png()})
    joiner = Joiner()

    write = join_final(store, FinalJoins(snapshot), TENANT, PARENT, joiner=joiner)

    assert write is not None and len(joiner.calls) == 1
    assert joiner.overlays[0] is not None  # one overlay over the whole video
    block = write.params["draft"]
    assert block["status"] == "final_ready" and block["final_revision"] == 1
    assert block["final_object_key"] == write.object_key
    assert write.object_key.startswith(f"t/{TENANT}/generated/{PARENT}/join-final-")
    assert block["final_sha256"] == hashlib.sha256(store.files[write.object_key]).hexdigest()
    assert block["fingerprint"] == shown["fingerprint"]  # the preview's: no re-join
    assert (write.width, write.height) == part_final.JOIN_FINAL_SIZE
    provenance = write.params["join_final"]
    assert provenance["version"] == part_final.JOIN_FINAL_VERSION
    assert provenance["recipe"] == "join-v1" and provenance["cost_usd"] == "0"
    assert provenance["logo"]["key"] == LOGO_KEY
    assert [p["raw_final_key"] for p in provenance["parts"]] == [
        part_final.raw_key(p) for p in parts
    ]

    # the same final again: the kept file is reused, never encoded twice
    again = join_final(store, FinalJoins(snapshot), TENANT, PARENT, joiner=joiner)
    assert again is not None and again.object_key == write.object_key and len(joiner.calls) == 1
    assert again.params["draft"]["final_sha256"] == block["final_sha256"]


def test_nothing_is_joined_before_the_approval_or_once_the_final_is_made() -> None:
    parts = (_final(1), _final(2))
    store, joiner = Store(_raw_files(*parts)), Joiner()
    not_approved = _snapshot(*parts)
    assert join_final(store, FinalJoins(not_approved), TENANT, PARENT, joiner=joiner) is None
    made = _approved(not_approved)
    made = replace(made, joined_block={**made.joined_block, "status": "final_ready"})
    assert join_final(store, FinalJoins(made), TENANT, PARENT, joiner=joiner) is None
    # parts that are not the approved versions never become a final
    other = _approved(not_approved)
    other = replace(other, joined_block={**other.joined_block, "approved_fingerprint": "zz"})
    assert join_final(store, FinalJoins(other), TENANT, PARENT, joiner=joiner) is None
    assert joiner.calls == []


def test_an_undecodable_raw_final_fails_the_join_for_good_and_an_io_error_retries() -> None:
    parts = (_final(1), _final(2))
    snapshot = _approved(_snapshot(*parts))
    joins = FinalJoins(snapshot)
    store = Store(_raw_files(*parts))
    assert join_final(store, joins, TENANT, PARENT, joiner=Joiner(JoinError("bad data"))) is None
    assert joins.failed == [part_final.JOIN_FINAL_FAILED_TEXT]

    error = JoinError("disk full")
    error.__cause__ = OSError(28, "No space left on device")
    with pytest.raises(JoinError):
        join_final(store, FinalJoins(snapshot), TENANT, PARENT, joiner=Joiner(error))

    gone = FinalJoins(snapshot)
    missing = Store({str(part_final.raw_key(parts[0])): b"raw-1"})
    assert join_final(missing, gone, TENANT, PARENT, joiner=Joiner()) is None
    assert gone.failed == [part_final.JOIN_FINAL_FAILED_TEXT]


def test_the_real_final_join_lays_the_logo_on_every_frame(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(part_final, "JOIN_FINAL_SIZE", (96, 170))
    parts = (_final(1, seconds=1, generation=1), _final(2, seconds=1, generation=1))
    files = {
        str(part_final.raw_key(p)): _clip(tmp_path / f"{i}.mp4", 1) for i, p in enumerate(parts)
    }
    plain = _approved(_snapshot(*parts))
    shown = {
        **dict(plain.joined_block or {}),
        "logo": {"key": LOGO_KEY, "sha256": "x"},
        "fingerprint": preview_fingerprint(parts, {"logo": {"key": LOGO_KEY}}),
    }
    shown["approved_fingerprint"] = shown["fingerprint"]
    branded = replace(plain, joined_block=shown, joined_fingerprint=shown["fingerprint"])
    store_a, store_b = Store(files), Store({**files, LOGO_KEY: _logo_png()})
    a = join_final(store_a, FinalJoins(plain), TENANT, PARENT)
    b = join_final(store_b, FinalJoins(branded), TENANT, PARENT)
    assert a is not None and b is not None
    frames_a = _frames(store_a.files[a.object_key], tmp_path)
    frames_b = _frames(store_b.files[b.object_key], tmp_path)
    assert len(frames_a) == len(frames_b) == 48
    assert frames_a[0].shape[:2] == (170, 96)
    reddish = [
        int(((fb[..., 0].astype(int) - fa[..., 0].astype(int)) > 60).sum())
        for fa, fb in zip(frames_a, frames_b, strict=True)
    ]
    assert all(n > 0 for n in reddish)  # the logo on every frame, first part to last


# ---------------------------------------------------------------------------
# the join in a short-lived child process (the 768 MiB worker, 2026-11-06)

CRASH = (sys.executable, "-c", "import os; os._exit(137)")
HANG = (sys.executable, "-c", "import time; time.sleep(60)")


def _leftovers(folder: Path, *keep: Path) -> set[str]:
    return {p.name for p in folder.iterdir()} - {p.name for p in keep}


def test_the_child_joins_with_one_thread_and_leaves_only_its_output(tmp_path: Path) -> None:
    clips = [JoinClip(tmp_path / f"{i}.mp4") for i in range(2)]
    for clip in clips:
        _clip(clip.path, 1)
    out = tmp_path / "final.mp4"
    joined = join_in_child(clips, out=out, size=(96, 170), overlay=_logo_png())
    assert joined.frames == 48 and joined.poster and out.exists()
    assert (joined.width, joined.height) == (96, 170)
    assert _leftovers(tmp_path, out, *(c.path for c in clips)) == set()


def test_a_killed_child_is_a_retry_and_cleans_its_files(tmp_path: Path) -> None:
    out = tmp_path / "final.mp4"
    with pytest.raises(JoinError) as caught:
        join_in_child(
            [JoinClip(tmp_path / "a.mp4")], out=out, size=(96, 170), overlay=b"png", command=CRASH
        )
    assert io_failure(caught.value)  # retried by the next pass, never a failed row
    assert _leftovers(tmp_path) == set()


def test_a_hung_child_is_killed_at_the_timeout_and_retried(tmp_path: Path) -> None:
    began = time.monotonic()
    with pytest.raises(JoinError) as caught:
        join_in_child(
            [JoinClip(tmp_path / "a.mp4")], out=tmp_path / "f.mp4", size=(96, 170),
            timeout=1, command=HANG,
        )  # fmt: skip
    assert io_failure(caught.value) and time.monotonic() - began < 30
    assert _leftovers(tmp_path) == set()


def test_parts_the_child_cannot_decode_are_the_permanent_failure(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"this is not a video")
    with pytest.raises(JoinError) as caught:
        join_in_child([JoinClip(bad)], out=tmp_path / "f.mp4", size=(96, 170))
    assert not io_failure(caught.value)
    assert _leftovers(tmp_path, bad) == set()


def test_the_final_join_with_a_crashed_child_retries_and_never_fails_the_row() -> None:
    parts = (_final(1), _final(2))
    joins = FinalJoins(_approved(_snapshot(*parts)))

    def crashing(clips, **kw):  # noqa: ANN001, ANN003, ANN202
        return join_in_child(clips, command=CRASH, **kw)

    with pytest.raises(JoinError):
        join_final(Store(_raw_files(*parts)), joins, TENANT, PARENT, joiner=crashing)
    assert joins.failed == []
    # and a typed parts error in the child is the existing permanent path
    assert join_final(Store(_raw_files(*parts)), joins, TENANT, PARENT) is None
    assert joins.failed == [part_final.JOIN_FINAL_FAILED_TEXT]  # "raw-1" is no video


# ---------------------------------------------------------------------------
# the final join in segments: one child per part, then a stream copy (2026-11-07)


def _sound_clip(path: Path, seconds: float, tone: int | None) -> None:
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    from fractions import Fraction

    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=24)
        video.width, video.height, video.pix_fmt = 64, 114, "yuv420p"
        audio = None
        if tone:
            audio = sink.add_stream("aac", rate=48000)
            audio.layout = "stereo"
        for i in range(round(seconds * 24)):
            frame = av.VideoFrame.from_ndarray(
                np.full((114, 64, 3), (i * 5) % 255, np.uint8), format="rgb24"
            )
            frame.pts, frame.time_base = i, Fraction(1, 24)
            for packet in video.encode(frame):
                sink.mux(packet)
        if audio is not None:
            wave = (
                0.3 * np.sin(2 * np.pi * tone * np.arange(int(seconds * 48000)) / 48000)
            ).astype(np.float32)
            for start in range(0, wave.size, 1024):
                chunk = av.AudioFrame.from_ndarray(
                    np.tile(wave[start : start + 1024], (2, 1)), format="fltp", layout="stereo"
                )
                chunk.sample_rate, chunk.pts = 48000, start
                chunk.time_base = Fraction(1, 48000)
                for packet in audio.encode(chunk):
                    sink.mux(packet)
            for packet in audio.encode():
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)


def test_segments_laid_end_to_end_keep_every_frame_and_sample_in_sync(tmp_path: Path) -> None:
    av = pytest.importorskip("av")
    plan = [(1.0, 300), (1.5, None), (0.75, 500)]  # the middle part has no sound
    segments = []
    for index, (seconds, tone) in enumerate(plan):
        source = tmp_path / f"p{index}.mp4"
        _sound_clip(source, seconds, tone)
        segments.append(
            encode_segment(
                JoinClip(source), out=tmp_path / f"s{index}.mp4",
                pcm_out=tmp_path / f"s{index}.pcm", size=(96, 170), fade_in=index > 0,
                fade_out=index < 2, threads=1, poster=index == 0,
            )
        )  # fmt: skip
    # every segment's sound lasts exactly its frames (48000 / 24 = 2000 samples a frame)
    assert [(s.frames, s.samples) for s in segments] == [(24, 48000), (36, 72000), (18, 36000)]
    joined = concat_segments(segments, out=tmp_path / "final.mp4")
    assert joined.frames == 78 and joined.duration_sec == 3.25 and joined.poster
    with av.open(str(joined.path)) as source:
        frames = list(source.decode(source.streams.video[0]))
    with av.open(str(joined.path)) as source:
        samples = sum(f.samples for f in source.decode(source.streams.audio[0]))
    assert len(frames) == 78
    assert [round(float(f.time) * 24) for f in frames] == list(range(78))  # no gap, no repeat
    assert samples == 78 * 2000  # the whole soundtrack, no drift at the cuts
    assert (frames[0].width, frames[0].height) == (96, 170)


def test_a_segment_child_crash_or_hang_is_a_retry_and_bad_parts_are_final(tmp_path: Path) -> None:
    clip = JoinClip(tmp_path / "missing.mp4")
    out, pcm = tmp_path / "s.mp4", tmp_path / "s.pcm"
    with pytest.raises(JoinError) as crashed:
        segment_in_child(clip, out=out, pcm_out=pcm, size=(96, 170), overlay=b"png", command=CRASH)
    assert io_failure(crashed.value)
    with pytest.raises(JoinError) as hung:
        segment_in_child(clip, out=out, pcm_out=pcm, size=(96, 170), timeout=1, command=HANG)
    assert io_failure(hung.value)
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"this is not a video")
    with pytest.raises(JoinError) as broken:
        segment_in_child(JoinClip(bad), out=out, pcm_out=pcm, size=(96, 170))
    assert not io_failure(broken.value)
    assert _leftovers(tmp_path, bad) == set()


def test_the_final_join_keeps_each_segment_and_a_retry_encodes_only_the_missing() -> None:
    from fractions import Fraction

    from qualify_creative.video.join import JoinedVideo, JoinSegment

    parts = (_final(1), _final(2), _final(3))
    snapshot = _approved(_snapshot(*parts))
    store = Store(_raw_files(*parts))
    encoded: list[bytes] = []

    def segmenter(clip, *, out, pcm_out, overlay=None, poster=False, **_):  # noqa: ANN001, ANN003, ANN202
        encoded.append(clip.path.read_bytes())
        if len(encoded) == 3 and fail["once"]:
            fail["once"] = False
            raise JoinError("disk full") from OSError(28, "No space left on device")
        out.write_bytes(b"seg:" + clip.path.read_bytes())
        pcm_out.write_bytes(bytes(8 * 2000))
        return JoinSegment(out, pcm_out, 1, 2000, b"jpeg" if poster else None)

    def concat(segments, *, out):  # noqa: ANN001, ANN202
        out.write_bytes(b"|".join(s.path.read_bytes() for s in segments))
        return JoinedVideo(out, 1080, 1920, Fraction(24), 3, 0.125, segments[0].poster)

    fail = {"once": True}
    with pytest.raises(JoinError):  # part 3's child hit a full disk: retried
        join_final(store, FinalJoins(snapshot), TENANT, PARENT, segmenter=segmenter, concat=concat)
    kept = sorted(k for k in store.files if "/join-segment-" in k)
    assert len([k for k in kept if k.endswith(".mp4")]) == 2  # parts 1 and 2, by fingerprint
    assert not any(k.endswith(".mp4") and "raw" in k for k in kept)
    write = join_final(
        store, FinalJoins(snapshot), TENANT, PARENT, segmenter=segmenter, concat=concat
    )
    assert write is not None
    assert encoded == [b"raw-1", b"raw-2", b"raw-3", b"raw-3"]  # 1 and 2 never again
    assert store.files[write.object_key] == b"seg:raw-1|seg:raw-2|seg:raw-3"
    assert write.params["join_final"]["frames"] == 3


# ---------------------------------------------------------------------------
# the child's memory hints (Deivid, 2026-11-07): no transparent huge pages; lookahead


class FakeLibc:
    def __init__(self, result: int = 0, error: Exception | None = None) -> None:
        self.calls: list[tuple[int, ...]] = []
        self.result, self.error = result, error

    def prctl(self, *args: int) -> int:
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.result


def test_the_child_turns_transparent_huge_pages_off_on_linux() -> None:
    from qualify_creative.video.join_child import PR_SET_THP_DISABLE, disable_thp

    libc = FakeLibc()
    assert disable_thp(platform="linux", libc=libc) is True
    assert libc.calls == [(PR_SET_THP_DISABLE, 1, 0, 0, 0)] and PR_SET_THP_DISABLE == 41


def test_huge_pages_left_on_never_fail_the_join(capsys) -> None:  # noqa: ANN001
    from qualify_creative.video.join_child import disable_thp

    refused = FakeLibc(result=-1)
    assert disable_thp(platform="linux", libc=refused) is False
    missing = FakeLibc(error=AttributeError("no prctl"))
    assert disable_thp(platform="linux", libc=missing) is False
    assert "huge pages left on" in capsys.readouterr().err
    elsewhere = FakeLibc()
    assert disable_thp(platform="win32", libc=elsewhere) is False and elsewhere.calls == []


def test_the_segment_lookahead_override_reaches_the_encoder_and_the_fingerprint(
    tmp_path: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    from qualify_creative.video import join as video_join

    part = _final(1)
    base = part_final.segment_fingerprint(part, (0.0, None), None, fade_in=False, fade_out=False)
    # unset: the segments' default, lookahead 0 and crf 17 (2026-11-07)
    assert video_join.segment_x264()["rc-lookahead"] == "0"
    assert video_join.segment_x264()["crf"] == "17"
    assert video_join.JOIN_X264["rc-lookahead"] == "10"  # the preview join keeps its own
    monkeypatch.setenv(video_join.SEGMENT_LOOKAHEAD_ENV, "5")
    assert video_join.SEGMENT_LOOKAHEAD_ENV == "QUALIFY_JOIN_SEGMENT_LOOKAHEAD"
    assert video_join.segment_x264() == {**video_join.JOIN_SEGMENT_X264, "rc-lookahead": "5"}
    other = part_final.segment_fingerprint(part, (0.0, None), None, fade_in=False, fade_out=False)
    assert other != base  # another recipe: a segment kept with 10 is never reused
    monkeypatch.setenv(video_join.SEGMENT_LOOKAHEAD_ENV, "lots")
    assert video_join.segment_lookahead() == "0"  # not a whole number: ignored

    monkeypatch.setenv(video_join.SEGMENT_LOOKAHEAD_ENV, "3")
    used: list[dict[str, str]] = []
    real = video_join.segment_x264

    def recording() -> dict[str, str]:
        used.append(real())
        return used[-1]

    monkeypatch.setattr(video_join, "segment_x264", recording)
    source = tmp_path / "p.mp4"
    _sound_clip(source, 0.5, None)
    segment = encode_segment(
        JoinClip(source), out=tmp_path / "s.mp4", pcm_out=tmp_path / "s.pcm", size=(96, 170)
    )
    assert segment.frames == 12 and used == [{**video_join.JOIN_SEGMENT_X264, "rc-lookahead": "3"}]


def test_the_segment_crf_override_reaches_the_encoder_and_the_fingerprint(monkeypatch) -> None:  # noqa: ANN001
    from qualify_creative.video import join as video_join

    part = _final(1)
    base = part_final.segment_fingerprint(part, (0.0, None), None, fade_in=False, fade_out=False)
    assert video_join.SEGMENT_CRF_ENV == "QUALIFY_JOIN_SEGMENT_CRF"
    assert video_join.segment_x264()["crf"] == video_join.JOIN_SEGMENT_X264["crf"]  # unset
    assert video_join.segment_crf() == "17"  # the segments' default
    monkeypatch.setenv(video_join.SEGMENT_CRF_ENV, "18")
    monkeypatch.setenv(video_join.SEGMENT_LOOKAHEAD_ENV, "10")
    assert video_join.segment_x264() == {  # back to the join's own, for a measurement
        **video_join.JOIN_SEGMENT_X264,
        "crf": "18",
        "rc-lookahead": "10",
    }
    other = part_final.segment_fingerprint(part, (0.0, None), None, fade_in=False, fade_out=False)
    assert other != base
    for bad in ("52", "-1", "high", ""):
        monkeypatch.setenv(video_join.SEGMENT_CRF_ENV, bad)
        assert video_join.segment_crf() == video_join.JOIN_SEGMENT_X264["crf"]


# ---------------------------------------------------------------------------
# review of 2026-11-08


def test_the_join_child_sees_no_database_url_nor_key(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    from qualify_creative.video.join_child import child_env

    worker = {
        "PATH": "/usr/bin",
        "PYTHONPATH": "/app",
        "TMPDIR": "/tmp",
        "LC_ALL": "C.UTF-8",
        "QUALIFY_JOIN_SEGMENT_CRF": "17",
        "QUALIFY_APP_DSN": "postgresql://secret",
        "QUALIFY_R2_SECRET_ACCESS_KEY": "r2",
        "R2_ACCESS_KEY_ID": "r2",
        "BYTEPLUS_ARK_API_KEY": "ark",
        "QUALIFY_BYTEPLUS_ARK_API_KEY": "ark",
        "QUALIFY_ANTHROPIC_API_KEY": "sk",
    }
    env = child_env(worker)
    assert env == {
        "PATH": "/usr/bin",
        "PYTHONPATH": "/app",
        "TMPDIR": "/tmp",
        "LC_ALL": "C.UTF-8",
        "QUALIFY_JOIN_SEGMENT_CRF": "17",
        "MALLOC_ARENA_MAX": "2",
    }
    # and in a real child: what it can see of the worker's secrets is nothing
    for name in ("QUALIFY_APP_DSN", "R2_ACCESS_KEY_ID", "BYTEPLUS_ARK_API_KEY"):
        monkeypatch.setenv(name, "secret")
    probe = (
        sys.executable,
        "-c",
        "import os, sys; "
        "sys.stderr.write('seen=' + ','.join(sorted(k for k in os.environ if 'DSN' in k "
        "or k.startswith(('R2_', 'BYTEPLUS_', 'QUALIFY_R2', 'QUALIFY_BYTEPLUS'))))); sys.exit(9)",
    )
    with pytest.raises(JoinError) as seen:
        segment_in_child(
            JoinClip(tmp_path / "a.mp4"),
            out=tmp_path / "s.mp4",
            pcm_out=tmp_path / "s.pcm",
            size=(96, 170),
            command=probe,
        )
    assert "seen=" in str(seen.value) and "seen=:" not in str(seen.value)
    assert str(seen.value).split("seen=", 1)[1].strip() == ""


def test_a_failed_part_is_reported_apart_from_a_part_still_being_made() -> None:
    parts = (_part(1), replace(_part(2), status="failed"))
    assert approval_problem(_snapshot(*parts), TENANT) == part_final.PART_FAILED
    assert str(part_final.PartFailed()) == (
        "Una parte de tu video no salió. Pide otra versión de esa parte para poder aprobarlo."
    )
    assert str(part_final.PartsNotReady()) == (
        "Tu video completo todavía no está listo. Espera a que terminen todas sus partes."
    )
    assert str(part_final.ApproveWholeVideo()) == (
        "Las partes se aprueban juntas: aprueba tu video completo."
    )
    assert part_final.JOIN_FINAL_FAILED_TEXT == (
        "No pudimos preparar el video final. Toca Reintentar: no usa más segundos de tu video "
        "del mes."
    )
    assert part_final.PART_FINAL_NOT_KEPT_TEXT == (
        "No pudimos guardar el video final de esta parte. Toca Reintentar."
    )
    assert part_final.PART_EXPIRED_TEXT == (
        "Una parte venció: las vistas previas duran 7 días. Pide otra versión de esa parte."
    )


class CountingJoins(FinalJoins):
    def __init__(self, snapshot: PartsToJoin) -> None:
        super().__init__(snapshot)
        self.losses = 0

    def child_lost(self, *, tenant_id: UUID, parent_id: UUID) -> int:
        self.losses += 1
        return self.losses


def test_a_child_killed_three_times_fails_the_join_instead_of_looping() -> None:
    parts = (_final(1), _final(2))
    joins = CountingJoins(_approved(_snapshot(*parts)))
    store = Store(_raw_files(*parts))
    from qualify_creative.video.join_child import WORKER_STOPPING

    WORKER_STOPPING.clear()

    def killed(clip, *, out, pcm_out, size, **_):  # noqa: ANN001, ANN003, ANN202
        return segment_in_child(clip, out=out, pcm_out=pcm_out, size=size, command=CRASH)

    for _ in range(part_final.CHILD_LOSSES_MAX - 1):
        with pytest.raises(JoinError):  # retried by the next pass
            join_final(store, joins, TENANT, PARENT, segmenter=killed)
        assert joins.failed == []
    assert join_final(store, joins, TENANT, PARENT, segmenter=killed) is None
    assert joins.failed == [part_final.JOIN_FINAL_FAILED_TEXT]


def test_a_full_disk_or_a_stopping_worker_is_retried_without_counting() -> None:
    from qualify_creative.video.join_child import WORKER_STOPPING

    parts = (_final(1), _final(2))
    joins = CountingJoins(_approved(_snapshot(*parts)))
    store = Store(_raw_files(*parts))
    full_disk = (sys.executable, "-c", "import sys; sys.exit(4)")  # EXIT_IO

    def child(command):  # noqa: ANN001, ANN202
        def segmenter(clip, *, out, pcm_out, size, **_):  # noqa: ANN001, ANN003, ANN202
            return segment_in_child(clip, out=out, pcm_out=pcm_out, size=size, command=command)

        return segmenter

    WORKER_STOPPING.clear()
    try:
        for _ in range(part_final.CHILD_LOSSES_MAX + 1):
            with pytest.raises(JoinError) as retried:  # retried, never failed
                join_final(store, joins, TENANT, PARENT, segmenter=child(full_disk))
            assert io_failure(retried.value)
        WORKER_STOPPING.set()  # a deploy: the container's children are killed
        for _ in range(part_final.CHILD_LOSSES_MAX + 1):
            with pytest.raises(JoinError):
                join_final(store, joins, TENANT, PARENT, segmenter=child(CRASH))
        assert joins.losses == 0 and joins.failed == []
    finally:
        WORKER_STOPPING.clear()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_a_child_stopped_by_sigterm_is_not_lost_to_its_part() -> None:
    from qualify_creative.video.join_child import WORKER_STOPPING

    WORKER_STOPPING.clear()
    parts = (_final(1),)
    joins = CountingJoins(_approved(_snapshot(*parts)))
    stopped = (sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)")

    def segmenter(clip, *, out, pcm_out, size, **_):  # noqa: ANN001, ANN003, ANN202
        return segment_in_child(clip, out=out, pcm_out=pcm_out, size=size, command=stopped)

    with pytest.raises(JoinError):
        join_final(Store(_raw_files(*parts)), joins, TENANT, PARENT, segmenter=segmenter)
    assert joins.losses == 0
