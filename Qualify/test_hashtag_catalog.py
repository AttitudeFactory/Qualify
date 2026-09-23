"""`hashtag_catalog`: the taxonomy becomes data, and a phase's hashtags feed the catalog.
Runs on `MemoryHashtagRepository` — the Postgres implementation has its own contract suite
(`packages/api/tests/test_hashtag_repository.py`)."""

from __future__ import annotations

from uuid import UUID

import pytest
from qualify_api.hashtags import MATCH_TERM, MemoryHashtagRepository

from . import creator_discovery, hashtag_catalog
from .creator_discovery import Candidate, DiscoverySeed

TENANT = UUID("7a7a0000-0000-4000-8000-0000000000b1")


@pytest.fixture
def repo() -> MemoryHashtagRepository:
    return MemoryHashtagRepository()


def _seed(**kw) -> DiscoverySeed:
    base = {
        "handle": "midu",
        "niches": (),
        "terms": ("peluquería canina",),
        "country_code": "CO",
        "city": "Cúcuta",
    }
    base.update(kw)
    return DiscoverySeed(**base)


def _cand(user: str, tags: list[str], network: str = "tiktok") -> Candidate:
    return Candidate(network=network, username=user, hashtags_seen=tags)


# -- seed_taxonomy -----------------------------------------------------------------------


def test_seed_stores_every_taxonomy_hashtag_as_a_topic_of_its_niche(repo) -> None:
    summary = hashtag_catalog.seed_taxonomy(TENANT, repository=repo)
    expected = {t for spec in creator_discovery.NICHE_TAXONOMY.values() for t in spec["hashtags"]}
    assert summary.hashtags == len(expected)
    stored = repo.get(TENANT, "foodie")
    assert stored is not None
    assert (stored.kind, stored.niche, stored.source) == ("topic", "food_drink", "taxonomy")


def test_seed_links_the_niches_own_words_to_its_hashtags(repo) -> None:
    hashtag_catalog.seed_taxonomy(TENANT, repository=repo)
    hits = repo.resolve(TENANT, "recetas")
    assert hits and all(h.match == MATCH_TERM for h in hits)
    assert {h.hashtag.tag for h in hits} == {"food", "foodie", "comida"}
    # the niche label resolves too, accents and case aside
    label = creator_discovery.NICHE_LABELS["food_drink"]
    assert {h.hashtag.tag for h in repo.resolve(TENANT, label.upper())} >= {"foodie"}


def test_seeding_twice_changes_nothing(repo) -> None:
    hashtag_catalog.seed_taxonomy(TENANT, repository=repo)
    first = [(h.hashtag.tag, h.score) for h in repo.resolve(TENANT, "comida")]
    before = repo.get(TENANT, "food")
    hashtag_catalog.seed_taxonomy(TENANT, repository=repo)
    assert [(h.hashtag.tag, h.score) for h in repo.resolve(TENANT, "comida")] == first
    after = repo.get(TENANT, "food")
    assert (before.seen_count, before.kind) == (after.seen_count, after.kind)


def test_a_typo_of_a_taxonomy_word_resolves_after_seeding(repo) -> None:
    hashtag_catalog.seed_taxonomy(TENANT, repository=repo)
    hits = repo.resolve(TENANT, "restaurnates")  # transposed letters
    assert {h.hashtag.tag for h in hits} >= {"foodie"}


# -- classify_tag ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tag", "kind"),
    [
        ("fyp", "generic"),
        ("cucutafood", "place"),  # the seed's city
        ("colombia", "place"),  # the seed's country
        ("maracaibo", "place"),  # a known city, not the seed's
        ("programacion", "topic"),
        ("xyzzyplugh", "unknown"),
    ],
)
def test_classify_tag(tag: str, kind: str) -> None:
    assert hashtag_catalog.classify_tag(tag, _seed())[0] == kind


def test_a_topic_tag_carries_its_niche_and_a_place_its_country() -> None:
    assert hashtag_catalog.classify_tag("programacion", _seed())[1] == "technology"
    assert hashtag_catalog.classify_tag("cucutafood", _seed())[2] == "CO"
    assert hashtag_catalog.classify_tag("fyp", _seed()) == ("generic", None, None)


