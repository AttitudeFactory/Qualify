"""«Replicar con mi marca» for an idea (founder, 2026-11-04): `view()` says which ideas
can be replicated (`Idea.can_replicate`), and `reel_reference.prepare_idea_reference`
uses the source the shared analysis stored in R2 (ADR 44 VE-04a) — else the reel's CDN
video while its link is fresh (VE-04a's `url_is_stale`: under 20 h, not past the expiry
the CDN signed) — looked up on the server by `(network, reel_id)`, never a URL from the
client. An unreadable stored source is logged without its URL (N3). Offline: an in-memory
R2 behind the real `PublicObjectGate`, a synthetic MP4."""

from __future__ import annotations

import io
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from qualify_shared.objects.gate import ObjectNotFound, StoredObject
from qualify_shared.objects.public import PublicObjectGate, reel_source_key

from qualify_api.referentes import reel_reference as ref
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes.reel_store import (
    STATUS_OK,
    MemoryReelRunStore,
    NewIdea,
    PublicReel,
)

NOW = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
TENANT = uuid4()


class DictStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.opened: list[str] = []

    def put(self, key: str, fileobj: Any, content_type: str) -> None:
        self.objects[key] = fileobj.read()

    def open(self, key: str) -> io.BytesIO:
        self.opened.append(key)
        if key not in self.objects:
            raise ObjectNotFound(key)
        return io.BytesIO(self.objects[key])

    def list_prefix(self, prefix: str) -> Iterator[StoredObject]:
        yield from ()

    def delete_keys(self, keys: Sequence[str]) -> None:
        return None


