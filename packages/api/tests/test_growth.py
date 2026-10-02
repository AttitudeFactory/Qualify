"""The creator read history and the organic growth estimate over it (2026-10-01).

The estimate is checked on three synthetic creators — one organic, one that bought
followers, one that boosted a post — and the repository offline (memory) and, `db`-marked,
against Postgres with RLS."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session

from qualify_api.growth import (
    FollowerPoint,
    MemoryGrowthRepository,
    PostgresGrowthRepository,
    PostRead,
    ProfileRead,
    Reference,
    estimate_organic_growth,
)
from qualify_api.tenancy.models import Tenant

T0 = datetime(2026, 9, 1, tzinfo=UTC)
DAY = timedelta(days=1)
TENANT = UUID("a0000000-0000-4000-8000-0000000000e1")
OTHER = UUID("a0000000-0000-4000-8000-0000000000e2")


def _series(start: int, gains: list[int]) -> list[FollowerPoint]:
    points, count = [FollowerPoint(T0, start)], start
    for day, gain in enumerate(gains, start=1):
        count += gain
        points.append(FollowerPoint(T0 + day * DAY, count))
    return points


def _post(post_id: str, day: int, reads: list[tuple[int, int, int]]) -> list[PostRead]:
    """A post published on `day`, read on the following days: (day, views, likes)."""
    return [
        PostRead(
            "tiktok",
            "creator",
            post_id,
            taken_at=T0 + day * DAY,
            fetched_at=T0 + read_day * DAY,
            views=views,
            likes=likes,
            comments=likes // 20,
        )
        for read_day, views, likes in reads
    ]


def _organic_creator() -> tuple[list[FollowerPoint], list[PostRead]]:
    """Two posts a week, each read the day after and three days later; followers grow
    with the interactions at ~2 per 100 — all organic."""
    posts: list[PostRead] = []
    gains = [0] * 29  # indexed by day, 1..28
    for n, day in enumerate(range(0, 25, 3)):
        first, later = 2_000 + 100 * n, 3_000 + 100 * n
        posts += _post(f"p{n}", day, [(day + 1, first * 20, first), (day + 3, later * 20, later)])
        gains[day + 1] += round(first * 1.05 * 0.02)  # likes + comments, 2 followers per 100
        gains[day + 3] += round((later - first) * 1.05 * 0.02)
    return _series(10_000, gains[1:]), posts


def test_an_organic_creator_has_its_growth_explained_by_its_content() -> None:
    followers, posts = _organic_creator()
    estimate = estimate_organic_growth(followers, posts)
    assert estimate is not None
    assert estimate.k_from == "serie"
    assert abs(estimate.k - 0.021) < 0.002  # 2 per 100 interactions, as built
    assert estimate.delta > 0
    assert estimate.organic_share is not None and estimate.organic_share > 0.9
    assert estimate.unexplained < estimate.delta * 0.1
    assert not any(v.pushed for v in estimate.posts)
    assert estimate.confidence == 1.0


def test_bought_followers_are_growth_nothing_organic_explains() -> None:
    followers, posts = _organic_creator()
    # +3,000 followers landing over two days with no post behind them
    bumped = [
        FollowerPoint(p.at, p.followers + (3_000 if i >= 10 else 1_500 if i == 9 else 0))
        for i, p in enumerate(followers)
    ]
    estimate = estimate_organic_growth(bumped, posts)
    assert estimate is not None
    assert estimate.unexplained >= 2_800
    assert estimate.organic_share is not None and estimate.organic_share < 0.5
    assert "referencia" not in estimate.k_from  # the clean days still fix k


def test_a_boosted_post_is_flagged_and_its_interactions_do_not_count() -> None:
    followers, posts = _organic_creator()
    # one post with 10x the reach and a fifth of the engagement per view: ads
    boosted = _post("ads", 14, [(15, 600_000, 1_200), (17, 900_000, 1_500)])
    estimate = estimate_organic_growth(followers, posts + boosted)
    assert estimate is not None
    flagged = {v.post_id: v for v in estimate.posts if v.pushed}
    assert list(flagged) == ["ads"]
    assert "alcance muy alto con interacción muy baja" in flagged["ads"].reasons
    assert estimate.interactions_pushed == 1_500 + 1_500 // 20
    assert estimate.pushed_reach_share is not None and estimate.pushed_reach_share > 0.5
    assert "1 publicación(es) con señales de alcance pagado, excluidas." in estimate.notes


def test_views_arriving_after_72_hours_mark_a_boost_run_later() -> None:
    followers, posts = _organic_creator()
    # read at 24 h, at 96 h (past the 72 h mark) and a week later with 3x the views
    late = _post("late", 10, [(11, 50_000, 2_500), (14, 60_000, 2_800), (21, 200_000, 3_000)])
    estimate = estimate_organic_growth(followers, posts + late)
    assert estimate is not None
    verdict = next(v for v in estimate.posts if v.post_id == "late")
    assert verdict.late_wave_share is not None and verdict.late_wave_share > 0.6
    assert verdict.pushed and "72 h" in verdict.reasons[0]


def test_a_paid_label_alone_marks_a_post_as_pushed() -> None:
    followers, posts = _organic_creator()
    estimate = estimate_organic_growth(followers, posts, paid_post_ids={"p2"})
    assert estimate is not None
    verdict = next(v for v in estimate.posts if v.post_id == "p2")
    assert verdict.reasons == ("etiqueta de contenido pagado",)


def test_a_short_series_falls_back_to_the_reference_and_says_so() -> None:
    followers = _series(1_000, [10, 12])
    posts = _post("p", 0, [(1, 1_000, 50), (2, 1_200, 60)])
    estimate = estimate_organic_growth(followers, posts, reference=Reference(k=0.1))
    assert estimate is not None
    assert estimate.k_from == "referencia" and estimate.k == 0.1
    assert estimate.organic == min(22, round(0.1 * (60 + 3)))
    assert estimate.confidence < 0.5
    assert any("referencia" in n for n in estimate.notes)
    assert any("preliminar" in n for n in estimate.notes)


def test_fewer_than_two_points_is_no_estimate() -> None:
    assert estimate_organic_growth([FollowerPoint(T0, 10)], []) is None
    assert estimate_organic_growth([], []) is None


def test_a_falling_account_has_nothing_to_split() -> None:
    estimate = estimate_organic_growth(_series(1_000, [-10, -5]), [])
    assert estimate is not None
    assert estimate.delta == -15 and estimate.organic == 0 and estimate.unexplained == 0
    assert estimate.organic_share is None
    assert any("perdió seguidores" in n for n in estimate.notes)


# -- the repository ------------------------------------------------------------------------


def test_reads_normalize_the_handle_and_refuse_what_the_table_would() -> None:
    read = ProfileRead("tiktok", "@MiduDev", T0.timestamp(), followers=10)
    assert (read.handle, read.fetched_at) == ("midudev", T0)
    with pytest.raises(ValueError):
        ProfileRead("youtube", "x", T0)
    with pytest.raises(ValueError):
        ProfileRead("tiktok", "x", T0, source="poller")
    with pytest.raises(ValueError):
        PostRead("tiktok", "x", "", T0, T0)
    post = PostRead("instagram", "X", "abc", T0, T0, likes=3, comments=None, shares=2)
    assert post.interactions == 5


def test_the_memory_repository_keeps_every_read_in_order() -> None:
    repo = MemoryGrowthRepository()
    repo.record(
        TENANT,
        [
            ProfileRead("tiktok", "a", T0 + DAY, followers=120),
            ProfileRead("tiktok", "a", T0, followers=100),
            ProfileRead("tiktok", "a", T0 + 2 * DAY, followers=None),  # a read without the figure
            ProfileRead("instagram", "a", T0, followers=5),
        ],
        [
            PostRead("tiktok", "a", "p", T0, T0 + DAY, views=1),
            PostRead("tiktok", "a", "p", T0, T0, views=0),
        ],
    )
    assert [p.followers for p in repo.follower_series(TENANT, "tiktok", "a")] == [100, 120]
    assert [p.followers for p in repo.follower_series(TENANT, "tiktok", "a", since=T0 + DAY)] == [
        120
    ]
    assert [p.views for p in repo.post_reads(TENANT, "tiktok", "A")] == [0, 1]
    assert repo.follower_series(OTHER, "tiktok", "a") == []


@pytest.fixture
def seeded_tenants() -> None:
    with admin_session() as session:
        for tid, name in ((TENANT, "A"), (OTHER, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"growth-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )


@pytest.mark.db
def test_postgres_keeps_the_series_per_tenant(seeded_tenants: None) -> None:
    repo = PostgresGrowthRepository()
    handle = f"c{uuid4().hex[:10]}"
    repo.record(
        TENANT,
        [
            ProfileRead("tiktok", handle, T0, followers=100, total_likes=5),
            ProfileRead("tiktok", handle, T0 + DAY, source="discovery", followers=130),
        ],
        [
            PostRead("tiktok", handle, "v1", T0, T0, views=10, likes=1),
            PostRead(
                "tiktok",
                handle,
                "v1",
                T0,
                T0 + DAY,
                views=50,
                likes=4,
                ai_generated=True,
                ai_label="detected",
                ai_source="Sora",
            ),
        ],
    )
    repo.record(OTHER, [ProfileRead("tiktok", handle, T0, followers=999)])
    series = repo.follower_series(TENANT, "tiktok", handle)
    assert [p.followers for p in series] == [100, 130]
    posts = repo.post_reads(TENANT, "tiktok", handle)
    assert [(p.views, p.ai_generated, p.ai_source) for p in posts] == [
        (10, None, ""),
        (50, True, "Sora"),
    ]
    # RLS: the other tenant's read of the same public creator is its own series
    assert [p.followers for p in repo.follower_series(OTHER, "tiktok", handle)] == [999]