# -- capture -----------------------------------------------------------------------------


def test_capture_counts_one_sighting_per_account_per_network(repo) -> None:
    accounts = [
        _cand("a", ["groomingperros", "groomingperros", "#Perritos"]),  # dup within one account
        _cand("b", ["groomingperros"]),
        _cand("c", ["groomingperros"], network="instagram"),
    ]
    summary = hashtag_catalog.capture(TENANT, _seed(), "national", accounts, repository=repo)
    assert summary.hashtags == 2
    grooming = repo.get(TENANT, "groomingperros")
    assert grooming is not None
    assert grooming.seen_count == 3  # a, b (tiktok) + c (instagram)
    assert grooming.networks == ("instagram", "tiktok")
    assert grooming.source == "observed"
    assert repo.get(TENANT, "perritos") is not None  # `#` stripped, lowercased


def test_only_the_sector_phase_teaches_the_rubro_its_hashtags(repo) -> None:
    accounts = [_cand("a", ["groomingperros"]), _cand("b", ["groomingperros"])]
    for phase in ("national", "local"):
        summary = hashtag_catalog.capture(TENANT, _seed(), phase, accounts, repository=repo)
        assert summary.links == 0
    assert repo.resolve(TENANT, "peluquería canina") == ()

    summary = hashtag_catalog.capture(TENANT, _seed(), "sector", accounts, repository=repo)
    assert summary.links == 1
    hits = repo.resolve(TENANT, "peluqueria canina")
    assert [h.hashtag.tag for h in hits] == ["groomingperros"]
    assert hits[0].match == MATCH_TERM


def test_a_hashtag_one_account_used_is_a_habit_not_a_link(repo) -> None:
    accounts = [_cand("a", ["soloyo", "groomingperros"]), _cand("b", ["groomingperros"])]
    hashtag_catalog.capture(TENANT, _seed(), "sector", accounts, repository=repo)
    assert [h.hashtag.tag for h in repo.resolve(TENANT, "peluquería canina")] == ["groomingperros"]


def test_generic_and_place_tags_are_stored_but_never_linked(repo) -> None:
    accounts = [
        _cand("a", ["fyp", "cucutafood", "groomingperros"]),
        _cand("b", ["fyp", "cucutafood", "groomingperros"]),
    ]
    hashtag_catalog.capture(TENANT, _seed(), "sector", accounts, repository=repo)
    assert repo.get(TENANT, "fyp").kind == "generic"
    assert repo.get(TENANT, "cucutafood").kind == "place"
    assert [h.hashtag.tag for h in repo.resolve(TENANT, "peluquería canina")] == ["groomingperros"]


def test_a_rerun_strengthens_the_link(repo) -> None:
    accounts = [
        _cand("a", ["groomingperros", "perritos"]),
        _cand("b", ["groomingperros", "perritos"]),
    ]
    for _ in range(2):
        hashtag_catalog.capture(TENANT, _seed(), "sector", accounts, repository=repo)
    # more accounts use `groomingperros` afterwards: it now outranks `perritos`
    more = [_cand("c", ["groomingperros"]), _cand("d", ["groomingperros"])]
    hashtag_catalog.capture(TENANT, _seed(), "sector", more, repository=repo)
    hits = repo.resolve(TENANT, "peluquería canina")
    assert hits[0].hashtag.tag == "groomingperros"


def test_the_taxonomys_word_for_the_niche_is_taught_too(repo) -> None:
    seed = _seed(niches=("food_drink",), terms=())
    accounts = [_cand("a", ["comidacasera"]), _cand("b", ["comidacasera"])]
    hashtag_catalog.capture(TENANT, seed, "sector", accounts, repository=repo)
    assert "comidacasera" in {h.hashtag.tag for h in repo.resolve(TENANT, "foodie")}


def test_a_tag_the_repository_rejects_is_skipped_not_fatal(repo) -> None:
    accounts = [_cand("a", ["___", "buenotag"]), _cand("b", ["buenotag"])]
    summary = hashtag_catalog.capture(TENANT, _seed(), "sector", accounts, repository=repo)
    assert summary.skipped >= 1
    assert repo.get(TENANT, "buenotag") is not None


