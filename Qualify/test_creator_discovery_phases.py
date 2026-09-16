"""`creator_discovery`'s Brand Kit integration (2026-09-11) — the seed read from a
profile, the three-phase plan, a full phased run over `httpx.MockTransport`, and the
result cache. Fully offline, same posture as `test_creator_discovery.py`."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from . import creator_discovery as cd

API_KEY = "sk_test_123"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", API_KEY)


# --------------------------------------------------------------------------------------
# location + seed
# --------------------------------------------------------------------------------------


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
    assert cd.detect_location(text, hashtags) == expected


# --------------------------------------------------------------------------------------
# a shared city name never decides a country (§ 2026-09-15) — the general rule, not a
# Venezuela patch: it holds for every pair the table happens to contain.
# --------------------------------------------------------------------------------------


def test_the_ambiguous_half_of_the_weak_set_is_derived_from_the_table() -> None:
    """Nobody has to remember to list a collision: adding a country whose city another
    country already has makes both weak automatically."""
    shared = {slug for slug, codes in cd.CITY_COUNTRIES.items() if len(codes) > 1}
    assert shared <= cd.WEAK_CITY_SLUGS
    # the ones that exist today, so a table edit that silently drops one is visible
    assert {"valencia", "barcelona", "merida", "cordoba"} <= shared
    assert cd.CITY_COUNTRIES["valencia"] == frozenset({"ES", "VE"})


@pytest.mark.parametrize("text", ["Vivo en Valencia", "Barcelona vibes ✨", "Desde Córdoba"])
def test_a_shared_city_name_alone_yields_the_city_but_no_country(text: str) -> None:
    code, city = cd.detect_location(text)
    assert code == ""
    assert city != ""  # the city still scopes a local search; only the country is unknown


def test_the_operator_answer_settles_an_ambiguous_city() -> None:
    """The country the operator already picked on the rubro step disambiguates the bio
    exactly as naming it in the bio would."""
    assert cd.detect_location("Vivo en Valencia", country_hint="VE") == ("VE", "Valencia")
    assert cd.detect_location("Vivo en Valencia", country_hint="ES") == ("ES", "Valencia")
    # a hint the table does not know is ignored, not trusted
    assert cd.detect_location("Vivo en Valencia", country_hint="ZZ") == ("", "Valencia")
    # and a hint never invents a country the text did not place
    assert cd.detect_location("solo postres", country_hint="VE") == ("", "")


def test_an_ordinary_word_city_does_not_decide_a_country_either() -> None:
    """`salta` is a verb, `rosario` and `david` are names — unique in the table, but
    they cannot carry a country by themselves."""
    assert cd.detect_location("la masa salta en el sartén") == ("", "Salta")
    assert cd.detect_location("la masa salta en el sartén", country_hint="AR") == ("AR", "Salta")


def test_every_country_carries_enough_cities_and_a_demonym() -> None:
    """The guard behind the even-coverage rule: a country entered with one city loses
    every creator from its second one, and one without a demonym loses every bio that
    says "venezolana" instead of "Venezuela"."""
    for code, country in cd.COUNTRIES.items():
        assert len(country.cities) >= 8, f"{code} has too few cities to detect anything"
        assert country.aliases, f"{code} has no alias/demonym"
        assert all(len(cd._fold(a)) >= cd._MIN_ALIAS_LENGTH for a in country.aliases), code
        assert country.name


def test_country_evidence_drops_a_weak_city_when_another_country_is_named() -> None:
    """The national phase's admission test. A Spanish account that says "Valencia" is
    not Venezuelan, and the reverse holds too — whichever country the text names wins
    the shared name."""
    spanish = cd.Candidate("instagram", "tapas", bio="Tapas en Valencia, España")
    assert cd._has_country_evidence(spanish, "ES")
    assert not cd._has_country_evidence(spanish, "VE")

    venezuelan = cd.Candidate("instagram", "arepas", bio="Arepas en Valencia, Venezuela")
    assert cd._has_country_evidence(venezuelan, "VE")
    assert not cd._has_country_evidence(venezuelan, "ES")

    # nothing else named: the shared name is still evidence for both — it is all there
    # is, and the phase is scoped to one country anyway
    bare = cd.Candidate("instagram", "cafe", bio="Café en Valencia")
    assert cd._has_country_evidence(bare, "VE")
    assert cd._has_country_evidence(bare, "ES")

    # an unambiguous city needs no help
    zulia = cd.Candidate("tiktok", "zulia", bio="Maracaibo, mi ciudad")
    assert cd._has_country_evidence(zulia, "VE")


def test_country_evidence_reads_the_demonym_and_the_flag() -> None:
    demonym = cd.Candidate("tiktok", "cocina", bio="Cocina venezolana tradicional")
    flag = cd.Candidate("tiktok", "hecho", bio="Hecho en 🇻🇪")
    short = cd.Candidate("tiktok", "vzla", bio="Postres vzla 🍰")
    for candidate in (demonym, flag, short):
        assert cd._has_country_evidence(candidate, "VE")
        assert not cd._has_country_evidence(candidate, "CO")


def test_seed_reads_bio_category_and_own_hashtags_dropping_generic_and_own_tags() -> None:
    profile = {
        "username": "arepas.cucuta",
        "bio": "Las mejores arepas 📍 Cúcuta",
        "category": "Restaurant",
        "topHashtags": ["fyp", "arepascucuta", "cucutafood", "Viral", "comidacolombiana"],
    }
    seed = cd.seed_from_profile(profile)

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
    assert cd.seed_from_profile({"category": "Gym/Physical Fitness Center"}).niches == (
        "fitness_health",
    )
    assert cd.seed_from_profile({"category": "Digital creator"}).niches == ()


def test_explicit_answers_win_over_detection() -> None:
    profile = {"username": "x", "bio": "IA + Tecnología 📍 Cúcuta", "topHashtags": []}

    seed = cd.seed_from_profile(profile, sector="food_drink")
    assert seed.niches == ("food_drink",)
    assert (seed.country_code, seed.city) == ("CO", "Cúcuta")

    # an explicit rubro drops the snapshot's hashtags about another topic, keeps its own
    # and the place ones
    mixed = {**profile, "topHashtags": ["programacion", "recetas", "cucutafood"]}
    assert cd.seed_from_profile(mixed, sector="food_drink").hashtags == ("recetas", "cucutafood")
    assert cd.seed_from_profile(mixed).hashtags == ("programacion", "recetas", "cucutafood")

    # an explicit country drops a detected city that is not in it
    moved = cd.seed_from_profile(profile, country_code="MX")
    assert (moved.country_code, moved.city) == ("MX", "")

    explicit = cd.seed_from_profile(profile, country_code="co", city="Pamplona")
    assert (explicit.country_code, explicit.city) == ("CO", "Pamplona")


def test_signature_changes_with_every_input_the_plan_reads() -> None:
    base = cd.DiscoverySeed("x", ("food_drink",), ("cucutafood",), "CO", "Cúcuta")
    variants = [
        cd.DiscoverySeed("y", ("food_drink",), ("cucutafood",), "CO", "Cúcuta"),
        cd.DiscoverySeed("x", ("technology",), ("cucutafood",), "CO", "Cúcuta"),
        cd.DiscoverySeed("x", ("food_drink",), ("otra",), "CO", "Cúcuta"),
        cd.DiscoverySeed("x", ("food_drink",), ("cucutafood",), "VE", "Cúcuta"),
        cd.DiscoverySeed("x", ("food_drink",), ("cucutafood",), "CO", "Bogotá"),
    ]
    assert len({base.signature(), *(v.signature() for v in variants)}) == 6
    # accents / case in the city do not split the cache
    same = cd.DiscoverySeed("X", ("food_drink",), ("cucutafood",), "co", "cucuta")
    assert same.signature() == base.signature()


# --------------------------------------------------------------------------------------
# phase plan
# --------------------------------------------------------------------------------------


def _labels(key: str, seed: cd.DiscoverySeed) -> list[tuple[str, str | None]]:
    return [(q.label, region) for q, region in cd.phase_queries(key, seed)]


def test_phase_queries_scope_sector_then_country_then_city() -> None:
    seed = cd.DiscoverySeed("mi.marca", ("food_drink",), ("cucutafood",), "CO", "Cúcuta")

    # the only own hashtag names the city, so the sector search is the taxonomy's terms
    assert _labels("sector", seed) == [
        ("tiktok:keyword:foodie", None),
        ("tiktok:keyword:restaurantes", None),
        ("tiktok:keyword:recetas", None),
    ]
    assert _labels("national", seed) == [("tiktok:keyword:comida Colombia", "CO")]
    # the account's own city hashtag is preferred over the composed one
    assert _labels("local", seed) == [
        ("tiktok:keyword:foodie Cúcuta", "CO"),
        ("tiktok:hashtag:#cucutafood", "CO"),
    ]


def test_sector_prefers_the_accounts_own_topical_hashtags_over_broad_terms() -> None:
    seed = cd.DiscoverySeed(
        "midu.dev",
        ("technology", "education"),
        ("programacion", "comidacolombia", "software", "css"),
        "CO",
        "",
    )
    # place tags (`comidacolombia`) are skipped; two own tags, then the taxonomy's
    # sector terms — `programación` de-duplicates against `#programacion`
    assert _labels("sector", seed) == [
        ("tiktok:keyword:programacion", None),
        ("tiktok:keyword:software", None),
        ("tiktok:keyword:aprende a programar", None),
        ("tiktok:keyword:programador", None),
    ]


def test_local_falls_back_to_the_composed_city_hashtag() -> None:
    seed = cd.DiscoverySeed("x", ("fitness_health",), (), "CO", "Bogotá")
    assert _labels("local", seed)[1] == ("tiktok:hashtag:#bogotafitness", "CO")


def test_phases_without_their_input_explain_instead_of_spending() -> None:
    seed = cd.DiscoverySeed("x", ("food_drink",))

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be made")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        national = cd.run_phase("national", seed, client=client, pool={}, picked=set())
        local = cd.run_phase("local", seed, client=client, pool={}, picked=set())
        empty = cd.run_phase(
            "sector", cd.DiscoverySeed("x", ()), client=client, pool={}, picked=set()
        )

    assert national.credits == local.credits == empty.credits == 0
    assert "país" in national.note
    assert "ciudad" in local.note
    assert "rubro" in empty.note


# --------------------------------------------------------------------------------------
# a full phased run
# --------------------------------------------------------------------------------------


def _video(
    username: str,
    bio: str,
    followers: int,
    *,
    likes: int = 100,
    comments: int = 10,
    desc: str = "",
    hashtags: tuple[str, ...] = (),
    region: str | None = None,
) -> dict:
    author = {"unique_id": username, "signature": bio, "follower_count": followers}
    if region:
        author["region"] = region
    return {
        "author": author,
        "statistics": {"digg_count": likes, "comment_count": comments, "play_count": 1000},
        "desc": desc,
        "text_extra": [{"hashtag_name": tag} for tag in hashtags],
    }


def _keyword(*videos: dict) -> httpx.Response:
    return httpx.Response(
        200, json={"success": True, "search_item_list": [{"aweme_info": v} for v in videos]}
    )


def _google(*urls: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "success": True,
            "results": [{"title": u, "url": u, "description": ""} for u in urls],
            "next_page": 2,
        },
    )


def _ig_profile(
    followers: int, bio: str = "", *, related: tuple[str, ...] = (), private: bool = False
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "success": True,
            "credits_charged": 1,
            "data": {
                "user": {
                    "biography": bio,
                    "is_private": private,
                    "category_name": "Digital creator",
                    "edge_followed_by": {"count": followers},
                    "edge_related_profiles": {
                        "edges": [{"node": {"username": r, "is_private": False}} for r in related]
                    },
                }
            },
        },
    )


def test_phased_run_ranks_by_influence_and_never_repeats_an_account(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, str]]] = []
    ig_profiles = {
        # sector, from Google + the seed's related accounts + chaining
        "ig.global": (3_000_000, "Food 🌎", ("ig.chain",)),
        "ig.chain": (900_000, "Recetas", ()),
        "ig.seedrel": (250_000, "Cocina", ()),
        "ig.private": (5_000_000, "", ()),
        # national / local
        "ig.bogota": (400_000, "Restaurante en Bogotá 🇨🇴", ()),
        "ig.cucuta": (60_000, "Arepas en Cúcuta", ()),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        calls.append((request.url.path, params))
        path = request.url.path
        if path == "/v1/tiktok/search/keyword":
            query = params["query"]
            if query == "foodie" and "cursor" not in params:
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "cursor": 30,
                        "has_more": 1,
                        "search_item_list": [
                            {"aweme_info": _video("global.food", "Food lover · NYC", 2_000_000)},
                            # the account itself, spelled the TikTok way (no dot)
                            {"aweme_info": _video("mimarca", "la cuenta que busca", 5_000)},
                        ],
                    },
                )
            if query == "foodie" and params.get("cursor") == "30":
                # page 2 carries the bigger account page 1 did not
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "cursor": 60,
                        "has_more": 0,
                        "search_item_list": [
                            {"aweme_info": _video("comida.col", "Comida colombiana 🇨🇴", 300_000)},
                            {"aweme_info": _video("mega.food", "Food", 4_000_000)},
                        ],
                    },
                )
            if query == "comida Colombia":
                return _keyword(
                    _video("bogota.sabor", "", 80_000, desc="El mejor ajiaco de Bogotá"),
                    _video("tacos.mx", "Tacos desde México", 90_000),
                    _video("sabor.cucuta", "Foodie de Cúcuta", 150_000),
                )
            if query == "foodie Cúcuta":
                # measured behaviour: an empty search answers 404 not_found
                return httpx.Response(404, json={"success": False, "error": "not_found"})
            if query == "restaurantes":
                return _keyword(
                    # a news outlet: biggest of all, never a referente
                    _video("bbcnews", "BBC News", 16_000_000, desc="jobs"),
                    # off-topic: nothing about food in its own words
                    _video("stream.art", "El canal del stream art", 9_000_000, desc="hoy"),
                )
            return _keyword()
        if path == "/v1/tiktok/search/hashtag":
            assert params == {"hashtag": "cucutafood", "region": "CO"}
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "aweme_list": [
                        # hashtag feeds report 0 followers — enrichment fills them
                        _video("oculto.uno", "arepas", 0, likes=900, hashtags=("cucutafood",)),
                        _video("local.chico", "Cúcuta", 0, likes=400, hashtags=("cucutafood",)),
                        _video("oculto.dos", "postres", 0, likes=50, hashtags=("cucutafood",)),
                    ],
                },
            )
        if path == "/v1/tiktok/profile":
            assert params["cache_max_age"] == "30d"
            known = {
                "oculto.uno": 20_000,
                "local.chico": 12_000,
                "oculto.dos": 3_000,
                "tt.google": 700_000,  # from Google, read for its size
                "ig.global": 8_000_000,  # the Instagram account mirrored onto TikTok
            }
            if params["handle"] not in known:
                return httpx.Response(404, json={"success": False, "error": "not_found"})
            followers = known[params["handle"]]
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "credits_charged": 1,
                    "user": {"signature": "Food, food, food"},
                    "stats": {"followerCount": followers, "heartCount": followers * 10},
                },
            )
        if path == "/v1/google/search":
            query = params["query"]
            if query == "foodie site:tiktok.com":
                # Google mostly returns video URLs for TikTok — the handle is in them
                return _google(
                    "https://www.tiktok.com/@tt.google/video/7603926762661219615",
                    "https://www.tiktok.com/discover/elevate-pilates-bogota",
                )
            if query.endswith("site:tiktok.com"):
                return _google()
            if query == "foodie site:instagram.com":
                return _google(
                    "https://www.instagram.com/ig.global/",
                    "https://www.instagram.com/p/abc123/",
                    "https://www.instagram.com/explore/tags/foodie/",
                    "https://www.instagram.com/ig.private/",
                )
            if query == "comida Colombia site:instagram.com":
                return _google("https://www.instagram.com/ig.bogota/")
            if query == "foodie Cúcuta site:instagram.com":
                return _google(
                    "https://www.instagram.com/ig.cucuta/",
                    "https://www.instagram.com/mi.marca/",  # the brand itself
                )
            return _google()
        if path == "/v1/instagram/profile":
            assert params["cache_max_age"] == "30d"
            if params["handle"] == "mega.food":
                return _ig_profile(6_000_000, "Same person, no niche word in this bio")
            if params["handle"] not in ig_profiles:
                return httpx.Response(404, json={"success": False, "error": "not_found"})
            followers, bio, related = ig_profiles[params["handle"]]
            return _ig_profile(
                followers, bio, related=related, private=params["handle"] == "ig.private"
            )
        raise AssertionError(f"unexpected call {path} {params}")

    seed = cd.DiscoverySeed(
        "mi.marca", ("food_drink",), ("cucutafood",), "CO", "Cúcuta", related=("ig.seedrel",)
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    runner = cd.PhasedDiscovery(seed, client=client)
    sector, national, local = runner.run_all()
    client.close()

    handles = lambda phase: [c.username for c in phase.accounts]  # noqa: E731

    # sector: both TikTok pages (the 4M account was on page 2), both Instagram sources
    # (Google, the seed's related account, the chained related account), biggest first,
    # never the brand itself, never a private account
    # `mega.food` exists under the same handle on Instagram (the mirror lookup) and is
    # bigger there; `ig.global` mirrors onto TikTok; `tt.google` came from Google
    assert [(c.network, c.username) for c in sector.accounts] == [
        ("tiktok", "ig.global"),
        ("instagram", "mega.food"),
        ("tiktok", "mega.food"),
        ("instagram", "ig.global"),
        ("tiktok", "global.food"),
        ("instagram", "ig.chain"),
        ("tiktok", "tt.google"),
        ("instagram", "ig.seedrel"),
    ]
    assert cd.account_card(sector.accounts[0])["reason"] == "también en Instagram"
    assert cd.account_card(sector.accounts[1])["reason"] == "también en TikTok"
    assert "stream.art" not in handles(sector)  # off-topic, however big
    assert sector.queries == [
        "tiktok:keyword:foodie",
        "tiktok:keyword:restaurantes",
        "tiktok:keyword:recetas",
        "tiktok:google:foodie",
        "tiktok:google:restaurantes",
        "tiktok:google:recetas",
        "instagram:google:foodie",
        "instagram:google:restaurantes",
        "instagram:google:recetas",
    ]
    # 2 pages for foodie + 1 each for the two empty searches; 6 Google; TikTok: 1 read
    # (tt.google) + 1 mirror (ig.global; the others 404 → free); Instagram: 4 reads +
    # 1 mirror (mega.food)
    assert sector.credits == 4 + 6 + 2 + 5
    assert "bbcnews" not in handles(sector)  # a news outlet, however big

    # national: country evidence required (Bogotá in a caption yes, México no), and the
    # Cúcuta account is reserved for the local phase even though it is bigger
    assert national.title == "Referentes en Colombia"
    # `comida.col` did not fit the sector's eight slots, so it is national's now
    assert handles(national) == ["ig.bogota", "comida.col", "bogota.sabor"]
    # the mirror lookups of this phase's TikTok accounts all 404 → no credit, no error
    assert national.errors == []
    # no bio in the keyword feed → the caption describes the account
    assert cd.account_card(national.accounts[2])["blurb"] == "El mejor ajiaco de Bogotá"

    # local: the keyword 404 is an empty result, not an error; the hidden-follower
    # TikTok accounts were enriched, then ranked with the Instagram one
    assert local.title == "Referentes en Cúcuta"
    assert local.errors == []
    assert handles(local) == [
        "sabor.cucuta",
        "ig.cucuta",
        "oculto.uno",
        "local.chico",
        "oculto.dos",
    ]
    # keyword, hashtag, 2 Google, ig read, 3 enrich (mirrors 404 → free)
    assert local.credits == 1 + 1 + 2 + 1 + 3
    assert local.queries == [
        "tiktok:keyword:foodie Cúcuta",
        "tiktok:hashtag:#cucutafood",
        "tiktok:google:foodie Cúcuta",
        "instagram:google:foodie Cúcuta",
    ]
    enriched = {"oculto.uno", "local.chico", "oculto.dos"}
    assert sum(1 for p, q in calls if p == "/v1/tiktok/profile" and q["handle"] in enriched) == 3

    card = cd.account_card(local.accounts[0])
    assert card == {
        "handle": "@sabor.cucuta",
        "network": "TikTok",
        "followers": "150K",
        "likes": "100/vídeo",
        "url": "https://www.tiktok.com/@sabor.cucuta",
        "blurb": "Foodie de Cúcuta",
        "reason": "«comida Colombia»",
        "avatar": "",
    }
    assert cd.account_card(local.accounts[2])["reason"] == "#cucutafood"
    assert cd.account_card(local.accounts[2])["likes"] == "200K"  # heartCount from the read
    assert cd.account_card(sector.accounts[5])["reason"] == "similar a @ig.global"
    assert cd.account_card(sector.accounts[7])["reason"] == "similar a @mi.marca"
    assert cd.account_card(local.accounts[1])["reason"] == "«foodie Cúcuta»"


def test_instagram_handles_from_google_keeps_profile_urls_only() -> None:
    payload = {
        "results": [
            {"url": "https://www.instagram.com/mouredev/"},
            {"url": "https://www.instagram.com/p/Dcbp_I6jGWK/"},
            {"url": "https://www.instagram.com/reel/DbvjKiFApRB/"},
            {"url": "https://www.instagram.com/popular/programacion-de-tv/"},
            {"url": "https://instagram.com/midu.dev"},
            {"url": "https://www.instagram.com/MoureDev/"},  # duplicate, other case
            {"url": "https://www.tiktok.com/@x"},
        ]
    }
    assert cd.instagram_handles_from_google(payload) == ["mouredev", "midu.dev"]


def test_google_terms_follow_the_phase_scoping() -> None:
    seed = cd.DiscoverySeed(
        "midu.dev", ("technology",), ("programacion", "software"), "CO", "Cúcuta"
    )
    assert cd.google_terms("sector", seed) == ["programacion", "software", "aprende a programar"]
    assert cd.google_terms("national", seed) == ["tecnología Colombia"]
    assert cd.google_terms("local", seed) == ["programación Cúcuta"]
    assert cd.google_terms("sector", cd.DiscoverySeed("x", ())) == []


def test_pick_accounts_keeps_both_networks_represented() -> None:
    tiktok = [cd.Candidate("tiktok", f"t{i}", followers=1_000_000 - i) for i in range(9)]
    instagram = [cd.Candidate("instagram", f"i{i}", followers=10_000 - i) for i in range(9)]
    picked = cd._pick_accounts(tiktok + instagram)
    assert [c.username for c in picked] == ["t0", "t1", "t2", "t3", "i0", "i1", "i2", "i3"]
    # one network alone fills every slot
    assert [c.username for c in cd._pick_accounts(tiktok)] == [f"t{i}" for i in range(8)]
    # a small network keeps what it has, the big one takes the rest
    mixed = cd._pick_accounts(tiktok + instagram[:1])
    assert [c.username for c in mixed] == ["t0", "t1", "t2", "t3", "t4", "t5", "t6", "i0"]


def test_run_query_pages_until_has_more_is_false() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        cursor = request.url.params.get("cursor")
        if cursor is None:
            return httpx.Response(
                200,
                json={"success": True, "cursor": 30, "has_more": 1, "search_item_list": []},
            )
        return httpx.Response(
            200, json={"success": True, "cursor": 30, "has_more": 1, "search_item_list": []}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        cd.run_query(client, cd.Query("tiktok", "keyword", "x", "food_drink"), pages=5)
    # page 3 would have repeated cursor 30 → stopped after two calls
    assert seen == [{"query": "x"}, {"query": "x", "cursor": "30"}]


def test_profile_facts_reads_both_shapes() -> None:
    tiktok = cd.profile_facts(
        "tiktok",
        {"user": {"signature": "bio", "verified": True}, "stats": {"followerCount": 5, "heart": 9}},
    )
    assert (tiktok.followers, tiktok.total_likes, tiktok.is_verified, tiktok.bio) == (
        5,
        9,
        True,
        "bio",
    )
    instagram = cd.profile_facts(
        "instagram",
        {
            "data": {
                "user": {
                    "biography": "b",
                    "category_name": None,
                    "business_category_name": "None",
                    "overall_category_name": "Restaurant",
                    "edge_followed_by": {"count": 7},
                    "edge_related_profiles": {
                        "edges": [
                            {"node": {"username": "a", "is_private": False}},
                            {"node": {"username": "p", "is_private": True}},
                        ]
                    },
                }
            }
        },
    )
    assert (instagram.followers, instagram.category, instagram.related) == (7, "Restaurant", ("a",))


def test_vendor_errors_are_recorded_and_the_run_is_not_cached(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"success": False, "error": "insufficient credits"})

    seed = cd.DiscoverySeed("x", ("food_drink",))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = cd.run_phase("sector", seed, client=client, pool={}, picked=set())

    assert result.accounts == []
    assert result.errors and "402" in result.errors[0]
    cache = tmp_path / "cache.json"
    cd.save_cached_phases(seed, [cd.phase_to_dict(result)], path=cache)
    assert not cache.exists()
    # …but a phase that FOUND accounts is kept even when one call failed on the way
    found = {"key": "sector", "title": "t", "accounts": [{"handle": "@x"}], "errors": ["500"]}
    cd.save_cached_phase("sector", seed, found, path=cache)
    assert cd.load_cached_phase("sector", seed, path=cache) == found


# --------------------------------------------------------------------------------------
# cache + formatting
# --------------------------------------------------------------------------------------


def test_cache_round_trip_expiry_and_cap(tmp_path: Path) -> None:
    cache = tmp_path / "cache.json"
    seed = cd.DiscoverySeed("x", ("food_drink",), (), "CO", "Cúcuta")
    phases = [{"key": key, "title": key, "accounts": [], "errors": []} for key in cd.PHASES]

    assert cd.load_cached_phases(seed, path=cache) is None
    cd.save_cached_phases(seed, phases, path=cache, now=1_000.0)
    assert cd.load_cached_phases(seed, path=cache, now=1_000.0 + 60) == phases
    assert cd.load_cached_phases(seed, path=cache, now=1_000.0 + 8 * 24 * 3600) is None

    for i in range(30):
        other = cd.DiscoverySeed(f"h{i}", ("food_drink",))
        cd.save_cached_phase("sector", other, phases[0], path=cache, now=2_000.0 + i)
    import json

    kept = json.loads(cache.read_text("utf-8"))
    assert len(kept) == len(cd.PHASES) + 30 <= cd._CACHE_MAX_ENTRIES
    assert cd.phase_signature("sector", cd.DiscoverySeed("h29", ("food_drink",))) in kept
    for i in range(cd._CACHE_MAX_ENTRIES):
        cd.save_cached_phase(
            "local", cd.DiscoverySeed(f"z{i}", ()), phases[0], path=cache, now=3_000.0 + i
        )
    assert len(json.loads(cache.read_text("utf-8"))) == cd._CACHE_MAX_ENTRIES


def test_a_changed_city_reuses_the_sector_and_country_phases(tmp_path: Path) -> None:
    """The file first, per phase: only what the change touches is searched again."""
    cache = tmp_path / "cache.json"
    cucuta = cd.DiscoverySeed("x", ("food_drink",), (), "CO", "Cúcuta")
    bogota = cd.DiscoverySeed("x", ("food_drink",), (), "CO", "Bogotá")
    for key in cd.PHASES:
        cd.save_cached_phase(key, cucuta, {"key": key, "accounts": [], "errors": []}, path=cache)

    assert cd.load_cached_phase("sector", bogota, path=cache) is not None
    assert cd.load_cached_phase("national", bogota, path=cache) is not None
    assert cd.load_cached_phase("local", bogota, path=cache) is None
    # a different country invalidates the national and local phases, not the sector
    venezuela = cd.DiscoverySeed("x", ("food_drink",), (), "VE", "Cúcuta")
    assert cd.load_cached_phase("sector", venezuela, path=cache) is not None
    assert cd.load_cached_phase("national", venezuela, path=cache) is None


def test_profile_store_remembers_reads_and_misses(tmp_path: Path) -> None:
    import time

    now = time.time()
    path = tmp_path / "profiles.json"
    store = cd.ProfileStore(path)
    facts = cd.ProfileFacts(followers=5, bio="b", related=("a", "c"), category="Restaurant")
    store.put("instagram", "Some.One", facts, now=now)
    store.put("tiktok", "ghost", None, now=now)
    store.save()

    again = cd.ProfileStore(path)
    assert again.get("instagram", "someone", now=now + 60) == (True, facts)
    assert again.get("tiktok", "ghost", now=now + 60) == (True, None)
    assert again.get("tiktok", "unknown") == (False, None)
    assert again.get("instagram", "someone", now=now + 31 * 24 * 3600) == (False, None)

    # a read served from the store costs nothing and never hits the vendor
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    candidate = cd.Candidate("instagram", "someone")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        charged, got, error = cd._read_profile(client, candidate, None, again)
    assert (charged, got, error) == (0, facts, None)
    assert candidate.followers == 5 and "Restaurant" in candidate.texts

    # an in-memory store (path=None) never writes
    cd.ProfileStore(None).save()


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "—"), (0, "—"), (850, "850"), (12_000, "12K"), (12_400, "12.4K"), (1_250_000, "1.2M")],
)
def test_compact_follower_counts(value: int | None, expected: str) -> None:
    assert cd._compact(value) == expected


def test_media_outlets_are_not_referentes() -> None:
    assert cd._is_media_outlet(cd.Candidate("tiktok", "bbcnews", full_name="BBC News"))
    tv = cd.Candidate("instagram", "tvn", bio="Instagram oficial de TVN")
    tv.texts.append("TV channel")
    assert cd._is_media_outlet(tv)
    ig = cd.Candidate("instagram", "diario.x")
    ig.texts.append("Media/News Company")
    assert cd._is_media_outlet(ig)
    assert not cd._is_media_outlet(cd.Candidate("tiktok", "mouredev", bio="Aprende a programar"))
    # a caption mentioning the news is not a category
    creator = cd.Candidate("tiktok", "dev", bio="Software engineer")
    creator.texts.append("Reacting to the news about AI agents and what it means for coders")
    assert not cd._is_media_outlet(creator)


def test_sector_phase_requires_the_accounts_own_words_to_mention_the_niche() -> None:
    seed = cd.DiscoverySeed("x", ("technology",))
    on_topic = cd.Candidate("instagram", "mouredev", bio="Aprende a programar", followers=1)
    off_topic = cd.Candidate("instagram", "olgaenvivo", bio="El canal del stream art", followers=9)
    assert cd._fits_phase("sector", on_topic, seed)
    assert not cd._fits_phase("sector", off_topic, seed)
    # a caption counts as the account's words too
    off_topic.texts.append("my sim rig software! #techtok")
    assert cd._fits_phase("sector", off_topic, seed)
    # the other phases do not ask for it (a restaurant's bio is often just an address)
    address = cd.Candidate("instagram", "carritosrest", bio="📍Av 0 # 15-71 CÚCUTA", followers=1)
    assert cd._fits_phase(
        "local", address, cd.DiscoverySeed("x", ("food_drink",), (), "CO", "Cúcuta")
    )


# --------------------------------------------------------------------------------------
# any rubro, in the operator's own words
# --------------------------------------------------------------------------------------


def test_free_text_rubro_drives_every_phase_without_the_taxonomy() -> None:
    seed = cd.seed_from_profile(
        {"username": "x", "topHashtags": ["fyp", "perritos", "cucutafisio"]},
        rubro_text="Fisioterapia deportiva / rehabilitación",
        country_code="CO",
        city="Cúcuta",
    )
    assert seed.terms == ("Fisioterapia deportiva", "rehabilitación")
    assert seed.niches == ()  # nothing in the taxonomy — and nothing needed
    # `perritos` is about neither term; the place tag stays
    assert seed.hashtags == ("cucutafisio",)
    assert seed.chips()[:2] == ["Fisioterapia deportiva", "rehabilitación"]

    assert [q.term for q, _ in cd.phase_queries("sector", seed)] == [
        "Fisioterapia deportiva",
        "rehabilitación",
    ]
    assert cd.google_terms("national", seed) == ["Fisioterapia deportiva Colombia"]
    assert [q.label for q, _ in cd.phase_queries("local", seed)] == [
        "tiktok:keyword:Fisioterapia deportiva Cúcuta",
        "tiktok:hashtag:#cucutafisio",
    ]
    # a category on top only adds vocabulary
    both = cd.seed_from_profile({"username": "x"}, sector="fitness_health", rubro_text="crossfit")
    assert cd.sector_terms(both) == [
        "crossfit",
        "fitness",
        "entrenador personal",
        "rutina de ejercicio",
    ]


def test_relevance_stems_match_any_rubro_in_its_own_words() -> None:
    seed = cd.DiscoverySeed("x", (), terms=("peluquería canina",))
    assert cd.relevance_stems(seed) == {"peluq", "canin"}
    groomer = cd.Candidate("tiktok", "g", bio="Peluquero canino en Bogotá 🐶", followers=1)
    baker = cd.Candidate("tiktok", "b", bio="Panadería artesanal", followers=9)
    assert cd._fits_phase("sector", groomer, seed)
    assert not cd._fits_phase("sector", baker, seed)
    # no rubro at all → nothing to require
    assert cd._fits_phase("sector", baker, cd.DiscoverySeed("x", ()))


def test_tiktok_handles_from_google_reads_video_urls_and_skips_discover_pages() -> None:
    payload = {
        "results": [
            {"url": "https://www.tiktok.com/@groomermichel/video/7603926762661219615"},
            {"url": "https://www.tiktok.com/discover/elevate-pilates-bogota"},
            {"url": "https://www.tiktok.com/tag/tecnicacraniosacrale"},
            {"url": "https://www.tiktok.com/@abogadoguillermoh"},
            {"url": "https://www.tiktok.com/@GroomerMichel/photo/1"},  # duplicate
        ]
    }
    assert cd.tiktok_handles_from_google(payload) == ["groomermichel", "abogadoguillermoh"]


def test_split_terms() -> None:
    assert cd.split_terms("Peluquería canina, spa para mascotas y guardería") == (
        "Peluquería canina",
        "spa para mascotas",
        "guardería",
    )
    assert cd.split_terms("  ") == ()
    assert cd.split_terms("a, b, c, d, e") == ()  # too short to search with


def test_a_vendor_5xx_is_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cd, "_RETRY_DELAY_SECONDS", 0)
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        if len(attempts) == 1:
            return httpx.Response(500, json={"success": False, "error": "Internal Server Error"})
        return _keyword(_video("ok", "bio", 10))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        found = cd.run_query(client, cd.Query("tiktok", "keyword", "x", "food_drink"))
    assert [c.username for c in found] == ["ok"] and len(attempts) == 2

    # a 4xx is not retried
    def bad(request: httpx.Request) -> httpx.Response:
        attempts.append("bad")
        return httpx.Response(400, json={"success": False, "error": "missing_parameter"})

    attempts.clear()
    with httpx.Client(transport=httpx.MockTransport(bad)) as client:
        with pytest.raises(cd.ScrapeCreatorsError):
            cd.run_query(client, cd.Query("tiktok", "keyword", "x", "food_drink"))
    assert attempts == ["bad"]
