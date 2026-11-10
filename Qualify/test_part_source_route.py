"""The original reel, part by part (step 2, m-24992893), offline: `avatar_proxy.
part_source_path` signs ONE path per analysis (or "" once the copy is gone), the route
`/avatar/source/…` (`avatar_proxy.avatar_api` through `httpx.ASGITransport`) answers it by
byte range from an in-memory R2 behind the real public door — 206 + `Content-Range`,
416 out of range, `HEAD` with the size, the whole copy without `Range`, a `no-store` 404
on a miss and nothing read for a path it did not sign — and `reel_wait_provider.
reel_plan` gives every entry that path with the part's stretch (`start_s` / `end_s`)."""

from __future__ import annotations

import io
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from qualify_api.referentes import reel_analysis_original
from qualify_api.referentes.reel_analysis_types import (
    AnalysisProvenance,
    ReelAnalysis,
    ShotAnalysis,
)
from qualify_shared.objects.gate import ObjectNotFound
from qualify_shared.objects.public import PublicObjectGate, reel_source_key

from . import avatar_proxy as ap
from . import r2_media
from . import reel_wait_provider as provider

ANALYSIS_ID = UUID("0b9a1c2d-3e4f-4a5b-8c6d-7e8f9a0b1c2d")
POST = "7118207082913942826"
KEY = reel_source_key("tiktok", POST, ANALYSIS_ID)
VIDEO = bytes(range(256)) * 40  # 10,240 bytes


def _shot(index: int, start: float, end: float) -> ShotAnalysis:
    return ShotAnalysis(shot_index=index, start_s=start, end_s=end)


def _analysis(*shots: ShotAnalysis, source_available: bool = True) -> ReelAnalysis:
    return ReelAnalysis(
        id=ANALYSIS_ID,
        network="tiktok",
        post_id=POST,
        analysis_version=1,
        post_url=f"https://www.tiktok.com/@x/video/{POST}",
        source_seconds=shots[-1].end_s,
        width=720,
        height=1280,
        fps=30.0,
        covered_from_s=0.0,
        covered_to_s=shots[-1].end_s,
        edit_eligible=True,
        source_available=source_available,
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
    )


