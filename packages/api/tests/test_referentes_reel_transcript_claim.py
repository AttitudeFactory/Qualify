"""VE-04b guard (m-24921057, migration 0136, founder 2026-11-06) offline: two businesses
transcribing the same shared reel at the same moment never pay ScrapeCreators twice.

`MemoryReelRunStore` mirrors `PostgresReelRunStore` (`test_referentes_reel_runs_db.py`
pins the SQL): a reel's Instagram transcript is claimed before it is paid
(`claim_transcript`, `public_reels.transcript_lock_until`); a fresh claim is not taken
twice, a stale one is, a failed call releases it; a reel claimed by another business is
not paid here and does not count as paid against `reels.MAX_PAID_TRANSCRIPTS` (it keeps
its eligible slot); once written it is read back for free. The raw answer of a paid
transcript is kept once in `vendor_payloads` (house rule), pointed at by the reel.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from qualify_api.creators.repository import params_key
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes import reels
from qualify_api.referentes.reel_store import (
    TRANSCRIPT_VENDOR,
    KeptAnswer,
    MemoryReelRunStore,
)
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import usage

TENANT_A = UUID("a0000000-0000-4000-8000-0000000000c1")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000000c2")
NOW = datetime(2027, 1, 4, 12, 0, tzinfo=UTC)
CLAIM = timedelta(seconds=rr.TRANSCRIPT_CLAIM_SECONDS)


def _seed(store: MemoryReelRunStore, *ids: str, network: str = "instagram") -> None:
    store.upsert_reels(
        TENANT_A,
        [
            rr._public_reel(
                {
                    "id": reel_id,
                    "network": network,
                    "handle": "foodie",
                    "takenAt": NOW.timestamp() - 86400,
                    "views": 1000 - n,
                    "caption": f"reel {reel_id}",
                },
                NOW,
            )
            for n, reel_id in enumerate(ids)
        ],
    )


def _dicts(store: MemoryReelRunStore, *ids: str, network: str = "instagram") -> list[dict]:
    return [
        rr._reel_dict(store.reels[(network, i)], None, f"https://v.tiktokcdn.com/{i}.vtt")
        for i in ids
    ]


def _ctx(tenant: UUID, store: MemoryReelRunStore, **kwargs: Any) -> rr._Context:
    return rr._Context(
        tenant_id=tenant,
        brand_id=uuid4(),
        run_id=uuid4(),
        days=30,
        now=NOW,
        store=store,
        clock=kwargs.pop("clock", NOW.timestamp),
        sleep=lambda s: None,
        claimed_at=NOW,
        **kwargs,
    )


class Fetcher:
    """A fake `TranscribeFn` that counts its calls (each one is a paid transcript)."""

    def __init__(self, *, hold: threading.Event | None = None) -> None:
        self.calls: list[str] = []
        self._lock = threading.Lock()
        self.hold = hold

    def __call__(self, reel: dict[str, Any], client: httpx.Client) -> sc.Transcript:
        with self._lock:
            self.calls.append(reel["id"])
        if self.hold is not None:
            self.hold.wait(timeout=5)
        return sc.Transcript(
            text=f"dicen {reel['id']}",
            segments=(sc.Segment(0.0, 1.0, "dicen"),),
            source=sc.TRANSCRIPT_VENDOR_STT,
        )


# -- the claim itself --------------------------------------------------------------------


def test_a_fresh_claim_is_taken_once_a_stale_one_again_and_a_save_clears_it() -> None:
    store = MemoryReelRunStore()
    _seed(store, "R1")
    mine = NOW + CLAIM
    assert store.claim_transcript(TENANT_A, "instagram", "R1", now=NOW, until=mine)
    # another business, any moment before it lapses: refused
    assert not store.claim_transcript(
        TENANT_B, "instagram", "R1", now=NOW + CLAIM - timedelta(seconds=1), until=mine + CLAIM
    )
    # a stale value never releases the live claim
    store.release_transcript(TENANT_B, "instagram", "R1", lock_until=NOW)
    assert store.transcript_locks[("instagram", "R1")] == mine
    # a crashed worker's claim lapses at its `until`: recoverable
    later = NOW + CLAIM
    assert store.claim_transcript(TENANT_B, "instagram", "R1", now=later, until=later + CLAIM)
    store.save_transcript(
        TENANT_B, "instagram", "R1", text="hola", source=TRANSCRIPT_VENDOR, now=later
    )
    assert ("instagram", "R1") not in store.transcript_locks
    # a transcript is never claimed again, at any time
    far = NOW + timedelta(days=30)
    assert not store.claim_transcript(TENANT_A, "instagram", "R1", now=far, until=far + CLAIM)
    # an unknown reel cannot be claimed (no row to claim, as in Postgres)
    assert not store.claim_transcript(TENANT_A, "instagram", "nope", now=NOW, until=mine)


def test_the_owner_releases_its_own_claim_only() -> None:
    store = MemoryReelRunStore()
    _seed(store, "R1")
    mine = NOW + CLAIM
    assert store.claim_transcript(TENANT_A, "instagram", "R1", now=NOW, until=mine)
    store.release_transcript(TENANT_A, "instagram", "R1", lock_until=mine)
    assert store.claim_transcript(TENANT_B, "instagram", "R1", now=NOW, until=mine)


# -- through the run's transcription step ---------------------------------------------------


def test_two_businesses_at_once_pay_one_transcript_and_the_other_reads_it_later() -> None:
    store = MemoryReelRunStore()
    _seed(store, "R1")
    tried = threading.Event()

    real_claim = store.claim_transcript

    def claim(tenant: UUID, network: str, reel_id: str, **kw: Any) -> bool:
        got = real_claim(tenant, network, reel_id, **kw)
        if not got:
            tried.set()  # the second business met the first one's claim
        return got

    store.claim_transcript = claim  # type: ignore[method-assign]
    fetch = Fetcher(hold=tried)  # the first business holds its call until the other tried
    barrier = threading.Barrier(2)
    paid: dict[UUID, int] = {}
    dicts = {t: _dicts(store, "R1") for t in (TENANT_A, TENANT_B)}

    def go(tenant: UUID) -> None:
        barrier.wait(timeout=5)
        paid[tenant] = rr._transcribe(_ctx(tenant, store), dicts[tenant], fetch)

    threads = [threading.Thread(target=go, args=(t,)) for t in (TENANT_A, TENANT_B)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert fetch.calls == ["R1"]  # ONE paid call for both businesses
    assert sorted(paid.values()) == [0, 1]  # only the claimant counts it as paid
    assert not store.transcript_locks
    # the other business, on its next run, reads the stored transcript for free
    again = _dicts(store, "R1")
    assert again[0]["transcriptKnown"] and again[0]["transcript"] == "dicen R1"
    assert rr._transcribe(_ctx(TENANT_B, store), again, fetch) == 0
    assert fetch.calls == ["R1"]


def test_a_reel_claimed_elsewhere_is_not_paid_and_is_read_back_once_written() -> None:
    store = MemoryReelRunStore()
    _seed(store, "R1", "R2")
    other = NOW + CLAIM
    assert store.claim_transcript(TENANT_B, "instagram", "R1", now=NOW, until=other)

    def fetch(reel: dict[str, Any], client: httpx.Client) -> sc.Transcript:
        # while this business pays R2, the other one finishes R1
        store.save_transcript(
            TENANT_B,
            "instagram",
            "R1",
            text="lo dijo otra",
            source=TRANSCRIPT_VENDOR,
            now=NOW,
            segments=(),
            reader_version=sc.TRANSCRIPT_READER_VERSION,
        )
        time.sleep(0.01)
        return sc.Transcript(text="mio", source=sc.TRANSCRIPT_VENDOR_STT)

    ranked = _dicts(store, "R1", "R2")
    assert rr._transcribe(_ctx(TENANT_A, store), ranked, fetch) == 1  # R2 only
    by_id = {r["id"]: r for r in ranked}
    assert by_id["R1"]["transcriptKnown"] and by_id["R1"]["transcript"] == "lo dijo otra"
    assert by_id["R1"]["transcriptSegments"] == []  # plain dicts, never dataclasses
    assert by_id["R2"]["transcript"] == "mio"


def test_a_reel_claimed_elsewhere_keeps_its_slot_under_the_paid_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reels, "MAX_PAID_TRANSCRIPTS", 2)
    store = MemoryReelRunStore()
    _seed(store, "R1", "R2", "R3")
    assert store.claim_transcript(TENANT_B, "instagram", "R1", now=NOW, until=NOW + CLAIM)
    fetch = Fetcher()
    paid = rr._transcribe(_ctx(TENANT_A, store), _dicts(store, "R1", "R2", "R3"), fetch)
    # R1 is someone else's (not paid, not counted), R3 is past the two eligible ones
    assert fetch.calls == ["R2"] and paid == 1


@pytest.mark.parametrize(
    "failure",
    [
        sc.ScrapeCreatorsError("HTTP 500"),
        httpx.ConnectError("down"),
        sc.ScrapeCreatorsBlocked("cap", reason=usage.REASON_NO_TENANT),
        RuntimeError("unexpected"),
    ],
)
def test_a_failed_call_releases_the_claim(failure: Exception) -> None:
    store = MemoryReelRunStore()
    _seed(store, "R1")

    def fetch(reel: dict[str, Any], client: httpx.Client) -> sc.Transcript:
        raise failure

    ctx = _ctx(TENANT_A, store)
    if isinstance(failure, RuntimeError):
        with pytest.raises(RuntimeError):
            rr._transcribe(ctx, _dicts(store, "R1"), fetch)
    else:
        assert rr._transcribe(ctx, _dicts(store, "R1"), fetch) == 0
    assert not store.transcript_locks  # free again: a later run retries at once
    assert store.reels[("instagram", "R1")].transcript_at is None
    assert store.claim_transcript(TENANT_B, "instagram", "R1", now=NOW, until=NOW + CLAIM)


def test_tiktok_subtitles_are_free_and_never_claimed() -> None:
    store = MemoryReelRunStore()
    _seed(store, "T1", network="tiktok")
    seen: list[dict[Any, Any]] = []

    def fetch(reel: dict[str, Any], client: httpx.Client) -> sc.Transcript:
        seen.append(dict(store.transcript_locks))
        return sc.Transcript(text="papas", source=sc.TRANSCRIPT_TIKTOK_VTT)

    rr._transcribe(_ctx(TENANT_A, store), _dicts(store, "T1", network="tiktok"), fetch)
    assert seen == [{}]
    assert store.reels[("tiktok", "T1")].transcript == "papas"
    assert store.reels[("tiktok", "T1")].transcript_payload_id is None and not store.payloads


# -- the raw answer is kept, once -----------------------------------------------------------


def _answer(reel_id: str, *, cached: bool = False) -> dict[str, Any]:
    return {
        "success": True,
        "credits_charged": 0 if cached else 1,
        "cached": cached,
        "transcripts": [
            {
                "text": f"hola {reel_id}",
                "transcript_with_timestamp": [{"start": 0.5, "end": 1.5, "text": "hola"}],
            }
        ],
    }


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The vendor's side of the real gate (`sc._vendor_request`), counting requests."""
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_ve04b")
    calls: list[str] = []

    def answer(client: httpx.Client, path: str, params: dict[str, str]) -> httpx.Response:
        calls.append(params["url"])
        reel_id = params["url"].rstrip("/").rsplit("/", 1)[-1]
        return httpx.Response(
            200,
            json=_answer(reel_id, cached=reel_id.startswith("C")),
            request=httpx.Request("GET", f"https://api.scrapecreators.com{path}"),
        )

    monkeypatch.setattr(sc, "_vendor_request", answer)
    return calls


