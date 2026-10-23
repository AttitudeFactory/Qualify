"""The AI review of referentes, end to end without the network (§ request 2026-09-25):

- the search side (`creator_discovery.apply_review`, version 9): what the review drops,
  what it flags, and that a failed review never empties a phase nor gets stored;
- the bridge (`referentes_review`): the reviewer the wizard builds, the manual add's
  input parsing, lookup and review — which warns but never refuses;
- persistence (`referentes_provider`): manual referentes stored as the brand's manual
  pseudo-phase and restored in their bucket, never recomputed;
- the wizard's pieces (`card_view`, `manual_outcome`, the discarded list).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.claude_tools import CallStats
from qualify_api.referentes import MemoryReferentesRepository
from qualify_api.referentes.ai import AccountReview, AccountToReview, BrandBrief

from . import creative_wizard_pages as wiz
from . import creator_discovery as cd
from . import referentes_provider as rp
from . import referentes_review as rr

TENANT = UUID("5e5e0000-0000-4000-8000-0000000000c1")


def _candidate(network: str, username: str, followers: int, bio: str = "") -> cd.Candidate:
    return cd.Candidate(
        network=network,
        username=username,
        followers=followers,
        bio=bio,
        profile_url=f"https://{network}.com/@{username}",
        sources=[f"{network}:hashtag:#restaurante"],
    )


def _verdict(fits: bool, kind: str = "marca", reason: str = "r") -> cd.AccountVerdict:
    return cd.AccountVerdict(kind=kind, fits=fits, reason=reason, reviewed_by="claude-haiku-4-5")


# --------------------------------------------------------------------------------------
# the search: apply_review
# --------------------------------------------------------------------------------------


def test_the_review_drops_what_does_not_fit_and_flags_the_rest() -> None:
    chef = _candidate("instagram", "elchef", 50_000)
    hotdogs = _candidate("tiktok", "perrosya", 90_000)
    unanswered = _candidate("tiktok", "sinrespuesta", 10_000)
    seen: list[str] = []

    def reviewer(key: str, accounts: list[cd.Candidate]) -> dict[Any, cd.AccountVerdict]:
        seen.append(key)
        return {
            chef.key: _verdict(True, "creador", "Chef de cocina de autor."),
            hotdogs.key: _verdict(False, "marca", "Comida rápida, otro formato."),
        }

    result = cd.PhaseResult(key="sector", title="t")
    kept = cd.apply_review("sector", [chef, hotdogs, unanswered], reviewer, result)

    assert seen == ["sector"]
    # an account the model skipped counts as unreviewed, and stays
    assert {c.username for c in kept} == {"elchef", "sinrespuesta"}
    assert result.discarded == [hotdogs]
    assert (chef.account_kind, chef.review_reason) == ("creador", "Chef de cocina de autor.")
    assert chef.reviewed_by == "claude-haiku-4-5"
    assert unanswered.account_kind == ""
    card = cd.account_card(chef)
    assert (card["kind"], card["kind_label"]) == ("creador", "Creador")
    assert cd.phase_to_dict(result)["discarded"] == [
        {"handle": "@perrosya", "network": "TikTok", "reason": "Comida rápida, otro formato."}
    ]


def test_a_failed_review_falls_back_to_the_unreviewed_pick() -> None:
    accounts = [_candidate("tiktok", "a", 10), _candidate("instagram", "b", 20)]

    def broken(key: str, found: list[cd.Candidate]) -> dict[Any, cd.AccountVerdict]:
        raise RuntimeError("529 overloaded")

    result = cd.PhaseResult(key="sector", title="t")
    assert cd.apply_review("sector", accounts, broken, result) == accounts
    assert result.review_failed is True and result.discarded == []


def test_only_what_the_pick_could_reach_is_reviewed() -> None:
    many = [_candidate("tiktok", f"t{i}", 1000 + i) for i in range(15)]
    many += [_candidate("instagram", f"i{i}", 1000 + i) for i in range(3)]
    many.append(_candidate("tiktok", "nofollowers", 0))
    shortlist = cd.review_shortlist(many)
    assert len([c for c in shortlist if c.network == "tiktok"]) == cd.REVIEW_PER_NETWORK
    assert shortlist[0].username == "t14"  # best ranked first
    assert "nofollowers" not in {c.username for c in shortlist}  # the pick never shows it


def test_a_discarded_account_is_not_offered_by_a_later_phase() -> None:
    off_topic = _candidate("tiktok", "memes", 900_000)
    result = cd.PhaseResult(key="sector", title="t")
    cd.apply_review("sector", [off_topic], lambda k, a: {off_topic.key: _verdict(False)}, result)
    picked: set[tuple[str, str]] = set()
    picked.update(c.key for c in result.discarded)  # what run_phase does
    assert off_topic.key in picked


# --------------------------------------------------------------------------------------
# the bridge: make_reviewer
# --------------------------------------------------------------------------------------


def _seed() -> cd.DiscoverySeed:
    return cd.DiscoverySeed(
        handle="casaolivo",
        niches=("food_drink",),
        hashtags=("cocinadeautor",),
        country_code="CO",
        city="Bogotá",
        terms=("restaurante de autor",),
        chosen_hashtags=("restaurantesbogota",),
    )


class FakeReview:
    def __init__(self, answers: dict[str, tuple[str, bool, str]]) -> None:
        self.answers = answers
        self.calls: list[tuple[BrandBrief, list[AccountToReview], str]] = []

    def __call__(
        self, brief: BrandBrief, items: list[AccountToReview], *, api_key: str, config: Any
    ) -> tuple[list[AccountReview], CallStats]:
        self.calls.append((brief, list(items), api_key))
        out = [
            AccountReview(id=i.id, kind=k, fits=f, reason=r)
            for i in items
            if i.id in self.answers
            for k, f, r in [self.answers[i.id]]
        ]
        return out, CallStats(config.model_id, None, 100, 20)


def test_the_brief_carries_the_rubro_the_place_and_the_search_hashtags() -> None:
    brief = rr.brand_brief(_seed(), bio="Cocina colombiana", category="Restaurante")
    assert brief.rubro == ("restaurante de autor",)
    assert brief.niches == (cd.NICHE_LABELS["food_drink"],)
    assert brief.hashtags == ("cocinadeautor", "restaurantesbogota")
    assert (brief.city, brief.country) == ("Bogotá", "Colombia")


def test_without_an_api_key_there_is_no_reviewer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)
    assert rr.make_reviewer(rr.brand_brief(_seed())) is None


def test_the_reviewer_maps_answers_back_to_the_candidates() -> None:
    chef = _candidate("instagram", "ElChef", 50_000, bio="Chef en Bogotá")
    chef.texts.extend(["Chef", "Nuevo menú de temporada con productores del Pacífico colombiano"])
    chef.hashtags_seen.extend(["cocinadeautor"])
    fake = FakeReview({"instagram:elchef": ("creador", True, "Chef de autor.")})
    reviewer = rr.make_reviewer(rr.brand_brief(_seed()), api_key="sk-test", review=fake)
    assert reviewer is not None

    verdicts = reviewer("sector", [chef])

    assert verdicts == {
        chef.key: cd.AccountVerdict("creador", True, "Chef de autor.", "claude-sonnet-5")
    }
    brief, items, key = fake.calls[0]
    assert key == "sk-test"
    item = items[0]
    assert (item.id, item.handle, item.network) == ("instagram:elchef", "ElChef", "Instagram")
    assert item.category == "Chef"  # a short text is the Instagram category
    assert item.captions == ("Nuevo menú de temporada con productores del Pacífico colombiano",)
    assert item.hashtags == ("cocinadeautor",)


def test_a_shortlist_goes_out_as_parallel_calls_of_ten() -> None:
    accounts = [_candidate("tiktok", f"a{i}", 100 + i) for i in range(25)]
    fake = FakeReview({f"tiktok:a{i}": ("creador", True, "") for i in range(25)})
    reviewer = rr.make_reviewer(rr.brand_brief(_seed()), api_key="k", review=fake)
    assert reviewer is not None
    verdicts = reviewer("sector", accounts)
    assert sorted(len(items) for _, items, _ in fake.calls) == [5, 10, 10]
    assert len(verdicts) == 25


# --------------------------------------------------------------------------------------
# manual referentes: parsing
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "network", "expected"),
    [
        ("@ElChef", "instagram", ("instagram", "elchef", "https://www.instagram.com/elchef/")),
        ("elchef", "tiktok", ("tiktok", "elchef", "https://www.tiktok.com/@elchef")),
        (
            "https://www.instagram.com/elchef/?hl=es",
            "tiktok",  # a link decides its own network
            ("instagram", "elchef", "https://www.instagram.com/elchef/"),
        ),
        (
            "tiktok.com/@la.chef",
            "instagram",
            ("tiktok", "la.chef", "https://www.tiktok.com/@la.chef"),
        ),
        (
            "https://www.youtube.com/@CocinaConMaria",
            "instagram",
            ("youtube", "cocinaconmaria", "https://www.youtube.com/@cocinaconmaria"),
        ),
        (
            "https://www.linkedin.com/in/juan-perez-chef",
            "instagram",
            ("linkedin", "juan-perez-chef", "https://www.linkedin.com/in/juan-perez-chef"),
        ),
        ("https://pasteleriadonarosa.com", "web", ("web", "pasteleriadonarosa.com", None)),
        ("Pastelería Doña Rosa", "otro", ("otro", "pasteleria-dona-rosa", "")),
        # a plain name with Instagram selected is an account we cannot read
        ("Pastelería Doña Rosa", "instagram", ("otro", "pasteleria-dona-rosa", "")),
    ],
)
def test_manual_input_is_understood(
    text: str, network: str, expected: tuple[str, str, str | None]
) -> None:
    target = rr.parse_manual(text, network)
    assert (target.network, target.handle) == expected[:2]
    if expected[2] is not None:
        assert target.url == expected[2]


@pytest.mark.parametrize(
    ("text", "network"),
    [("", "instagram"), ("   ", "tiktok"), ("doña.rosa", "instagram"), ("https://x.com/", "x")],
)
def test_manual_input_that_cannot_be_used_says_why(text: str, network: str) -> None:
    with pytest.raises(ValueError) as error:
        rr.parse_manual(text, network)
    assert str(error.value)  # a message for the operator


# --------------------------------------------------------------------------------------
# manual referentes: lookup + review
# --------------------------------------------------------------------------------------


def _lookup(found: bool, bio: str = "") -> Any:
    def lookup(
        network: str, handle: str, *, store: Any = None, payload_cache: Any = None
    ) -> tuple[cd.Candidate, bool, None]:
        candidate = cd.Candidate(
            network=network,
            username=handle,
            profile_url=f"https://www.instagram.com/{handle}/",
            bio=bio,
            followers=800 if found else None,
            sources=[f"{network}:manual"],
        )
        return candidate, found, None

    return lookup


def test_a_small_account_is_read_reviewed_and_carded() -> None:
    fake = FakeReview({"instagram:lachefita": ("creador", True, "Chef casera en Bogotá.")})
    result = rr.add_manual_account(
        rr.parse_manual("@lachefita", "instagram"),
        rr.brand_brief(_seed()),
        note="Poca actividad pero muy buena",
        api_key="k",
        lookup=_lookup(True, bio="Cocina casera"),
        review=fake,
        store=None,
    )
    assert result.missing is False and result.warning == ""
    card = result.card
    assert card["handle"] == "@lachefita" and card["network"] == "Instagram"
    assert card["manual"] == "1" and card["reason"] == rr.MANUAL_REASON
    assert (card["kind_label"], card["review"], card["fits"]) == (
        "Creador",
        "Chef casera en Bogotá.",
        "si",
    )
    assert card["blurb"] == "Cocina casera"
    assert fake.calls[0][1][0].manual is True
    assert fake.calls[0][1][0].note == "Poca actividad pero muy buena"


def test_a_manual_account_that_does_not_fit_is_added_with_a_warning() -> None:
    fake = FakeReview({"tiktok:perrosya": ("marca", False, "Comida rápida, otro formato.")})
    result = rr.add_manual_account(
        rr.parse_manual("perrosya", "tiktok"),
        rr.brand_brief(_seed()),
        api_key="k",
        lookup=_lookup(True),
        review=fake,
        store=None,
    )
    assert result.warning == "Comida rápida, otro formato."
    assert result.card["fits"] == "no"  # still carded: the operator decides


def test_an_account_with_no_social_profile_is_carded_from_the_note() -> None:
    fake = FakeReview({"otro:pasteleria-dona-rosa": ("marca", True, "Pastelería artesanal.")})

    def no_lookup(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("an account on no network we read is never looked up")

    result = rr.add_manual_account(
        rr.parse_manual("Pastelería Doña Rosa", "otro"),
        rr.brand_brief(_seed()),
        note="La mejor pastelería del barrio",
        api_key="k",
        lookup=no_lookup,
        review=fake,
        store=None,
    )
    card = result.card
    assert card["network"] == "Sin redes"
    assert card["handle"] == "pasteleria-dona-rosa"
    assert card["blurb"] == "La mejor pastelería del barrio"
    assert card["followers"] == "—"
    assert card["kind"] == "marca"


def test_a_profile_that_is_not_found_is_still_added_and_a_failed_review_is_not_fatal() -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("overloaded")

    result = rr.add_manual_account(
        rr.parse_manual("@noexiste", "instagram"),
        rr.brand_brief(_seed()),
        api_key="k",
        lookup=_lookup(False),
        review=broken,
        store=None,
    )
    assert result.missing is True
    assert result.card["handle"] == "@noexiste" and result.card["fits"] == ""
    assert any(e.startswith("review:") for e in result.errors)


# --------------------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------------------


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> MemoryReferentesRepository:
    memory = MemoryReferentesRepository()
    monkeypatch.setattr(rp, "REPOSITORY", memory)
    return memory


@pytest.fixture
def brand(repo: MemoryReferentesRepository) -> UUID:
    brand_id = uuid4()
    repo.add_brand(tenant_id=TENANT, brand_id=brand_id)
    return brand_id


def _manual(text: str, network: str) -> rr.ManualResult:
    return rr.add_manual_account(
        rr.parse_manual(text, network),
        rr.brand_brief(_seed()),
        api_key="k",
        lookup=_lookup(True),
        review=FakeReview({}),
        store=None,
    )


def test_manual_referentes_accumulate_and_come_back_in_their_bucket(
    repo: MemoryReferentesRepository, brand: UUID
) -> None:
    first = _manual("@lachefita", "instagram")
    second = _manual("Pastelería Doña Rosa", "otro")
    for result in (first, second, first):  # adding one again replaces it
        rp.save_manual_account(TENANT, brand, result.candidate, result.card, brand_handle="x")
    rp.write_labels(
        TENANT,
        brand,
        None,
        {
            wiz._account_key(first.card): "referente",
            wiz._account_key(second.card): "competencia",
        },
    )

    manual = [
        p for p in repo.current_phases(tenant_id=TENANT, brand_id=brand) if p.phase_key == "manual"
    ]
    assert len(manual) == 1
    assert {(a.network, a.handle) for a in manual[0].accounts} == {
        ("instagram", "lachefita"),
        ("otro", "pasteleria-dona-rosa"),
    }

    buckets, kept = rp.load_sort(TENANT, brand, cards=[])
    assert buckets == {
        "Instagram:@lachefita": "referente",
        "Sin redes:pasteleria-dona-rosa": "competencia",
    }
    # a manual card keeps saying so, instead of "de una búsqueda anterior"
    assert {c["reason"] for c in kept} == {rr.MANUAL_REASON}


def test_the_manual_pseudo_phase_is_never_recomputed(
    repo: MemoryReferentesRepository, brand: UUID
) -> None:
    result = _manual("@lachefita", "instagram")
    # A nested context, NOT `monkeypatch.undo()`: undo() would also drop the `repo`
    # fixture's REPOSITORY patch, and `plan_refresh` would then hit the real Postgres —
    # which is exactly what happened in the offline CI job (no database there).
    with pytest.MonkeyPatch.context() as older_algorithm:
        older_algorithm.setattr(cd, "PHASED_PLAN_VERSION", cd.PHASED_PLAN_VERSION - 1)
        rp.save_manual_account(TENANT, brand, result.candidate, result.card)
    assert rp.plan_refresh(TENANT) == []


def test_a_phase_whose_review_failed_is_not_stored(
    repo: MemoryReferentesRepository, brand: UUID
) -> None:
    result = cd.PhaseResult(
        key="sector", title="t", accounts=[_candidate("tiktok", "a", 10)], review_failed=True
    )
    assert rp.save_phase(TENANT, brand, "sector", _seed(), result, cd.phase_to_dict(result)) is (
        False
    )


def test_a_manual_card_label_maps_back_to_its_network() -> None:
    assert rp.card_identity({"network": "Sin redes", "handle": "dona-rosa"}) == (
        "otro",
        "dona-rosa",
    )
    assert rp.card_identity({"network": "YouTube", "handle": "@chef"}) == ("youtube", "chef")


# --------------------------------------------------------------------------------------
# the wizard's pieces
# --------------------------------------------------------------------------------------


def test_a_card_stored_before_the_review_renders_with_empty_flags() -> None:
    view = wiz.card_view({"handle": "@x", "network": "TikTok"})
    assert view["kind_label"] == "" and view["review"] == "" and view["manual"] == ""
    assert view["avatar_src"] == "/avatar/tiktok/x"


def test_the_manual_outcome_warns_when_the_ai_thinks_it_does_not_fit() -> None:
    fits = rr.ManualResult(card={}, candidate=_candidate("tiktok", "a", 1))
    message, tone = wiz.manual_outcome(
        {"handle": "@a", "kind_label": "Creador", "review": "Chef de autor."}, "referente", fits
    )
    assert tone == "ok"
    assert message == "Agregamos @a a «Te inspira». Creador: Chef de autor."

    doubtful = rr.ManualResult(
        card={}, candidate=_candidate("tiktok", "a", 1), missing=True, warning="Otro rubro."
    )
    message, tone = wiz.manual_outcome(
        {"handle": "@a", "network": "TikTok"}, "competencia", doubtful
    )
    assert tone == "warn"
    assert "No encontramos ese perfil en TikTok" in message
    assert "la IA cree que no encaja: Otro rubro." in message


def test_the_discarded_list_follows_the_category_on_screen() -> None:
    state = wiz.BrandConnectState()
    state._apply_phase(
        {
            "key": "sector",
            "title": "t",
            "accounts": [],
            "discarded": [{"handle": "@memes", "network": "TikTok", "reason": "Humor."}],
        }
    )
    state._apply_phase({"key": "local", "title": "l", "accounts": [], "discarded": []})
    assert [d["handle"] for d in state.discarded_accounts] == ["@memes"]
    # a retry of the same phase replaces its list rather than adding to it
    state._apply_phase({"key": "sector", "title": "t", "accounts": [], "discarded": []})
    assert state.discarded_accounts == []
