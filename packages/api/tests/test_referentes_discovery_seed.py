"""`qualify_api.referentes.discovery_seed` — the referentes search's seed read from the
brand's own account (`seed_from_profile`), the location detection and the niche taxonomy
it stands on. Moved with the module from `Qualify/test_creator_discovery*.py`
(m-24852195), unchanged. Pure functions: no network, no database."""

from __future__ import annotations

import pytest

from qualify_api.referentes import discovery_seed as ds


def test_unknown_niche_is_rejected_loudly() -> None:
    with pytest.raises(ValueError, match="unknown niche"):
        ds.resolve_niche("crypto")


def test_detect_niches_folds_accents_and_matches_emoji() -> None:
    assert ds.detect_niches("Amante de la buena comida 🍽️") == ["food_drink"]
    assert ds.detect_niches("Diseñadora de modas. Gastronomía local") == [
        "food_drink",
        "fashion_beauty",
    ]
    assert ds.detect_niches("hola") == []


@pytest.mark.parametrize(
    ("text", "hashtags", "expected"),
    [
        ("📍 Cúcuta, Colombia", [], ("CO", "Cúcuta")),
        ("comida rica todos los días", ["cucutafood"], ("CO", "Cúcuta")),
        ("Hecho con amor en 🇲🇽", [], ("MX", "")),
        ("Desde Valencia, España", [], ("ES", "Valencia")),
        # the same city name, the other country — the country named decides, both ways
        ("Desde Valencia, Venezuela", [], ("VE", "Valencia")),
        # `cali` is too short to match inside a hashtag — `#calidadtotal` is not Cali
        ("productos de calidad", ["calidadtotal"], ("", "")),
        ("Vivo en Bogotá", [], ("CO", "Bogotá")),
        # a city only ONE country has still stands on its own
        ("Delivery en todo Maracaibo", [], ("VE", "Maracaibo")),
        # the demonym names the country as well as the name does
        ("cocina venezolana desde siempre", [], ("VE", "")),
        ("Somos 100% dominicanos", [], ("DO", "")),
    ],
)
def test_detect_location(text: str, hashtags: list[str], expected: tuple[str, str]) -> None:
    assert ds.detect_location(text, hashtags) == expected


def test_the_ambiguous_half_of_the_weak_set_is_derived_from_the_table() -> None:
    """Nobody has to remember to list a collision: adding a country whose city another
    country already has makes both weak automatically."""
    shared = {slug for slug, codes in ds.CITY_COUNTRIES.items() if len(codes) > 1}
    assert shared <= ds.WEAK_CITY_SLUGS
    # the ones that exist today, so a table edit that silently drops one is visible
    assert {"valencia", "barcelona", "merida", "cordoba"} <= shared
    assert ds.CITY_COUNTRIES["valencia"] == frozenset({"ES", "VE"})


@pytest.mark.parametrize("text", ["Vivo en Valencia", "Barcelona vibes ✨", "Desde Córdoba"])
def test_a_shared_city_name_alone_yields_the_city_but_no_country(text: str) -> None:
    code, city = ds.detect_location(text)
    assert code == ""
    assert city != ""  # the city still scopes a local search; only the country is unknown


def test_the_operator_answer_settles_an_ambiguous_city() -> None:
    """The country the operator already picked on the rubro step disambiguates the bio
    exactly as naming it in the bio would."""
    assert ds.detect_location("Vivo en Valencia", country_hint="VE") == ("VE", "Valencia")
    assert ds.detect_location("Vivo en Valencia", country_hint="ES") == ("ES", "Valencia")
    # a hint the table does not know is ignored, not trusted
    assert ds.detect_location("Vivo en Valencia", country_hint="ZZ") == ("", "Valencia")
    # and a hint never invents a country the text did not place
    assert ds.detect_location("solo postres", country_hint="VE") == ("", "")


def test_an_ordinary_word_city_does_not_decide_a_country_either() -> None:
    """`salta` is a verb, `rosario` and `david` are names — unique in the table, but
    they cannot carry a country by themselves."""
    assert ds.detect_location("la masa salta en el sartén") == ("", "Salta")
    assert ds.detect_location("la masa salta en el sartén", country_hint="AR") == ("AR", "Salta")


