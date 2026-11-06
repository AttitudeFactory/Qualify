"""VE-10a (m-24921067), offline: the joined 480p preview of a video by parts.

The rules are pure (`part_span`, `ready_parts`, `join_fingerprint`,
`parent_video_status`); `join_preview` runs against an in-memory store and a fake
`PartJoinStore` — with the real PyAV join (`join_clips`) on tiny synthetic clips where
it matters, a recording joiner elsewhere. No network, no vendor, no database."""

from __future__ import annotations

import time
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.video.join import JoinedVideo, JoinError

from qualify_api.creative import part_join
from qualify_api.creative.draft_mode import draft_pending
from qualify_api.creative.media import MediaProducer, MediaWrite
from qualify_api.creative.part_join import (
    FINISH_JOIN,
    JOIN_PREVIEW_STATUS,
    PARENT_GENERATING,
    PARENT_JOINING,
    PARENT_PREVIEWING,
    JoinNotKept,
    PartPreview,
    PartsToJoin,
    join_fingerprint,
    join_key,
    join_preview,
    parent_video_status,
    part_span,
    ready_parts,
    run_join,
)
from qualify_api.creative.service import ContentService
from qualify_api.planner.post_reader import UnpublishableReason

from .test_planner_publishable import _post, _reason, _video

TENANT = uuid4()
PARENT = uuid4()


def _params(
    *,
    mode: str = "reference",
    seconds: int = 4,
    generation: int = 5,
    offset: float | None = None,
    created_at: float | None = None,
    status: str = "draft",
) -> dict[str, Any]:
    window = {"key": "w", "start_s": 3, "end_s": 8, "offset_s": offset} if mode == "edit" else None
    return {
        "part": {
            "index": 1,
            "mode": mode,
            "seconds": seconds,
            "generation_seconds": generation,
            "window": window,
            "raw_key": "t/x/generated/y/r1/queue-z.bin",
        },
        "draft": {
            "status": status,
            "created_at": time.time() if created_at is None else created_at,
            "model": "seedance-2-5",
            "duration_seconds": generation,
            "raw_key": "t/x/generated/y/r1/queue-z.bin",
        },
    }


def _part(index: int, **kwargs: Any) -> PartPreview:
    draft = kwargs.pop("draft_id", uuid4())
    status = kwargs.pop("status", "generated")
    version = kwargs.pop("version_id", uuid4())
    key = kwargs.pop("object_key", f"t/{TENANT}/generated/{draft}/r1/clip.mp4")
    return PartPreview(
        draft_id=draft,
        part_index=index,
        status=status,
        revision=1,
        version_id=version,
        object_key=key,
        params=_params(**kwargs),
    )


def _snapshot(*parts: PartPreview, planned: int | None = None, joined: str | None = None):
    return PartsToJoin(
        parent_id=PARENT,
        revision=1,
        planned=len(parts) if planned is None else planned,
        parts=parts,
        joined_fingerprint=joined,
    )


class Joins:
    """A `PartJoinStore` double: one snapshot; `save` records and moves the join on."""

    def __init__(self, snapshot: PartsToJoin) -> None:
        self.snapshot = snapshot
        self.saved: list[MediaWrite] = []

    def read(self, *, tenant_id: UUID, parent_id: UUID) -> PartsToJoin | None:
        return self.snapshot if parent_id == self.snapshot.parent_id else None

    def save(self, *, tenant_id: UUID, parent_id: UUID, write: MediaWrite) -> bool:
        self.saved.append(write)
        fingerprint = write.params["draft"]["fingerprint"]
        if fingerprint == self.snapshot.joined_fingerprint:
            return False
        self.snapshot = PartsToJoin(**{**self.snapshot.__dict__, "joined_fingerprint": fingerprint})
        return True


class Store:
    """An in-memory store with `keep` (the R2 shape): a key is never overwritten."""

    def __init__(self, files: dict[str, bytes] | None = None, *, keep_ok: bool = True) -> None:
        self.files = dict(files or {})
        self.keep_ok = keep_ok
        self.kept: list[str] = []

    def read(self, key: str) -> bytes:
        return self.files[key]

    def write(self, key: str, data: bytes) -> None:
        self.files[key] = data

    def keep(self, tenant_id: UUID, key: str, data: bytes, content_type: str) -> bool:
        if not self.keep_ok:
            return False
        if key in self.files:
            return True  # the bucket refuses the overwrite; the name is the content
        self.files[key] = data
        self.kept.append(key)
        return True


