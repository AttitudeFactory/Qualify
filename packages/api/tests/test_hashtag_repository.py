"""The hashtag catalog contract (migration 0023), run against BOTH implementations:
`MemoryHashtagRepository` offline, `PostgresHashtagRepository` against the compose
Postgres (`db` marker) — so the database's own guarantees (the CHECKs, the trigram
fuzzy match, the upsert's classification rule) are exercised, not just this module's belief
in them.

The catalog is SHARED and persists across runs, so every test builds its own words from a
random token (`_word`): a real rubro spelled the same in two runs would otherwise see the
rows the previous run left behind."""

from __future__ import annotations

import string
from uuid import UUID, uuid4

import pytest

from qualify_api.hashtags import (
    MATCH_FUZZY_TAG,
    MATCH_FUZZY_TERM,
    MATCH_TERM,
    HashtagRepository,
    MemoryHashtagRepository,
    NewHashtag,
    NewTermLink,
    PostgresHashtagRepository,
    fold,
    normalize_tag,
)

TENANT = UUID("7a7a0000-0000-4000-8000-0000000000a1")


def _word() -> str:
    """A pronounceable-enough token unique to one test: hex digits mapped to letters, so
    it survives `fold` (which keeps digits too, but letters make trigrams that do not
    collide with another run's word)."""
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


# -- normalization -----------------------------------------------------------------------


def test_normalize_tag_strips_hash_and_lowercases() -> None:
    assert normalize_tag("  #CucutaFood ") == "cucutafood"


@pytest.mark.parametrize("bad", ["", "#", "dos palabras", "a#b"])
def test_normalize_tag_rejects_what_is_not_one_token(bad: str) -> None:
    with pytest.raises(ValueError):
        normalize_tag(bad)


def test_fold_drops_accents_spaces_and_punctuation() -> None:
    assert fold("Peluquería Canina!") == "peluqueriacanina"


def test_new_hashtag_validates_its_vocabulary() -> None:
    with pytest.raises(ValueError):
        NewHashtag(tag="ok", source="nope")
    with pytest.raises(ValueError):
        NewHashtag(tag="ok", source="observed", kind="weird")
    with pytest.raises(ValueError):
        NewHashtag(tag="ok", source="observed", country_code="COL")
    with pytest.raises(ValueError):
        NewHashtag(tag="___", source="observed")
    assert NewHashtag(tag="ok", source="observed", country_code="co").country_code == "CO"


def test_new_term_link_validates() -> None:
    with pytest.raises(ValueError):
        NewTermLink(term="!!!", tag="ok", source="observed")
    with pytest.raises(ValueError):
        NewTermLink(term="x y", tag="ok", source="observed", weight=0)


# -- upsert ------------------------------------------------------------------------------


def test_upsert_creates_then_accumulates_sightings(repo: HashtagRepository) -> None:
    tag = f"{_word()}food"
    repo.upsert_hashtags(TENANT, [NewHashtag(tag=tag, source="observed", network="tiktok", seen=2)])
    repo.upsert_hashtags(
        TENANT, [NewHashtag(tag=f"#{tag.upper()}", source="observed", network="instagram", seen=3)]
    )
    stored = repo.get(TENANT, tag)
    assert stored is not None
    assert stored.tag == tag
    assert stored.seen_count == 5
    assert stored.networks == ("instagram", "tiktok")
    assert stored.source == "observed"
    assert stored.last_seen_at >= stored.first_seen_at


def test_upsert_counts_distinct_tags(repo: HashtagRepository) -> None:
    tag = _word()
    written = repo.upsert_hashtags(
        TENANT, [NewHashtag(tag=tag, source="observed"), NewHashtag(tag=tag, source="observed")]
    )
    assert written == 1


def test_a_sighting_never_erases_what_is_known(repo: HashtagRepository) -> None:
    tag = f"{_word()}gym"
    repo.upsert_hashtags(
        TENANT,
        [NewHashtag(tag=tag, source="taxonomy", kind="topic", niche="fitness_sports")],
    )
    repo.upsert_hashtags(TENANT, [NewHashtag(tag=tag, source="observed", seen=1)])
    stored = repo.get(TENANT, tag)
    assert stored is not None
    assert (stored.kind, stored.niche, stored.source) == ("topic", "fitness_sports", "taxonomy")


