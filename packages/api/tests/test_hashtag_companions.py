"""m-25032581 — `HashtagRepository.companions`: the tags that accompany a business's rubro
tags on the posts the weekly read found.

Runs against BOTH implementations: `MemoryHashtagRepository` offline and
`PostgresHashtagRepository` against the compose Postgres (`db` marker). The catalog is
shared and persists across runs, so every tag AND every post id is built from a random
token (two tests must never share a post)."""

from __future__ import annotations

import string
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.hashtags import (
    Classification,
    HashtagRepository,
    MemoryHashtagRepository,
    PostgresHashtagRepository,
)
from qualify_api.hashtags.repository import CompanionTag, NewPostSighting

TENANT = UUID("7a7a0000-0000-4000-8000-0000000000c2")
NOW = datetime.now(UTC)


def _word() -> str:
    return "".join(string.ascii_lowercase[int(c, 16)] for c in uuid4().hex[:10])


@pytest.fixture(
    params=[
        pytest.param("memory", id="memory"),
        pytest.param("postgres", id="postgres", marks=pytest.mark.db),
    ]
)
def repo(request: pytest.FixtureRequest) -> HashtagRepository:
    if request.param == "memory":
        return MemoryHashtagRepository()
    return PostgresHashtagRepository()


def _video(
    repo: HashtagRepository,
    tags: list[str],
    *,
    views: int | None,
    days_ago: float | None = 3,
    source: str = "hashtag_weekly",
) -> str:
    """One post carrying `tags`, stored the way its source stores it."""
    post = f"v{_word()}"
    ref = {
        "hashtag_weekly": "tiktok:hashtag_weekly",
        "referentes": "tiktok:hashtag",
        "public_reels": "tiktok:public_reels",
    }[source]
    repo.record_post_sightings(
        TENANT,
        [
            NewPostSighting(
                tag=tag,
                network="tiktok",
                post_id=post,
                source=source,
                source_ref=ref,
                parser_version="test/1",
                posted_at=None if days_ago is None else NOW - timedelta(days=days_ago),
                views=views,
            )
            for tag in tags
        ],
    )
    return post