class Joiner:
    """A recording `join_clips`: writes a stand-in file, never encodes."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[list[Any]] = []
        self.overlays: list[bytes | None] = []
        self.error = error

    def __call__(self, clips, *, out: Path, size, overlay=None):  # noqa: ANN001, ANN204
        self.calls.append(list(clips))
        self.overlays.append(overlay)
        if self.error is not None:
            raise self.error
        out.write_bytes(b"joined:" + b"|".join(c.path.read_bytes() for c in clips))
        return JoinedVideo(
            path=out, width=size[0], height=size[1], fps=Fraction(24), frames=96,
            duration_sec=4.0, poster=b"\xff\xd8jpeg",
        )  # fmt: skip


def _files(*parts: PartPreview) -> dict[str, bytes]:
    return {str(p.object_key): f"clip-{p.part_index}".encode() for p in parts}


# ---------------------------------------------------------------------------
# part_span (pure)


def test_a_reference_part_keeps_its_own_seconds_of_what_was_asked() -> None:
    assert part_span(_params(seconds=4, generation=5)) == (0.0, 4.0)
    assert part_span(_params(seconds=5, generation=5)) == (0.0, None)


def test_an_edit_part_keeps_its_cuts_inside_the_window_by_its_signed_offset() -> None:
    # the window opened 0.2 s before the part's first cut (a cut at 3.2 s, window from 3)
    assert part_span(_params(mode="edit", seconds=4, generation=5, offset=0.2)) == (0.2, 4.2)
    # whole window used: to its end
    assert part_span(_params(mode="edit", seconds=4, generation=5, offset=1.0)) == (1.0, None)
    # negative: the window opened 0.5 s after the part's start — those seconds are missing
    assert part_span(_params(mode="edit", seconds=4, generation=5, offset=-0.5)) == (0.0, 3.5)


def test_a_part_without_provenance_or_offset_is_kept_from_its_start() -> None:
    assert part_span({}) == (0.0, None)
    assert part_span(_params(mode="edit", seconds=4, generation=5, offset=None)) == (0.0, 4.0)


# ---------------------------------------------------------------------------
# ready_parts / parent_video_status (pure)


def test_three_ready_parts_are_joined_in_plan_order() -> None:
    parts = (_part(2), _part(1), _part(3))
    ready = ready_parts(_snapshot(*parts), TENANT)
    assert ready is not None and [p.part_index for p in ready] == [1, 2, 3]


@pytest.mark.parametrize(
    "broken",
    [
        {"status": "drafting"},
        {"status": "failed"},
        {"version_id": None},
        {"object_key": None},
        {"object_key": f"t/{uuid4()}/generated/x/r1/clip.mp4"},  # another business's
        {"created_at": time.time() - 8 * 24 * 3600},  # expired: 7 days
        {"block": "final"},  # not a vista previa any more
    ],
)
def test_one_part_missing_failed_or_expired_joins_nothing(broken: dict[str, Any]) -> None:
    block = broken.pop("block", None)
    part = _part(2, **broken)
    if block:
        part = PartPreview(**{**part.__dict__, "params": _params(status=block)})
    assert ready_parts(_snapshot(_part(1), part, _part(3)), TENANT) is None


def test_a_purged_part_joins_nothing() -> None:
    part = PartPreview(**{**_part(2).__dict__, "purged": True})
    assert ready_parts(_snapshot(_part(1), part), TENANT) is None


def test_a_part_not_created_yet_joins_nothing() -> None:
    assert ready_parts(_snapshot(_part(1), _part(2), planned=3), TENANT) is None
    assert ready_parts(_snapshot(_part(1), _part(3), planned=2), TENANT) is None


def test_the_parents_screen_state_is_computed_not_a_machine_state() -> None:
    parts = (_part(1), _part(2), _part(3))
    assert parent_video_status(None, TENANT) == PARENT_GENERATING
    assert parent_video_status(_snapshot(_part(1), planned=3), TENANT) == PARENT_GENERATING
    assert parent_video_status(_snapshot(*parts), TENANT) == PARENT_JOINING
    fingerprint = join_fingerprint(parts, [part_span(p.params) for p in parts])
    assert parent_video_status(_snapshot(*parts, joined=fingerprint), TENANT) == PARENT_PREVIEWING
    from qualify_api.creative.fsm import DRAFT_STATUSES

    assert not {PARENT_GENERATING, PARENT_JOINING, PARENT_PREVIEWING} & set(DRAFT_STATUSES)


def test_another_version_of_one_part_is_another_fingerprint() -> None:
    parts = [_part(1), _part(2), _part(3)]
    spans = [part_span(p.params) for p in parts]
    first = join_fingerprint(parts, spans)
    assert join_fingerprint(parts, spans) == first  # stable
    parts[1] = PartPreview(**{**parts[1].__dict__, "version_id": uuid4()})
    assert join_fingerprint(parts, spans) != first


# ---------------------------------------------------------------------------
# join_preview


def test_three_ready_parts_make_one_joined_preview_that_is_not_publishable() -> None:
    old = time.time() - 3600
    parts = (_part(1, created_at=old + 60), _part(2, created_at=old), _part(3, mode="edit",
             seconds=4, generation=5, offset=0.2))  # fmt: skip
    joins, store, joiner = Joins(_snapshot(*parts)), Store(_files(*parts)), Joiner()
    write = join_preview(store, joins, TENANT, PARENT, joiner=joiner)
    assert write is not None and len(joiner.calls) == 1
    clips = joiner.calls[0]
    assert [(c.start_s, c.end_s) for c in clips] == [(0.0, 4.0), (0.0, 4.0), (0.2, 4.2)]
    fingerprint = write.params["draft"]["fingerprint"]
    assert write.object_key == join_key(TENANT, PARENT, fingerprint)
    assert write.object_key.endswith(f"/generated/{PARENT}/join-{fingerprint}.mp4")
    assert store.files[write.object_key].startswith(b"joined:clip-1|clip-2|clip-3")
    block = write.params["draft"]
    assert block["finish"] == FINISH_JOIN and block["status"] == JOIN_PREVIEW_STATUS
    assert block["parts"] == [[str(p.draft_id), str(p.version_id)] for p in parts]
    assert block["created_at"] == old  # the oldest part's
    assert (write.width, write.height) == (480, 854)
    # provenance: which parts, versions, files, trims, recipe — cost 0
    joined = write.params["join"]
    assert joined["cost_usd"] == "0" and joined["version"] == part_join.JOIN_PREVIEW_VERSION
    assert [p["offset_s"] for p in joined["parts"]] == [None, None, 0.2]
    assert joined["parts"][0]["raw_key"].endswith("queue-z.bin")
    # criterion 2: never publishable, never a Seedance final
    assert draft_pending(write.params)
    assert (
        _reason(_post(_video(draft_pending=draft_pending(write.params)), category="reel"))
        is UnpublishableReason.MEDIA_DRAFT_PENDING
    )
    asset = SimpleNamespace(params=write.params)
    repo = SimpleNamespace(draft_videos_for=lambda **_: (asset,))
    waiting = ContentService._waiting_drafts(SimpleNamespace(_repo=repo), TENANT, PARENT)  # type: ignore[arg-type]
    assert waiting == ()


def test_the_same_parts_again_join_nothing_and_charge_nothing() -> None:
    parts = (_part(1), _part(2), _part(3))
    joins, store, joiner = Joins(_snapshot(*parts)), Store(_files(*parts)), Joiner()
    media = SimpleNamespace(
        join_preview=lambda t, p: join_preview(store, joins, t, p, joiner=joiner),
        save_join_preview=lambda t, p, w: joins.save(tenant_id=t, parent_id=p, write=w),
    )
    assert run_join(media, TENANT, PARENT) is True
    assert run_join(media, TENANT, PARENT) is False  # same fingerprint: nothing at all
    assert len(joiner.calls) == 1 and len(joins.saved) == 1
    assert len([k for k in store.kept if k.endswith(".mp4")]) == 1


def test_another_version_of_one_part_joins_again_under_another_key() -> None:
    parts = [_part(1), _part(2), _part(3)]
    joins, store, joiner = Joins(_snapshot(*parts)), Store(_files(*parts)), Joiner()
    first = join_preview(store, joins, TENANT, PARENT, joiner=joiner)
    assert first is not None
    joins.save(tenant_id=TENANT, parent_id=PARENT, write=first)
    regenerated = PartPreview(
        **{**parts[1].__dict__, "version_id": uuid4(), "object_key": f"t/{TENANT}/x/r2/clip.mp4"}
    )
    store.files[str(regenerated.object_key)] = b"clip-2b"
    joins.snapshot = PartsToJoin(**{**joins.snapshot.__dict__, "parts": (parts[0], regenerated,
                                    parts[2])})  # fmt: skip
    second = join_preview(store, joins, TENANT, PARENT, joiner=joiner)
    assert second is not None and second.object_key != first.object_key
    assert second.params["draft"]["fingerprint"] != first.params["draft"]["fingerprint"]
    assert len(joiner.calls) == 2


def test_a_join_already_in_the_store_is_reused_not_encoded_again() -> None:
    parts = (_part(1), _part(2))
    fingerprint = join_fingerprint(parts, [part_span(p.params) for p in parts])
    key = join_key(TENANT, PARENT, fingerprint)
    store = Store({**_files(*parts), key: b"kept by a run whose write never landed"})
    joiner = Joiner()
    write = join_preview(store, Joins(_snapshot(*parts)), TENANT, PARENT, joiner=joiner)
    assert write is not None and write.object_key == key and joiner.calls == []
    assert write.params["thumbnail_key"] is None  # no poster was kept for it


def test_parts_that_cannot_be_decoded_join_nothing_and_do_not_retry_forever() -> None:
    parts = (_part(1), _part(2))
    joiner = Joiner(error=JoinError("no video stream"))
    write = join_preview(Store(_files(*parts)), Joins(_snapshot(*parts)), TENANT, PARENT,
                         joiner=joiner)  # fmt: skip
    assert write is None and len(joiner.calls) == 1


def test_a_joined_file_that_cannot_be_kept_keeps_the_previous_join() -> None:
    parts = (_part(1), _part(2))
    joins = Joins(_snapshot(*parts, joined="before"))
    with pytest.raises(JoinNotKept):
        join_preview(Store(_files(*parts), keep_ok=False), joins, TENANT, PARENT, joiner=Joiner())
    assert joins.saved == [] and joins.snapshot.joined_fingerprint == "before"


def test_a_part_not_ready_joins_nothing_and_reads_no_file() -> None:
    parts = (_part(1), _part(2, status="drafting"))
    joiner = Joiner()
    assert join_preview(Store(), Joins(_snapshot(*parts)), TENANT, PARENT, joiner=joiner) is None
    assert joiner.calls == []


def test_the_producer_delegates_to_its_join_store(monkeypatch) -> None:  # noqa: ANN001
    parts = (_part(1), _part(2))
    joins, store, joiner = Joins(_snapshot(*parts)), Store(_files(*parts)), Joiner()
    producer = MediaProducer.__new__(MediaProducer)
    producer._store, producer._part_joins = store, None  # type: ignore[attr-defined]
    assert producer.join_preview(TENANT, PARENT) is None  # not wired: nothing joined
    producer._part_joins = joins  # type: ignore[attr-defined]
    monkeypatch.setattr(part_join, "join_clips", joiner)
    write = producer.join_preview(TENANT, PARENT)
    assert write is not None and len(joiner.calls) == 1
    assert producer.save_join_preview(TENANT, PARENT, write) is True
    assert joins.saved == [write]


# ---------------------------------------------------------------------------
# the real PyAV join on tiny clips


def _clip(path: Path, seconds: float, shade: int) -> bytes:
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    fps = 24
    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=fps)
        video.width, video.height, video.pix_fmt = 64, 114, "yuv420p"
        for i in range(round(seconds * fps)):
            frame = av.VideoFrame.from_ndarray(
                np.full((114, 64, 3), shade, dtype=np.uint8), format="rgb24"
            )
            frame.pts, frame.time_base = i, Fraction(1, fps)
            for packet in video.encode(frame):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    return path.read_bytes()


def test_the_real_join_trims_every_part_to_its_span(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    av = pytest.importorskip("av")
    monkeypatch.setattr(part_join, "JOIN_PREVIEW_SIZE", (96, 170))  # small and fast
    parts = (
        _part(1, seconds=1, generation=2),  # «Nueva»: keeps 1 of its 2 s
        _part(2, mode="edit", seconds=1, generation=2, offset=0.5),  # keeps 0.5–1.5
    )
    store = Store(
        {
            str(parts[0].object_key): _clip(tmp_path / "a.mp4", 2, 40),
            str(parts[1].object_key): _clip(tmp_path / "b.mp4", 2, 200),
        }
    )
    write = join_preview(store, Joins(_snapshot(*parts)), TENANT, PARENT)
    assert write is not None and (write.width, write.height) == (96, 170)
    out = tmp_path / "joined.mp4"
    out.write_bytes(store.files[write.object_key])
    with av.open(str(out)) as source:
        stream = source.streams.video[0]
        frames = sum(1 for _ in source.decode(stream))
        assert (stream.width, stream.height) == (96, 170)
        assert len(source.streams.audio) == 1  # silence where the parts had none
    assert abs(frames - 48) <= 1  # 1 s + 1 s at 24 fps
    assert write.params["join"]["frames"] == frames
    assert write.params["thumbnail_key"] in store.files


def test_an_explicit_trim_of_the_plan_wins() -> None:
    params = _params(seconds=2, generation=4)
    params["part"].update(trim_start_s=1.0, trim_end_s=3.0)
    assert part_span(params) == (1.0, 3.0)
    params["part"].update(trim_start_s=1.0, trim_end_s=9.0)  # past the clip: cut to it
    assert part_span(params) == (1.0, 4.0)


def test_a_new_parent_passes_the_brand_preflight() -> None:
    """Found by the memory harness: a NEW parent through the production producer failed
    its brand-reference preflight (`invalid_parameters`) and never got its text."""
    from qualify_api.creative.brand_references import BrandReferencesSet

    from .test_content_service import make_kit
    from .test_creative_parts import FOUR_PARTS, parent_brief

    brief = parent_brief(*FOUR_PARTS)
    brief = brief.model_copy(
        update={"media": brief.media.model_copy(update={"resource_plan_version": 2})}
    )
    producer = MediaProducer.__new__(MediaProducer)
    producer._preflight_brand_references(brief, make_kit(), BrandReferencesSet(block_version=9))


# ---------------------------------------------------------------------------
# the run's lease during a long join (arm64 / QEMU, 2026-11-06)


class LeaseStore:
    """A `PipelineStore` double for the lease: `renew` extends it while it is held."""

    def __init__(self, lease_s: float, *, lost_after: int | None = None) -> None:
        self.lease_s = lease_s
        self.until = time.monotonic() + lease_s
        self.renews = 0
        self.lost_after = lost_after

    def renew(self, run: object) -> bool:
        self.renews += 1
        if self.lost_after is not None and self.renews > self.lost_after:
            return False
        if time.monotonic() >= self.until:
            return False  # expired: someone else may own it now
        self.until = time.monotonic() + self.lease_s
        return True

    def held(self) -> bool:
        return time.monotonic() < self.until


def test_a_join_longer_than_its_lease_keeps_the_lease() -> None:
    from qualify_api.creative.pipeline import lease_kept

    store = LeaseStore(0.3)
    with lease_kept(store, SimpleNamespace(draft_id=PARENT, phase="join"), every_s=0.1):
        time.sleep(1.0)  # a slow encode: three leases long
    assert store.held() and store.renews >= 5
    bare = LeaseStore(0.3)
    time.sleep(1.0)  # the same encode without the heartbeat loses it
    assert not bare.held()


def test_a_lost_lease_stops_the_heartbeat_for_good() -> None:
    from qualify_api.creative.pipeline import lease_kept

    store = LeaseStore(10, lost_after=1)
    with lease_kept(store, SimpleNamespace(draft_id=PARENT, phase="join"), every_s=0.05):
        time.sleep(0.5)
    assert store.renews == 2  # renewed once, then refused: never tried again


def test_a_store_without_renew_keeps_nothing() -> None:
    from qualify_api.creative.pipeline import lease_kept

    with lease_kept(object(), SimpleNamespace(draft_id=PARENT, phase="join")):
        pass
