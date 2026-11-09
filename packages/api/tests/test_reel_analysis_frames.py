"""The parts list's thumbnails from the analysis frames (UI-3, m-24921077), offline:
`reel_analysis_frames.representative_frame` (pure), `frame_key` / `frame_name` (the door's
own builder, never a key from outside), `open_frame` over an in-memory R2 behind the real
public door, and `get_analysis`'s `frames_available` after the 30-day purge."""

from __future__ import annotations

import ast
import io
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.objects.gate import ObjectNotFound, StoredObject
from qualify_shared.objects.public import PublicObjectGate, reel_frame_key

from qualify_api.referentes import reel_analysis_frames as rf
from qualify_api.referentes.reel_analysis import get_analysis
from qualify_api.referentes.reel_analysis_store import AnalysisRecord, InMemoryAnalysisStore
from qualify_api.referentes.reel_analysis_types import (
    ANALYSIS_VERSION,
    STATUS_OK,
    AnalysisProvenance,
    ReelAnalysis,
    ShotAnalysis,
)

ANALYSIS_ID = UUID("0b9a1c2d-3e4f-4a5b-8c6d-7e8f9a0b1c2d")
OTHER_ID = UUID("1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f")
POST = "DQx9abc_12"
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def key(shot: int, n: int, *, analysis_id: UUID = ANALYSIS_ID, post: str = POST) -> str:
    return reel_frame_key("instagram", post, analysis_id, shot, n)


def shot(index: int, start: float, end: float, *frames: tuple[int, float]) -> ShotAnalysis:
    return ShotAnalysis(
        shot_index=index,
        start_s=start,
        end_s=end,
        frame_keys=tuple(key(index, n) for n, _ in frames),
        frame_times_s=tuple(t for _, t in frames),
    )


def analysis(*shots: ShotAnalysis, frames_available: bool = True) -> ReelAnalysis:
    return ReelAnalysis(
        id=ANALYSIS_ID,
        network="instagram",
        post_id=POST,
        analysis_version=ANALYSIS_VERSION,
        post_url=f"https://www.instagram.com/reel/{POST}/",
        source_seconds=20.0,
        width=720,
        height=1280,
        fps=30.0,
        covered_from_s=0.0,
        covered_to_s=20.0,
        edit_eligible=True,
        source_available=True,
        transcript_text="",
        transcript_segments=(),
        transcript_source="none",
        reel_sheet={},
        shots=tuple(shots),
        provenance=AnalysisProvenance(
            model_id="claude-haiku-5-5",
            model_revision=None,
            prompt_version="p1",
            schema_version="s1",
            detector_version="d1",
            sampling_version="m1",
            sampling_params={},
            source_sha256="0" * 64,
        ),
        finished_at=NOW,
        frames_available=frames_available,
    )


# -- the pick (pure) ----------------------------------------------------------------------


def test_a_cut_with_three_frames_gives_its_middle_one() -> None:
    pick = rf.representative_frame(analysis(shot(0, 0, 4, (0, 0.5), (1, 2.0), (2, 3.5))), [0])
    assert pick == rf.FramePick("instagram", POST, ANALYSIS_ID, "00-1")


def test_a_cut_with_one_frame_gives_it() -> None:
    pick = rf.representative_frame(analysis(shot(3, 0, 2, (0, 1.0))), [3])
    assert pick is not None and pick.frame == "03-0"


def test_a_part_of_several_cuts_takes_the_middle_of_all_their_frames_in_time_order() -> None:
    reel = analysis(
        shot(2, 6, 9, (0, 7.0)),
        shot(1, 3, 6, (1, 5.0), (0, 4.0)),  # stored out of order: time decides
        shot(0, 0, 3, (0, 1.0)),  # not in the part
    )
    pick = rf.representative_frame(reel, [1, 2])
    # frames of cuts 1-2 by time: 01-0 (4.0), 01-1 (5.0), 02-0 (7.0) → the middle
    assert pick is not None and pick.frame == "01-1"


def test_no_frame_purged_frames_or_unknown_cuts_give_nothing() -> None:
    assert rf.representative_frame(analysis(shot(0, 0, 4)), [0]) is None
    assert rf.representative_frame(analysis(shot(0, 0, 4, (0, 1.0))), [5]) is None
    assert rf.representative_frame(analysis(shot(0, 0, 4, (0, 1.0))), []) is None
    purged = analysis(shot(0, 0, 4, (0, 1.0)), frames_available=False)
    assert rf.representative_frame(purged, [0]) is None


def test_a_stored_key_of_another_analysis_or_reel_is_never_picked() -> None:
    foreign = ShotAnalysis(
        0,
        0.0,
        4.0,
        frame_keys=(
            key(0, 0, analysis_id=OTHER_ID),
            key(0, 1, post="OtherPost1"),
            "public/reel-covers/instagram/x.jpg",
            "../../t/secret/frames/00-0.jpg",
        ),
        frame_times_s=(0.5, 1.0, 1.5, 2.0),
    )
    assert rf.representative_frame(analysis(foreign), [0]) is None


