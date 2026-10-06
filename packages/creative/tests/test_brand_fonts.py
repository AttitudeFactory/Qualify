"""`qualify_creative.brand.fonts` (§ request 2026-10-05): the family a font file declares,
a guess from its name when it cannot be read, and whether Google Fonts serves it. The
font files are built here, byte by byte — CI has no fonts to read."""

from __future__ import annotations

import struct
import zlib

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
