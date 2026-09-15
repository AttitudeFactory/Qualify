"""Pictures on the discovery cards (request 2026-09-14): the vendor's avatar URL is
captured wherever an account is sighted, survives merges and the profile cache, and
`avatar_path` turns it into the backend route the card's `<img>` asks for."""

from __future__ import annotations

from . import creator_discovery as cd

_TT_SIGNED = "https://p16-common-sign.tiktokcdn-us.com/tos/abc~c5_1080x1080.jpeg?x-expires=1"
_IG_SIGNED = "https://scontent.cdninstagram.com/v/t51/pic.jpg?_nc_ht=x&oh=y"


def test_tiktok_feed_authors_carry_the_url_list_picture() -> None:
    """Since 2026-09-14 the SMALLEST size present wins (speed), so the fixture's
    `avatar_thumb` — not its `avatar_larger` — is what the candidate carries."""
    author = {
        "unique_id": "sof_lol",
        "avatar_larger": {"uri": "tos/abc", "url_list": ["https://big", "https://big2"]},
        "avatar_thumb": {"uri": "tos/abc", "url_list": [_TT_SIGNED]},
    }
    [candidate] = cd.candidates_from_tiktok_videos(
        {"aweme_list": [{"author": author}]}, "tiktok:keyword:x"
    )
    assert candidate.avatar == _TT_SIGNED
    # only the larger one present: falls back to it rather than nothing
    assert cd._tiktok_avatar({"avatar_larger": {"url_list": ["https://only"]}}) == "https://only"
    assert cd._tiktok_avatar({"avatar_larger": {"url_list": []}, "avatar_thumb": "nope"}) == ""
    assert cd._tiktok_avatar({}) == ""


def test_tiktok_avatar_prefers_the_smallest_size_present() -> None:
    """§ request 2026-09-14 ("más rápido cargar las imágenes"): smaller sizes always
    win over larger ones when more than one is present, in this priority order —
    `168x168` > `thumb` > `medium` > `300x300` > `larger`."""

    def field(url: str) -> dict[str, object]:
        return {"url_list": [url]}

    assert (
        cd._tiktok_avatar(
            {
                "avatar_168x168": field("https://168"),
                "avatar_thumb": field("https://thumb"),
                "avatar_larger": field("https://larger"),
            }
        )
        == "https://168"
    )
    assert (
        cd._tiktok_avatar(
            {"avatar_thumb": field("https://thumb"), "avatar_larger": field("https://larger")}
        )
        == "https://thumb"
    )
    assert (
        cd._tiktok_avatar(
            {"avatar_medium": field("https://medium"), "avatar_300x300": field("https://300")}
        )
        == "https://medium"
    )
    assert cd._tiktok_avatar({"avatar_larger": field("https://larger")}) == "https://larger"


def test_profile_reads_carry_the_picture_on_both_networks() -> None:
    tiktok = cd.profile_facts(
        "tiktok",
        {"user": {"signature": "b", "avatarLarger": "https://big", "avatarThumb": _TT_SIGNED}},
    )
    assert tiktok.avatar == _TT_SIGNED  # the thumb wins over the larger one, for speed
    instagram = cd.profile_facts(
        "instagram",
        {
            "data": {
                "user": {
                    "biography": "b",
                    "profile_pic_url_hd": _IG_SIGNED,
                    "profile_pic_url": "https://small",
                }
            }
        },
    )
    assert instagram.avatar == _IG_SIGNED
    assert (
        cd.profile_facts(
            "instagram", {"data": {"user": {"profile_pic_url": "https://small"}}}
        ).avatar
        == "https://small"
    )


def test_instagram_reel_owners_and_merges_keep_a_picture() -> None:
    [candidate] = cd.candidates_from_instagram_reels(
        {"reels": [{"owner": {"username": "midu.dev", "profile_pic_url": _IG_SIGNED}}]},
        "instagram:reels",
    )
    assert candidate.avatar == _IG_SIGNED
    bare = cd.Candidate(network="instagram", username="midu.dev")
    bare.merge(candidate)
    assert bare.avatar == _IG_SIGNED
    # a profile read is the freshest sighting — its URL replaces an older one
    cd._apply_facts(
        bare, cd.ProfileFacts(followers=1, bio="", avatar="https://fresh"), "instagram:profile"
    )
    assert bare.avatar == "https://fresh"
    cd._apply_facts(bare, cd.ProfileFacts(followers=1, bio=""), "instagram:profile")
    assert bare.avatar == "https://fresh"  # a read without one keeps what there was


def test_the_profile_cache_round_trips_the_picture(tmp_path) -> None:
    cache = cd.ProfileStore(tmp_path / "profiles.json")
    cache.put(
        "tiktok", "sof_lol", cd.ProfileFacts(followers=5, bio="b", avatar=_TT_SIGNED), now=100.0
    )
    known, facts = cache.get("tiktok", "sof_lol", now=200.0)
    assert known and facts is not None and facts.avatar == _TT_SIGNED


def test_account_card_and_avatar_path() -> None:
    candidate = cd.Candidate(
        network="tiktok",
        username="Sof_Lol",
        profile_url="https://www.tiktok.com/@Sof_Lol",
        avatar=_TT_SIGNED,
    )
    card = cd.account_card(candidate)
    assert card["avatar"] == _TT_SIGNED
    path = cd.avatar_path(card)
    assert path == (
        f"{cd.AVATAR_ROUTE}/tiktok/Sof_Lol?u="
        "https%3A%2F%2Fp16-common-sign.tiktokcdn-us.com%2Ftos%2Fabc~c5_1080x1080.jpeg%3Fx-expires%3D1"
    )
    # a card from a cache written before pictures existed still gets a path (the
    # proxy has a by-handle fallback); a card with no handle or an unknown network gets none
    assert cd.avatar_path({"handle": "@midu.dev", "network": "Instagram"}) == (
        f"{cd.AVATAR_ROUTE}/instagram/midu.dev"
    )
    assert cd.avatar_path({"handle": "", "network": "TikTok"}) == ""
    assert cd.avatar_path({"handle": "@x", "network": "YouTube"}) == ""


def test_tiktok_avatar_skips_the_heic_entries_of_a_url_list() -> None:
    """Measured 2026-09-14: every TikTok feed author carries `url_list` as
    `[heic, heic, jpeg]` for the same picture, and HEIC renders nowhere but Safari."""
    heic_1 = "https://p16.tiktokcdn.com/a~tplv-cropcenter-q:168:168:q70.heic?x=1"
    heic_2 = "https://p19.tiktokcdn.com/a~tplv-cropcenter-q:168:168:q70.heic?x=1"
    jpeg = "https://p16.tiktokcdn.com/a~tplv-cropcenter-q:168:168:q70.jpeg?x=1"
    assert cd._tiktok_avatar({"avatar_168x168": {"url_list": [heic_1, heic_2, jpeg]}}) == jpeg
    # only HEIC available: keep it (the proxy converts it) rather than nothing
    assert cd._tiktok_avatar({"avatar_thumb": {"url_list": [heic_1]}}) == heic_1
