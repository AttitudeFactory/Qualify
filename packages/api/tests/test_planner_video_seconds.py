"""m-25026481: a video Historia warns from the video's STORED length — pure.

`publishable.destination_options(video_seconds=...)` is the rule; the planner readers
(`draft_post_reader.first_video_seconds`) feed it from `image_assets.params.duration_seconds`.
A long video story is a warning, never a block: Historia stays available.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qualify_api.planner.draft_post_reader import first_video_seconds
from qualify_api.planner.publishable import (
    STORY_VIDEO_MAX_SECONDS,
    STORY_VIDEO_TOLERANCE_SECONDS,
    STORY_VIDEO_WARNING,
    destination_options,
    format_video_duration,
    story_video_too_long,
    video_seconds_of,
)


def _by_destination(media_types: tuple[str, ...], **kw: object) -> dict:
    return {o.destination: o for o in destination_options(media_types, **kw)}  # type: ignore[arg-type]


def _story(seconds: float | None) -> object:
    return _by_destination(("VIDEO",), video_seconds=seconds)["story"]


# -- destination_options --------------------------------------------------------------------


@pytest.mark.parametrize("seconds", [None, 0, -3.0, float("nan"), float("inf")])
def test_an_unknown_length_keeps_todays_generic_warning(seconds: float | None) -> None:
    story = _story(seconds)
    assert story.available and story.warning == STORY_VIDEO_WARNING
    # the positional call every caller made before is the same answer
    legacy = _by_destination(("VIDEO",))["story"]
    assert (
        legacy.warning
        == STORY_VIDEO_WARNING
        == (
            "Una Historia de video puede durar como máximo 60 segundos. Si este video es más "
            "largo, Instagram la rechazará al publicar."
        )
    )


@pytest.mark.parametrize("seconds", [5.0, 59.9, 60.0])
def test_a_video_within_the_limit_has_no_warning(seconds: float) -> None:
    story = _story(seconds)
    assert (story.offered, story.available, story.warning) == (True, True, "")


@pytest.mark.parametrize("seconds", [60.2, 60.5])
def test_the_tolerance_grey_zone_keeps_the_generic_warning(seconds: float) -> None:
    # nothing proves Meta takes a 60.2 s clip, but calling it too long would be a guess
    story = _story(seconds)
    assert story.available and story.warning == STORY_VIDEO_WARNING
    assert not story_video_too_long(seconds)


@pytest.mark.parametrize(
    ("seconds", "length"), [(60.6, "1 min 1 s"), (85.0, "1 min 25 s"), (125.4, "2 min 5 s")]
)
def test_a_video_over_the_limit_warns_with_its_length_and_stays_available(
    seconds: float, length: str
) -> None:
    story = _story(seconds)
    assert story.offered and story.available  # a warning, never a block
    assert story.warning == (
        f"Este video dura {length} y una Historia admite hasta 1 minuto: Instagram la "
        "rechazará. Elige Reel o sube un video más corto."
    )


@pytest.mark.parametrize("seconds", [None, 10.0, 85.0])
def test_the_reel_is_unaffected_by_the_length(seconds: float | None) -> None:
    options = _by_destination(("VIDEO",), video_seconds=seconds)
    assert (options["reel"].available, options["reel"].warning) == (True, "")
    assert not options["post"].offered


def test_images_and_carousels_ignore_a_length_passed_anyway() -> None:
    for media, size in ((("IMAGE",), (1080, 1350)), (("IMAGE", "VIDEO"), None)):
        assert _by_destination(media, image_size=size, video_seconds=85.0) == _by_destination(
            media, image_size=size
        )


# -- helpers --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (59, "59 s"),
        (60, "1 min"),
        (85, "1 min 25 s"),
        (125.4, "2 min 5 s"),
        (120, "2 min"),
        (65, "1 min 5 s"),
        (0.4, "0 s"),
    ],
)
def test_the_length_reads_like_the_owner_says_it(seconds: float, text: str) -> None:
    assert format_video_duration(seconds) == text


def test_too_long_means_known_and_beyond_the_tolerance() -> None:
    limit = STORY_VIDEO_MAX_SECONDS + STORY_VIDEO_TOLERANCE_SECONDS
    assert (STORY_VIDEO_MAX_SECONDS, STORY_VIDEO_TOLERANCE_SECONDS) == (60, 0.5)
    assert not story_video_too_long(limit) and story_video_too_long(limit + 0.01)
    assert not any(story_video_too_long(v) for v in (None, 0, -90.0, float("nan")))


@pytest.mark.parametrize(
    ("raw", "seconds"),
    [
        (85, 85.0),
        (14.2, 14.2),
        ("6.5", 6.5),
        (None, None),
        (0, None),
        (-1, None),
        ("abc", None),
        (True, None),
        ([], None),
        ({}, None),
        ("nan", None),
        ("inf", None),
    ],
)
def test_a_stored_length_is_read_defensively(raw: object, seconds: float | None) -> None:
    assert video_seconds_of(raw) == seconds


# -- readers --------------------------------------------------------------------------------


def _asset(media_type: str, position: int, params: object = None) -> SimpleNamespace:
    return SimpleNamespace(media_type=media_type, position=position, params=params)


def test_the_reader_takes_the_first_videos_stored_length() -> None:
    assets = [
        _asset("video", 2, {"duration_seconds": 12}),
        _asset("image", 0, {"duration_seconds": 99}),  # an image's never counts
        _asset("video", 1, {"duration_seconds": 85, "thumbnail_key": "t/x/p.jpg"}),
    ]
    assert first_video_seconds(assets) == 85.0  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "params",
    [
        None,
        {},
        {"duration_seconds": 0},
        {"duration_seconds": "garbage"},
        {"duration_seconds": None},
        {"draft": {"duration_seconds": 85}},
        ["not", "a", "dict"],
    ],
)
def test_without_a_usable_length_the_reader_says_unknown(params: object) -> None:
    assert first_video_seconds([_asset("video", 0, params)]) is None  # type: ignore[list-item]


def test_a_piece_without_video_has_no_length() -> None:
    assert first_video_seconds([_asset("image", 0, {"duration_seconds": 85})]) is None  # type: ignore[list-item]
    assert first_video_seconds([]) is None
