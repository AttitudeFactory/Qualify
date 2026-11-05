"""Keeping each idea's video in R2 during the weekly run (`reel_analysis`, founder
2026-11-04; the R8 slice of VE-04a m-24921056), offline: a synthetic MP4 made with PyAV,
`httpx.MockTransport` as the CDN, the in-memory analysis store and an in-memory R2 behind
the real `PublicObjectGate`. Nothing here reaches a network, R2 or a paid service.

Pins the architect's spec: the stored-but-undescribed state (and every 0119 rule it must
keep), one copy for every business, the 20 h link window without a request, no
redirects, the 80 MiB ceiling, unreadable files, the retry of a failed row with a fresh
link while attempts < 3, the lease, the conversion (≤ 60 s, no audio, H.264, ≤ 1280 px),
and the hook through R4's `run(analyze=…)`."""

from __future__ import annotations

import io
import tempfile
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from qualify_shared.objects import PublicObjectGate, StoredObject, public_source_key

from qualify_api.referentes import reel_analysis as ra
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes.reel_runs import IdeaSource

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

NOW = datetime(2026, 11, 9, 11, 30, tzinfo=UTC)
CDN = "https://scontent.cdninstagram.com/v/reel-{}.mp4?oe=signed"
CHARGE = ra.RunCharge(uuid4(), uuid4(), uuid4())


