"""The calendar card's thumbnail source (`draft_post_reader.thumbnail_source`) — pure.

Whatever it returns ends up in an `<img>`: an http(s) URL or a local upload-store key.
It must never hand over something a browser cannot show as an image — an object-store
(R2) key, a video file, an expired provider URL — or the card renders a broken image.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from qualify_api.planner.draft_post_reader import thumbnail_source

NOW = datetime(2026, 9, 27, 21, 0, tzinfo=UTC)
R2_VIDEO = "t/a0000000-0000-4000-8000-000000000001/media/conn/95821e3a"


def _asset(
    media_type: str = "image",
    media_url: str = "https://cdn.example/img.jpg",
    *,
    object_key: str | None = None,
    expires_in: timedelta | None = None,
    params: dict | None = None,
    position: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        media_type=media_type,
        media_url=media_url,
        object_key=object_key,
        media_expires_at=NOW + expires_in if expires_in is not None else None,
        params=params,
        position=position,
    )


def test_an_http_image_is_shown_as_is() -> None:
    assert thumbnail_source(preview_key=None, assets=[_asset()], now=NOW) == (
        "https://cdn.example/img.jpg"
    )


def test_the_posts_preview_key_comes_first() -> None:
    local = "generated/t/d/slide-1.png"
    assets = [_asset(media_url=local, object_key=local)]
    assert thumbnail_source(preview_key="generated/t/d/cover.png", assets=assets, now=NOW) == (
        "generated/t/d/cover.png"
    )


def test_a_local_generated_image_key_is_returned_for_the_ui_to_resolve() -> None:
    local = "generated/t/d/slide-1.png"
    assets = [_asset(media_url=local, object_key=local)]
    assert thumbnail_source(preview_key=local, assets=assets, now=NOW) == local


def test_a_video_shows_its_poster_never_the_video_file() -> None:
    video = "generated/t/d/video.mp4"
    assets = [
        _asset(
            "video",
            video,
            object_key=video,
            params={"thumbnail_key": "generated/t/d/thumbnail.jpg"},
        )
    ]
    # preview_key falls back to the video file itself when HeyGen gave no poster (0027's
    # `preview_of`): that file is skipped, the poster is used.
    assert thumbnail_source(preview_key=video, assets=assets, now=NOW) == (
        "generated/t/d/thumbnail.jpg"
    )


def test_a_video_without_a_poster_gets_the_placeholder() -> None:
    video = "generated/t/d/video.mp4"
    assets = [_asset("video", video, object_key=video)]
    assert thumbnail_source(preview_key=video, assets=assets, now=NOW) is None


def test_an_r2_video_is_never_a_thumbnail_but_an_r2_image_is() -> None:
    """The QUA-111 E2E POSTs: an MP4 in R2, no poster — an `<img>` cannot show a video.
    An R2 IMAGE is a thumbnail since 2026-10-06: generated pieces live in R2 only, and the
    app serves it through `/r2media` (`planner_provider._thumbnail_url`)."""
    assets = [_asset("video", R2_VIDEO, object_key=R2_VIDEO)]
    assert thumbnail_source(preview_key=None, assets=assets, now=NOW) is None
    image_in_r2 = "t/a0000000-0000-4000-8000-000000000001/generated/d/r1/slide-1.jpg"
    assert thumbnail_source(preview_key=image_in_r2, assets=[], now=NOW) == image_in_r2


def test_an_expired_provider_url_is_not_shown() -> None:
    expired = _asset(expires_in=timedelta(hours=-1))
    assert thumbnail_source(preview_key=None, assets=[expired], now=NOW) is None
    # …also when the POST's preview_key points at that same expired URL (0027 backfill).
    assert thumbnail_source(preview_key=expired.media_url, assets=[expired], now=NOW) is None


def test_the_first_item_is_the_first_by_position() -> None:
    assets = [
        _asset(media_url="https://cdn.example/second.jpg", position=1),
        _asset(media_url="https://cdn.example/first.jpg", position=0),
    ]
    assert thumbnail_source(preview_key=None, assets=assets, now=NOW) == (
        "https://cdn.example/first.jpg"
    )


def test_no_media_and_no_preview_is_the_placeholder() -> None:
    assert thumbnail_source(preview_key=None, assets=[], now=NOW) is None