def test_classification_only_moves_up_the_classifier_ranking(repo: HashtagRepository) -> None:
    tag = f"{_word()}moda"
    repo.upsert_hashtags(TENANT, [NewHashtag(tag=tag, source="observed")])  # unknown, rule

    # unknown → decided: any classifier may fill in what nobody decided.
    repo.upsert_hashtags(
        TENANT, [NewHashtag(tag=tag, source="observed", kind="topic", niche="fashion_beauty")]
    )
    # same rank does not replace the first decision
    repo.upsert_hashtags(TENANT, [NewHashtag(tag=tag, source="observed", kind="generic")])
    stored = repo.get(TENANT, tag)
    assert stored is not None and (stored.kind, stored.classified_by) == ("topic", "rule")

    # a stronger classifier does
    repo.upsert_hashtags(
        TENANT,
        [NewHashtag(tag=tag, source="ai", kind="place", classified_by="ai", country_code="CO")],
    )
    stored = repo.get(TENANT, tag)
    assert stored is not None
    assert (stored.kind, stored.classified_by, stored.country_code) == ("place", "ai", "CO")

    # a person's decision is final: neither a rule nor an AI pass moves it
    repo.upsert_hashtags(
        TENANT, [NewHashtag(tag=tag, source="manual", kind="noise", classified_by="manual")]
    )
    repo.upsert_hashtags(
        TENANT, [NewHashtag(tag=tag, source="ai", kind="topic", classified_by="ai")]
    )
    stored = repo.get(TENANT, tag)
    assert stored is not None and (stored.kind, stored.classified_by) == ("noise", "manual")


def test_an_unknown_kind_never_replaces_a_decision(repo: HashtagRepository) -> None:
    tag = f"{_word()}chef"
    repo.upsert_hashtags(TENANT, [NewHashtag(tag=tag, source="taxonomy", kind="topic")])
    repo.upsert_hashtags(
        TENANT, [NewHashtag(tag=tag, source="ai", kind="unknown", classified_by="manual")]
    )
    stored = repo.get(TENANT, tag)
    assert stored is not None and stored.kind == "topic"


def test_get_of_an_unseen_tag_is_none(repo: HashtagRepository) -> None:
    assert repo.get(TENANT, _word()) is None


# -- resolve -----------------------------------------------------------------------------


def _seed_rubro(repo: HashtagRepository, word: str) -> tuple[str, str]:
    """`<word>canina` as a rubro term, with two hashtags of different weight."""
    term = f"{word} canina"
    main, minor = f"{word}caninos", f"{word}perritos"
    repo.upsert_hashtags(
        TENANT,
        [
            NewHashtag(tag=main, source="taxonomy", kind="topic", seen=10),
            NewHashtag(tag=minor, source="taxonomy", kind="topic", seen=1),
        ],
    )
    repo.link_terms(
        TENANT,
        [
            NewTermLink(term=term, tag=main, source="taxonomy", weight=5),
            NewTermLink(term=term, tag=minor, source="taxonomy", weight=1),
        ],
    )
    return term, main


def test_exact_term_resolves_by_weight(repo: HashtagRepository) -> None:
    word = _word()
    term, main = _seed_rubro(repo, word)
    # spelling, case, accents and spacing do not matter
    hits = repo.resolve(TENANT, f"  {word.upper()}  Canina ")
    assert [h.match for h in hits] == [MATCH_TERM, MATCH_TERM]
    assert hits[0].hashtag.tag == main
    assert hits[0].score == 1.0


def test_a_typo_resolves_through_the_fuzzy_tier(repo: HashtagRepository) -> None:
    word = _word()
    _, main = _seed_rubro(repo, word)
    typo = f"{word[:4]}{word[5:]} canina"  # one letter dropped
    hits = repo.resolve(TENANT, typo)
    assert hits, "a one-letter typo of a known rubro must still resolve"
    assert hits[0].match == MATCH_FUZZY_TERM
    assert hits[0].hashtag.tag == main
    assert 0.5 <= hits[0].score < 1.0


def test_a_typed_hashtag_resolves_through_the_fuzzy_tag_tier(repo: HashtagRepository) -> None:
    tag = f"{_word()}comidarapida"
    repo.upsert_hashtags(TENANT, [NewHashtag(tag=tag, source="observed", kind="topic", seen=1)])
    hits = repo.resolve(TENANT, tag[:-1])  # nobody linked a term to it
    assert hits and hits[0].match == MATCH_FUZZY_TAG
    assert hits[0].hashtag.tag == tag


def test_garbage_resolves_to_nothing(repo: HashtagRepository) -> None:
    _seed_rubro(repo, _word())
    assert repo.resolve(TENANT, "qzxwvkjhgfd") == ()
    assert repo.resolve(TENANT, "ab") == ()  # too short to mean anything
    assert repo.resolve(TENANT, "  !!  ") == ()