def synthetic_mp4(
    seconds: float = 2.0, size: tuple[int, int] = (360, 640), fps: int = 30, audio: bool = True
) -> bytes:
    """A small H.264 MP4 (with an AAC track when `audio`), made in memory."""
    out = io.BytesIO()
    with av.open(out, "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=fps)
        video.width, video.height = size
        video.pix_fmt = "yuv420p"
        sound = sink.add_stream("aac", rate=44100) if audio else None
        frames = int(seconds * fps)
        for i in range(frames):
            pixels = np.full((size[1], size[0], 3), (7 * i) % 255, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts = i
            frame.time_base = Fraction(1, fps)
            for packet in video.encode(frame):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
        if sound is not None:
            samples = av.AudioFrame.from_ndarray(
                np.zeros((1, 1024), dtype=np.float32), format="fltp", layout="mono"
            )
            samples.sample_rate = 44100
            for packet in sound.encode(samples):
                sink.mux(packet)
            for packet in sound.encode():
                sink.mux(packet)
    return out.getvalue()


class DictStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, fileobj: Any, content_type: str) -> None:
        self.objects[key] = fileobj.read()

    def open(self, key: str) -> io.BytesIO:
        return io.BytesIO(self.objects[key])

    def list_prefix(self, prefix: str) -> Iterator[StoredObject]:
        for key, data in sorted(self.objects.items()):
            if key.startswith(prefix):
                yield StoredObject(key, len(data))

    def delete_keys(self, keys: Sequence[str]) -> None:
        for key in keys:
            self.objects.pop(key, None)


class CDNServer:
    """The vendor's CDN, scripted: what each URL answers, and every request made."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requests: list[str] = []
        self.answers: dict[str, httpx.Response] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        return self.answers.get(str(request.url)) or httpx.Response(200, content=self.body)


@pytest.fixture(scope="module")
def mp4() -> bytes:
    return synthetic_mp4()


@pytest.fixture
def world(mp4: bytes) -> dict[str, Any]:
    cdn = CDNServer(mp4)
    return {
        "store": ra.MemoryAnalysisStore(),
        "r2": DictStore(),
        "cdn": cdn,
        "client": httpx.Client(transport=httpx.MockTransport(cdn)),
        "clock": [NOW],
    }


def _source(post_id: str = "C1", *, read: timedelta = timedelta(hours=2), **kw: Any) -> IdeaSource:
    return IdeaSource(
        network=kw.pop("network", "instagram"),
        post_id=post_id,
        post_url=f"https://www.instagram.com/reel/{post_id}/",
        video_url=kw.pop("video_url", CDN.format(post_id)),
        caption="",
        transcript="",
        video_url_at=NOW - read,
    )


def _analyze(world: dict[str, Any], *sources: IdeaSource) -> Decimal:
    return ra.analyze_run_ideas(
        CHARGE,
        list(sources),
        store=world["store"],
        gate=PublicObjectGate(world["r2"]),
        client=world["client"],
        clock=lambda: world["clock"][0],
    )


def _row(world: dict[str, Any], post_id: str = "C1") -> Any:
    store: ra.MemoryAnalysisStore = world["store"]
    return next(r for r in store.rows.values() if r.row.post_id == post_id)


# --------------------------------------------------------------------------------------
# stored, not described
# --------------------------------------------------------------------------------------


def test_an_ideas_video_is_stored_and_left_for_the_description(world: dict[str, Any]) -> None:
    assert _analyze(world, _source()) == Decimal("0")  # nothing paid in this slice
    item = _row(world)
    row = item.row
    key = public_source_key("instagram", "C1", row.id)
    assert (row.status, row.stage, row.attempts) == ("queued", "detecting", 1)
    assert row.lease_token is None and row.lease_until is None  # 0119's ck_pra_lease
    assert item.pending_video_url is None and row.error_code is None  # never kept
    assert row.source_key == key and row.video_stored
    assert row.source_purge_after == NOW + timedelta(days=30)
    values = item.values
    assert len(values["source_sha256"]) == 64 and values["covered_from_s"] == 0
    assert 0 < values["covered_to_s"] == values["source_seconds"] <= 60
    assert values["width"] > 0 and values["height"] > 0 and values["fps"] == 30.0
    assert values["edit_eligible"] is True
    assert world["cdn"].requests == [CDN.format("C1")]
    with av.open(io.BytesIO(world["r2"].objects[key])) as stored:
        assert not stored.streams.audio  # no original audio
        assert stored.streams.video[0].codec_context.name == "h264"


def test_one_copy_serves_every_business(world: dict[str, Any]) -> None:
    _analyze(world, _source())
    _analyze(world, _source())  # another business gets the same reel as an idea
    assert world["cdn"].requests == [CDN.format("C1")]  # downloaded once
    assert len(world["store"].rows) == 1 and len(world["r2"].objects) == 1


# --------------------------------------------------------------------------------------
# what is refused, and without what
# --------------------------------------------------------------------------------------


def test_a_link_read_twenty_hours_ago_is_not_even_requested(world: dict[str, Any]) -> None:
    _analyze(world, _source(read=timedelta(hours=20)))
    row = _row(world).row
    assert (row.status, row.error_code) == ("failed", "source_expired")
    assert world["cdn"].requests == [] and world["r2"].objects == {}


def test_a_redirect_is_refused_and_leaves_nothing(world: dict[str, Any]) -> None:
    world["cdn"].answers[CDN.format("C1")] = httpx.Response(
        302, headers={"location": "https://127.0.0.1/private"}
    )
    before = set(Path(tempfile.gettempdir()).glob("qualify-reel-*"))
    _analyze(world, _source())
    row = _row(world).row
    assert (row.status, row.error_code) == ("failed", "source_unavailable")
    assert world["cdn"].requests == [CDN.format("C1")]  # never followed
    assert world["r2"].objects == {}
    assert set(Path(tempfile.gettempdir()).glob("qualify-reel-*")) == before  # no temp file


def test_a_host_outside_the_cdn_is_never_requested(world: dict[str, Any]) -> None:
    _analyze(world, _source(video_url="https://unavatar.io/reel.mp4"))
    assert _row(world).row.error_code == "source_unavailable"
    assert world["cdn"].requests == []


def test_a_body_over_the_ceiling_is_cut(world: dict[str, Any], monkeypatch: Any) -> None:
    monkeypatch.setattr(ra, "MAX_SOURCE_BYTES", 1000)
    _analyze(world, _source())
    assert _row(world).row.error_code == "source_too_large"
    assert world["r2"].objects == {}


def test_an_unreadable_file_ends_source_unreadable(world: dict[str, Any]) -> None:
    world["cdn"].body = b"this is not a video"
    _analyze(world, _source())
    assert _row(world).row.error_code == "source_unreadable"
    assert world["r2"].objects == {}


# --------------------------------------------------------------------------------------
# retries and the lease
# --------------------------------------------------------------------------------------


def test_a_fresh_link_retries_a_failed_row_while_attempts_last(world: dict[str, Any]) -> None:
    _analyze(world, _source(read=timedelta(hours=30)))  # expired: failed, attempt 1
    assert _row(world).row.error_code == "source_expired"
    _analyze(world, _source(read=timedelta(hours=1)))  # a later run lists it, fresh link
    row = _row(world).row
    assert (row.status, row.stage, row.attempts) == ("queued", "detecting", 2)
    assert row.video_stored


def test_no_retry_once_three_attempts_were_spent(world: dict[str, Any]) -> None:
    """Each later run brings a fresh link, and the CDN keeps answering 404: three
    attempts, then the row stays failed and nothing is requested again."""
    world["cdn"].answers[CDN.format("C1")] = httpx.Response(404)
    for _ in range(4):
        _analyze(world, _source(read=timedelta(minutes=5)))
        world["clock"][0] += timedelta(hours=1)
    row = _row(world).row
    assert (row.status, row.error_code, row.attempts) == (
        "failed",
        "source_unavailable",
        ra.MAX_ATTEMPTS,
    )
    assert len(world["cdn"].requests) == ra.MAX_ATTEMPTS


def test_a_stale_link_never_retries_a_failed_row(world: dict[str, Any]) -> None:
    _analyze(world, _source(read=timedelta(hours=30)))
    _analyze(world, _source(read=timedelta(hours=30)))
    row = _row(world).row
    assert (row.status, row.attempts) == ("failed", 1) and world["cdn"].requests == []


def test_a_live_lease_is_left_alone_and_an_expired_one_taken_over(
    world: dict[str, Any],
) -> None:
    store: ra.MemoryAnalysisStore = world["store"]
    row = store.upsert("instagram", "C1", post_url="https://x/", video_url=CDN.format("C1"))
    assert store.claim(row.id, token=uuid4(), now=NOW) is not None  # another worker
    _analyze(world, _source())
    assert world["cdn"].requests == [] and _row(world).row.status == "running"
    world["clock"][0] = NOW + ra.LEASE + timedelta(seconds=1)  # that worker died
    _analyze(world, _source(read=timedelta(hours=1)))
    row = _row(world).row
    assert row.video_stored and row.attempts == 2


def test_a_lost_lease_writes_nothing_more(world: dict[str, Any], monkeypatch: Any) -> None:
    store: ra.MemoryAnalysisStore = world["store"]
    monkeypatch.setattr(store, "renew", lambda *a, **k: False)  # another worker took it
    monkeypatch.setattr(ra, "LEASE_RENEW_EVERY", timedelta(0))
    assert _analyze(world, _source()) == Decimal("0")
    row = _row(world).row
    assert row.status == "running" and not row.video_stored  # left to its new owner


# --------------------------------------------------------------------------------------
# the conversion
# --------------------------------------------------------------------------------------


def test_the_copy_is_cut_scaled_and_silent(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(ra, "MAX_SOURCE_SECONDS", 1)
    monkeypatch.setattr(ra, "MAX_SIDE", 160)
    source = tmp_path / "in.mp4"
    source.write_bytes(synthetic_mp4(seconds=3, size=(360, 640)))
    target = tmp_path / "out.mp4"
    shape = ra.transcode(source, target, keep=lambda: None)
    assert (shape.width, shape.height) == (90, 160) and shape.seconds == 1.0
    with av.open(str(target)) as stored:
        stream = stored.streams.video[0]
        assert not stored.streams.audio
        assert (stream.codec_context.width, stream.codec_context.height) == (90, 160)
        assert sum(1 for _ in stored.decode(stream)) == 30


def test_fitted_size_keeps_the_aspect_and_is_even() -> None:
    assert ra.fitted_size(1080, 1920) == (720, 1280)
    assert ra.fitted_size(640, 360) == (640, 360)  # never upscaled
    assert ra.fitted_size(1081, 1921) == (720, 1280)


# --------------------------------------------------------------------------------------
# the hook
# --------------------------------------------------------------------------------------


def test_one_idea_that_fails_never_stops_the_others(world: dict[str, Any]) -> None:
    world["cdn"].answers[CDN.format("C1")] = httpx.Response(404)
    _analyze(world, _source("C1"), _source("C2"))
    assert _row(world, "C1").row.error_code == "source_unavailable"
    assert _row(world, "C2").row.video_stored


def test_a_stop_goes_through_the_hook(world: dict[str, Any], monkeypatch: Any) -> None:
    def stop(*_: Any, **__: Any) -> Any:
        raise rr.RunInterrupted("signal 15")

    monkeypatch.setattr(ra, "keep_source", stop)
    with pytest.raises(rr.RunInterrupted):
        _analyze(world, _source())


def test_the_hook_runs_after_an_ok_run_and_never_changes_it(world: dict[str, Any]) -> None:
    """Through R4's `run(analyze=RunHook(...))`: the run ends ok, then its ideas' videos
    are kept; the run's cost is unchanged (the copy is free)."""
    from qualify_api.claude_tools import CallStats
    from qualify_api.referentes import (
        MemoryReferentesRepository,
        NewDiscoveredAccount,
        NewDiscoveryPhase,
        reels_ai,
    )
    from qualify_api.referentes import ai as review_ai
    from qualify_api.referentes.reel_store import MemoryReelRunStore
    from qualify_api.referentes.reels_ai import ReelReview

    tenant, brand = uuid4(), uuid4()
    repo = MemoryReferentesRepository()
    repo.add_brand(tenant_id=tenant, brand_id=brand)
    repo.save_phase(
        NewDiscoveryPhase(
            tenant_id=tenant,
            brand_id=brand,
            phase_key="sector",
            algorithm_version=1,
            seed_signature="s",
            seed={"handle": "burgerco", "terms": ["hamburguesería"], "hashtags": []},
            title="Sector",
            accounts=(NewDiscoveredAccount(network="instagram", handle="foodie", card={}),),
        )
    )
    repo.set_label(
        tenant_id=tenant,
        brand_id=brand,
        network="instagram",
        handle="foodie",
        label="referente",
        labeled_by=None,
    )
    feed = [
        {
            "id": f"F{k}",
            "network": "instagram",
            "handle": "foodie",
            "url": f"https://www.instagram.com/reel/F{k}/",
            "caption": f"hamburguesa {k}",
            "takenAt": (NOW - timedelta(days=k + 1)).timestamp(),
            "views": 1000 * (3 - k),
            "seconds": 12,
            "video": CDN.format(f"F{k}"),
        }
        for k in range(3)
    ]

    def review(brief: Any, batch: list[Any], **_: Any) -> Any:
        answers = [
            ReelReview(id=r.id, fits=True, reason="ok", format="receta", hook="pregunta")
            for r in batch
        ]
        return answers, CallStats(reels_ai.REVIEW_MODEL, None, 10, 10)

    store = MemoryReelRunStore()
    run = rr.enqueue_run(tenant, brand, "manual", store=store, clock=NOW.timestamp)
    hook = ra.RunHook(
        store=world["store"],
        gate=PublicObjectGate(world["r2"]),
        client=world["client"],
        clock=lambda: NOW,
    )
    outcome = rr.run(
        tenant,
        run.id,
        store=store,
        repository=repo,
        brief=lambda t, b: review_ai.BrandBrief(handle="burgerco", rubro=("hamburguesería",)),
        api_key="k",
        fetch=lambda network, handle, **_: [dict(r) for r in feed],
        transcribe_fetch=lambda reel, client: "dicen",
        review=review,
        analyze=hook,
        clock=NOW.timestamp,
        sleep=lambda seconds: None,
    )
    assert outcome.status == "ok" and outcome.ideas == 3
    stored = [r for r in world["store"].rows.values() if r.row.video_stored]
    assert len(stored) == 3 and len(world["r2"].objects) == 3
    assert store.runs[run.id].cost_usd == outcome.cost_usd


def test_run_charge_names_the_run() -> None:
    charge = ra.RunCharge(UUID(int=1), UUID(int=2), UUID(int=3))
    assert charge.run_id == UUID(int=3)
