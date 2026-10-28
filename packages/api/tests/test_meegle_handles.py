"""The explicit channel selects the parser, never the other way round (m-24882931)."""

import pytest

from qualify_api.meegle.handles import normalize_channel, normalize_handle


@pytest.mark.parametrize(
    "raw, expected",
    [(" Instagram ", "instagram"), ("TikTok", "tiktok"), (None, None), ("facebook", None)],
)
def test_channel(raw: str | None, expected: str | None) -> None:
    assert normalize_channel(raw) == expected


@pytest.mark.parametrize(
    "raw", ["@Mi.Negocio", "mi.negocio", "https://www.tiktok.com/@mi.negocio?lang=es"]
)
def test_tiktok_profile(raw: str) -> None:
    assert normalize_handle("tiktok", raw) == "mi.negocio"


@pytest.mark.parametrize(
    "raw",
    [
        "https://vm.tiktok.com/abc/",
        "https://www.tiktok.com/@abc/video/1",
        "https://instagram.com/abc/",
        "no tengo",
        "https://tiktok.com.evil.test/@abc",
        "https://tiktok.com/@abc.",
    ],
)
def test_tiktok_invalid_and_short_urls_are_rejected_offline(raw: str) -> None:
    assert normalize_handle("tiktok", raw) is None


def test_never_infers_a_network() -> None:
    assert normalize_handle("", "@negocio") is None
    assert normalize_handle("instagram", "https://tiktok.com/@negocio") is None