def test_generic_and_noise_tags_never_steer_a_search(repo: HashtagRepository) -> None:
    word = _word()
    term = f"{word} viral"
    repo.upsert_hashtags(
        TENANT,
        [
            NewHashtag(tag=f"{word}fyp", source="observed", kind="generic"),
            NewHashtag(tag=f"{word}spam", source="observed", kind="noise"),
            NewHashtag(tag=f"{word}real", source="observed", kind="topic"),
        ],
    )
    repo.link_terms(
        TENANT,
        [
            NewTermLink(term=term, tag=f"{word}{k}", source="observed")
            for k in ("fyp", "spam", "real")
        ],
    )
    assert [h.hashtag.tag for h in repo.resolve(TENANT, term)] == [f"{word}real"]
    everything = repo.resolve(TENANT, term, kinds=("topic", "generic", "noise"))
    assert len(everything) == 3


def test_resolve_prefers_the_strongest_tier_only(repo: HashtagRepository) -> None:
    word = _word()
    term, _ = _seed_rubro(repo, word)
    repo.upsert_hashtags(
        TENANT, [NewHashtag(tag=f"{word}cania", source="observed", kind="topic", seen=99)]
    )
    hits = repo.resolve(TENANT, term)  # exact tier has hits: the fuzzy tag never mixes in
    assert {h.match for h in hits} == {MATCH_TERM}


def test_resolve_respects_limit(repo: HashtagRepository) -> None:
    word = _word()
    term, _ = _seed_rubro(repo, word)
    assert len(repo.resolve(TENANT, term, limit=1)) == 1


# -- link_terms --------------------------------------------------------------------------


def test_link_creates_a_tag_the_catalog_had_not_seen(repo: HashtagRepository) -> None:
    word = _word()
    tag = f"{word}nuevo"
    repo.link_terms(TENANT, [NewTermLink(term=f"{word} rubro", tag=tag, source="observed")])
    stored = repo.get(TENANT, tag)
    assert stored is not None
    assert (stored.kind, stored.seen_count, stored.source) == ("unknown", 0, "observed")
    assert [h.hashtag.tag for h in repo.resolve(TENANT, f"{word} rubro", kinds=("unknown",))] == [
        tag
    ]


def test_observed_links_accumulate_but_a_seed_is_idempotent(repo: HashtagRepository) -> None:
    word = _word()
    tag_seed, tag_obs = f"{word}seed", f"{word}obs"
    term = f"{word} algo"
    for _ in range(3):
        repo.link_terms(
            TENANT, [NewTermLink(term=term, tag=tag_seed, source="taxonomy", accumulate=False)]
        )
    repo.link_terms(TENANT, [NewTermLink(term=term, tag=tag_obs, source="observed")])
    repo.link_terms(TENANT, [NewTermLink(term=term, tag=tag_obs, source="observed")])
    # observed twice (weight 2) outranks the seed run three times (weight stays 1)
    hits = repo.resolve(TENANT, term, kinds=("unknown",))
    assert [h.hashtag.tag for h in hits] == [tag_obs, tag_seed]


def test_link_returns_distinct_links_written(repo: HashtagRepository) -> None:
    word = _word()
    link = NewTermLink(term=f"{word} x", tag=f"{word}y", source="observed")
    assert repo.link_terms(TENANT, [link, link]) == 1


# -- for_niche ---------------------------------------------------------------------------


def test_for_niche_orders_by_sightings(repo: HashtagRepository) -> None:
    niche = f"niche_{_word()}"
    repo.upsert_hashtags(
        TENANT,
        [
            NewHashtag(tag=f"{_word()}a", source="taxonomy", kind="topic", niche=niche, seen=1),
            NewHashtag(tag=f"{_word()}b", source="taxonomy", kind="topic", niche=niche, seen=9),
        ],
    )
    tags = repo.for_niche(TENANT, niche)
    assert [t.seen_count for t in tags] == [9, 1]
    assert repo.for_niche(TENANT, niche, limit=1)[0].seen_count == 9
    assert repo.for_niche(TENANT, f"niche_{_word()}") == ()


# -- the database's own floor (Postgres only) ---------------------------------------------


@pytest.mark.db
def test_the_database_rejects_a_tag_the_repository_would_never_write() -> None:
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    for bad in ("#withhash", "Upper", "has space", ""):
        with pytest.raises(IntegrityError), tenant_session(TENANT) as session:
            session.execute(
                text("INSERT INTO hashtags (tag, slug, source) VALUES (:tag, 'x', 'observed')"),
                {"tag": bad},
            )


@pytest.mark.db
def test_the_catalog_is_shared_not_tenant_scoped() -> None:
    """One tenant's write is visible to another: the catalog is public data by design
    (0023's docstring), and this pins that it stays that way."""
    other = UUID("7a7a0000-0000-4000-8000-0000000000a2")
    repo = PostgresHashtagRepository()
    tag = f"{_word()}shared"
    repo.upsert_hashtags(TENANT, [NewHashtag(tag=tag, source="observed", seen=1)])
    assert repo.get(other, tag) is not None
