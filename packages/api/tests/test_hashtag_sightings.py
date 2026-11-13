"""m-25026377 — the catalog keeps the views and date of the posts each tag was on
(migration 0162), and «popular» means views in the last 90 days.

Runs against BOTH implementations: `MemoryHashtagRepository` offline and
`PostgresHashtagRepository` against the compose Postgres (`db` marker), so the upsert's
`ON CONFLICT`, the `GREATEST`/`COALESCE` rules and the window query are exercised for
real. The catalog is shared and persists across runs, so every test builds its words from
a random token."""

from __future__ import annotations

import string
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.hashtags import (
    HashtagRepository,
    MemoryHashtagRepository,
    NewHashtag,
    NewTermLink,
    PostgresHashtagRepository,
)
from qualify_api.hashtags import catalog as hashtag_catalog
from qualify_api.hashtags.repository import (
    POPULAR_WINDOW_DAYS,
    NewPostSighting,
    ReelPost,
    sighting_batch,
)
from qualify_api.referentes.discovery_seed import DiscoverySeed

TENANT = UUID("7a7a0000-0000-4000-8000-0000000000c1")
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


@pytest.fixture(autouse=True)
def _no_paid_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Acceptance 1: storing views and dates spends nothing — the metered gate of
    ScrapeCreators (ADR 42) and any HTTP send fail the test if reached."""

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a paid call was made")

    from qualify_api.vendors import scrapecreators

    monkeypatch.setattr(scrapecreators, "metered_get", _forbidden)
    monkeypatch.setattr(httpx.Client, "send", _forbidden)


def _sighting(tag: str, post: str, *, views: int | None, days_ago: float | None) -> NewPostSighting:
    return NewPostSighting(
        tag=tag,
        network="tiktok",
        post_id=post,
        source="referentes",
        source_ref="tiktok:hashtag",
        parser_version="referentes-feed/1",
        posted_at=None if days_ago is None else NOW - timedelta(days=days_ago),
        views=views,
    )


# -- validation ------------------------------------------------------------------------

_REF = "tiktok:hashtag"


def test_sighting_validates_its_vocabulary() -> None:
    with pytest.raises(ValueError):
        _sighting("ok", "", views=1, days_ago=1)
    with pytest.raises(ValueError):
        _sighting("ok", "p1", views=-1, days_ago=1)
    with pytest.raises(ValueError):
        NewPostSighting("ok", "youtube", "p1", "referentes", _REF, "v1")
    with pytest.raises(ValueError):
        NewPostSighting("ok", "tiktok", "p1", "nope", _REF, "v1")
    with pytest.raises(ValueError):
        NewPostSighting("ok", "tiktok", "p1", "referentes", _REF, "")
    with pytest.raises(ValueError):
        NewPostSighting("ok", "tiktok", "p1", "referentes", _REF, "v1", datetime(2026, 1, 1))
    assert NewPostSighting("ok", "tiktok", "p1", "referentes", _REF, "v1").source_ref == _REF


@pytest.mark.parametrize(
    "ref",
    ["", "tiktok", "tiktok:hashtag:#cucutafood", "tiktok:peluquería canina", "youtube:feed"],
)
def test_source_ref_holds_a_kind_never_a_search_s_words(ref: str) -> None:
    with pytest.raises(ValueError):
        NewPostSighting("ok", "tiktok", "p1", "referentes", ref, "v1")


@pytest.mark.parametrize(
    ("label", "kind"),
    [
        ("tiktok:hashtag:#cucutafood", "tiktok:hashtag"),
        ("tiktok:keyword:peluquería canina cúcuta", "tiktok:keyword"),
        ("instagram:reels:bianki shawarma", "instagram:reels"),
        ("whatever the operator typed", "tiktok:feed"),
        ("", "tiktok:feed"),
    ],
)
def test_feed_kind_drops_the_query_words(label: str, kind: str) -> None:
    assert hashtag_catalog.feed_kind(kind.split(":")[0], label) == kind


def _stored_refs(repo: HashtagRepository, tag: str) -> set[str]:
    if isinstance(repo, MemoryHashtagRepository):
        return {s.source_ref for (t, _n, _p), s in repo._sightings.items() if t == tag}
    with tenant_session(TENANT) as session:
        rows = session.execute(
            text(
                "SELECT s.source_ref FROM hashtag_post_sightings s "
                "JOIN hashtags h ON h.id = s.hashtag_id WHERE h.tag = :tag"
            ),
            {"tag": tag},
        ).all()
    return {r.source_ref for r in rows}


def test_no_search_words_reach_the_sightings_table(repo: HashtagRepository) -> None:
    tag, secret = _word(), _word()
    accounts = [
        _Account(
            "tiktok",
            "a",
            [tag],
            [
                _Post("k1", None, 5, (tag,), f"tiktok:keyword:{secret} cucuta"),
                _Post("k2", None, 5, (tag,), f"tiktok:hashtag:#{secret}"),
                _Post("k3", None, 5, (tag,), f"{secret} sin formato"),
            ],
        )
    ]
    hashtag_catalog.capture(TENANT, _seed(), "national", accounts, repository=repo)
    refs = _stored_refs(repo, tag)
    assert refs == {"tiktok:keyword", "tiktok:hashtag", "tiktok:feed"}
    assert not any(secret in ref for ref in refs)


# -- batching and lock order (review items 2 and 5) ---------------------------------------


def test_sighting_batch_sorts_and_deduplicates() -> None:
    items = [
        _sighting("zeta", "p2", views=5, days_ago=1),
        _sighting("alfa", "p9", views=1, days_ago=1),
        _sighting("zeta", "p1", views=3, days_ago=None),
        _sighting("alfa", "p9", views=7, days_ago=None),  # same post: merged, never twice
        replace(_sighting("alfa", "p3", views=2, days_ago=1), network="instagram"),
    ]
    tags, sightings = sighting_batch(items)
    assert tags == [("alfa", ("instagram", "tiktok")), ("zeta", ("tiktok",))]
    assert [(s.tag, s.network, s.post_id) for s in sightings] == [
        ("alfa", "instagram", "p3"),
        ("alfa", "tiktok", "p9"),
        ("zeta", "tiktok", "p1"),
        ("zeta", "tiktok", "p2"),
    ]
    merged = sightings[1]
    assert merged.views == 7 and merged.posted_at is not None  # higher views, date kept


class _Recorder:
    """A stand-in for `tenant_session` that records each statement and its parameters."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, tenant_id: UUID) -> _Recorder:
        return self

    def __enter__(self) -> _Recorder:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, statement: object, params: dict) -> object:
        self.calls.append((str(statement), params))
        return SimpleNamespace(rowcount=0)