class R2:
    """What the public door calls to read a source by range, with every call kept."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple[Any, ...]] = []

    def _get(self, key: str) -> bytes:
        if key not in self.objects:
            raise ObjectNotFound(key)
        return self.objects[key]

    def size(self, key: str) -> int:
        self.calls.append(("size", key))
        return len(self._get(key))

    def open_range(self, key: str, start: int, end: int) -> io.BytesIO:
        self.calls.append(("range", key, start, end))
        return io.BytesIO(self._get(key)[start : end + 1])

    def open(self, key: str) -> io.BytesIO:  # never called by the route (static test too)
        raise AssertionError("the source route reads by range only")


@pytest.fixture
def r2(monkeypatch: pytest.MonkeyPatch) -> R2:
    store = R2()
    monkeypatch.setattr(reel_analysis_original, "_route_gate", lambda: PublicObjectGate(store))
    reel_analysis_original.clear_size_cache()
    yield store
    reel_analysis_original.clear_size_cache()


async def _call(path: str, method: str = "GET", **headers: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=ap.avatar_api)
    async with httpx.AsyncClient(transport=transport, base_url="http://qualify") as client:
        return await client.request(method, path, headers=headers)


def _path() -> str:
    return ap.part_source_path(_analysis(_shot(0, 0.0, 4.0)))


# -- the signed path (pure) ----------------------------------------------------------------


def test_one_signed_path_per_analysis_or_empty_once_the_copy_is_gone() -> None:
    reel = _analysis(_shot(0, 0.0, 4.0), _shot(1, 4.0, 9.5))
    path = ap.part_source_path(reel)
    assert path.startswith(f"/avatar/source/tiktok/{POST}/{ANALYSIS_ID}?s=")
    assert path == ap.part_source_path(reel)  # deterministic: the browser caches it
    assert ap.part_source_path(replace(reel, source_available=False)) == ""
    assert ap.part_source_path(replace(reel, post_id="../x")) == ""  # not a key the door makes


# -- the route -----------------------------------------------------------------------------


async def test_a_range_is_answered_206_with_its_content_range(r2: R2) -> None:
    r2.objects[KEY] = VIDEO
    response = await _call(_path(), Range="bytes=100-199")
    assert response.status_code == 206
    assert response.content == VIDEO[100:200]
    assert response.headers["content-range"] == f"bytes 100-199/{len(VIDEO)}"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "video/mp4"
    assert "private" in response.headers["cache-control"]


async def test_an_open_range_is_capped_and_the_size_is_read_once(
    r2: R2, monkeypatch: pytest.MonkeyPatch
) -> None:
    r2.objects[KEY] = VIDEO
    monkeypatch.setattr(r2_media, "MAX_RANGE_BYTES", 1000)
    first = await _call(_path(), Range="bytes=0-")
    assert first.status_code == 206 and first.content == VIDEO[:1000]
    assert first.headers["content-range"] == f"bytes 0-999/{len(VIDEO)}"
    tail = await _call(_path(), Range="bytes=-240")
    assert tail.content == VIDEO[-240:]
    assert [c for c in r2.calls if c[0] == "size"] == [("size", KEY)]  # remembered


async def test_out_of_range_is_416_with_the_size(r2: R2) -> None:
    r2.objects[KEY] = VIDEO
    response = await _call(_path(), Range=f"bytes={len(VIDEO)}-")
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(VIDEO)}"
    assert response.headers["cache-control"] == "no-store"


async def test_head_says_the_size_and_reads_no_byte(r2: R2) -> None:
    r2.objects[KEY] = VIDEO
    response = await _call(_path(), "HEAD")
    assert response.status_code == 200
    assert response.headers["content-length"] == str(len(VIDEO))
    assert [c[0] for c in r2.calls] == ["size"]


async def test_without_range_the_whole_copy_comes_range_by_range(
    r2: R2, monkeypatch: pytest.MonkeyPatch
) -> None:
    r2.objects[KEY] = VIDEO
    monkeypatch.setattr(ap, "MAX_RANGE_BYTES", 4096)
    response = await _call(_path())
    assert response.status_code == 200 and response.content == VIDEO
    assert [c for c in r2.calls if c[0] == "range"] == [
        ("range", KEY, 0, 4095),
        ("range", KEY, 4096, 8191),
        ("range", KEY, 8192, len(VIDEO) - 1),
    ]


async def test_a_purged_copy_is_a_no_store_404(r2: R2) -> None:
    response = await _call(_path(), Range="bytes=0-")
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"


async def test_an_unsigned_or_forged_path_reads_nothing(r2: R2) -> None:
    r2.objects[KEY] = VIDEO
    base = f"/avatar/source/tiktok/{POST}/{ANALYSIS_ID}"
    other = UUID("1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f")
    forged = f"/avatar/source/tiktok/{POST}/{other}?s=" + ap.part_source_signature(
        "tiktok", POST, ANALYSIS_ID
    )
    for path in (base, base + "?s=0000", forged, f"/avatar/source/tiktok/{POST}/nope?s=x"):
        response = await _call(path, Range="bytes=0-")
        assert response.status_code == 404, path
        assert response.headers["cache-control"] == "no-store"
    assert r2.calls == []


# -- the plan's entries --------------------------------------------------------------------


def test_every_entry_gets_the_analysis_path_and_its_own_stretch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reel = _analysis(_shot(0, 0.0, 3.0), _shot(1, 3.0, 7.04), _shot(2, 7.04, 12.5))
    monkeypatch.setattr(provider.reel_analysis, "get_analysis", lambda tenant, aid: reel)
    entries = provider.reel_plan(UUID(int=1), ANALYSIS_ID)
    assert entries
    path = ap.part_source_path(reel)
    for entry in entries:
        cuts = entry["plan"]["shot_indexes"]
        assert entry["source"] == path
        assert entry["start_s"] == round(reel.shots[cuts[0]].start_s, 1)
        assert entry["end_s"] == round(reel.shots[cuts[-1]].end_s, 1)
    assert entries[0]["start_s"] == 0.0 and entries[-1]["end_s"] == 12.5


def test_a_purged_copy_gives_entries_no_source(monkeypatch: pytest.MonkeyPatch) -> None:
    reel = _analysis(_shot(0, 0.0, 5.0), source_available=False)
    monkeypatch.setattr(provider.reel_analysis, "get_analysis", lambda tenant, aid: reel)
    entries = provider.reel_plan(UUID(int=1), ANALYSIS_ID)
    assert entries and all(e["source"] == "" for e in entries)
    assert entries[0]["start_s"] == 0.0 and entries[0]["end_s"] == 5.0


def test_part_stretch_is_none_for_a_part_without_cuts_of_the_reel() -> None:
    reel = _analysis(_shot(0, 0.0, 5.0), _shot(1, 5.0, 9.0))
    assert provider.part_stretch(reel, ()) is None
    assert provider.part_stretch(reel, (7,)) is None
    assert provider.part_stretch(reel, (1,)) == (5.0, 9.0)
