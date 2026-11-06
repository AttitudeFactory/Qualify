"""VE-04b guard (m-24921057, migration 0136) against real Postgres: two businesses
transcribing the same shared reel at the same moment pay ScrapeCreators ONCE.

Real threads, two tenants, `PostgresReelRunStore` through `tenant_session`, the REAL gate
(`sc.metered_get`) over a fake wire (`sc._vendor_request`, nothing paid, nothing on the
network) and the REAL consumption ledger. Also: a stale claim is reclaimable, a fresh one
is not, a failed call releases it; the raw answer is kept once in `vendor_payloads`;
`consumption_ledger.idempotency_key` is unique and a repeated key is dropped, never fatal.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from qualify_shared.db.admin import admin_session
from sqlalchemy import text

from qualify_api import consumption
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes import reels
from qualify_api.referentes.reel_store import PostgresReelRunStore
from qualify_api.tenancy.models import Brand, Tenant
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import usage

pytestmark = pytest.mark.db


def _world() -> tuple[UUID, UUID]:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant, name="VE-04b", country="CO", timezone="America/Bogota", currency="COP"
            )
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="VE-04b brand"))
    return tenant, brand


def _reel(store: PostgresReelRunStore, tenant: UUID, reel_id: str) -> dict[str, Any]:
    now = datetime.now(UTC)
    public = rr._public_reel(
        {
            "id": reel_id,
            "network": "instagram",
            "handle": f"h{reel_id.lower()}",
            "takenAt": now.timestamp() - 3600,
            "views": 10,
            "caption": "smash burger",
        },
        now,
    )
    store.upsert_reels(tenant, [public])
    return rr._reel_dict(public, None, "")


def _ctx(tenant: UUID, brand: UUID, store: PostgresReelRunStore) -> rr._Context:
    now = datetime.now(UTC)
    return rr._Context(
        tenant_id=tenant,
        brand_id=brand,
        run_id=uuid4(),
        days=30,
        now=now,
        store=store,
        clock=time.time,
        sleep=lambda s: None,
        claimed_at=now,
        charge=usage.UsageCharge(tenant, brand),
    )


def _row(reel_id: str) -> Any:
    with admin_session() as session:
        return session.execute(
            text(
                "SELECT transcript, transcript_at, transcript_lock_until, "
                "transcript_payload_id, transcript_payload_fetched_at FROM public_reels "
                "WHERE network = 'instagram' AND reel_id = :r"
            ),
            {"r": reel_id},
        ).one()


@pytest.fixture
def two() -> Iterator[tuple[tuple[UUID, UUID], tuple[UUID, UUID]]]:
    yield _world(), _world()


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The vendor: answers a paid transcript after holding the call a moment (so the
    other business's claim lands while this one is in flight), counting requests."""
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_ve04b")
    sc.configure_consumption_ledger(None)  # the real ledger (the conftest restores it)
    calls: list[str] = []
    lock = threading.Lock()

    def answer(client: httpx.Client, path: str, params: dict[str, str]) -> httpx.Response:
        with lock:
            calls.append(params["url"])
        time.sleep(0.5)
        return httpx.Response(
            200,
            json={
                "success": True,
                "credits_charged": 1,
                "cached": False,
                "transcripts": [
                    {
                        "text": "hola",
                        "transcript_with_timestamp": [{"start": 0.4, "end": 1.2, "text": "hola"}],
                    }
                ],
            },
            request=httpx.Request("GET", f"https://api.scrapecreators.com{path}"),
        )

    monkeypatch.setattr(sc, "_vendor_request", answer)
    return calls


def test_two_businesses_transcribing_one_reel_at_once_pay_once(two, wire: list[str]) -> None:
    (ta, ba), (tb, bb) = two
    store = PostgresReelRunStore()
    reel_id = f"G{uuid4().hex[:10]}"
    dicts = {ta: [_reel(store, ta, reel_id)], tb: [_reel(store, tb, reel_id)]}
    barrier = threading.Barrier(2)
    paid: dict[UUID, int] = {}
    errors: list[BaseException] = []

    def go(tenant: UUID, brand: UUID) -> None:
        try:
            barrier.wait(timeout=10)
            paid[tenant] = rr._transcribe(
                _ctx(tenant, brand, store), dicts[tenant], reels.transcribe_one
            )
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=go, args=pair) for pair in ((ta, ba), (tb, bb))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    url = f"https://www.instagram.com/reel/{reel_id}/"
    assert wire == [url]  # ONE vendor call for both businesses
    assert sorted(paid.values()) == [0, 1]
    with admin_session() as session:
        ledger = session.execute(
            text(
                "SELECT tenant_id, idempotency_key FROM consumption_ledger "
                "WHERE tenant_id = ANY(:t) AND operation = 'reels_transcript'"
            ),
            {"t": [ta, tb]},
        ).all()
        payloads = session.execute(
            text(
                "SELECT id, fetched_at, credits_charged, payload FROM vendor_payloads "
                "WHERE vendor = 'scrapecreators' AND path = :p AND params_key LIKE :u"
            ),
            {"p": sc.TRANSCRIPT_PATH, "u": f"%{reel_id}%"},
        ).all()
    assert len(ledger) == 1  # exactly one consumption row, the claimant's
    assert len(payloads) == 1 and payloads[0].credits_charged == 1
    assert payloads[0].payload["transcripts"][0]["text"] == "hola"
    row = _row(reel_id)
    assert row.transcript == "hola" and row.transcript_lock_until is None
    assert (row.transcript_payload_id, row.transcript_payload_fetched_at) == (
        payloads[0].id,
        payloads[0].fetched_at,
    )
    # the business that did not pay reads the stored transcript, for free
    loser = tb if paid[tb] == 0 else ta
    stored = store.stored_transcripts(loser, [("instagram", reel_id)])
    assert stored[("instagram", reel_id)].transcript == "hola"
    again = [rr._reel_dict(stored[("instagram", reel_id)], None, "")]
    assert again[0]["transcriptKnown"]
    assert rr._transcribe(_ctx(loser, uuid4(), store), again, reels.transcribe_one) == 0
    assert wire == [url]


