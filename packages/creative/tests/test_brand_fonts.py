"""`qualify_creative.brand.fonts` (§ request 2026-10-05): the family a font file declares,
a guess from its name when it cannot be read, and whether Google Fonts serves it. The
font files are built here, byte by byte — CI has no fonts to read."""

from __future__ import annotations

import struct
import urllib.error
import zlib

import pytest

from qualify_creative.brand import fonts


def _name_table(records: list[tuple[int, int, int, int, str]]) -> bytes:
    """A `name` table: (platform, encoding, language, name_id, text) records."""
    strings = b""
    entries = b""
    for platform, encoding, language, name_id, text in records:
        raw = text.encode("mac_roman" if platform == 1 else "utf-16-be")
        entries += struct.pack(
            ">HHHHHH", platform, encoding, language, name_id, len(raw), len(strings)
        )
        strings += raw
    header = struct.pack(">HHH", 0, len(records), 6 + len(entries))
    return header + entries + strings


def _ttf(name: bytes, flavor: bytes = b"\x00\x01\x00\x00") -> bytes:
    offset = 12 + 16
    directory = flavor + struct.pack(">HHHH", 1, 16, 0, 0)
    directory += struct.pack(">4sIII", b"name", 0, offset, len(name))
    return directory + name


def _woff(name: bytes) -> bytes:
    packed = zlib.compress(name)
    offset = 44 + 20
    header = b"wOFF" + b"\x00\x01\x00\x00" + struct.pack(">IHH", 0, 1, 0) + b"\x00" * 32
    entry = struct.pack(">4sIIII", b"name", offset, len(packed), len(name), 0)
    return header + entry + packed


def test_the_typographic_family_wins_over_the_style_linked_one() -> None:
    table = _name_table(
        [
            (3, 1, 0x409, 1, "Montserrat SemiBold"),
            (3, 1, 0x409, 16, "Montserrat"),
            (1, 0, 0, 1, "Montserrat Mac"),
        ]
    )
    assert fonts.family_name(_ttf(table), "whatever.ttf") == "Montserrat"
    assert fonts.family_name(_ttf(table, b"OTTO"), "x.otf") == "Montserrat"


def test_without_a_typographic_family_the_family_record_is_read() -> None:
    table = _name_table([(1, 0, 0, 1, "Marca Sans"), (3, 1, 0x40A, 1, "Marca Sans ES")])
    assert fonts.family_name(_ttf(table)) == "Marca Sans ES"  # Windows before Mac


def test_a_woff_is_inflated_and_read() -> None:
    table = _name_table([(3, 1, 0x409, 1, "Nunito")])
    assert fonts.family_name(_woff(table), "Nunito-Bold.woff") == "Nunito"


def _woff_raw(packed: bytes, orig_length: int) -> bytes:
    header = b"wOFF" + b"\x00\x01\x00\x00" + struct.pack(">IHH", 0, 1, 0) + b"\x00" * 32
    entry = struct.pack(">4sIIII", b"name", 44 + 20, len(packed), orig_length, 0)
    return header + entry + packed


def test_a_woff_bomb_is_never_inflated() -> None:
    """PR #86 review: 64 MB of zeros packs into ~64 KB. Declared honestly it is above the
    table cap; declared small, inflation stops at the declared length — either way the
    app never holds the expanded stream, and the name comes from the file name."""
    bomb = zlib.compress(b"\x00" * (64 * 1024 * 1024))
    assert fonts.family_name(_woff_raw(bomb, 64 * 1024 * 1024), "Marca-Bold.woff") == "Marca"
    assert fonts.family_name(_woff_raw(bomb, 4096), "Marca-Bold.woff") == "Marca"


def test_a_woff_that_lies_about_its_table_length_falls_back_to_the_file_name() -> None:
    table = _name_table([(3, 1, 0x409, 1, "Nunito")])
    packed = zlib.compress(table)
    assert fonts.family_name(_woff_raw(packed, len(table) + 50), "Lato-Bold.woff") == "Lato"


def test_a_woff2_or_garbage_falls_back_to_the_file_name() -> None:
    assert fonts.family_name(b"wOF2" + b"\x00" * 60, "OpenSans-SemiBoldItalic.woff2") == "Open Sans"
    assert fonts.family_name(b"not a font", "Baloo2-ExtraBold.ttf") == "Baloo 2"
    assert fonts.family_name(b"\x00\x01\x00\x00\xff", "") == ""  # truncated, no name


