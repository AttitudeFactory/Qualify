"""VE-04b (m-24921057, ADR 44) through the persistent run: the transcript the listing
already pays for is kept WITH its timings, end to end — the REAL `reels.transcribe_one`
and the REAL gate (`sc.metered_get`) over a fake wire (`sc._vendor_request`, as in
`test_reels_worker_r5_charges.py`), the run's memory store, a scripted Claude, and a
recorder for the consumption ledger. TikTok's subtitles come from a fixture (the CDN read
is replaced, never reached).

Per the ticket's acceptance criteria:
1. a run makes the same vendor calls as with the untimed reader of before, and stores
   the same text;
2. the stretches (start, end) are stored on `public_reels` with their reader version and
   reach the analysis's `ReelSource.transcript_segments` with no new call (ADR 42 R14);
3. a stretch of music heard as "ah" is stored as given;
4. every paid transcript leaves ONE consumption-ledger row, keyed by the gate's request
   key; a second run pays nothing and writes no row.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api.claude_tools import CallStats
from qualify_api.referentes import (
    MemoryReferentesRepository,
    NewDiscoveredAccount,
    NewDiscoveryPhase,
    reels,
    reels_ai,
)
from qualify_api.referentes import ai as review_ai
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes.reel_analysis_types import TranscriptSegment
from qualify_api.referentes.reel_store import (
    STATUS_OK,
    MemoryReelRunStore,
    segments_from_json,
    segments_to_json,
)
from qualify_api.referentes.reels_ai import ReelReview, ReelToReview
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import usage

NOW = 1_800_000_000.0
DAY = 24 * 3600
BRIEF = review_ai.BrandBrief(handle="burgerco", rubro=("hamburguesería",))
TENANT = UUID("a0000000-0000-4000-8000-0000000000a1")


def _reel(network: str, handle: str, reel_id: str, days_ago: float, caption: str) -> dict:
    return {
        "id": reel_id,
        "network": network,
        "handle": handle,
        "url": f"https://www.instagram.com/reel/{reel_id}/",
        "caption": caption,
        "cover": "",
        "takenAt": NOW - days_ago * DAY,
        "views": 9_000,
        "likes": 900,
        "comments": 1,
        "shares": None,
        "saves": None,
        "seconds": 12,
        "sound": "Audio original",
        "video": f"https://scontent.cdninstagram.com/{reel_id}.mp4",
        **({"captionUrl": f"https://v.tiktokcdn.com/{reel_id}.vtt"} if network == "tiktok" else {}),
    }


FEEDS: dict[str, list[dict[str, Any]]] = {
    "foodie": [
        _reel("instagram", "foodie", "F1", 2, "la smash burger del centro"),
        _reel("instagram", "foodie", "F2", 3, "probando hamburguesas"),
    ],
    "vecino": [_reel("tiktok", "vecino", "V1", 1, "papas y burger")],
}


#: The vendor's transcript answer, in the live shape (2026-11-06, see
#: `test_referentes_scrapecreators_client.py`): text plus nested timed stretches; a sung
#: bit heard as "ah" included.
def _transcript_answer(reel_id: str) -> dict[str, Any]:
    return {
        "success": True,
        "credits_remaining": 5000,
        "credits_charged": 1,
        "transcripts": [
            {
                "id": "1",
                "shortcode": reel_id,
                "text": f"  hola  {reel_id} ah ",
                "transcript_with_timestamp": [
                    {"start": 0.42, "end": 2.9, "text": f"hola {reel_id}"},
                    {"start": 10.749, "end": 12.829, "text": "ah"},
                ],
            }
        ],
        "cached": False,
    }


VTT = (
    "WEBVTT\n\n"
    "00:00:00.500 --> 00:00:01.500\npapas\n\n"
    "00:00:01.500 --> 00:00:03.000\ny burger\n\n"
    "00:00:03.000 --> 00:00:04.000\nah\n"
)


class Wire:
    """The vendor's side of `sc._vendor_request`: answers each transcript request with
    `_transcript_answer`, records every request."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def __call__(self, client: httpx.Client, path: str, params: dict[str, str]) -> httpx.Response:
        url = params.get("url", "")
        with self._lock:
            self.requests.append((path, url))
        reel_id = url.rstrip("/").rsplit("/", 1)[-1]
        return httpx.Response(
            200,
            json=_transcript_answer(reel_id),
            request=httpx.Request("GET", f"https://api.scrapecreators.com{path}"),
        )


@dataclass
class Vendor:
    """List reads (scripted, free here) and the TikTok CDN read, counted."""

    lists: list[str] = field(default_factory=list)
    cdn: list[str] = field(default_factory=list)

    def fetch(
        self, network: str, handle: str, *, since: float, client: Any, max_pages: int
    ) -> list[dict[str, Any]]:
        self.lists.append(handle)
        return [dict(r) for r in FEEDS[handle]]

    def captions_timed(self, url: str, *, client: Any = None) -> sc.Transcript:
        self.cdn.append(url)
        return sc.Transcript(
            text=sc.vtt_text(VTT), segments=sc.vtt_cues(VTT), source=sc.TRANSCRIPT_TIKTOK_VTT
        )

    def captions(self, url: str, *, client: Any = None) -> str:
        return self.captions_timed(url, client=client).text