def test_postgres_writes_n_reels_in_two_statements_in_tag_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.hashtags import repository as module

    recorder = _Recorder()
    monkeypatch.setattr(module, "tenant_session", recorder)
    reels = [
        ReelPost("instagram", f"r{i}", NOW, f"#zeta #alfa #mid{i % 3}", 10 * i, 2)
        for i in range(50)
    ]
    summary = hashtag_catalog.capture_reels(TENANT, reels, repository=PostgresHashtagRepository())
    assert summary.sightings == 150
    assert len(recorder.calls) == 2  # was 2 per (reel, tag): 300 for these 50 reels
    (tag_sql, tag_params), (sighting_sql, sighting_params) = recorder.calls
    assert "INSERT INTO hashtags" in tag_sql and "ORDER BY u.tag" in tag_sql
    assert (
        tag_params["tags"] == sorted(tag_params["tags"]) == ["alfa", "mid0", "mid1", "mid2", "zeta"]
    )
    assert (
        'ORDER BY u.tag COLLATE "C", u.network COLLATE "C", u.post_id COLLATE "C"' in sighting_sql
    )
    keys = list(
        zip(sighting_params["tags"], sighting_params["networks"], sighting_params["post_ids"])
    )
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
    assert set(sighting_params["source_refs"]) == {"instagram:public_reels"}


# -- the paid classification queue (review item 4) ----------------------------------------


