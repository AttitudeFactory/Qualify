"""`qualify_api.meegle.instagram.normalize_instagram_handle` (m-24852194, PB-1) — pure."""

from __future__ import annotations

import pytest

from qualify_api.meegle.instagram import normalize_instagram_handle


@pytest.mark.parametrize(
    "raw",
    [
        "usuario",
        "@usuario",
        "  @Usuario  ",
        "USUARIO",
        "https://www.instagram.com/usuario/",
        "https://www.instagram.com/usuario",
        "http://instagram.com/usuario",
        "instagram.com/usuario?igsh=MWxyZ2w5dHN0bW1zZQ==",
        "www.instagram.com/Usuario/?hl=es",
        "https://m.instagram.com/usuario/#top",
        "https://www.instagram.com/@usuario/",
        "https://instagr.am/usuario",
    ],
)
def test_every_way_of_writing_the_account_gives_the_username(raw: str) -> None:
    assert normalize_instagram_handle(raw) == "usuario"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("la.nona_arepera", "la.nona_arepera"),
        ("@polette.heladeria", "polette.heladeria"),
        ("bianki_2024", "bianki_2024"),
        ("a" * 30, "a" * 30),
    ],
)
def test_valid_charset_is_kept(raw: str, expected: str) -> None:
    assert normalize_instagram_handle(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "@",
        "la nona",  # spaces
        "usuario!",  # outside the charset
        "josé",  # no accents in IG usernames
        "a" * 31,  # too long
        ".usuario",
        "usuario.",
        "us..uario",
        "https://www.instagram.com/",
        "instagram.com",
        "https://www.instagram.com/p/C1a2b3c4/",  # a post, not a profile
        "https://www.instagram.com/reel/C1a2b3c4/",
        "https://www.facebook.com/usuario",  # another network
        "https://tiktok.com/@usuario",
    ],
)
def test_empty_or_not_an_account_is_none(raw: str | None) -> None:
    assert normalize_instagram_handle(raw) is None