def test_a_stale_claim_is_reclaimable_a_fresh_one_is_not(two) -> None:
    (ta, _), (tb, _) = two
    store = PostgresReelRunStore()
    reel_id = f"S{uuid4().hex[:10]}"
    _reel(store, ta, reel_id)
    now = datetime.now(UTC)
    claim = timedelta(seconds=rr.TRANSCRIPT_CLAIM_SECONDS)
    assert store.claim_transcript(ta, "instagram", reel_id, now=now, until=now + claim)
    # fresh: refused to the other business up to the last second
    almost = now + claim - timedelta(seconds=1)
    assert not store.claim_transcript(tb, "instagram", reel_id, now=almost, until=almost + claim)
    # a stale value never releases the live claim
    store.release_transcript(tb, "instagram", reel_id, lock_until=now)
    assert _row(reel_id).transcript_lock_until is not None
    # stale (the claimant crashed): reclaimable once it lapsed
    lapsed = now + claim
    assert store.claim_transcript(tb, "instagram", reel_id, now=lapsed, until=lapsed + claim)
    store.save_transcript(tb, "instagram", reel_id, text="ya", source="vendor_stt", now=lapsed)
    row = _row(reel_id)
    assert row.transcript == "ya" and row.transcript_lock_until is None
    far = now + timedelta(days=60)
    assert not store.claim_transcript(ta, "instagram", reel_id, now=far, until=far + claim)


def test_a_failed_vendor_call_releases_the_claim(two, monkeypatch: pytest.MonkeyPatch) -> None:
    (ta, ba), (tb, bb) = two
    store = PostgresReelRunStore()
    reel_id = f"F{uuid4().hex[:10]}"
    dicts = [_reel(store, ta, reel_id)]

    def broken(reel: dict[str, Any], client: httpx.Client) -> str:
        assert _row(reel_id).transcript_lock_until is not None  # claimed before the call
        raise sc.ScrapeCreatorsError("Scrape Creators failed with HTTP 500")

    assert rr._transcribe(_ctx(ta, ba, store), dicts, broken) == 0
    row = _row(reel_id)
    assert row.transcript_at is None and row.transcript_lock_until is None
    # retryable at once, by any business
    now = datetime.now(UTC)
    assert store.claim_transcript(tb, "instagram", reel_id, now=now, until=now + timedelta(1))


def test_a_repeated_ledger_key_is_dropped_never_fatal(two) -> None:
    (ta, ba), _ = two
    key = f"reels_transcript:{uuid4()}"
    row = {
        "tenant_id": ta,
        "brand_id": ba,
        "operation": "reels_transcript",
        "provider": consumption.SCRAPECREATORS,
        "model_id": sc.TRANSCRIPT_LEDGER_MODEL,
        "cost_usd": 0.002,
        "idempotency_key": key,
        "metadata": {"credits": 1},
    }
    consumption.record_consumption(**row)
    consumption.record_consumption(**row)  # the same key again: dropped
    # inside a scope: the repeated key is dropped, the rest of the scope is still written
    with consumption.consumption_scope(ta, brand_id=ba, operation="ve04b_scope"):
        consumption.record_consumption(**{**row, "operation": "ve04b_scope"})
        consumption.record_consumption(
            provider=consumption.ANTHROPIC, model_id="claude-haiku", cost_usd=0.001
        )
        consumption.record_consumption(
            provider=consumption.ANTHROPIC, model_id="claude-haiku", cost_usd=0.001
        )
    with admin_session() as session:
        keyed = session.scalar(
            text("SELECT count(*) FROM consumption_ledger WHERE idempotency_key = :k"),
            {"k": key},
        )
        keyless = session.scalar(
            text(
                "SELECT count(*) FROM consumption_ledger WHERE tenant_id = :t "
                "AND operation = 've04b_scope' AND idempotency_key IS NULL"
            ),
            {"t": ta},
        )
    assert keyed == 1 and keyless == 2  # rows without a key never conflict
