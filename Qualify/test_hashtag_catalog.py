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


# -- ai_hashtags_for (Claude chooses; fakes stand in for the API) --------------------------

from qualify_api.hashtags import ai as hashtag_ai  # noqa: E402


@pytest.fixture
def fresh_choices(monkeypatch):
    monkeypatch.setattr(hashtag_catalog, "_seeded", False)
    monkeypatch.setattr(hashtag_catalog, "_choices", {})
    monkeypatch.setenv("QUALIFY_ANTHROPIC_API_KEY", "sk-test")


def _selector(picks: list[str], calls: list | None = None):
    def select(brand, catalog, niches, *, api_key, starting, max_picks):
        if calls is not None:
            calls.append((brand, catalog, niches, [c.tag for c in starting], api_key, max_picks))
        chosen = [hashtag_ai.HashtagPick(t, "alta", f"encaja: {t}") for t in picks]
        return chosen, hashtag_ai.CallStats("claude-sonnet-5", "claude-sonnet-5", 900, 150)

    return select


def test_ai_choice_gets_a_starting_list_tools_and_keeps_provenance(repo, fresh_choices) -> None:
    _taught(repo, "smash burgers", ["smashburger", "burgerlovers", "cucutafood", "fyp"])
    calls: list = []
    seed = _seed(niches=("food_drink",), terms=("smash burgers",), hashtags=("burgerlovers",))
    choice = hashtag_catalog.ai_hashtags_for(
        TENANT, seed, bio="Smash 🍔", repository=repo, selector=_selector(["smashburger"], calls)
    )
    brand, catalog, niches, starting, key, max_picks = calls[0]
    assert (brand.bio, brand.own_hashtags, key) == ("Smash 🍔", ("burgerlovers",), "sk-test")
    assert max_picks == creator_discovery.SECTOR_CATALOG_TAGS
    assert niches == creator_discovery.NICHE_LABELS
    # the lexical hit, the niche's tags — never places, generic tags or the brand's own
    assert {"smashburger", "foodie", "comida"} <= set(starting)
    assert not {"cucutafood", "fyp", "burgerlovers"} & set(starting)
    assert choice.by == "ai" and choice.tags == ("smashburger",)
    assert choice.picks["smashburger"] == {
        "model": "claude-sonnet-5",
        "fit": "alta",
        "reason": "encaja: smashburger",
    }


def test_the_catalog_tools_apply_the_same_filter(repo, fresh_choices) -> None:
    """Whatever Claude searches for, a place, a generic tag or the brand's own tag is
    never shown to it — the filter lives on the catalog side of the tools."""
    _taught(repo, "smash burgers", ["smashburger", "burgerlovers", "cucutaburger", "fyp"])
    seed = _seed(terms=("smash burgers",), hashtags=("burgerlovers",))
    tools = hashtag_catalog.CatalogTools(TENANT, seed, repo)
    assert [c.tag for c in tools.search("smash burgers")] == ["smashburger"]
    hashtag_catalog.ensure_seeded(TENANT, repository=repo)
    assert {c.tag for c in tools.niche("food_drink")} == {"food", "foodie", "comida"}
    assert tools.search("zzqqxxww") == []


def test_an_empty_ai_choice_is_respected_not_replaced(repo, fresh_choices) -> None:
    seed = _seed(niches=("food_drink",), terms=("taller de motos",))
    choice = hashtag_catalog.ai_hashtags_for(TENANT, seed, repository=repo, selector=_selector([]))
    assert (choice.by, choice.tags) == ("ai", ())


def test_without_a_key_the_rule_path_answers(repo, fresh_choices, monkeypatch) -> None:
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY")
    seed = _seed(niches=("food_drink",), terms=())

    def never(*_a, **_k):
        raise AssertionError("no AI call without a key")

    choice = hashtag_catalog.ai_hashtags_for(TENANT, seed, repository=repo, selector=never)
    assert choice.by == "rule"
    assert set(choice.tags) == {"food", "foodie", "comida"}


def test_a_failed_ai_call_falls_back_to_the_rule_path(repo, fresh_choices) -> None:
    def boom(*_a, **_k):
        raise hashtag_ai.HashtagAIError("refused")

    seed = _seed(niches=("food_drink",), terms=())
    choice = hashtag_catalog.ai_hashtags_for(TENANT, seed, repository=repo, selector=boom)
    assert choice.by == "rule" and choice.picks == {}


def test_the_same_brand_is_not_asked_twice_within_the_ttl(repo, fresh_choices) -> None:
    calls: list = []
    seed = _seed(niches=("food_drink",), terms=())
    for moment in (1_000.0, 1_000.0 + 3600):
        hashtag_catalog.ai_hashtags_for(
            TENANT, seed, repository=repo, selector=_selector(["foodie"], calls), now=moment
        )
    assert len(calls) == 1
    hashtag_catalog.ai_hashtags_for(
        TENANT, seed, repository=repo, selector=_selector(["foodie"], calls), now=1_000.0 + 86_400
    )
    assert len(calls) == 2


# -- classify_pending ----------------------------------------------------------------------


def _classifier(answers: dict[str, tuple[str, str | None]], calls: list | None = None):
    def classify(tags, niches, *, api_key):
        if calls is not None:
            calls.append(list(tags))
        results = [hashtag_ai.TagClassification(t, *answers[t], None) for t in tags if t in answers]
        return results, hashtag_ai.CallStats("claude-haiku-4-5", "claude-haiku-4-5", 500, 300)

    return classify


def test_classify_pending_settles_what_the_rule_left_open(repo, fresh_choices) -> None:
    hashtag_catalog.capture(
        TENANT,
        _seed(),
        "national",
        [_cand("a", ["techtok", "xqzvbnm", "cucutafood"])],
        repository=repo,
    )
    calls: list = []
    summary = hashtag_catalog.classify_pending(
        TENANT,
        repository=repo,
        classifier=_classifier(
            {"techtok": ("topic", "technology"), "xqzvbnm": ("noise", None)}, calls
        ),
    )
    assert calls == [["techtok", "xqzvbnm"]]  # the rule already knew cucutafood is a place
    assert (summary.asked, summary.changed) == (2, 2)
    stored = repo.get(TENANT, "techtok")
    assert (stored.kind, stored.niche, stored.classified_by) == ("topic", "technology", "ai")
    assert repo.needs_classification(TENANT) == ()
    # nothing left: the next pass makes no call at all
    assert (
        hashtag_catalog.classify_pending(
            TENANT, repository=repo, classifier=_classifier({}, calls)
        ).asked
        == 0
    )
    assert len(calls) == 1


def test_classify_pending_without_a_key_changes_nothing(repo, fresh_choices, monkeypatch) -> None:
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY")
    hashtag_catalog.capture(TENANT, _seed(), "national", [_cand("a", ["techtok"])], repository=repo)

    def never(*_a, **_k):
        raise AssertionError("no AI call without a key")

    assert hashtag_catalog.classify_pending(TENANT, repository=repo, classifier=never).changed == 0
    assert repo.get(TENANT, "techtok").kind == "unknown"


def test_classify_pending_never_raises(repo, fresh_choices) -> None:
    hashtag_catalog.capture(TENANT, _seed(), "national", [_cand("a", ["techtok"])], repository=repo)

    def boom(*_a, **_k):
        raise RuntimeError("network down")

    summary = hashtag_catalog.classify_pending(TENANT, repository=repo, classifier=boom)
    assert (summary.asked, summary.changed) == (1, 0)