def test_mismatched_times_fall_back_to_the_stored_order() -> None:
    odd = ShotAnalysis(0, 0.0, 4.0, frame_keys=(key(0, 0), key(0, 1), key(0, 2)))
    pick = rf.representative_frame(analysis(odd), [0])
    assert pick is not None and pick.frame == "00-1"


def test_the_key_is_rebuilt_by_the_door_and_refuses_what_it_cannot_key() -> None:
    assert rf.frame_key("instagram", POST, ANALYSIS_ID, "07-3") == key(7, 3)
    for network, post, frame in (
        ("facebook", POST, "00-0"),
        ("instagram", "a/b", "00-0"),
        ("instagram", "..", "00-0"),
        ("instagram", POST, "0-0"),
        ("instagram", POST, "00-100"),
        ("instagram", POST, "00-0.jpg"),
        ("instagram", POST, "../00-0"),
    ):
        assert rf.frame_key(network, post, ANALYSIS_ID, frame) is None, (network, post, frame)


# -- the route's read ---------------------------------------------------------------------


class R2:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.reads: list[str] = []

    def put(self, object_key: str, fileobj: Any, content_type: str) -> None:
        self.objects[object_key] = fileobj.read()

    def open(self, object_key: str) -> io.BytesIO:
        self.reads.append(object_key)
        if object_key not in self.objects:
            raise ObjectNotFound(object_key)
        return io.BytesIO(self.objects[object_key])

    def list_prefix(self, prefix: str) -> Iterator[StoredObject]:
        for k, data in sorted(self.objects.items()):
            if k.startswith(prefix):
                yield StoredObject(k, len(data))

    def delete_keys(self, keys: list[str]) -> None:
        for k in keys:
            self.objects.pop(k, None)


def test_open_frame_reads_the_rebuilt_key_or_gives_none() -> None:
    store = R2()
    store.objects[key(1, 2)] = b"\xff\xd8frame"
    gate = PublicObjectGate(store)  # type: ignore[arg-type]
    assert rf.open_frame("instagram", POST, ANALYSIS_ID, "01-2", gate=gate) == b"\xff\xd8frame"
    assert rf.open_frame("instagram", POST, ANALYSIS_ID, "01-3", gate=gate) is None
    assert rf.open_frame("instagram", POST, ANALYSIS_ID, "../x", gate=gate) is None
    assert rf.open_frame("facebook", POST, ANALYSIS_ID, "01-2", gate=gate) is None
    assert store.reads == [key(1, 2), key(1, 3)]  # nothing read for what the door refuses


def test_an_r2_failure_is_none_never_an_error() -> None:
    class Broken(R2):
        def open(self, object_key: str) -> io.BytesIO:
            raise TimeoutError("slow")

    gate = PublicObjectGate(Broken())  # type: ignore[arg-type]
    assert rf.open_frame("instagram", POST, ANALYSIS_ID, "00-0", gate=gate) is None


def test_the_module_only_reads_the_public_door() -> None:
    path = Path(rf.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    door = {
        "put_public",
        "put_public_if_absent",
        "open_public",
        "public_size",
        "open_public_range",
        "delete_public_prefix",
        "delete_public_object",
    }
    calls = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in door}
    assert calls == {"open_public"}


# -- the analysis says whether its frames are still there ----------------------------------


def _ok_record(*, frames_purged_at: datetime | None) -> AnalysisRecord:
    return AnalysisRecord(
        id=uuid4(),
        network="instagram",
        post_id=POST,
        analysis_version=ANALYSIS_VERSION,
        status=STATUS_OK,
        post_url=f"https://www.instagram.com/reel/{POST}/",
        created_at=NOW - timedelta(days=1),
        source_key=None,
        source_seconds=12.0,
        width=720,
        height=1280,
        fps=30.0,
        covered_from_s=0.0,
        covered_to_s=12.0,
        edit_eligible=True,
        model_id="claude-haiku-5-5",
        prompt_version="p1",
        schema_version="s1",
        detector_version="d1",
        sampling_version="m1",
        sampling_params={},
        cost_usd=Decimal("0"),
        finished_at=NOW,
        frames_purged_at=frames_purged_at,
    )


@pytest.mark.parametrize(("purged_at", "available"), [(None, True), (NOW, False)])
def test_get_analysis_says_whether_the_frames_are_still_stored(
    purged_at: datetime | None, available: bool
) -> None:
    store = InMemoryAnalysisStore()
    record = _ok_record(frames_purged_at=purged_at)
    store.put(record, [ShotAnalysis(0, 0.0, 4.0)])
    found = get_analysis(uuid4(), record.id, store=store)
    assert found is not None and found.frames_available is available
