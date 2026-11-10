"""m-24992894: each part with a vista previa to watch carries its video, its poster and
its length on its row; no other part does. Pure (`derive_progress`, `_seconds`)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from qualify_api.creative.fsm import APPROVED, DRAFTING, FAILED, GENERATED
from qualify_api.creative.part_progress import (
    PartFacts,
    PartState,
    _seconds,
    derive_progress,
    poster_key,
)

NOW = 1_800_000_000.0
PARENT = UUID("7a7a0000-0000-4000-8000-000000000002")
VIDEO = "t/x/generated/c/r1/clip-logo.mp4"
POSTER = "t/x/generated/c/r1/first-frame.jpg"


def made(index: int, status: str = GENERATED, **kw: object) -> PartFacts:
    base: dict[str, object] = {
        "index": index,
        "mode": "reference",
        "seconds": 4,
        "draft_id": uuid4(),
        "status": status,
        "has_video": True,
        "preview": {"status": "draft", "created_at": NOW - 60},
        "video_key": VIDEO,
        "poster_key": POSTER,
        "video_seconds": 6.0,
    }
    base.update(kw)
    return PartFacts(**base)  # type: ignore[arg-type]


def test_a_part_to_review_or_ready_carries_its_preview() -> None:
    progress = derive_progress(PARENT, [made(1), made(2, APPROVED)], now=NOW)
    for row in progress.parts:
        assert row.has_preview
        assert row.preview_video_key == VIDEO
        assert row.preview_poster_key == POSTER
        assert row.preview_seconds == 6.0


def test_a_part_without_a_preview_to_watch_carries_none() -> None:
    expired = made(1, preview={"status": "draft", "created_at": NOW - 8 * 24 * 3600})
    rows = derive_progress(
        PARENT,
        [
            expired,
            made(2, purged=True),
            made(3, FAILED, has_video=False),
            made(4, DRAFTING, has_video=False, jobs=("queued",)),
            PartFacts(index=5, mode="reference", seconds=4),
        ],
        now=NOW,
    ).parts
    assert rows[0].state is PartState.EXPIRED
    for row in rows:
        assert not row.has_preview
        assert (row.preview_video_key, row.preview_poster_key, row.preview_seconds) == (
            "",
            "",
            None,
        )


def test_a_preview_without_a_recorded_length_or_poster_keeps_the_video() -> None:
    row = derive_progress(PARENT, [made(1, poster_key=None, video_seconds=None)], now=NOW).parts[0]
    assert row.preview_video_key == VIDEO
    assert row.preview_poster_key == ""
    assert row.preview_seconds is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (6, 6.0),
        ("6", 6.0),
        ("5.5", 5.5),
        (None, None),
        ("", None),
        ("x", None),
        (0, None),
        (-2, None),
        (True, None),
        ("nan", None),
    ],
)
def test_seconds_as_stored(value: object, expected: float | None) -> None:
    assert _seconds(value) == expected


@pytest.mark.parametrize(
    ("thumbnail", "preview", "expected"),
    [
        (POSTER, VIDEO, POSTER),
        (None, POSTER, POSTER),
        (None, VIDEO, None),  # `preview_of` without a thumbnail: the mp4 is never a poster
        ("", "t/x/r1/still.PNG", "t/x/r1/still.PNG"),
        (VIDEO, None, None),
        (None, None, None),
    ],
)
def test_the_poster_is_a_picture_or_none(
    thumbnail: str | None, preview: str | None, expected: str | None
) -> None:
    assert poster_key(thumbnail, preview) == expected
