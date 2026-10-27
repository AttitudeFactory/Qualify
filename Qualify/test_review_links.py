"""Retention email links survive login without opening arbitrary return URLs."""

from uuid import UUID

import pytest

from .review_links import review_destination, review_href

PIECE = UUID("a0000000-0000-4000-8000-000000000001")


@pytest.mark.parametrize("suffix", ["", "/", "?confirm=true&next=https://evil.example"])
def test_piece_return_preserves_only_the_valid_piece_path(suffix: str) -> None:
    assert review_destination(f"/drafts/{PIECE}{suffix}") == f"/drafts/{PIECE}"


@pytest.mark.parametrize(
    "raw",
    [
        f"https://evil.example/drafts/{PIECE}",
        f"//evil.example/drafts/{PIECE}",
        f"/drafts/{PIECE}#confirm",
        f"/drafts/{PIECE}/delete",
        f"/drafts/{PIECE}//",
        "/drafts/not-a-uuid",
        "/drafts/../settings",
        "/drafts/%2f%2fevil.example",
        "/drafts/",
    ],
)
def test_piece_return_rejects_external_ambiguous_or_action_paths(raw: str) -> None:
    assert review_destination(raw) == ""


def test_existing_review_return_still_preserves_the_review_piece() -> None:
    assert review_destination(review_href(str(PIECE))) == review_href(str(PIECE))