def test_a_reel_only_tag_stays_out_of_the_classification_queue(repo: HashtagRepository) -> None:
    tag = _word()
    hashtag_catalog.capture_reels(
        TENANT, [ReelPost("tiktok", _word(), NOW, f"#{tag}", 9, 2)], repository=repo
    )
    queued = {t.tag for t in repo.needs_classification(TENANT, limit=100_000)}
    assert tag not in queued

    # the same tag later seen by a referentes search joins the queue
    accounts = [_Account("tiktok", "a", [tag], [_Post("v9", None, 1, (tag,))])]
    hashtag_catalog.capture(TENANT, _seed(), "national", accounts, repository=repo)
    queued = {t.tag for t in repo.needs_classification(TENANT, limit=100_000)}
    assert tag in queued


# -- idempotency (acceptance 4) --------------------------------------------------------


def test_the_same_sighting_twice_is_one_row(repo: HashtagRepository) -> None:
    tag = _word()
    item = _sighting(tag, "post-1", views=500, days_ago=3)
    assert repo.record_post_sightings(TENANT, [item]) == 1
    assert repo.record_post_sightings(TENANT, [item, item]) == 1
    recent = repo.recent_views(TENANT, [tag], now=NOW)
    assert (recent[tag].views, recent[tag].posts) == (500, 1)
    # recording a sighting is not a tag sighting: seen_count is the account count
    stored = repo.get(TENANT, tag)
    assert stored is not None and stored.seen_count == 0 and "tiktok" in stored.networks


def test_a_post_seen_again_keeps_the_higher_views_and_its_date(repo: HashtagRepository) -> None:
    tag = _word()
    repo.record_post_sightings(TENANT, [_sighting(tag, "p", views=900, days_ago=10)])
    repo.record_post_sightings(TENANT, [_sighting(tag, "p", views=400, days_ago=None)])
    repo.record_post_sightings(TENANT, [_sighting(tag, "p", views=None, days_ago=None)])
    recent = repo.recent_views(TENANT, [tag], now=NOW)
    assert (recent[tag].views, recent[tag].posts) == (900, 1)
    repo.record_post_sightings(TENANT, [_sighting(tag, "p", views=1500, days_ago=10)])
    assert repo.recent_views(TENANT, [tag], now=NOW)[tag].views == 1500


# -- the 90-day window -----------------------------------------------------------------


def test_recent_views_count_only_dated_posts_inside_the_window(repo: HashtagRepository) -> None:
    tag, other = _word(), _word()
    repo.record_post_sightings(
        TENANT,
        [
            _sighting(tag, "fresh", views=1000, days_ago=5),
            _sighting(tag, "edge", views=10, days_ago=POPULAR_WINDOW_DAYS - 1),
            _sighting(tag, "old", views=1_000_000, days_ago=POPULAR_WINDOW_DAYS + 5),
            _sighting(tag, "undated", views=1_000_000, days_ago=None),
            _sighting(tag, "no-views", views=None, days_ago=2),
            _sighting(other, "old", views=7, days_ago=400),
        ],
    )
    recent = repo.recent_views(TENANT, [tag, other], now=NOW)
    assert (recent[tag].views, recent[tag].posts) == (1010, 3)
    assert other not in recent


# -- «popular» ordering (acceptance 2) -------------------------------------------------


def _rubro(repo: HashtagRepository, term: str, tags_by_weight: list[tuple[str, int]]) -> None:
    repo.upsert_hashtags(
        TENANT, [NewHashtag(tag=t, source="observed", kind="topic") for t, _ in tags_by_weight]
    )
    repo.link_terms(
        TENANT,
        [NewTermLink(term=term, tag=t, source="observed", weight=w) for t, w in tags_by_weight],
    )


def test_resolve_popular_orders_by_recent_views(repo: HashtagRepository) -> None:
    term = _word()
    relevant, watched, stale = _word(), _word(), _word()
    # relevance order (what `resolve` returns): relevant > stale > watched
    _rubro(repo, term, [(relevant, 9), (stale, 5), (watched, 2)])
    repo.record_post_sightings(
        TENANT,
        [
            _sighting(watched, "w1", views=80_000, days_ago=4),
            _sighting(watched, "w2", views=20_000, days_ago=30),
            _sighting(relevant, "r1", views=300, days_ago=7),
            _sighting(stale, "s1", views=5_000_000, days_ago=200),
        ],
    )

    assert [h.hashtag.tag for h in repo.resolve(TENANT, term)] == [relevant, stale, watched]

    popular = repo.resolve_popular(TENANT, term, now=NOW)
    # what the model would receive, in this order, with the number behind it
    assert [(h.hashtag.tag, h.recent_views, h.recent_posts) for h in popular] == [
        (watched, 100_000, 2),
        (relevant, 300, 1),
        (stale, 0, 0),
    ]
    assert repo.resolve_popular(TENANT, term, limit=1, now=NOW)[0].hashtag.tag == watched


