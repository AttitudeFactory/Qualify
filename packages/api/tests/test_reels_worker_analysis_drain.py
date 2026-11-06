"""The shared analysis queue as the `reels-worker` drains it in production (ADR 42 R8,
m-24854855, over ADR 44 VE-04a/c): `reel_worker.production_drain` builds VE-04a's
`default_worker()` and runs `drain_once`. Proven offline:

- with `QUALIFY_REEL_ANALYSIS_DESCRIBE` off (the default) the row is downloaded from the
  CDN and stored in R2, and NOTHING else is called — no model, no ScrapeCreators;
- switched on, VE-04c's describe step runs (a stand-in for `ReelDescriber` here) and its
  cost lands on the shared row only — never in a business's consumption ledger (decision
  #10 of the epic) nor in R5's credit ledger — and the fleet's daily cap of model calls
  holds the call on this production path too.

Every `httpx.Client` of the process is replaced by a recorder, so a request to any host
(the vendor's API, the model's) would show up; Postgres and R2 are VE-04a's in-memory
doubles; the reel is a synthetic MP4 made with PyAV."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import IO, Any
from uuid import uuid4

import httpx
import pytest

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from qualify_shared.objects.gate import ObjectNotFound, StoredObject  # noqa: E402
from qualify_shared.objects.public import reel_source_key  # noqa: E402

from qualify_api.referentes import reel_analysis_worker as w  # noqa: E402
from qualify_api.referentes import reel_worker as rw  # noqa: E402
from qualify_api.referentes import worker as cli  # noqa: E402
from qualify_api.referentes.reel_analysis import FLEET_DAILY_ENV  # noqa: E402
from qualify_api.referentes.reel_analysis_store import (  # noqa: E402
    AnalysisRecord,
    DescribeResult,
    InMemoryAnalysisStore,
)
from qualify_api.referentes.reel_analysis_types import (  # noqa: E402
    ANALYSIS_VERSION,
    OBSERVED,
    STATUS_OK,
    STATUS_QUEUED,
    ReelSource,
    ShotAnalysis,
)
from qualify_api.vendors import scrapecreators, usage  # noqa: E402

IG_URL = "https://scontent-bog1-1.cdninstagram.com/o1/v/t16/clip.mp4?efg=abc"
IG_CDN = "cdninstagram.com"


def _on_host(host: str, domain: str) -> bool:
    """`host` is `domain` or one of its subdomains — compared as a parsed host, never as a
    substring (`cdninstagram.com.evil.example` is not Instagram's CDN)."""
    host = host.lower()
    return host == domain or host.endswith("." + domain)


def _mp4(seconds: float = 2.0, fps: int = 30, size: tuple[int, int] = (64, 112)) -> bytes:
    """A synthetic H.264 MP4 — no real reel."""
    out = io.BytesIO()
    width, height = size
    with av.open(out, "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=fps, options={"preset": "ultrafast"})
        video.width, video.height, video.pix_fmt = width, height, "yuv420p"
        for i in range(int(seconds * fps)):
            pixels = np.full((height, width, 3), (7 * i) % 255, dtype=np.uint8)
            for packet in video.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    return out.getvalue()


class Bucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None:
        self.objects[key] = fileobj.read()

    def open(self, key: str) -> IO[bytes]:
        return io.BytesIO(self.objects[key])

    def size(self, key: str) -> int:
        if key not in self.objects:
            raise ObjectNotFound(key)  # what R2ObjectStore raises; put_public_if_absent needs it
        return len(self.objects[key])

    def open_range(self, key: str, start: int, end: int) -> IO[bytes]:
        return io.BytesIO(self.objects[key][start : end + 1])

    def list_prefix(self, prefix: str) -> list[StoredObject]:
        return [StoredObject(k, len(v)) for k, v in self.objects.items() if k.startswith(prefix)]

    def delete_keys(self, keys: list[str]) -> None:
        for key in keys:
            self.objects.pop(key, None)


@pytest.fixture
def production(monkeypatch: pytest.MonkeyPatch) -> tuple[InMemoryAnalysisStore, Bucket, list]:
    """`default_worker()` exactly as production builds it, over in-memory doubles."""
    import qualify_shared.objects.config as r2_config
    import qualify_shared.objects.s3 as r2_s3

    from qualify_api.referentes import reel_analysis_queue

    store, bucket, requests = InMemoryAnalysisStore(), Bucket(), []
    clip = _mp4()
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if _on_host(request.url.host, IG_CDN):
            return httpx.Response(200, content=clip)
        return httpx.Response(599)  # anything else is a failure of this test

    def recording_client(*_: Any, **__: Any) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(handler), follow_redirects=False)

    def no_paid_call(*_: Any, **__: Any) -> Any:
        raise AssertionError("the analysis drain must never call ScrapeCreators")

    monkeypatch.delenv(w.DESCRIBE_ENV, raising=False)  # the default: download only
    monkeypatch.setattr(httpx, "Client", recording_client)
    monkeypatch.setattr(scrapecreators, "metered_get", no_paid_call)
    monkeypatch.setattr(r2_config.R2Settings, "from_env", classmethod(lambda cls: None))
    monkeypatch.setattr(r2_s3, "R2ObjectStore", lambda settings: bucket)
    monkeypatch.setattr(reel_analysis_queue, "PostgresAnalysisQueue", lambda: store)
    monkeypatch.setattr(rw, "_analysis_worker", None)
    return store, bucket, requests


def test_the_production_drain_downloads_and_stores_and_calls_nothing_else(production) -> None:
    store, bucket, requests = production
    now = datetime.now(UTC)
    record, _ = store.ensure(
        ReelSource(
            network="instagram",
            post_id="DABC1",
            post_url="https://www.instagram.com/reel/DABC1/",
            video_url=IG_URL,
        ),
        ANALYSIS_VERSION,
        now,
    )

    outcome = rw.production_drain()

    assert w.DEFAULT_DESCRIBE is None and rw._analysis_worker.describe is None
    assert outcome is not None and outcome.outcome == w.OUTCOME_DOWNLOADED
    assert outcome.cost_usd == 0
    assert requests == [IG_URL]  # one GET, to the CDN: no vendor, no model
    row = store.rows()[0]
    key = reel_source_key("instagram", "DABC1", record.id)
    assert (row.status, row.source_key, row.model_calls) == (STATUS_QUEUED, key, 0)
    assert row.source_purge_after is not None
    assert row.source_purge_after - now - timedelta(days=30) < timedelta(minutes=1)
    assert key in bucket.objects and row.pending_video_url is None

    assert rw.production_drain() is None  # nothing left to download: no request
    assert requests == [IG_URL]


def test_only_the_all_tenants_service_is_built_with_the_production_drain() -> None:
    every = cli.production_worker(
        None, batch=1, schedule_every=timedelta(minutes=15), should_stop=lambda: False
    )
    assert every._drain is rw.production_drain


# --------------------------------------------------------------------------------------
# describing switched on (VE-04c): who pays, and the fleet's cap
# --------------------------------------------------------------------------------------

HAIKU_COST = Decimal("0.0055")


class FakeHaiku:
    """`ReelDescriber`'s stand-in on the production path: like the real step, it asks
    `charge_model_call` BEFORE each model call and counts only the calls let through."""

    built: list[FakeHaiku] = []

    def __init__(self, *_: Any, **__: Any) -> None:
        self.calls_made = 0
        FakeHaiku.built.append(self)

    def __call__(self, job: w.DescribeInput) -> DescribeResult:
        job.charge_model_call()  # ≤ 2 a row; the fleet's calls of the last 24 h
        self.calls_made += 1
        key = job.put_frame(0, 0, b"\xff\xd8jpeg")
        return DescribeResult(
            shots=(
                ShotAnalysis(
                    0,
                    0.0,
                    job.source.covered_to_s,
                    frame_keys=(key,),
                    frame_times_s=(0.3,),
                    people_presence=OBSERVED,
                ),
            ),
            reel_sheet={"hook": {"status": "unknown"}},
            model_id="claude-haiku-5-5",
            model_revision="rev-1",
            prompt_version="p1",
            schema_version="s1",
            detector_version="d1",
            sampling_version="m1",
            sampling_params={"max_frames": 32},
            input_tokens=40_000,
            output_tokens=3_000,
            cost_usd=HAIKU_COST,
        )


@pytest.fixture
def described(production, monkeypatch: pytest.MonkeyPatch):
    """The production drain with `QUALIFY_REEL_ANALYSIS_DESCRIBE=1` (and a test key), its
    Haiku step faked; both business ledgers refuse any write."""
    from qualify_api import consumption
    from qualify_api.claude_tools import API_KEY_ENV
    from qualify_api.referentes import reel_analysis_ai

    def no_business_ledger(*_: Any, **__: Any) -> Any:
        raise AssertionError("a shared analysis is nobody's: no consumption row (decision #10)")

    FakeHaiku.built.clear()
    monkeypatch.setenv(w.DESCRIBE_ENV, "1")
    monkeypatch.setenv(API_KEY_ENV, "sk-test-not-a-key")
    monkeypatch.setattr(reel_analysis_ai, "ReelDescriber", FakeHaiku)
    monkeypatch.setattr(consumption, "record_consumption", no_business_ledger)
    monkeypatch.setattr(consumption, "consumption_scope", no_business_ledger)
    return production


def _queued(store: InMemoryAnalysisStore, post_id: str = "DABC1") -> AnalysisRecord:
    record, _ = store.ensure(
        ReelSource(
            network="instagram",
            post_id=post_id,
            post_url=f"https://www.instagram.com/reel/{post_id}/",
            video_url=IG_URL,
        ),
        ANALYSIS_VERSION,
        datetime.now(UTC),
    )
    return record


def test_a_described_analysis_costs_the_shared_row_and_no_business(described) -> None:
    store, bucket, requests = described
    record = _queued(store)

    outcome = rw.production_drain()

    assert len(FakeHaiku.built) == 1 and rw._analysis_worker.describe is FakeHaiku.built[0]
    assert outcome is not None and outcome.outcome == w.OUTCOME_OK
    assert outcome.cost_usd == HAIKU_COST and FakeHaiku.built[0].calls_made == 1
    row = next(r for r in store.rows() if r.id == record.id)
    assert (row.status, row.model_calls, row.cost_usd) == (STATUS_OK, 1, HAIKU_COST)
    assert usage.store().events == []  # nothing in R5's credit ledger either
    assert requests == [IG_URL]  # the CDN only: no vendor


def test_the_fleets_daily_cap_holds_the_model_call_on_the_production_path(
    described, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _bucket, _requests = described
    monkeypatch.setenv(FLEET_DAILY_ENV, "1")
    now = datetime.now(UTC)
    store.put(  # the fleet already made its one call of the last 24 h
        AnalysisRecord(
            id=uuid4(),
            network="instagram",
            post_id="DONE1",
            analysis_version=ANALYSIS_VERSION,
            status=STATUS_OK,
            post_url="https://www.instagram.com/reel/DONE1/",
            created_at=now - timedelta(hours=2),
            model_calls=1,
            finished_at=now - timedelta(hours=1),
        )
    )
    record = _queued(store)

    outcome = rw.production_drain()

    assert outcome is not None and outcome.outcome == w.OUTCOME_FLEET_PAUSED
    assert FakeHaiku.built[0].calls_made == 0  # refused BEFORE the model call
    row = next(r for r in store.rows() if r.id == record.id)
    assert (row.status, row.model_calls, row.cost_usd) == (STATUS_QUEUED, 0, Decimal("0"))
    assert row.source_key is not None  # the download is kept for later