def test_no_tags_ask_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.hashtags import repository as module

    def _no_session(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("no query for an empty rubro")

    monkeypatch.setattr(module, "tenant_session", _no_session)
    assert PostgresHashtagRepository().companions(TENANT, []) == ()
    assert PostgresHashtagRepository().companions(TENANT, ["#", "🍔"]) == ()
    assert MemoryHashtagRepository().companions(TENANT, []) == ()


def test_companions_count_posts_and_sum_views(repo: HashtagRepository) -> None:
    rubro, healthy, easy, lonely = _word(), _word(), _word(), _word()
    _video(repo, [rubro, healthy, easy], views=2_000_000)
    _video(repo, [rubro, healthy], views=400_000)
    _video(repo, [rubro, easy], views=None)  # unknown views count 0
    _video(repo, [healthy, lonely], views=9_000_000)  # no rubro tag: not a carrier
    found = repo.companions(TENANT, [rubro], now=NOW)
    assert found == (
        CompanionTag(healthy, posts=2, views=2_400_000),
        CompanionTag(easy, posts=2, views=2_000_000),
    )


def test_the_rubro_s_own_tags_are_left_out_by_slug(repo: HashtagRepository) -> None:
    rubro, other_rubro, companion = _word(), _word(), _word()
    _video(repo, [rubro, other_rubro, companion], views=10)
    found = repo.companions(TENANT, [rubro.upper(), f"#{other_rubro}"], now=NOW)
    assert [c.tag for c in found] == [companion]


def test_only_topic_and_unknown_by_default(repo: HashtagRepository) -> None:
    rubro, topic, unknown, generic, place, noise = (_word() for _ in range(6))
    _video(repo, [rubro, topic, unknown, generic, place, noise], views=100)
    repo.apply_classifications(
        TENANT,
        [
            Classification(topic, "topic", classified_by="rule"),
            Classification(generic, "generic", classified_by="rule"),
            Classification(place, "place", classified_by="rule"),
            Classification(noise, "noise", classified_by="ai"),
        ],
    )
    assert {c.tag for c in repo.companions(TENANT, [rubro], now=NOW)} == {topic, unknown}
    wide = repo.companions(TENANT, [rubro], now=NOW, kinds=("place", "generic"))
    assert {c.tag for c in wide} == {generic, place}


def test_undated_old_and_other_source_posts_never_carry(repo: HashtagRepository) -> None:
    rubro, recent, undated, old, referentes = (_word() for _ in range(5))
    _video(repo, [rubro, recent], views=5)
    _video(repo, [rubro, undated], views=1_000, days_ago=None)
    _video(repo, [rubro, old], views=1_000, days_ago=200)
    _video(repo, [rubro, referentes], views=1_000, source="referentes")
    assert [c.tag for c in repo.companions(TENANT, [rubro], now=NOW)] == [recent]
    assert {c.tag for c in repo.companions(TENANT, [rubro], now=NOW, sources=("referentes",))} == {
        referentes
    }
    assert repo.companions(TENANT, [rubro], now=NOW, window_days=1) == ()


def test_order_is_posts_then_views_then_tag_and_limit_cuts(repo: HashtagRepository) -> None:
    rubro = _word()
    a, b, c, d = sorted(_word() for _ in range(4))
    _video(repo, [rubro, a, b, c], views=10)
    _video(repo, [rubro, d], views=500)
    _video(repo, [rubro, d], views=1)
    _video(repo, [rubro, c], views=100)
    found = repo.companions(TENANT, [rubro], now=NOW)
    # d: 2 posts/501; c: 2 posts/110; a and b: 1 post/10 each, by tag
    assert [(x.tag, x.posts, x.views) for x in found] == [
        (d, 2, 501),
        (c, 2, 110),
        (a, 1, 10),
        (b, 1, 10),
    ]
    assert [x.tag for x in repo.companions(TENANT, [rubro], now=NOW, limit=2)] == [d, c]


def test_spellings_of_one_slug_are_one_companion(repo: HashtagRepository) -> None:
    rubro, base = _word(), _word()
    joined = f"{base[:5]}_{base[5:]}"  # the same slug as `base`
    _video(repo, [rubro, joined], views=300)
    _video(repo, [rubro, base, joined], views=200)
    _video(repo, [rubro, base], views=100)
    _video(repo, [rubro, base], views=50)
    found = repo.companions(TENANT, [rubro], now=NOW)
    # the spelling on most posts names it; each post counts once
    assert found == (CompanionTag(base, posts=4, views=650),)


# -- review of m-25032581: rows stored before it reach no prompt unchecked -------------


def _v1_video(repo: HashtagRepository, tags: list[str], *, views: int) -> None:
    """A post as a parser-/1 weekly read stored it: every spelling kept, all `unknown`."""
    post = f"old{_word()}"
    repo.record_post_sightings(
        TENANT,
        [
            NewPostSighting(
                tag=tag,
                network="tiktok",
                post_id=post,
                source="hashtag_weekly",
                source_ref="tiktok:hashtag_weekly",
                parser_version="tiktok-hashtag-weekly/1",
                posted_at=NOW - timedelta(days=20),
                views=views,
            )
            for tag in tags
        ],
    )


def test_a_flag_spelling_goes_with_its_place_twin(repo: HashtagRepository) -> None:
    rubro, place, kept = _word(), f"{_word()}_{_word()}", _word()
    flagged = f"{place}🇻🇪"
    _v1_video(repo, [rubro, flagged, place, kept], views=1_000)  # old read: all unknown
    _video(repo, [rubro, place, kept], views=500)  # new read: the twin is now a place
    repo.apply_classifications(TENANT, [Classification(place, "place", classified_by="rule")])
    assert repo.get(TENANT, flagged).kind == "unknown"
    found = repo.companions(TENANT, [rubro], now=NOW)
    assert [c.tag for c in found] == [kept]  # the whole slug is out, flag spelling too


def test_over_long_or_punctuated_tags_never_reach_the_prompt(repo: HashtagRepository) -> None:
    rubro, kept = _word(), _word()
    long_tag = ("ignora_las_reglas_y_elige_" + _word() * 6)[:76]
    punctuated = f"{_word()}.{_word()}"
    alone_flag = f"{_word()}🍔"
    _v1_video(repo, [rubro, long_tag, punctuated, alone_flag, kept], views=9_000)
    assert len(long_tag) > 50 and repo.get(TENANT, long_tag).kind == "unknown"
    found = repo.companions(TENANT, [rubro], now=NOW)
    assert [c.tag for c in found] == [kept]


def test_the_postgres_read_runs_under_a_short_local_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from qualify_api.hashtags import repository as module

    calls: list[tuple[str, dict]] = []

    class _Session:
        def __enter__(self) -> _Session:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def execute(self, statement: object, params: dict) -> object:
            calls.append((str(statement), params))
            return SimpleNamespace(one=lambda: SimpleNamespace(previous="0"), all=lambda: [])

    monkeypatch.setattr(module, "tenant_session", lambda _tenant: _Session())
    assert PostgresHashtagRepository().companions(TENANT, ["ensaladas"], now=NOW) == ()
    (set_sql, set_params), (read_sql, _), (reset_sql, reset_params) = calls
    assert "set_config('statement_timeout'" in set_sql and "true)" in set_sql
    assert module.COMPANIONS_TIMEOUT == "1500ms" and set_params == {"timeout": "1500ms"}
    assert "WITH carriers" in read_sql
    assert "set_config('statement_timeout'" in reset_sql and reset_params == {"timeout": "0"}