def test_resolve_popular_without_views_is_resolve(repo: HashtagRepository) -> None:
    term = _word()
    a, b, c = _word(), _word(), _word()
    _rubro(repo, term, [(a, 3), (b, 2), (c, 1)])
    plain = repo.resolve(TENANT, term, limit=4)
    popular = repo.resolve_popular(TENANT, term, limit=4, now=NOW)
    assert [h.hashtag.tag for h in popular] == [h.hashtag.tag for h in plain]
    assert all(h.recent_views == 0 for h in plain)  # `resolve` itself is unchanged
    assert repo.resolve_popular(TENANT, "ab", now=NOW) == ()


# -- catalog.capture: a referentes phase (acceptance 1) --------------------------------


@dataclass(frozen=True)
class _Post:
    post_id: str
    posted_ts: int | None
    views: int | None
    hashtags: tuple[str, ...]
    source: str = "tiktok:hashtag:#prueba"  # a query label, as the feeds give it


@dataclass
class _Account:
    network: str
    username: str
    hashtags_seen: list[str]
    post_sightings: list[_Post] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return (self.network, self.username.lower())


def _seed() -> DiscoverySeed:
    return DiscoverySeed(handle="x", niches=(), terms=(), country_code="CO", city="Cúcuta")


def test_capture_stores_views_and_dates_of_the_phase_posts(repo: HashtagRepository) -> None:
    tag, other = _word(), _word()
    ts = int((NOW - timedelta(days=6)).timestamp())
    accounts = [
        _Account(
            "tiktok",
            "a",
            [tag, other],
            [_Post("v1", ts, 12_000, (tag, other)), _Post("v2", None, 99, (tag,))],
        ),
        # the same video reached through another query, with a fresher count
        _Account("tiktok", "a2", [tag], [_Post("v1", ts, 15_000, (tag,), "tiktok:keyword:x")]),
        # an account with no post detail (an older caller) still feeds the counts
        _Account("instagram", "b", [tag]),
    ]
    summary = hashtag_catalog.capture(TENANT, _seed(), "national", accounts, repository=repo)
    assert summary.sightings == 3  # (tag,v1) (other,v1) (tag,v2) — none for b
    recent = repo.recent_views(TENANT, [tag, other], now=NOW)
    assert (recent[tag].views, recent[tag].posts) == (15_000, 1)  # v2 is undated
    assert (recent[other].views, recent[other].posts) == (12_000, 1)

    again = hashtag_catalog.capture(TENANT, _seed(), "national", accounts, repository=repo)
    assert again.sightings == summary.sightings
    assert repo.recent_views(TENANT, [tag], now=NOW)[tag] == recent[tag]


# -- catalog.capture_reels / backfill_public_reels: a reels read (acceptance 1) ---------


def _reel(reel_id: str, caption: str, *, views: int | None, days_ago: float) -> ReelPost:
    return ReelPost(
        network="instagram",
        reel_id=reel_id,
        taken_at=NOW - timedelta(days=days_ago),
        caption=caption,
        views=views,
        parser_version=2,
    )


def test_capture_reels_stores_each_caption_tag_once_per_reel(repo: HashtagRepository) -> None:
    tag, other = _word(), _word()
    reels = [
        _reel("r1", f"Shawarma #{tag} #{other} #{tag.upper()}", views=7_000, days_ago=3),
        _reel("r2", f"otro #{tag}", views=None, days_ago=1),
        _reel("r3", "sin etiquetas", views=10, days_ago=1),
    ]
    summary = hashtag_catalog.capture_reels(TENANT, reels, repository=repo)
    assert summary.sightings == 3
    assert hashtag_catalog.capture_reels(TENANT, reels, repository=repo).sightings == 3
    recent = repo.recent_views(TENANT, [tag, other], now=NOW)
    assert (recent[tag].views, recent[tag].posts) == (7_000, 2)
    assert (recent[other].views, recent[other].posts) == (7_000, 1)
    stored = repo.get(TENANT, tag)
    assert stored is not None and stored.seen_count == 0  # re-running never inflates it


