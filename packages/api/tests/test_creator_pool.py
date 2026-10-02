"""The shared creator pool (migration 0036): the vendor's answers with a time to live,
every account seen and which search saw it — global, so one tenant's search serves the
next. Memory twin offline; Postgres `db`-marked."""

from __future__ import annotations

import time
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session

from qualify_api.creators import (
    PROFILE_TTL,
    SEARCH_TTL,
    CreatorFacts,
    MemoryCreatorPoolRepository,
    PostgresCreatorPoolRepository,
    Sighting,
    params_key,
)
from qualify_api.tenancy.models import Tenant

TENANT = UUID("a0000000-0000-4000-8000-0000000000e5")
OTHER = UUID("a0000000-0000-4000-8000-0000000000e6")


def test_payloads_live_their_endpoints_ttl_whatever_the_params_order() -> None:
    repo = MemoryCreatorPoolRepository()
    now = time.time()
    repo.put_payload(
        "/v1/tiktok/search/keyword", {"query": "foodie", "cursor": "30"}, {"n": 1}, now=now
    )
    repo.put_payload("/v1/tiktok/profile", {"handle": "x"}, {}, status=404, now=now)
    hit = repo.get_payload("/v1/tiktok/search/keyword", {"cursor": "30", "query": "foodie"})
    assert hit is not None and hit.payload == {"n": 1} and hit.status == 200
    assert hit.expires_at - hit.fetched_at == SEARCH_TTL
    gone = repo.get_payload("/v1/tiktok/profile", {"handle": "x"})
    assert gone is not None and gone.status == 404
    assert gone.expires_at - gone.fetched_at == PROFILE_TTL
    assert repo.get_payload("/v1/tiktok/search/keyword", {"query": "foodie"}) is None
    later = now + SEARCH_TTL.total_seconds()
    assert (
        repo.get_payload(
            "/v1/tiktok/search/keyword", {"query": "foodie", "cursor": "30"}, now=later
        )
        is None
    )
    assert params_key({"b": 1, "a": "x"}) == params_key({"a": "x", "b": "1"})


def test_a_feed_sighting_never_blanks_what_a_profile_read_brought() -> None:
    repo = MemoryCreatorPoolRepository()
    read = CreatorFacts(
        "tiktok",
        "@MiduDev",
        bio="Dev",
        external_url="https://midu.dev",
        followers=400_000,
        related=("mouredev",),
        hashtags=("js",),
        read_at=time.time(),
    )
    repo.upsert_creators([read])
    feed = CreatorFacts(
        "tiktok",
        "midudev",
        followers=None,
        hashtags=("react",),
        posts_seen=3,
        ai_posts_seen=1,
        likes_seen=900,
        views_seen=30_000,
    )
    repo.upsert_creators([feed])
    kept = repo.creator("tiktok", "midudev")
    assert kept is not None
    assert (kept.bio, kept.external_url, kept.followers) == ("Dev", "https://midu.dev", 400_000)
    assert kept.hashtags == ("js", "react") and kept.related == ("mouredev",)
    assert (kept.posts_seen, kept.ai_posts_seen, kept.views_seen) == (3, 1, 30_000)
    assert kept.read_at is not None
    # a fresh read replaces everything it carries
    repo.upsert_creators(
        [CreatorFacts("tiktok", "midudev", bio="New", followers=1, read_at=time.time())]
    )
    assert repo.creator("tiktok", "midudev").bio == "New"  # type: ignore[union-attr]
    with pytest.raises(ValueError):
        CreatorFacts("tiktok", "x", posts_seen=1, ai_posts_seen=2)


def test_sightings_answer_which_accounts_a_term_surfaced() -> None:
    repo = MemoryCreatorPoolRepository()
    now = time.time()
    repo.upsert_creators(
        [
            CreatorFacts("tiktok", "big", followers=1_000, seen_at=now),
            CreatorFacts("tiktok", "small", followers=10, seen_at=now),
            CreatorFacts("instagram", "other", followers=50, seen_at=now),
        ]
    )
    repo.record_sightings(
        [
            Sighting("tiktok", "big", "keyword", "programacion", "CO", seen_at=now),
            Sighting("tiktok", "small", "keyword", "programacion", "CO", seen_at=now - 10 * 86_400),
            Sighting("instagram", "other", "google", "programacion", seen_at=now),
        ]
    )
    assert [c.handle for c in repo.seen_for("keyword", "programacion")] == ["big", "small"]
    assert [c.handle for c in repo.seen_for("keyword", "programacion", since=now - 86_400)] == [
        "big"
    ]
    assert [c.handle for c in repo.seen_for("google", "programacion")] == ["other"]
    with pytest.raises(ValueError):
        Sighting("tiktok", "x", "feed", "t")


@pytest.fixture
def seeded_tenants() -> None:
    with admin_session() as session:
        for tid, name in ((TENANT, "A"), (OTHER, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"creator-pool-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )


@pytest.mark.db
def test_postgres_pool_is_shared_across_tenants(seeded_tenants: None) -> None:
    """What tenant A's search wrote, tenant B's search reads — the point of the pool."""
    a = PostgresCreatorPoolRepository(TENANT)
    b = PostgresCreatorPoolRepository(OTHER)
    term = f"t{uuid4().hex[:8]}"
    handle = f"c{uuid4().hex[:10]}"
    a.put_payload(
        "/v1/tiktok/search/keyword", {"query": term}, {"aweme_list": [1]}, credits_charged=1
    )
    hit = b.get_payload("/v1/tiktok/search/keyword", {"query": term})
    assert hit is not None and hit.payload == {"aweme_list": [1]}
    a.put_payload("/v1/tiktok/search/keyword", {"query": term}, {"aweme_list": [2]})  # replaced
    assert b.get_payload("/v1/tiktok/search/keyword", {"query": term}).payload == {
        "aweme_list": [2]
    }  # type: ignore[union-attr]

    a.upsert_creators([CreatorFacts("tiktok", handle, followers=5, hashtags=("x",))])
    a.upsert_creators(
        [CreatorFacts("tiktok", handle, bio="b", hashtags=("y",), read_at=time.time())]
    )
    seen = b.creator("tiktok", handle)
    assert (
        seen is not None and seen.bio == "b" and seen.hashtags == ("x", "y") and seen.followers == 5
    )
    a.record_sightings([Sighting("tiktok", handle, "keyword", term, "CO")])
    a.record_sightings([Sighting("tiktok", handle, "keyword", term, "CO")])  # seen again: counted
    assert [c.handle for c in b.seen_for("keyword", term)] == [handle]