def test_the_file_name_guess_drops_the_style_but_keeps_the_width() -> None:
    cases = {
        "OpenSans-SemiBoldItalic.woff2": "Open Sans",
        "Inter[wght].ttf": "Inter",
        "roboto_condensed-bold.woff2": "Roboto Condensed",
        "MontserratBold.otf": "Montserrat",
        "PlayfairDisplay-VariableFont_wght.ttf": "Playfair Display",
        "Poppins-ExtraLight400.ttf": "Poppins",
        "Lato.ttf": "Lato",
    }
    for name, family in cases.items():
        assert fonts.family_from_filename(name) == family, name


def test_google_fonts_answers_200_for_a_family_it_serves_and_400_otherwise() -> None:
    asked: list[str] = []

    def fetch(status: int):
        def _fetch(url: str) -> int:
            asked.append(url)
            return status

        return _fetch

    assert fonts.on_google_fonts("Playfair Display", fetch=fetch(200)) is True
    assert asked[-1].endswith("family=Playfair+Display")
    assert fonts.on_google_fonts("Marca Sans", fetch=fetch(400)) is False
    assert fonts.on_google_fonts("Marca Sans", fetch=fetch(503)) is None

    def offline(_url: str) -> int:
        raise OSError("no network")

    assert fonts.on_google_fonts("Lato", fetch=offline) is None  # unknown is not "no"
    assert fonts.on_google_fonts("", fetch=fetch(200)) is False


def test_a_familys_file_comes_from_google_fonts_bold_first_and_is_kept() -> None:
    """m-24828920: a kit that names a family but holds no file still draws in it."""
    asked: list[str] = []
    css = b"@font-face { src: url(https://fonts.gstatic.com/s/lobster/v32/x.ttf); }"

    def fetch(url: str) -> bytes:
        asked.append(url)
        if "wght@700" in url:
            raise _http(url, 400)  # Lobster has no bold
        return css if url.startswith(fonts.GOOGLE_FONTS_CSS) else b"\x00\x01\x00\x00ttf"

    fonts._downloaded.clear()
    fonts._missing.clear()
    assert fonts.google_font_file("Lobster", fetch=fetch) == b"\x00\x01\x00\x00ttf"
    assert asked == [
        f"{fonts.GOOGLE_FONTS_CSS}?family=Lobster:wght@700",
        f"{fonts.GOOGLE_FONTS_CSS}?family=Lobster",
        "https://fonts.gstatic.com/s/lobster/v32/x.ttf",
    ]
    assert fonts.google_font_file("Lobster", fetch=fetch) == b"\x00\x01\x00\x00ttf"
    assert len(asked) == 3  # downloaded once per process


def _http(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "", None, None)  # type: ignore[arg-type]


def test_a_family_google_fonts_does_not_serve_is_not_asked_again_for_a_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review 2026-10-22: every piece of such a brand made two blocking requests."""
    asked: list[str] = []

    def not_served(url: str) -> bytes:
        asked.append(url)
        raise _http(url, 400)

    now = [1000.0]
    monkeypatch.setattr(fonts.time, "monotonic", lambda: now[0])
    fonts._downloaded.clear()
    fonts._missing.clear()
    assert fonts.google_font_file("Marca Sans", fetch=not_served) is None
    assert len(asked) == 2  # the bold face, then any face
    now[0] += 23 * 3600
    assert fonts.google_font_file("Marca Sans", fetch=not_served) is None
    assert len(asked) == 2  # a fact for the day: not asked again
    now[0] += 2 * 3600
    assert fonts.google_font_file("Marca Sans", fetch=not_served) is None
    assert len(asked) == 4


def test_an_unreachable_google_fonts_is_asked_again_minutes_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []

    def offline(url: str) -> bytes:
        asked.append(url)
        raise OSError("no network")

    now = [1000.0]
    monkeypatch.setattr(fonts.time, "monotonic", lambda: now[0])
    fonts._downloaded.clear()
    fonts._missing.clear()
    assert fonts.google_font_file("Lato", fetch=offline) is None
    assert fonts.google_font_file("Lato", fetch=offline) is None
    assert len(asked) == 2  # the miss is remembered…
    now[0] += 11 * 60
    assert fonts.google_font_file("Lato", fetch=lambda url: b"/* no font-face */") is None
    assert fonts.google_font_file("", fetch=offline) is None
