"""The shared analysis queue as the `reels-worker` drains it in production (ADR 42 R8,
m-24854855, over ADR 44 VE-04a): `reel_worker.production_drain` builds VE-04a's
`default_worker()` — whose describe step stays `DEFAULT_DESCRIBE` (None until VE-04c) —
and runs `drain_once`. Proven offline: the row is downloaded from the CDN and stored in
R2, and NOTHING else is called — no model, no ScrapeCreators. Every `httpx.Client` of the
process is replaced by a recorder, so a request to any host (the vendor's API, the
model's) would show up; Postgres and R2 are VE-04a's in-memory doubles; the reel is a
synthetic MP4 made with PyAV."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from typing import IO, Any

import httpx
import pytest

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from qualify_shared.objects.gate import StoredObject  # noqa: E402
from qualify_shared.objects.public import reel_source_key  # noqa: E402

from qualify_api.referentes import reel_analysis_worker as w  # noqa: E402
from qualify_api.referentes import reel_worker as rw  # noqa: E402
from qualify_api.referentes import worker as cli  # noqa: E402
from qualify_api.referentes.reel_analysis_store import InMemoryAnalysisStore  # noqa: E402
from qualify_api.referentes.reel_analysis_types import (  # noqa: E402
    ANALYSIS_VERSION,
    STATUS_QUEUED,
    ReelSource,
)
from qualify_api.vendors import scrapecreators  # noqa: E402

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