def test_capture_with_nothing_seen_writes_nothing(repo) -> None:
    summary = hashtag_catalog.capture(TENANT, _seed(), "sector", [_cand("a", [])], repository=repo)
    assert summary == hashtag_catalog.CaptureSummary()


def test_ensure_seeded_runs_once_per_process(repo, monkeypatch) -> None:
    monkeypatch.setattr(hashtag_catalog, "_seeded", False)
    assert hashtag_catalog.ensure_seeded(TENANT, repository=repo) is True
    assert repo.get(TENANT, "foodie") is not None
    assert hashtag_catalog.ensure_seeded(TENANT, repository=repo) is False


def test_a_failed_seed_is_retried(repo, monkeypatch) -> None:
    monkeypatch.setattr(hashtag_catalog, "_seeded", False)

    def boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(repo, "upsert_hashtags", boom)
    with pytest.raises(RuntimeError):
        hashtag_catalog.ensure_seeded(TENANT, repository=repo)
    assert hashtag_catalog._seeded is False


# -- catalog_hashtags_for ----------------------------------------------------------------


def _taught(repo, term: str, tags: list[str]) -> None:
    """A finished sector search for `term` whose accounts all used `tags`."""
    seed = _seed(terms=(term,))
    accounts = [_cand("a", tags), _cand("b", tags), _cand("c", tags)]
    hashtag_catalog.capture(TENANT, seed, "sector", accounts, repository=repo)


def test_a_rubro_nothing_has_searched_yet_resolves_to_nothing(repo, monkeypatch) -> None:
    monkeypatch.setattr(hashtag_catalog, "_seeded", False)
    seed = _seed(terms=("xilofonos",))
    assert hashtag_catalog.catalog_hashtags_for(TENANT, seed, repository=repo) == ()


def test_a_search_teaches_the_next_operator_even_through_a_typo(repo, monkeypatch) -> None:
    monkeypatch.setattr(hashtag_catalog, "_seeded", False)
    _taught(repo, "smash burgers", ["smashburger", "burgerlovers", "fyp"])
    typo = _seed(terms=("smsh burgers",))
    found = hashtag_catalog.catalog_hashtags_for(TENANT, typo, repository=repo)
    assert set(found) == {"smashburger", "burgerlovers"}  # generic `fyp` never steers


def test_the_niches_most_seen_tags_come_along(repo, monkeypatch) -> None:
    monkeypatch.setattr(hashtag_catalog, "_seeded", False)
    seed = _seed(niches=("food_drink",), terms=())
    found = hashtag_catalog.catalog_hashtags_for(TENANT, seed, repository=repo)
    assert set(found) == {"food", "foodie", "comida"}


def test_own_hashtags_and_the_brands_own_name_are_not_repeated(repo, monkeypatch) -> None:
    monkeypatch.setattr(hashtag_catalog, "_seeded", False)
    _taught(repo, "smash burgers", ["smashburger", "burgerlovers", "midusmash"])
    seed = _seed(handle="midu", terms=("smash burgers",), hashtags=("burgerlovers",))
    assert hashtag_catalog.catalog_hashtags_for(TENANT, seed, repository=repo) == ("smashburger",)


def test_place_tags_never_steer_the_rubro(repo, monkeypatch) -> None:
    monkeypatch.setattr(hashtag_catalog, "_seeded", False)
    _taught(repo, "smash burgers", ["cucutafood", "smashburger"])
    seed = _seed(terms=("smash burgers",))
    assert hashtag_catalog.catalog_hashtags_for(TENANT, seed, repository=repo) == ("smashburger",)


def test_a_seed_carries_at_most_a_handful(repo, monkeypatch) -> None:
    monkeypatch.setattr(hashtag_catalog, "_seeded", False)
    _taught(repo, "smash burgers", [f"burgertag{i}" for i in range(9)])
    seed = _seed(terms=("smash burgers",))
    found = hashtag_catalog.catalog_hashtags_for(TENANT, seed, repository=repo)
    assert len(found) == hashtag_catalog.CATALOG_HASHTAGS