def test_a_paid_transcript_keeps_its_raw_answer_once(wire: list[str]) -> None:
    store = MemoryReelRunStore()
    _seed(store, "R1", "C2")  # C2: the vendor answers from its own cache, for free
    ctx = _ctx(TENANT_A, store, charge=usage.UsageCharge(TENANT_A, None))
    assert rr._transcribe(ctx, _dicts(store, "R1", "C2"), reels.transcribe_one) == 2
    assert sorted(wire) == [
        "https://www.instagram.com/reel/C2/",
        "https://www.instagram.com/reel/R1/",
    ]
    assert len(store.payloads) == 2  # one raw answer per transcript, the cached one too
    for reel_id, credits in (("R1", 1), ("C2", 0)):
        url = f"https://www.instagram.com/reel/{reel_id}/"
        key = (sc.TRANSCRIPT_PATH, params_key({"url": url, "cache_max_age": "30"}))
        payload_id, fetched_at, body, kept_credits = store.payloads[key]
        reel = store.reels[("instagram", reel_id)]
        assert body == _answer(reel_id, cached=reel_id == "C2") and kept_credits == credits
        assert (reel.transcript_payload_id, reel.transcript_payload_fetched_at) == (
            payload_id,
            fetched_at,
        )
    # a second run pays nothing and keeps no second copy
    assert rr._transcribe(ctx, _dicts(store, "R1", "C2"), reels.transcribe_one) == 0
    assert len(wire) == 2 and len(store.payloads) == 2
    # a late duplicate save keeps nothing and never moves the stored pointer
    before = store.reels[("instagram", "R1")]
    store.save_transcript(
        TENANT_A,
        "instagram",
        "R1",
        text="otra",
        source=TRANSCRIPT_VENDOR,
        now=NOW + timedelta(hours=1),
        raw=KeptAnswer(sc.TRANSCRIPT_PATH, {"url": "x"}, {"success": True}, 1),
    )
    assert store.reels[("instagram", "R1")] == before and len(store.payloads) == 2