def test_every_country_carries_enough_cities_and_a_demonym() -> None:
    """The guard behind the even-coverage rule: a country entered with one city loses
    every creator from its second one, and one without a demonym loses every bio that
    says "venezolana" instead of "Venezuela"."""
    for code, country in ds.COUNTRIES.items():
        assert len(country.cities) >= 8, f"{code} has too few cities to detect anything"
        assert country.aliases, f"{code} has no alias/demonym"
        assert all(len(ds._fold(a)) >= ds._MIN_ALIAS_LENGTH for a in country.aliases), code
        assert country.name


def test_seed_reads_bio_category_and_own_hashtags_dropping_generic_and_own_tags() -> None:
    profile = {
        "username": "arepas.cucuta",
        "bio": "Las mejores arepas 📍 Cúcuta",
        "category": "Restaurant",
        "topHashtags": ["fyp", "arepascucuta", "cucutafood", "Viral", "comidacolombiana"],
    }
    seed = ds.seed_from_profile(profile)

    assert seed.handle == "arepas.cucuta"
    assert seed.niches == ("food_drink",)
    # generic (fyp, viral) and the account's own handle tag (arepascucuta) are gone
    assert seed.hashtags == ("cucutafood", "comidacolombiana")
    assert (seed.country_code, seed.city) == ("CO", "Cúcuta")
    assert seed.chips() == [
        "Comida y bebida",
        "#cucutafood",
        "#comidacolombiana",
        "Cúcuta, Colombia",
    ]


def test_instagram_english_category_detects_the_niche() -> None:
    assert ds.seed_from_profile({"category": "Gym/Physical Fitness Center"}).niches == (
        "fitness_health",
    )
    assert ds.seed_from_profile({"category": "Digital creator"}).niches == ()


def test_explicit_answers_win_over_detection() -> None:
    profile = {"username": "x", "bio": "IA + Tecnología 📍 Cúcuta", "topHashtags": []}

    seed = ds.seed_from_profile(profile, sector="food_drink")
    assert seed.niches == ("food_drink",)
    assert (seed.country_code, seed.city) == ("CO", "Cúcuta")

    # an explicit rubro drops the snapshot's hashtags about another topic, keeps its own
    # and the place ones
    mixed = {**profile, "topHashtags": ["programacion", "recetas", "cucutafood"]}
    assert ds.seed_from_profile(mixed, sector="food_drink").hashtags == ("recetas", "cucutafood")
    assert ds.seed_from_profile(mixed).hashtags == ("programacion", "recetas", "cucutafood")

    # an explicit country drops a detected city that is not in it
    moved = ds.seed_from_profile(profile, country_code="MX")
    assert (moved.country_code, moved.city) == ("MX", "")

    explicit = ds.seed_from_profile(profile, country_code="co", city="Pamplona")
    assert (explicit.country_code, explicit.city) == ("CO", "Pamplona")


def test_signature_changes_with_every_input_the_plan_reads() -> None:
    base = ds.DiscoverySeed("x", ("food_drink",), ("cucutafood",), "CO", "Cúcuta")
    variants = [
        ds.DiscoverySeed("y", ("food_drink",), ("cucutafood",), "CO", "Cúcuta"),
        ds.DiscoverySeed("x", ("technology",), ("cucutafood",), "CO", "Cúcuta"),
        ds.DiscoverySeed("x", ("food_drink",), ("otra",), "CO", "Cúcuta"),
        ds.DiscoverySeed("x", ("food_drink",), ("cucutafood",), "VE", "Cúcuta"),
        ds.DiscoverySeed("x", ("food_drink",), ("cucutafood",), "CO", "Bogotá"),
    ]
    assert len({base.signature(), *(v.signature() for v in variants)}) == 6
    # accents / case in the city do not split the cache
    same = ds.DiscoverySeed("X", ("food_drink",), ("cucutafood",), "co", "cucuta")
    assert same.signature() == base.signature()


def test_split_terms() -> None:
    assert ds.split_terms("Peluquería canina, spa para mascotas y guardería") == (
        "Peluquería canina",
        "spa para mascotas",
        "guardería",
    )
    assert ds.split_terms("  ") == ()
    assert ds.split_terms("a, b, c, d, e") == ()  # too short to search with