@dataclass
class Claude:
    def review(self, brief: Any, batch: list[ReelToReview], **_: Any) -> tuple[list, CallStats]:
        answers = [
            ReelReview(
                id=r.id,
                fits=True,
                reason="ok",
                format="receta",
                hook="pregunta",
                affinity="producto",
            )
            for r in batch
        ]
        return answers, CallStats(reels_ai.REVIEW_MODEL, None, 1000, 100)


class Clock:
    def __init__(self) -> None:
        self.moment = NOW

    def __call__(self) -> float:
        return self.moment


def _brand(repo: MemoryReferentesRepository) -> UUID:
    brand = uuid4()
    repo.add_brand(tenant_id=TENANT, brand_id=brand)
    repo.save_phase(
        NewDiscoveryPhase(
            tenant_id=TENANT,
            brand_id=brand,
            phase_key="sector",
            algorithm_version=1,
            seed_signature="s",
            seed={"handle": "burgerco", "terms": ["hamburguesería"], "hashtags": []},
            title="Sector",
            accounts=(
                NewDiscoveredAccount(
                    network="instagram", handle="foodie", card={"kind": "creador"}
                ),
                NewDiscoveredAccount(network="tiktok", handle="vecino", card={"kind": "marca"}),
            ),
        )
    )
    for network, handle in (("instagram", "foodie"), ("tiktok", "vecino")):
        repo.set_label(
            tenant_id=TENANT,
            brand_id=brand,
            network=network,
            handle=handle,
            label="referente",
            labeled_by=None,
        )
    return brand


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_ve04b")
    fake = Wire()
    monkeypatch.setattr(sc, "_vendor_request", fake)
    return fake


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> Vendor:
    fake = Vendor()
    monkeypatch.setattr(sc, "fetch_tiktok_captions_timed", fake.captions_timed)
    monkeypatch.setattr(sc, "fetch_tiktok_captions", fake.captions)
    return fake


@pytest.fixture
def ledger() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    lock = threading.Lock()

    def record(**row: Any) -> None:
        with lock:
            rows.append(row)

    sc.configure_consumption_ledger(record)  # the conftest puts the no-op back after
    return rows


@pytest.fixture
def booked() -> usage.InMemoryUsageStore:
    active = usage.InMemoryUsageStore()
    usage.configure_store(active)  # the conftest puts the default back after the test
    return active


def _untimed_transcribe(reel: dict[str, Any], client: httpx.Client) -> str:
    """`reels.transcribe_one` as it was before VE-04b: the untimed readers."""
    if reel["network"] == "instagram":
        return sc.fetch_instagram_transcript(str(reel["url"]), client=client)
    if reel["network"] == "tiktok" and reel.get("captionUrl"):
        return sc.fetch_tiktok_captions(str(reel["captionUrl"]), client=client)
    return ""


def _run(
    store: MemoryReelRunStore,
    repo: MemoryReferentesRepository,
    brand: UUID,
    vendor: Vendor,
    clock: Clock,
    *,
    trigger: str = "weekly",
    **kwargs: Any,
) -> rr.RunOutcome:
    queued = rr.enqueue_run(TENANT, brand, trigger, store=store, clock=clock)
    return rr.run(
        TENANT,
        queued.id,
        store=store,
        repository=repo,
        fetch=vendor.fetch,
        review=Claude().review,
        clock=clock,
        brief=lambda t, b: BRIEF,
        api_key="k",
        sleep=lambda seconds: None,
        **kwargs,
    )


def _transcript_calls(wire: Wire) -> list[tuple[str, str]]:
    return [r for r in wire.requests if r[0] == "/v2/instagram/media/transcript"]


# --------------------------------------------------------------------------------------
# criterion 1 — the same vendor calls and the same text as the untimed reader of before
# --------------------------------------------------------------------------------------


def test_a_run_makes_the_same_calls_and_stores_the_same_text_as_before(
    wire: Wire, vendor: Vendor, ledger: list[dict[str, Any]], booked: usage.InMemoryUsageStore
) -> None:
    before_store, before_repo = MemoryReelRunStore(), MemoryReferentesRepository()
    before = _run(
        before_store,
        before_repo,
        _brand(before_repo),
        vendor,
        Clock(),
        transcribe_fetch=_untimed_transcribe,
    )
    calls_before, cdn_before = sorted(_transcript_calls(wire)), sorted(vendor.cdn)
    wire.requests.clear()
    vendor.cdn.clear()

    store, repo = MemoryReelRunStore(), MemoryReferentesRepository()
    after = _run(store, repo, _brand(repo), vendor, Clock())  # the default: transcribe_one
    assert before.status == after.status == STATUS_OK
    assert sorted(_transcript_calls(wire)) == calls_before and len(calls_before) == 2
    assert sorted(vendor.cdn) == cdn_before and len(cdn_before) == 1
    assert after.transcripts_paid == before.transcripts_paid == 2
    texts = {k: r.transcript for k, r in store.reels.items()}
    assert texts == {k: r.transcript for k, r in before_store.reels.items()}
    assert texts[("instagram", "F1")] == "hola F1 ah"  # whitespace collapsed, as before
    # the untimed reader of before claims no timings: NULL, not []
    assert before_store.reels[("instagram", "F1")].transcript_segments is None


