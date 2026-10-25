"""`creator_discovery`'s Brand Kit integration (2026-09-11) — the three-phase plan, a full phased
run over `httpx.MockTransport`, and the result cache. Fully offline, same posture as
`test_creator_discovery.py`."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from . import creator_discovery as cd

API_KEY = "sk_test_123"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", API_KEY)


# --------------------------------------------------------------------------------------
# country evidence of a candidate. The location detection and the seed it feeds moved
# with `seed_from_profile` to `qualify_api.referentes.discovery_seed` (m-24852195):
# their tests are in `packages/api/tests/test_referentes_discovery_seed.py`.
# --------------------------------------------------------------------------------------


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
    # up to `LOCAL_TERMS` rubro terms with the city (plan 12, 2026-10-05: one term found
    # nobody for a niche rubro in a small city), then the account's own city hashtag,
    # preferred over the composed one
    assert _labels("local", seed) == [
        ("tiktok:keyword:foodie Cúcuta", "CO"),
        ("tiktok:keyword:comida Cúcuta", "CO"),
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
    assert _labels("local", seed)[-1] == ("tiktok:hashtag:#bogotafitness", "CO")


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
    assert national.title == "Negocios parecidos al tuyo en Colombia"
    # `comida.col` did not fit the sector's eight slots, so it is national's now
    assert handles(national) == ["ig.bogota", "comida.col", "bogota.sabor"]
    # the mirror lookups of this phase's TikTok accounts all 404 → no credit, no error
    assert national.errors == []
    # no bio in the keyword feed → the caption describes the account
    assert cd.account_card(national.accounts[2])["blurb"] == "El mejor ajiaco de Bogotá"

    # local: the keyword 404 is an empty result, not an error; the hidden-follower
    # TikTok accounts were enriched, then ranked with the Instagram one
    assert local.title == "Negocios parecidos al tuyo en Cúcuta"
    assert local.errors == []
    assert handles(local) == [
        "sabor.cucuta",
        "ig.cucuta",
        "oculto.uno",
        "local.chico",
        "oculto.dos",
    ]
    # 2 keywords (plan 12: two rubro terms with the city), hashtag, 4 Google (2 terms ×
    # 2 networks), ig read, 3 enrich (mirrors 404 → free)
    assert local.credits == 2 + 1 + 4 + 1 + 3
    assert local.queries == [
        "tiktok:keyword:foodie Cúcuta",
        "tiktok:keyword:comida Cúcuta",
        "tiktok:hashtag:#cucutafood",
        "tiktok:google:foodie Cúcuta",
        "tiktok:google:comida Cúcuta",
        "instagram:google:foodie Cúcuta",
        "instagram:google:comida Cúcuta",
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
        # no reviewer in this run: the AI review's keys are empty
        "kind": "",
        "kind_label": "",
        "review": "",
        "reviewed_by": "",
        # § 2026-10-01: the bio in full, the profile's link, the AI share, the reach signal
        "bio": "Foodie de Cúcuta",
        "external_url": "",
        "ai": "",
        "signal": "",
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
    # the two most specific local terms (plan 12)
    assert cd.google_terms("local", seed) == ["programación Cúcuta", "tecnología Cúcuta"]
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


def _ig_post(caption: str | None) -> dict:
    edges = [] if caption is None else [{"node": {"text": caption}}]
    return {"node": {"edge_media_to_caption": {"edges": edges}}}


def test_an_instagram_read_keeps_its_posts_captions_and_hashtags() -> None:
    """The shape measured live 2026-09-25 (`/v1/instagram/profile`, `mouredev`): the read
    carries the last 12 posts. Their hashtags reach `hashtags_seen` — the only way an
    Instagram account found through Google, related profiles or a mirror feeds the
    catalog — without counting as feed sightings (engagement stays untouched)."""
    posts = [
        _ig_post("Aprende #Python gratis 💬 #programacion #IA"),
        _ig_post(None),  # a post without caption
        _ig_post("Otro curso #programacion #javascript"),
        "not a dict",
    ]
    facts = cd.profile_facts(
        "instagram",
        {"data": {"user": {"edge_owner_to_timeline_media": {"count": 99, "edges": posts}}}},
    )
    assert facts.captions == (
        "Aprende #Python gratis 💬 #programacion #IA",
        "Otro curso #programacion #javascript",
    )

    candidate = cd.Candidate("instagram", "dev")
    cd._apply_facts(candidate, facts, "instagram:profile")
    cd._apply_facts(candidate, facts, "instagram:profile")  # a second read adds nothing
    assert candidate.hashtags_seen == ["python", "programacion", "ia", "javascript"]
    assert candidate.texts.count("Otro curso #programacion #javascript") == 1
    assert (candidate.posts_seen, candidate.likes_seen) == (0, 0)


def test_profile_facts_caps_the_captions_it_keeps() -> None:
    posts = [_ig_post(f"post {i} #tag{i}") for i in range(cd.PROFILE_CAPTIONS + 5)]
    facts = cd.profile_facts(
        "instagram", {"data": {"user": {"edge_owner_to_timeline_media": {"edges": posts}}}}
    )
    assert len(facts.captions) == cd.PROFILE_CAPTIONS


def test_vendor_errors_are_recorded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"success": False, "error": "insufficient credits"})

    seed = cd.DiscoverySeed("x", ("food_drink",))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = cd.run_phase("sector", seed, client=client, pool={}, picked=set())

    assert result.accounts == []
    assert result.errors and "402" in result.errors[0]


# --------------------------------------------------------------------------------------
# the run's memory of profile reads + formatting
# --------------------------------------------------------------------------------------


def test_profile_store_remembers_reads_and_misses() -> None:
    """The in-memory store (a run's own, the CLI's); the Postgres one with its time to
    live is `creator_cache_provider.PostgresProfileStore`, same three methods."""
    store = cd.ProfileStore()
    facts = cd.ProfileFacts(
        followers=5,
        bio="b",
        related=("a", "c"),
        category="Restaurant",
        captions=("menú del día #almuerzo",),
        external_url="https://some.one",
    )
    store.put("instagram", "Some.One", facts)
    store.put("tiktok", "ghost", None)
    store.save()  # nothing to flush

    assert store.get("instagram", "someone") == (True, facts)
    assert store.get("tiktok", "ghost") == (True, None)
    assert store.get("tiktok", "unknown") == (False, None)
    # the document shape the Postgres store keeps round-trips every field
    assert cd.facts_from_document(cd.facts_to_document(facts)) == facts

    # a read served from the store costs nothing and never hits the vendor
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    candidate = cd.Candidate("instagram", "someone")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        charged, got, error = cd._read_profile(client, candidate, None, store)
    assert (charged, got, error) == (0, facts, None)
    assert candidate.followers == 5 and "Restaurant" in candidate.texts
    assert candidate.hashtags_seen == ["almuerzo"]
    assert candidate.external_url == "https://some.one"


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


# --------------------------------------------------------------------------------------
# the shared hashtag catalog (v6): `DiscoverySeed.catalog_hashtags`
# --------------------------------------------------------------------------------------


def test_catalog_hashtags_join_the_sector_queries_and_extend_the_cap() -> None:
    plain = cd.DiscoverySeed("x", (), (), "CO", "", terms=("smash burgers",))
    with_catalog = cd.DiscoverySeed(
        "x", (), (), "CO", "", terms=("smash burgers",), catalog_hashtags=("burgers", "hamburguesa")
    )
    assert cd.sector_terms(plain) == ["smash burgers"]
    # after the operator's words, before any taxonomy phrasing; each one is one more query
    assert cd.sector_terms(with_catalog) == ["smash burgers", "burgers", "hamburguesa"]


def test_catalog_hashtags_never_displace_the_taxonomy_phrasings() -> None:
    base = cd.DiscoverySeed("midu.dev", ("technology", "education"), ("programacion", "css"), "CO")
    enriched = cd.DiscoverySeed(
        "midu.dev",
        ("technology", "education"),
        ("programacion", "css"),
        "CO",
        catalog_hashtags=("devs", "coding"),
    )
    without = cd.sector_terms(base)
    with_tags = cd.sector_terms(enriched)
    assert len(with_tags) == len(without) + 2
    assert [t for t in with_tags if t not in ("devs", "coding")] == without


def test_catalog_hashtags_skip_place_tags_and_duplicates_in_the_sector() -> None:
    seed = cd.DiscoverySeed(
        "x",
        (),
        (),
        "CO",
        "Cúcuta",
        terms=("burgers",),
        catalog_hashtags=("cucutafood", "burgers", "smash"),
    )
    assert cd.sector_terms(seed) == ["burgers", "smash"]


def test_a_rubro_outside_the_taxonomy_gets_a_composed_city_hashtag_from_the_catalog() -> None:
    seed = cd.DiscoverySeed(
        "x", (), (), "CO", "Cúcuta", terms=("smash burgers",), catalog_hashtags=("burgers",)
    )
    assert _labels("local", seed) == [
        ("tiktok:keyword:smash burgers Cúcuta", "CO"),
        ("tiktok:hashtag:#cucutaburgers", "CO"),
    ]


def test_the_taxonomy_and_the_accounts_own_city_tag_still_win_over_the_catalog() -> None:
    niche = cd.DiscoverySeed(
        "x", ("food_drink",), (), "CO", "Bogotá", catalog_hashtags=("burgers",)
    )
    assert _labels("local", niche)[-1] == ("tiktok:hashtag:#bogotafood", "CO")
    own = cd.DiscoverySeed(
        "x", (), ("cucutafood",), "CO", "Cúcuta", terms=("burgers",), catalog_hashtags=("smash",)
    )
    assert _labels("local", own)[-1] == ("tiktok:hashtag:#cucutafood", "CO")


def test_no_catalog_means_no_extra_local_query() -> None:
    seed = cd.DiscoverySeed("x", (), (), "CO", "Cúcuta", terms=("smash burgers",))
    assert _labels("local", seed) == [("tiktok:keyword:smash burgers Cúcuta", "CO")]


def test_catalog_hashtags_repair_a_misspelled_rubro_in_the_relevance_filter() -> None:
    typo = cd.DiscoverySeed("x", (), (), "CO", "", terms=("ventas de hmaburguesas",))
    fixed = cd.DiscoverySeed(
        "x", (), (), "CO", "", terms=("ventas de hmaburguesas",), catalog_hashtags=("hamburguesas",)
    )
    burger = cd.Candidate("tiktok", "smashhouse", bio="Las mejores hamburguesas smash")
    assert not cd._about_the_sector(burger, typo)  # "hmabu" is not "hambu"
    assert cd._about_the_sector(burger, fixed)


def test_catalog_hashtags_show_in_the_chips_without_repeating_own_tags() -> None:
    seed = cd.DiscoverySeed(
        "x", ("food_drink",), ("burgers",), "CO", "", catalog_hashtags=("burgers", "smash")
    )
    chips = seed.chips()
    assert chips.count("#burgers") == 1
    assert "#smash" in chips


def test_the_catalog_never_changes_the_cache_key() -> None:
    """The catalog grows with every search; a key that followed it would discard stored
    phases (and their credits) each time it did."""
    a = cd.DiscoverySeed("x", ("food_drink",), (), "CO", "Cúcuta", terms=("burgers",))
    b = cd.DiscoverySeed(
        "x", ("food_drink",), (), "CO", "Cúcuta", terms=("burgers",), catalog_hashtags=("smash",)
    )
    assert a.signature() == b.signature()
    for key in cd.PHASES:
        assert cd.phase_signature(key, a) == cd.phase_signature(key, b)


# -- the operator's pills (`chosen_hashtags`, § request 2026-09-25) -------------------


def test_chosen_hashtags_replace_the_catalogs_and_widen_the_sector_queries() -> None:
    seed = cd.DiscoverySeed(
        "smash",
        (),
        terms=("hamburgueseria",),
        catalog_hashtags=("foodie",),
        chosen_hashtags=("hamburguesas", "burger", "smashburger", "burgerlovers", "cheeseburger"),
    )
    terms = cd.sector_terms(seed)
    assert terms[0] == "hamburgueseria"
    assert terms[1:] == ["hamburguesas", "burger", "smashburger", "burgerlovers", "cheeseburger"]
    assert "foodie" not in terms  # the catalog's pick yields to the operator's
    assert seed.steering_hashtags() == seed.chosen_hashtags
    assert "#cheeseburger" in seed.chips() and "#foodie" not in seed.chips()


def test_changing_the_pills_is_a_new_sector_and_local_search_but_not_a_national_one() -> None:
    base = cd.DiscoverySeed(
        "smash", (), terms=("hamburgueseria",), country_code="VE", city="Caracas"
    )
    picked = cd.DiscoverySeed(
        "smash",
        (),
        terms=("hamburgueseria",),
        country_code="VE",
        city="Caracas",
        chosen_hashtags=("hamburguesas",),
    )
    assert base.signature() != picked.signature()
    assert cd.phase_signature("sector", base) != cd.phase_signature("sector", picked)
    assert cd.phase_signature("local", base) != cd.phase_signature("local", picked)
    assert cd.phase_signature("national", base) == cd.phase_signature("national", picked)
    # the catalog's own choice still never is part of any key
    catalog = cd.DiscoverySeed("smash", (), terms=("hamburgueseria",), catalog_hashtags=("x",))
    assert (
        catalog.signature() == cd.DiscoverySeed("smash", (), terms=("hamburgueseria",)).signature()
    )


# -- the two networks walk at once (2026-10-01) ---------------------------------------------


def test_both_networks_walk_at_the_same_time_and_fold_in_network_order() -> None:
    """With an executor the TikTok and Instagram walks of a phase overlap (the barrier
    only opens when both are inside); their credits, queries and errors land in `result`
    in network order, whichever finished first."""
    gate = threading.Barrier(2, timeout=5)
    result = cd.PhaseResult(key="sector", title="Sector")

    def walk(network: str, acc: cd.PhaseResult) -> None:
        gate.wait()  # raises BrokenBarrierError if the walks ran one after the other
        if network == "instagram":
            acc.credits += 1
            acc.queries.append("instagram:google:x")
        else:
            threading.Event().wait(0.05)  # TikTok finishes second on purpose
            acc.credits += 2
            acc.queries.append("tiktok:google:x")
            acc.errors.append("tiktok:google:y: 500")

    with ThreadPoolExecutor(max_workers=2) as executor:
        cd._run_networks(executor, result, walk)
    assert result.credits == 3
    assert result.queries == ["tiktok:google:x", "instagram:google:x"]
    assert result.errors == ["tiktok:google:y: 500"]


def test_without_an_executor_the_networks_walk_one_after_the_other() -> None:
    seen: list[str] = []
    result = cd.PhaseResult(key="sector", title="Sector")
    cd._run_networks(None, result, lambda network, acc: seen.append(network))
    assert seen == ["tiktok", "instagram"]


def test_a_failed_walk_raises_on_the_calling_thread() -> None:
    result = cd.PhaseResult(key="sector", title="Sector")

    def walk(network: str, acc: cd.PhaseResult) -> None:
        if network == "instagram":
            raise RuntimeError("instagram walk broke")
        acc.credits += 1

    with ThreadPoolExecutor(max_workers=2) as executor:
        with pytest.raises(RuntimeError, match="instagram walk broke"):
            cd._run_networks(executor, result, walk)


# -- what tells an account apart at a glance (2026-10-01) ----------------------------------


def test_feed_videos_with_tiktoks_ai_label_are_counted_per_account() -> None:
    def video(handle: str, aigc: dict | None, views: int = 1_000) -> dict:
        item = {
            "author": {"unique_id": handle, "nickname": handle, "follower_count": 10},
            "statistics": {"digg_count": 10, "comment_count": 1, "play_count": views},
            "desc": "hola",
        }
        if aigc is not None:
            item["aigc_info"] = aigc
        return item

    found = cd.candidates_from_tiktok_videos(
        {
            "aweme_list": [
                video("sora.fan", {"aigc_label_type": 2, "created_by_ai": True}),
                video("sora.fan", {"aigc_label_type": 0, "created_by_ai": False}),
                video("sora.fan", None),  # a trimmed read says nothing
                video("plain", {"aigc_label_type": 0, "created_by_ai": False}),
            ]
        },
        "tiktok:keyword:x",
    )
    pool: dict[tuple[str, str], cd.Candidate] = {}
    for candidate in found:
        existing = pool.get(candidate.key)
        if existing is None:
            pool[candidate.key] = candidate
        else:
            existing.merge(candidate)
    fan, plain = pool[("tiktok", "sora.fan")], pool[("tiktok", "plain")]
    assert (fan.posts_seen, fan.ai_posts_seen) == (3, 1)
    assert cd.account_card(fan)["ai"] == "1/3"
    assert cd.account_card(plain)["ai"] == ""


def test_reach_far_above_the_phase_with_little_interaction_is_flagged() -> None:
    def seen(handle: str, views: int, likes: int) -> cd.Candidate:
        c = cd.Candidate("tiktok", handle, followers=1000)
        c.absorb_post(likes=likes, comments=0, views=views, text="")
        return c

    peers = [seen(f"p{i}", 10_000, 500) for i in range(4)]  # 5 % likes per view
    pushed = seen("ads", 100_000, 400)  # 10x the reach, 0.4 % per view
    viral = seen("viral", 100_000, 6_000)  # 10x the reach, but the audience reacts
    signals = cd.reach_signals([*peers, pushed, viral])
    assert signals[("tiktok", "ads")] == cd.REACH_SIGNAL
    assert signals[("tiktok", "viral")] == ""
    assert all(signals[p.key] == "" for p in peers)
    # too few measured accounts: nothing is judged
    assert cd.reach_signals([pushed, viral]) == {}
    # and the phase's cards carry it
    result = cd.PhaseResult(key="sector", title="s", accounts=[*peers, pushed])
    cards = cd.phase_to_dict(result)["accounts"]
    assert [c["signal"] != "" for c in cards] == [False] * 4 + [True]


def test_place_phase_titles_name_similar_businesses() -> None:
    """NAV-11 (m-24849129): the owner reads «Negocios parecidos al tuyo …», never
    «Referentes en …», for the country and city phases."""
    seed = cd.DiscoverySeed("x", ("food_drink",), (), "CO", "Cúcuta")
    bare = cd.DiscoverySeed("x", ("food_drink",))
    assert cd.phase_title("national", seed) == "Negocios parecidos al tuyo en Colombia"
    assert cd.phase_title("local", seed) == "Negocios parecidos al tuyo en Cúcuta"
    assert cd.phase_title("national", bare) == "Negocios parecidos al tuyo en tu país"
    assert cd.phase_title("local", bare) == "Negocios parecidos al tuyo cerca de ti"


@pytest.mark.parametrize(
    ("key", "stored", "shown"),
    [
        ("national", "Referentes en Colombia", "Negocios parecidos al tuyo en Colombia"),
        ("national", "Referentes nacionales", "Negocios parecidos al tuyo en tu país"),
        ("local", "Referentes en Cúcuta", "Negocios parecidos al tuyo en Cúcuta"),
        ("local", "Referentes locales", "Negocios parecidos al tuyo cerca de ti"),
        ("local", "Negocios parecidos al tuyo en Cúcuta", "Negocios parecidos al tuyo en Cúcuta"),
        ("sector", "Referentes del sector", "Referentes del sector"),
    ],
)
def test_a_saved_search_shows_its_title_in_todays_words(key: str, stored: str, shown: str) -> None:
    assert cd.owner_phase_title(key, stored) == shown