# -- database trouble around the claim --------------------------------------------------


def test_a_paid_answer_whose_save_fails_keeps_its_claim_until_it_lapses() -> None:
    class SaveDown(MemoryReelRunStore):
        def save_transcript(self, *args: Any, **kwargs: Any) -> None:
            raise OperationalError("UPDATE public_reels", {}, Exception("db down"))

    store = SaveDown()
    _seed(store, "R1")
    fetch = Fetcher()
    with pytest.raises(OperationalError):
        rr._transcribe(_ctx(TENANT_A, store), _dicts(store, "R1"), fetch)
    assert fetch.calls == ["R1"]  # paid once
    # not released: no retry pays it again at once...
    assert store.transcript_locks[("instagram", "R1")] == NOW + CLAIM
    assert not store.claim_transcript(TENANT_B, "instagram", "R1", now=NOW, until=NOW + CLAIM)
    # ...but it lapses by itself
    later = NOW + CLAIM
    assert store.claim_transcript(TENANT_B, "instagram", "R1", now=later, until=later + CLAIM)


def test_a_claim_the_database_cannot_take_skips_that_reel_only() -> None:
    class ClaimDown(MemoryReelRunStore):
        def claim_transcript(self, tenant_id: UUID, network: str, reel_id: str, **kw: Any) -> bool:
            if reel_id == "R1":
                raise OperationalError("UPDATE public_reels", {}, Exception("db down"))
            return super().claim_transcript(tenant_id, network, reel_id, **kw)

    store = ClaimDown()
    _seed(store, "R1", "R2")
    fetch = Fetcher()
    ranked = _dicts(store, "R1", "R2")
    assert rr._transcribe(_ctx(TENANT_A, store), ranked, fetch) == 1
    assert fetch.calls == ["R2"]  # never paid without its claim
    by_id = {r["id"]: r for r in ranked}
    assert not by_id["R1"]["transcriptKnown"] and by_id["R2"]["transcriptKnown"]
    assert store.reels[("instagram", "R1")].transcript_at is None
