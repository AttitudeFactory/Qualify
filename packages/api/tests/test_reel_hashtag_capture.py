"""m-25026377 — a reels read feeds the hashtag catalog with the views and date of every
hashtag in the captions it stored, through `reel_store.capture_reel_hashtags` right after
`upsert_reels`.

What it pins: the real run (`reel_runs.run`, offline harness of
`test_referentes_reel_runs.py`) writes sightings; running again writes no duplicate rows;
a broken catalog never fails or rolls back the run; and nothing on the way reaches the
vendor's metered gate or any HTTP send. The `db` tests prove the same two properties over
`PostgresReelRunStore` + `PostgresHashtagRepository`."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest

from qualify_api.hashtags import MemoryHashtagRepository, PostgresHashtagRepository
from qualify_api.referentes import MemoryReferentesRepository
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes.reel_store import (
    STATUS_OK,
    MemoryReelRunStore,
    PostgresReelRunStore,
    capture_reel_hashtags,
)

from .test_referentes_reel_runs import (
    BRIEF,
    DAY,
    NOW,
    TENANT_A,
    Claude,
    Clock,
    _brand,
    _reel,
)

_FEEDS: dict[str, list[dict[str, Any]]] = {
    "foodie": [
        _reel("instagram", "foodie", "H1", 2, 9_000, "la smash #burgercucuta #smash"),
        _reel("instagram", "foodie", "H2", 5, 4_000, "otra #burgercucuta"),
    ],
    "vecino": [_reel("tiktok", "vecino", "H3", 1, 1_500, "papas #burgercucuta")],
}


@dataclass
class _Vendor:
    lists: list[tuple[str, str]] = field(default_factory=list)

    def fetch(
        self, network: str, handle: str, *, since: float, client: Any, max_pages: int
    ) -> list[dict[str, Any]]:
        self.lists.append((network, handle))
        return [dict(r) for r in _FEEDS[handle]]

    def transcribe(self, reel: dict[str, Any], client: Any) -> str:
        return "dicen algo"


class _BrokenCatalog(MemoryHashtagRepository):
    def record_post_sightings(self, tenant_id: Any, items: Any) -> int:
        raise RuntimeError("catalog down — secret caption #nope")


@pytest.fixture(autouse=True)
def _no_paid_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a paid call was made")

    from qualify_api.vendors import scrapecreators

    monkeypatch.setattr(scrapecreators, "metered_get", _forbidden)
    monkeypatch.setattr(httpx.Client, "send", _forbidden)


def _run(store: MemoryReelRunStore, repo: Any, vendor: _Vendor, clock: Clock, brand: Any):
    queued = rr.enqueue_run(TENANT_A, brand, "weekly", store=store, clock=clock)
    return rr.run(
        TENANT_A,
        queued.id,
        store=store,
        repository=repo,
        brief=lambda t, b: BRIEF,
        api_key="k",
        fetch=vendor.fetch,
        transcribe_fetch=vendor.transcribe,
        review=Claude().review,
        clock=clock,
        sleep=lambda seconds: None,
    )


def test_a_reels_run_stores_sightings_once_even_when_read_again() -> None:
    catalog = MemoryHashtagRepository()
    store = MemoryReelRunStore(hashtag_repository=catalog)
    repo, vendor, clock = MemoryReferentesRepository(), _Vendor(), Clock()
    brand = _brand(repo, TENANT_A)
    now = datetime.fromtimestamp(NOW, UTC)

    assert _run(store, repo, vendor, clock, brand).status == STATUS_OK
    first = catalog.recent_views(TENANT_A, ["burgercucuta", "smash"], now=now)
    assert (first["burgercucuta"].views, first["burgercucuta"].posts) == (14_500, 3)
    assert (first["smash"].views, first["smash"].posts) == (9_000, 1)
    rows = dict(catalog._sightings)

    # a week later the accounts are read again (new run, same reels, newer metrics)
    clock.moment = NOW + 8 * DAY
    reads = len(vendor.lists)
    assert _run(store, repo, vendor, clock, brand).status == STATUS_OK
    assert len(vendor.lists) > reads  # the reels really were stored a second time
    assert catalog._sightings.keys() == rows.keys()  # no duplicate (tag, network, post)
    again = catalog.recent_views(TENANT_A, ["burgercucuta"], now=now)
    assert again["burgercucuta"] == first["burgercucuta"]


def test_a_broken_catalog_never_fails_the_run(caplog: pytest.LogCaptureFixture) -> None:
    store = MemoryReelRunStore(hashtag_repository=_BrokenCatalog())
    repo, vendor, clock = MemoryReferentesRepository(), _Vendor(), Clock()
    brand = _brand(repo, TENANT_A)
    with caplog.at_level(logging.WARNING):
        outcome = _run(store, repo, vendor, clock, brand)
    assert outcome.status == STATUS_OK
    assert {key[1] for key in store.reels} == {"H1", "H2", "H3"}  # the reels are stored
    logged = [r.getMessage() for r in caplog.records if "reel sightings" in r.getMessage()]
    assert logged and all("RuntimeError" in m for m in logged)
    assert not any("secret" in m or "#nope" in m for m in logged)  # type only, no payload


def test_the_memory_store_feeds_nothing_by_default() -> None:
    store = MemoryReelRunStore()
    reel = rr._public_reel(_FEEDS["foodie"][0], datetime.fromtimestamp(NOW, UTC))
    store.upsert_reels(TENANT_A, [reel])  # no catalog configured: no Postgres reached
    assert store.reels


# -- Postgres ------------------------------------------------------------------------------


def _pg_reel(reel_id: str, caption: str, views: int, read_at: datetime) -> Any:
    return rr._public_reel(
        {
            "id": reel_id,
            "network": "tiktok",
            "handle": f"h{reel_id}",
            "takenAt": read_at.timestamp() - 3 * 86_400,
            "views": views,
            "caption": caption,
        },
        read_at,
    )


@pytest.mark.db
def test_postgres_upsert_feeds_the_catalog_once() -> None:
    tenant, tag = uuid4(), f"t{uuid4().hex[:10]}"
    now = datetime.now(UTC)
    store = PostgresReelRunStore()  # default catalog: the Postgres one
    reel_id = f"x{uuid4().hex[:8]}"
    store.upsert_reels(tenant, [_pg_reel(reel_id, f"mira #{tag}", 700, now)])
    store.upsert_reels(tenant, [_pg_reel(reel_id, f"mira #{tag}", 900, now + timedelta(hours=1))])
    recent = PostgresHashtagRepository().recent_views(tenant, [tag], now=now)
    assert (recent[tag].views, recent[tag].posts) == (900, 1)


@pytest.mark.db
def test_postgres_reels_survive_a_broken_catalog() -> None:
    tenant, now = uuid4(), datetime.now(UTC)
    store = PostgresReelRunStore()
    store.hashtag_repository = _BrokenCatalog()
    reel = _pg_reel(f"y{uuid4().hex[:8]}", "con #etiqueta", 5, now)
    store.upsert_reels(tenant, [reel])
    (got,) = store.reels_of(tenant, [("tiktok", reel.handle)], since=now - timedelta(days=30))
    assert got.reel_id == reel.reel_id and got.views == 5


def test_capture_reel_hashtags_with_nothing_does_nothing() -> None:
    assert capture_reel_hashtags(TENANT_A, [], MemoryHashtagRepository()) == 0
