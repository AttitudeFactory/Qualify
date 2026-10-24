"""NAV-11 (m-24849129): a failed publish reaches the owner in plain Spanish, never as its
diagnostic code (`publish_attempts.platform_error_code`)."""

from __future__ import annotations

import pytest

from qualify_api.publishing import failure_text as ft
from qualify_api.publishing.service import (
    CEILING_EXCEEDED,
    CHILD_ERROR_PREFIX,
    CONNECTION_NOT_ACTIVE_PREFIX,
    CONTAINER_ERROR_PREFIX,
    PLATFORM_CODE_PREFIX,
)


@pytest.mark.parametrize(
    ("code", "text"),
    [
        (f"{CONNECTION_NOT_ACTIVE_PREFIX}:expired", ft.CONNECTION_TEXT),
        (CEILING_EXCEEDED, ft.SLOW_TEXT),
        (f"{CONTAINER_ERROR_PREFIX}_error", ft.FILE_REFUSED_TEXT),
        (f"{CONTAINER_ERROR_PREFIX}_expired", ft.FILE_REFUSED_TEXT),
        (f"{PLATFORM_CODE_PREFIX}:9007", ft.REFUSED_TEXT),
        (f"{CHILD_ERROR_PREFIX}:container_error", ft.CAROUSEL_ITEM_TEXT),
        ("http_500", ft.UPLOAD_TEXT),
        ("upload_failed", ft.UPLOAD_TEXT),
        ("unrecognised_response", ft.UPLOAD_TEXT),
        ("OAuthException", ft.GENERIC_TEXT),
        ("", ft.GENERIC_TEXT),
        (None, ft.GENERIC_TEXT),
    ],
)
def test_every_code_has_the_owners_words(code: str | None, text: str) -> None:
    assert ft.failure_text(code) == text


def test_no_text_carries_a_code_or_an_english_word() -> None:
    texts = [value for name, value in vars(ft).items() if name.endswith("_TEXT")]
    assert len(texts) == 7
    for text in texts:
        assert "_" not in text and ":" not in text
        lowered = text.lower()
        for word in ("post", "error", "upload", "container", "http", "feed"):
            assert word not in lowered, (word, text)
