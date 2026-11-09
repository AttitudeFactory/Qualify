"""The parts list's thumbnails (UI-3, m-24921077), offline: `avatar_proxy.
part_thumbnail_path` signs the middle stored frame of a part's cuts, and the route
`/avatar/frame/…` (`avatar_proxy.avatar_api` through `httpx.ASGITransport`) serves it from
an in-memory R2 behind the real public door — a week in the browser, a `no-store` 404 on
a miss, and nothing read for a path it did not sign."""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from qualify_api.creative.parts import plan_from_analysis
from qualify_api.referentes import reel_analysis_frames
from qualify_api.referentes.reel_analysis_types import (
    AnalysisProvenance,
    ReelAnalysis,
    ShotAnalysis,
)
from qualify_shared.objects.gate import ObjectNotFound, StoredObject
from qualify_shared.objects.public import PublicObjectGate, reel_frame_key

from . import avatar_proxy as ap

ANALYSIS_ID = UUID("0b9a1c2d-3e4f-4a5b-8c6d-7e8f9a0b1c2d")
POST = "DQx9abc_12"


def _key(shot: int, n: int) -> str:
    return reel_frame_key("instagram", POST, ANALYSIS_ID, shot, n)


def _shot(index: int, start: float, end: float, frames: int) -> ShotAnalysis:
    step = (end - start) / (frames + 1)
    return ShotAnalysis(
        shot_index=index,
        start_s=start,
        end_s=end,
        frame_keys=tuple(_key(index, n) for n in range(frames)),
        frame_times_s=tuple(start + step * (n + 1) for n in range(frames)),
    )


def _analysis(*shots: ShotAnalysis, frames_available: bool = True) -> ReelAnalysis:
    return ReelAnalysis(
        id=ANALYSIS_ID,
        network="instagram",
        post_id=POST,
        analysis_version=1,
        post_url=f"https://www.instagram.com/reel/{POST}/",
        source_seconds=shots[-1].end_s,
        width=720,
        height=1280,
        fps=30.0,
        covered_from_s=0.0,
        covered_to_s=shots[-1].end_s,
        edit_eligible=True,
        source_available=True,
        transcript_text="",
        transcript_segments=(),
        transcript_source="none",
        reel_sheet={},
        shots=shots,
        provenance=AnalysisProvenance(
            model_id="m",
            model_revision=None,
            prompt_version="p",
            schema_version="s",
            detector_version="d",
            sampling_version="v",
            sampling_params={},
            source_sha256="0" * 64,
        ),
        finished_at=datetime(2026, 11, 9, tzinfo=UTC),
        frames_available=frames_available,
    )


class R2:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.reads: list[str] = []

    def put(self, key: str, fileobj: Any, content_type: str) -> None:
        self.objects[key] = fileobj.read()

    def open(self, key: str) -> io.BytesIO:
        self.reads.append(key)
        if key not in self.objects:
            raise ObjectNotFound(key)
        return io.BytesIO(self.objects[key])

    def list_prefix(self, prefix: str) -> Iterator[StoredObject]:
        for key, data in sorted(self.objects.items()):
            if key.startswith(prefix):
                yield StoredObject(key, len(data))

    def delete_keys(self, keys: list[str]) -> None:
        for key in keys:
            self.objects.pop(key, None)


@pytest.fixture
def r2(monkeypatch: pytest.MonkeyPatch) -> R2:
    store = R2()
    monkeypatch.setattr(reel_analysis_frames, "_route_gate", lambda: PublicObjectGate(store))
    return store


async def _get(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=ap.avatar_api)
    async with httpx.AsyncClient(transport=transport, base_url="http://qualify") as client:
        return await client.get(path)


def test_each_part_of_a_plan_gets_the_signed_path_of_its_middle_frame() -> None:
    reel = _analysis(_shot(0, 0.0, 5.0, 3), _shot(1, 5.0, 10.0, 1), _shot(2, 10.0, 15.0, 0))
    plan = plan_from_analysis(reel)
    paths = [ap.part_thumbnail_path(reel, part.shot_indexes) for part in plan]
    assert len(paths) == len(plan) and paths[0]
    first = plan[0].shot_indexes
    expected = reel_analysis_frames.representative_frame(reel, first)
    assert expected is not None
    assert paths[0] == ap.part_frame_path("instagram", POST, ANALYSIS_ID, expected.frame)
    assert paths[0].startswith(f"/avatar/frame/instagram/{POST}/{ANALYSIS_ID}/")
    assert paths[0] == ap.part_thumbnail_path(reel, first)  # deterministic: cacheable


def test_no_frame_or_purged_frames_give_an_empty_path() -> None:
    assert ap.part_thumbnail_path(_analysis(_shot(0, 0.0, 5.0, 0)), (0,)) == ""
    purged = _analysis(_shot(0, 0.0, 5.0, 2), frames_available=False)
    assert ap.part_thumbnail_path(purged, (0,)) == ""


async def test_the_signed_path_serves_the_frame_for_a_week_or_a_no_store_404(r2: R2) -> None:
    r2.objects[_key(0, 1)] = b"\xff\xd8frame"
    found = await _get(ap.part_frame_path("instagram", POST, ANALYSIS_ID, "00-1"))
    assert (found.status_code, found.content) == (200, b"\xff\xd8frame")
    assert found.headers["content-type"] == "image/jpeg"
    assert found.headers["cache-control"] == "public, max-age=604800"

    gone = await _get(ap.part_frame_path("instagram", POST, ANALYSIS_ID, "00-2"))
    assert gone.status_code == 404 and gone.headers["cache-control"] == "no-store"
    assert r2.reads == [_key(0, 1), _key(0, 2)]


async def test_an_unsigned_forged_or_malformed_path_is_refused_before_any_read(r2: R2) -> None:
    r2.objects[_key(0, 1)] = b"\xff\xd8frame"
    other = ap.part_frame_path("instagram", POST, ANALYSIS_ID, "00-2").split("?s=")[1]
    base = f"/avatar/frame/instagram/{POST}/{ANALYSIS_ID}"
    for path in (
        f"{base}/00-1",  # unsigned
        f"{base}/00-1?s=",
        f"{base}/00-1?s={other}",  # another frame's signature
        f"/avatar/frame/tiktok/{POST}/{ANALYSIS_ID}/00-1?s={other}",
        f"/avatar/frame/instagram/{POST}/not-a-uuid/00-1?s={other}",
        f"{base}/00-1?s=%C3%B1",  # non-ASCII
    ):
        refused = await _get(path)
        assert refused.status_code == 404, path
        assert refused.headers["cache-control"] == "no-store", path
    assert r2.reads == []


async def test_a_signed_path_the_door_cannot_key_reads_nothing(r2: R2) -> None:
    """Even a path the server signed only reaches R2 through the door's own builder."""
    bad = ap.part_frame_path("facebook", POST, ANALYSIS_ID, "00-1")
    refused = await _get(bad)
    assert refused.status_code == 404 and r2.reads == []
