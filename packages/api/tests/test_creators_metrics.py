"""`cm-1`, the creator's figures (m-24946127, design §9) — the cases of §10.4."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.creators import metrics as m

READ_AT = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def reel(
    code: str,
    *,
    days_ago: float,
    views: int | None = 1000,
    likes: int | None = 50,
    comments: int | None = 5,
    duration: float | None = 20.0,
    hidden: bool = False,
    paid: bool = False,
    coauthors: tuple[str, ...] | None = (),
    sound_id: str | None = None,
    sound_title: str = "",
    original: bool | None = None,
    read_at: datetime = READ_AT,
) -> m.ReelRead:
    return m.ReelRead(
        reel_id=code,
        url=f"https://www.instagram.com/reel/{code}/",
        taken_at=read_at - timedelta(days=days_ago),
        duration_s=duration,
        views=None if hidden else views,
        likes=None if hidden else likes,
        comments=comments,
        counts_hidden=hidden,
        is_paid_partnership=paid,
        coauthors=coauthors,
        sound_id=sound_id,
        sound_title=sound_title,
        sound_is_original=original,
    )


def snap(
    *,
    followers: int | None = 10000,
    read_at: datetime = READ_AT,
    handle: str = "fake.creator",
    reels_read: int = 0,
) -> m.SnapshotFacts:
    return m.SnapshotFacts(
        snapshot_id=uuid4(),
        network="instagram",
        handle=handle,
        read_at=read_at,
        status="ok",
        followers=followers,
        reels_read=reels_read,
    )


def test_two_measurable_reels_are_insufficient_never_zero() -> None:
    reels = [reel("a", days_ago=5), reel("b", days_ago=6)]
    median = m.median_views(reels, READ_AT)
    assert (median.status, median.value, median.sample) == ("insufficient", None, 2)
    assert m.engagement_rate(reels, READ_AT).status == "insufficient"


def test_a_one_day_old_reel_stays_out_of_the_median() -> None:
    reels = [
        reel("a", days_ago=5, views=100),
        reel("b", days_ago=6, views=200),
        reel("c", days_ago=7, views=300),
        reel("young", days_ago=1, views=1_000_000),
    ]
    median = m.median_views(reels, READ_AT)
    assert median.value == 200 and median.sample == 3
    sheet = m.build_sheet(uuid4(), snap(), reels, now=READ_AT)
    # it still shows among the top reels, marked «still gaining views»
    assert sheet.top_reels[0].reel_id == "young" and sheet.top_reels[0].is_young


def test_hidden_counts_are_not_zero_and_are_counted_apart() -> None:
    reels = [
        reel("a", days_ago=5, views=100),
        reel("b", days_ago=6, views=200),
        reel("h1", days_ago=7, hidden=True),
        reel("h2", days_ago=8, hidden=True),
    ]
    median = m.median_views(reels, READ_AT)
    assert median.status == "insufficient" and median.note == m.NOTE_HIDDEN_COUNTS
    sheet = m.build_sheet(uuid4(), snap(), reels, now=READ_AT)
    assert sheet.hidden_counts_reels == 2 and sheet.measurable_reels == 2


def test_a_viral_reel_does_not_move_the_engagement_rate() -> None:
    base = [reel(f"r{i}", days_ago=5 + i, views=1000, likes=90, comments=10) for i in range(4)]
    viral = reel("viral", days_ago=4, views=1_000_000, likes=900_000, comments=50_000)
    before = m.engagement_rate(base, READ_AT)
    after = m.engagement_rate([*base, viral], READ_AT)
    assert before.value == pytest.approx(0.10)
    assert after.value == pytest.approx(0.10)


def test_best_duration_needs_a_band_with_three_measurable_reels() -> None:
    reels = [
        reel("a", days_ago=5, duration=10),
        reel("b", days_ago=6, duration=10),
        reel("c", days_ago=7, duration=45),
        reel("d", days_ago=8, duration=45),
    ]
    sheet = m.build_sheet(uuid4(), snap(), reels, now=READ_AT)
    assert sheet.best_duration is None
    assert [b.label for b in sheet.duration_buckets] == ["≤15 s", "31–60 s"]


def test_best_duration_picks_the_band_with_the_highest_median() -> None:
    reels = [reel(f"s{i}", days_ago=5 + i, duration=12, views=500) for i in range(3)] + [
        reel(f"l{i}", days_ago=10 + i, duration=40, views=3000) for i in range(3)
    ]
    sheet = m.build_sheet(uuid4(), snap(), reels, now=READ_AT)
    assert sheet.best_duration is not None and sheet.best_duration.label == "31–60 s"
    assert sheet.best_duration.lift_vs_overall == pytest.approx(3000 / 1750)


def test_sheet_figures_on_a_regular_account() -> None:
    reels = [
        reel(f"r{i}", days_ago=4 + 2 * i, views=1000 + 100 * i, likes=80, comments=20)
        for i in range(6)
    ] + [reel("star", days_ago=20, views=10_000, likes=800, comments=200)]
    sheet = m.build_sheet(uuid4(), snap(followers=5000), reels, now=READ_AT + timedelta(days=8))
    assert sheet.metrics_version == "cm-1"
    assert sheet.median_views.value == 1300
    assert sheet.views_per_follower.value == pytest.approx(1300 / 5000)
    assert sheet.median_gap_days.value == pytest.approx(2.0)
    assert sheet.reels_per_week.value == pytest.approx(3.5)
    assert [r.reel_id for r in sheet.standout_reels] == ["star"]
    assert sheet.standout_reels[0].lift == pytest.approx(10_000 / 1300)
    assert sheet.standout_share.value == pytest.approx(1 / 7)
    assert sheet.freshness_days == 8 and sheet.stale is True
    assert sheet.top_reels[0].embed_url == "https://www.instagram.com/reel/star/embed/"


def test_no_followers_is_unknown_not_zero() -> None:
    reels = [reel(f"r{i}", days_ago=5 + i) for i in range(3)]
    sheet = m.build_sheet(uuid4(), snap(followers=None), reels, now=READ_AT)
    assert sheet.followers.status == "unknown"
    assert sheet.views_per_follower.status == "unknown"
    assert sheet.views_per_follower.note == m.NOTE_NO_FOLLOWERS


def test_paid_collabs_and_audios() -> None:
    reels = [
        reel("a", days_ago=5, paid=True, coauthors=("partner",), sound_id="o:1", original=True),
        reel("b", days_ago=6, coauthors=("partner", "other"), sound_id="o:1", original=True),
        reel("c", days_ago=7, coauthors=(), sound_title="Hit · Band"),
        reel("d", days_ago=8, coauthors=(), sound_title="hit  ·  band"),
    ]
    sheet = m.build_sheet(uuid4(), snap(), reels, now=READ_AT)
    assert sheet.paid_partnerships == 1
    assert sheet.collabs == 2 and sheet.collaborators == ("partner", "other")
    assert sheet.collabs_known is True
    assert [(a.reels, a.is_original) for a in sheet.top_audios] == [(2, True), (2, None)]


def test_collabs_are_unknown_on_a_parser_1_read() -> None:
    reels = [reel(f"r{i}", days_ago=5 + i, coauthors=None) for i in range(3)]
    sheet = m.build_sheet(uuid4(), snap(), reels, now=READ_AT)
    assert (sheet.collabs, sheet.collabs_known) == (0, False)


# -- compare -------------------------------------------------------------------------


def entry(
    tracked: UUID, reels: list[m.ReelRead], *, followers: int | None = 10000, read_at=READ_AT
) -> m.CompareEntry:
    return m.CompareEntry(tracked, snap(followers=followers, read_at=read_at), reels)


def regular(prefix: str, views: int, *, n: int = 10, likes: int = 50) -> list[m.ReelRead]:
    return [reel(f"{prefix}{i}", days_ago=4 + 3 * i, views=views, likes=likes) for i in range(n)]


def _row(comparison: m.Comparison, key: str) -> m.ComparisonRow:
    return next(r for r in comparison.rows if r.key == key)


def test_compare_an_unknown_never_wins() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    result = m.compare(
        [
            entry(a, regular("a", 1000)),
            entry(b, regular("b", 500)),
            # two reels over the whole window: insufficient, however many views
            entry(c, [reel("c1", days_ago=4, views=9_999), reel("c2", days_ago=27, views=9_999)]),
        ],
        now=READ_AT,
    )
    median = _row(result, "median_views")
    assert median.values[2].status == "insufficient"
    assert median.best == (0,)


def test_compare_highlights_every_tied_best() -> None:
    a, b = uuid4(), uuid4()
    result = m.compare([entry(a, regular("a", 800)), entry(b, regular("b", 800))], now=READ_AT)
    assert _row(result, "median_views").best == (0, 1)


def test_compare_never_highlights_followers_paid_or_duration() -> None:
    a, b = uuid4(), uuid4()
    result = m.compare(
        [entry(a, regular("a", 800), followers=99_000), entry(b, regular("b", 900))],
        now=READ_AT,
    )
    for key in ("followers", "paid_partnerships", "best_duration"):
        row = _row(result, key)
        assert row.highlights is False and row.best == ()
    assert [r.key for r in result.rows] == list(m.COMPARE_ROWS)
    assert result.metrics_version == "cm-1"


def test_compare_measures_each_creator_on_his_own_latest_reels() -> None:
    a, b = uuid4(), uuid4()
    busy = [reel(f"a{i}", days_ago=4 + 0.7 * i, views=1000) for i in range(40)]  # ~10/week
    quiet = [reel(f"b{i}", days_ago=4 + 9 * i, views=500) for i in range(8)]  # ~1/week
    result = m.compare([entry(a, busy), entry(b, quiet)], now=READ_AT)
    assert result.reels_per_creator == 8  # the fewest available, under 12
    first, second = result.creators
    assert (first.reels_used, second.reels_used) == (8, 8)
    assert first.used_to == READ_AT - timedelta(days=4)
    assert first.used_from == READ_AT - timedelta(days=4 + 0.7 * 7)
    assert second.used_from == READ_AT - timedelta(days=4 + 9 * 7)
    assert not first.few_reels and not second.few_reels
    median = _row(result, "median_views")
    assert [v.status for v in median.values] == ["ok", "ok"]  # the quiet one has data
    assert median.best == (0,)
    assert result.window_from == second.used_from and result.window_to == first.used_to
    assert not any(w.startswith(m.WARN_FEW_REELS) for w in result.warnings)


def test_compare_caps_at_twelve_and_flags_a_creator_with_too_few_reels() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    many = [reel(f"a{i}", days_ago=4 + i, views=1000) for i in range(30)]
    also_many = [reel(f"b{i}", days_ago=4 + i, views=900) for i in range(20)]
    result = m.compare([entry(a, many), entry(b, also_many)], now=READ_AT)
    assert result.reels_per_creator == 12
    assert [x.reels_used for x in result.creators] == [12, 12]
    few = [reel("c1", days_ago=5), reel("c2", days_ago=9)]
    result = m.compare([entry(a, many), entry(c, few)], now=READ_AT)
    # the weak creator does not drag the others down to 3 reels
    assert result.reels_per_creator == 12
    assert result.creators[0].reels_used == 12 and not result.creators[0].few_reels
    assert result.creators[1].few_reels is True and result.creators[1].reels_used == 2
    assert f"{m.WARN_FEW_REELS}:{c}" in result.warnings
    for key in ("median_views", "paid_partnerships"):  # «sin dato», never zero
        assert _row(result, key).values[1].status == "insufficient"
    assert _row(result, "paid_partnerships").values[0].status == "ok"


def test_compare_with_nobody_above_the_minimum_falls_back_to_it() -> None:
    a, b = uuid4(), uuid4()
    result = m.compare(
        [entry(a, [reel("a1", days_ago=5)]), entry(b, [])],
        now=READ_AT,
    )
    assert result.reels_per_creator == m.MIN_SAMPLE
    assert all(c.few_reels for c in result.creators)
    paid = _row(result, "paid_partnerships")
    assert [v.status for v in paid.values] == ["insufficient", "insufficient"]


def test_compare_pace_counts_hidden_and_young_reels_too() -> None:
    a, b = uuid4(), uuid4()
    # a reel every day; every other one hides its counts, plus two young ones
    daily = [reel(f"a{i}", days_ago=4 + i, hidden=i % 2 == 1) for i in range(24)] + [
        reel("y1", days_ago=1),
        reel("y2", days_ago=2),
    ]
    weekly = [reel(f"b{i}", days_ago=4 + 7 * i) for i in range(12)]
    result = m.compare([entry(a, daily), entry(b, weekly)], now=READ_AT)
    pace = _row(result, "reels_per_week")
    assert pace.values[0].value == pytest.approx(7.0)  # not 3.5 from measurable ones only
    assert pace.values[1].value == pytest.approx(1.0)
    assert pace.best == (0,)


def test_compare_warns_on_stale_and_far_apart_reads() -> None:
    a, b = uuid4(), uuid4()
    old = READ_AT - timedelta(days=10)
    result = m.compare(
        [
            entry(a, [reel(f"a{i}", days_ago=4 + 10 * i, views=900) for i in range(20)]),
            entry(
                b,
                [reel(f"b{i}", days_ago=4 + 10 * i, views=900, read_at=old) for i in range(20)],
                read_at=old,
            ),
        ],
        now=READ_AT,
    )
    assert f"stale:{b}" in result.warnings and m.WARN_READS_APART in result.warnings
    assert result.creators[1].stale is True


def test_reel_cards_list_only_the_other_accounts() -> None:
    reels = [reel(f"r{i}", days_ago=5 + i, coauthors=("fake.creator", "partner")) for i in range(3)]
    sheet = m.build_sheet(uuid4(), snap(), reels, now=READ_AT)
    assert sheet.top_reels[0].coauthors == ("partner",)
    assert sheet.collaborators == ("partner",) and sheet.collabs == 3