# --------------------------------------------------------------------------------------
# criteria 2 + 3 — stored with start/end and reader version, "ah" as given, into the
# analysis without a new call
# --------------------------------------------------------------------------------------


def test_the_timed_stretches_are_stored_and_reach_the_analysis(
    wire: Wire, vendor: Vendor, ledger: list[dict[str, Any]], booked: usage.InMemoryUsageStore
) -> None:
    store, repo = MemoryReelRunStore(), MemoryReferentesRepository()
    brand = _brand(repo)
    got: list[list[Any]] = []

    def analyze(tenant: UUID, brand_id: UUID, run_id: UUID, sources: Any) -> Decimal:
        calls = len(wire.requests)
        got.append(list(sources))
        assert len(wire.requests) == calls  # the analysis' input made no vendor call
        return Decimal("0")

    outcome = _run(store, repo, brand, vendor, Clock(), analyze=analyze)
    assert outcome.status == STATUS_OK
    f1 = store.reels[("instagram", "F1")]
    assert f1.transcript_segments == (
        TranscriptSegment(0.42, 2.9, "hola F1"),
        TranscriptSegment(10.749, 12.829, "ah"),  # music heard as "ah": stored as given
    )
    assert store.reader_versions[("instagram", "F1")] == sc.TRANSCRIPT_READER_VERSION
    v1 = store.reels[("tiktok", "V1")]
    assert [(s.start_s, s.end_s, s.text) for s in v1.transcript_segments or ()] == [
        (0.5, 1.5, "papas"),
        (1.5, 3.0, "y burger"),
        (3.0, 4.0, "ah"),
    ]  # a VTT of three cues: three stretches
    by_id = {s.post_id: s for s in got[0]}
    assert by_id["F1"].transcript_segments == f1.transcript_segments
    assert by_id["V1"].transcript_segments == v1.transcript_segments
    assert by_id["F1"].transcript == "hola F1 ah"


# --------------------------------------------------------------------------------------
# criterion 4 — one consumption row per paid transcript, never two, never paid twice
# --------------------------------------------------------------------------------------


def test_each_paid_transcript_leaves_one_ledger_row_and_a_rerun_none(
    wire: Wire, vendor: Vendor, ledger: list[dict[str, Any]], booked: usage.InMemoryUsageStore
) -> None:
    store, repo = MemoryReelRunStore(), MemoryReferentesRepository()
    brand = _brand(repo)
    clock = Clock()
    _run(store, repo, brand, vendor, clock)
    paid = _transcript_calls(wire)
    assert len(paid) == 2 and len(ledger) == 2  # one row per paid transcript
    keys = [e.request_key for e in booked.events if e.feature == sc.FEATURE_REELS_TRANSCRIPT]
    assert sorted(r["idempotency_key"] for r in ledger) == sorted(keys)  # reconciles
    assert len({r["idempotency_key"] for r in ledger}) == 2  # never two rows for one call
    for row in ledger:
        assert row["tenant_id"] == TENANT and row["brand_id"] == brand
        assert row["provider"] == "scrapecreators"
        assert row["operation"] == sc.FEATURE_REELS_TRANSCRIPT
        assert row["metadata"] == {"credits": 1, "cached": False}
    # TikTok's subtitles are free: no row for them
    clock.moment += 1
    again = _run(store, repo, brand, vendor, clock, trigger="manual")
    assert again.status == STATUS_OK and again.transcripts_paid == 0
    assert _transcript_calls(wire) == paid and len(ledger) == 2  # stored: not paid again


def test_the_reader_version_is_required_with_the_stretches() -> None:
    """Provenance: no stretches without the version of the reader that parsed them (0117
    `ck_public_reel_transcript_segments`)."""
    store = MemoryReelRunStore()
    with pytest.raises(ValueError):
        store.save_transcript(
            TENANT,
            "instagram",
            "F1",
            text="hola",
            source="vendor_stt",
            now=rr._utc(NOW),
            segments=(TranscriptSegment(0.0, 1.0, "hola"),),
        )


def test_stored_stretches_round_trip_through_json() -> None:
    segments = (TranscriptSegment(0.42, 2.9, "Café ñandú"), TranscriptSegment(10.749, 12.829, "ah"))
    raw = json.loads(segments_to_json(segments))
    assert raw == [
        {"start": 0.42, "end": 2.9, "text": "Café ñandú"},
        {"start": 10.749, "end": 12.829, "text": "ah"},
    ]
    assert segments_from_json(raw) == segments
    assert segments_from_json(None) is None and segments_from_json([]) == ()
    assert segments_from_json([{"start": "x", "end": 1, "text": "?"}, 3]) == ()
    assert reels.as_transcript(sc.Transcript(text="a  b", source="x")).text == "a b"