def _mp4(seconds: float = 6.0, size: tuple[int, int] = (360, 640), fps: int = 30) -> bytes:
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    out = io.BytesIO()
    with av.open(out, "w", format="mp4") as sink:
        stream = sink.add_stream("libx264", rate=fps)
        stream.width, stream.height = size
        stream.pix_fmt = "yuv420p"
        for i in range(int(seconds * fps)):
            pixels = np.full((size[1], size[0], 3), (5 * i) % 255, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = i, Fraction(1, fps)
            for packet in stream.encode(frame):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    return out.getvalue()


# --------------------------------------------------------------------------------------
# prepare_idea_reference
# --------------------------------------------------------------------------------------


@pytest.fixture
def r2(monkeypatch: pytest.MonkeyPatch) -> DictStore:
    store = DictStore()
    monkeypatch.setattr(ref, "_public_gate", lambda: PublicObjectGate(store))
    return store


def test_the_stored_copy_is_used_first(r2: DictStore, monkeypatch: pytest.MonkeyPatch) -> None:
    key = reel_source_key("instagram", "C1", uuid4())
    r2.objects[key] = _mp4()
    monkeypatch.setattr(ref, "_idea_video", lambda n, r: (key, "https://cdn.fbcdn.net/x.mp4"))
    monkeypatch.setattr(ref, "prepare_reference", lambda *a, **k: pytest.fail("no CDN read"))
    fitted = ref.prepare_idea_reference("instagram", "C1")
    assert r2.opened == [key]
    assert 4 <= fitted.duration_sec <= ref.REFERENCE_SECONDS + 0.1  # its first 5 s


def test_without_a_copy_the_fresh_cdn_link_is_used(
    r2: DictStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(ref, "_idea_video", lambda n, r: (None, "https://cdn.fbcdn.net/x.mp4"))
    monkeypatch.setattr(ref, "prepare_reference", lambda n, url: calls.append((n, url)) or "ok")
    assert ref.prepare_idea_reference("instagram", "C1") == "ok"
    assert calls == [("instagram", "https://cdn.fbcdn.net/x.mp4")]


def test_a_copy_missing_from_r2_falls_back_to_the_link_and_is_logged_without_urls(
    r2: DictStore, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    key = reel_source_key("instagram", "C1", uuid4())  # recorded, but gone from R2
    link = "https://cdn.fbcdn.net/x.mp4?oh=secret&oe=6A000000"
    monkeypatch.setattr(ref, "_idea_video", lambda n, r: (key, link))
    monkeypatch.setattr(ref, "prepare_reference", lambda n, url: "from the link")
    with caplog.at_level("WARNING", logger=ref.logger.name):
        assert ref.prepare_idea_reference("instagram", "C1") == "from the link"
    [record] = [r for r in caplog.records if r.name == ref.logger.name]
    text = record.getMessage()
    assert "network=instagram reel_id=C1" in text and "ObjectNotFound" in text
    assert "https://" not in text and "secret" not in text and key not in text


def test_neither_ends_in_one_plain_sentence(r2: DictStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ref, "_idea_video", lambda n, r: (None, None))
    with pytest.raises(ref.ReelReferenceUnavailable) as exc:
        ref.prepare_idea_reference("instagram", "C1")
    assert str(exc.value) == ref.IDEA_VIDEO_GONE
    assert "Actualiza" not in str(exc.value)


def test_a_dead_cdn_link_no_longer_asks_to_refresh() -> None:
    url = "https://scontent.cdninstagram.com/reel.mp4"
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(410))) as client:
        with pytest.raises(ref.ReelReferenceUnavailable) as exc:
            ref.prepare_reference("instagram", url, client=client)
    assert "Actualiza" not in str(exc.value)


# --------------------------------------------------------------------------------------
# view(): can_replicate
# --------------------------------------------------------------------------------------


def _ok_run_with_ideas(store: MemoryReelRunStore, reels: list[PublicReel]) -> Any:
    brand = uuid4()
    run = rr.enqueue_run(TENANT, brand, "manual", store=store, clock=NOW.timestamp)
    claimed = store.claim(TENANT, run.id, now=NOW)
    assert claimed is not None
    store.upsert_reels(TENANT, reels)
    ideas = [NewIdea(r.network, r.reel_id, n, 7, None) for n, r in enumerate(reels, 1)]
    assert store.save_ideas(TENANT, brand, run.id, ideas, started_at=NOW)
    assert store.finish(
        TENANT,
        run.id,
        status=STATUS_OK,
        now=NOW,
        credits=0,
        cost_usd=Decimal("0"),
        brief_hash=None,
        started_at=NOW,
    )
    return brand


def _reel(reel_id: str, *, read: timedelta | None, oe: datetime | None = None) -> PublicReel:
    url = f"https://scontent.cdninstagram.com/{reel_id}.mp4"
    if oe is not None:
        url += f"?oe={int(oe.timestamp()):X}"
    return PublicReel(
        network="instagram",
        reel_id=reel_id,
        handle="foodie",
        taken_at=NOW - timedelta(days=2),
        metrics_at=NOW - (read or timedelta(0)),
        parser_version=1,
        video_url=url if read else None,
        video_url_at=NOW - read if read else None,
    )


def test_view_says_which_ideas_can_be_replicated(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemoryReelRunStore()
    brand = _ok_run_with_ideas(
        store,
        [
            _reel("kept", read=timedelta(hours=40)),  # old link, but the run kept a copy
            _reel("fresh", read=timedelta(hours=2)),  # no copy, link read 2 h ago
            _reel("old", read=timedelta(hours=21)),  # no copy, link too old
            _reel("none", read=None),  # never had a link
            # read 2 h ago, but the CDN signed an expiry already past (`oe`, hex epoch)
            _reel("signed", read=timedelta(hours=2), oe=NOW - timedelta(minutes=1)),
        ],
    )
    store.stored_sources.add(("instagram", "kept"))
    monkeypatch.setattr(rr, "time", SimpleNamespace(time=NOW.timestamp))
    shown = rr.view(TENANT, brand, store=store)
    flags = {i.reel.reel_id: (i.source_available, i.can_replicate) for i in shown.ideas}
    assert flags == {
        "kept": (True, True),
        "fresh": (False, True),
        "old": (False, False),
        "none": (False, False),
        "signed": (False, False),
    }
