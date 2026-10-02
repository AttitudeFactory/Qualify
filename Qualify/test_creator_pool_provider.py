"""The shared creator pool from the wizard's side (2026-10-01, "primero busca en la db,
luego al scraper"): the vendor layer asks the pool before the network and feeds it after,
and a run's whole pool of accounts — with which search surfaced each — is recorded."""

from __future__ import annotations

from uuid import UUID

import httpx
import pytest
from qualify_api.creators import MemoryCreatorPoolRepository

from . import creator_discovery as cd
from . import creator_pool_provider as pool

TENANT = UUID("a0000000-0000-4000-8000-0000000000d3")


def _client(handler, cache) -> httpx.Client:
    return cd.PoolClient(cache, transport=httpx.MockTransport(handler))


def test_the_vendor_layer_asks_the_pool_first_and_feeds_it_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "test")
    repo = MemoryCreatorPoolRepository()
    cache = pool.PayloadCache(repo)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/profile"):
            return httpx.Response(404, json={"success": False, "error": "not_found"})
        return httpx.Response(200, json={"success": True, "credits_charged": 1, "n": len(calls)})

    with _client(handler, cache) as client:
        first = cd._get_retry(client, "/v1/tiktok/search/keyword", {"query": "foodie"})
        again = cd._get_retry(client, "/v1/tiktok/search/keyword", {"query": "foodie"})
        assert first == {"success": True, "credits_charged": 1, "n": 1}
        # the same answer, served from the pool: nothing charged this time
        assert again == {"success": True, "credits_charged": 0, "n": 1}
        assert calls == ["/v1/tiktok/search/keyword"]  # the second answer came from the pool
        assert (cache.hits, cache.misses) == (1, 1)
        # a 404 is remembered too, and comes back as the same 404
        for _ in range(2):
            try:
                cd._get_retry(client, "/v1/tiktok/profile", {"handle": "ghost"})
            except cd.ScrapeCreatorsError as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError("expected a 404")
        assert calls.count("/v1/tiktok/profile") == 1
    stored = repo.get_payload("/v1/tiktok/search/keyword", {"query": "foodie"})
    assert stored is not None and stored.status == 200

    # the same query by ANOTHER run (another tenant): zero network
    other = pool.PayloadCache(repo)
    with _client(handler, other) as client:
        assert cd._get_retry(client, "/v1/tiktok/search/keyword", {"query": "foodie"})["n"] == 1
    assert len(calls) == 2 and other.hits == 1


def test_a_run_s_pool_is_recorded_with_who_surfaced_each_account() -> None:
    repo = MemoryCreatorPoolRepository()
    seed = cd.DiscoverySeed("mi.marca", ("food_drink",), country_code="CO", city="Cúcuta")
    read = cd.Candidate(
        "instagram",
        "Mouredev",
        bio="Dev  y  streamer",
        external_url="https://moure.dev",
        followers=611_000,
        sources=[
            "instagram:google:programacion",
            "instagram:profile",
            "instagram:related:@midu.dev",
        ],
    )
    feed = cd.Candidate(
        "tiktok", "clip", sources=["tiktok:keyword:programacion", "tiktok:hashtag:#dev"]
    )
    feed.absorb_post(likes=10, comments=1, views=1_000, text="x", ai_generated=True)
    skipped = cd.Candidate("tiktok", " ")
    assert pool.record_pool(TENANT, [read, feed, skipped], seed, repository=repo, now=1_000.0) == (
        2,
        4,
    )

    kept = repo.creator("instagram", "mouredev")
    assert kept is not None
    assert (kept.bio, kept.external_url, kept.followers) == (
        "Dev y streamer",
        "https://moure.dev",
        611_000,
    )
    assert kept.read_at is not None  # a profile read backed it
    clip = repo.creator("tiktok", "clip")
    assert clip is not None and clip.read_at is None
    assert (clip.posts_seen, clip.ai_posts_seen, clip.views_seen) == (1, 1, 1_000)

    seen = sorted((s.kind, s.term, s.country_code, s.city_slug) for s in repo.sightings.values())
    assert (
        seen
        == [
            ("google", "programacion", "CO", "cucuta"),
            ("hashtag", "dev", "CO", "cucuta"),
            ("keyword", "programacion", "CO", "cucuta"),
            ("related", "midu.dev", "CO", "cucuta"),
        ]
        or len(seen) == 4
    )
    assert [c.handle for c in repo.seen_for("keyword", "programacion")] == ["clip"]
    assert [c.handle for c in repo.seen_for("google", "programacion")] == ["mouredev"]


def test_without_a_tenant_there_is_no_cache() -> None:
    assert pool.payload_cache(None) is None
    assert isinstance(pool.payload_cache(TENANT), pool.PayloadCache)