def test_backfill_reads_only_reels_inside_the_window() -> None:
    repo = MemoryHashtagRepository()
    tag = _word()
    repo.public_reels = [
        _reel("new", f"#{tag}", views=50, days_ago=10),
        _reel("old", f"#{tag}", views=9_999, days_ago=POPULAR_WINDOW_DAYS + 30),
    ]
    summary = hashtag_catalog.backfill_public_reels(TENANT, now=NOW, repository=repo)
    assert summary.sightings == 1
    assert repo.recent_views(TENANT, [tag], now=NOW)[tag].views == 50


@pytest.mark.db
def test_public_reels_since_reads_the_shared_table() -> None:
    # Read-only against 0117's table: whatever rows exist, every one is inside the window.
    since = NOW - timedelta(days=POPULAR_WINDOW_DAYS)
    rows = PostgresHashtagRepository().public_reels_since(TENANT, since)
    assert all(r.taken_at >= since for r in rows)


# -- one lock order for every writer (re-review item B) -----------------------------------

_NON_ASCII = ["pizza", "ñoquis", "árepa", "arepa", "zumo", "éxito", "Ñame".lower(), "café"]


def test_every_writer_sorts_by_code_point(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.hashtags import Classification
    from qualify_api.hashtags import repository as module

    expected = sorted(_NON_ASCII)  # Python `str` order = code point
    assert expected.index("pizza") < expected.index("ñoquis")  # en_US would invert these
    shuffled = list(reversed(_NON_ASCII))
    repo = PostgresHashtagRepository()

    for write in (
        lambda: repo.upsert_hashtags(
            TENANT, [NewHashtag(tag=t, source="observed") for t in shuffled]
        ),
        lambda: repo.link_terms(
            TENANT, [NewTermLink(term="x" * 3, tag=t, source="observed") for t in shuffled]
        ),
        lambda: repo.apply_classifications(
            TENANT, [Classification(tag=t, kind="topic") for t in shuffled]
        ),
    ):
        recorder = _Recorder()
        monkeypatch.setattr(module, "tenant_session", recorder)
        write()
        order = list(dict.fromkeys(params["tag"] for _sql, params in recorder.calls))
        assert order == expected

    recorder = _Recorder()
    monkeypatch.setattr(module, "tenant_session", recorder)
    repo.record_post_sightings(TENANT, [_sighting(t, "p", views=1, days_ago=1) for t in shuffled])
    (tag_sql, tag_params), (sighting_sql, sighting_params) = recorder.calls
    assert tag_params["tags"] == expected and sighting_params["tags"] == expected
    assert 'ORDER BY u.tag COLLATE "C"' in tag_sql and 'u.tag COLLATE "C"' in sighting_sql


@pytest.mark.db
def test_python_order_and_sql_order_agree_on_non_ascii_tags() -> None:
    with tenant_session(TENANT) as session:
        by_c = session.scalars(
            text('SELECT t FROM unnest(CAST(:tags AS text[])) AS t ORDER BY t COLLATE "C"'),
            {"tags": list(reversed(_NON_ASCII))},
        ).all()
    assert by_c == sorted(_NON_ASCII)


# -- the reel-only exclusion applies to reel-born tags only (re-review item C) -------------


def test_an_ai_tag_seen_in_a_reel_keeps_its_place_in_the_queue(repo: HashtagRepository) -> None:
    tag = _word()
    repo.upsert_hashtags(TENANT, [NewHashtag(tag=tag, source="ai")])  # remember_created, no term
    assert tag in {t.tag for t in repo.needs_classification(TENANT, limit=100_000)}
    hashtag_catalog.capture_reels(
        TENANT, [ReelPost("tiktok", _word(), NOW, f"#{tag}", 3, 2)], repository=repo
    )
    assert tag in {t.tag for t in repo.needs_classification(TENANT, limit=100_000)}
