"""Generated media lives in R2 only (§ request 2026-10-06: "quítalo del local"), so every
screen that shows it goes through `/r2media`: the generator's result, the draft's media
(and its video poster) and the calendar's thumbnails."""

from __future__ import annotations

from uuid import UUID

import pytest

from . import creative_provider, planner_provider
from .creative_vm import MediaVM

_TENANT_ID = UUID("a0000000-0000-4000-8000-000000000001")
_R2_IMAGE = f"t/{_TENANT_ID}/generated/d/r1/slide-1.jpg"
_R2_VIDEO = f"t/{_TENANT_ID}/generated/d/r1/video.mp4"
_R2_POSTER = f"t/{_TENANT_ID}/generated/d/r1/thumbnail.jpg"


def test_a_drafts_r2_media_and_its_poster_get_viewable_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        creative_provider,
        "issue_view_path",
        lambda tenant_id, key, media_type, *_a, **_k: f"/r2media/{media_type}:{key[-9:]}",
    )
    video = MediaVM(_R2_VIDEO, "video", 0, "Video", poster_key=_R2_POSTER)
    legacy = MediaVM("generated/t/d/slide-1.jpg", "image", 1, "Imagen")
    out = creative_provider._with_r2_urls(_TENANT_ID, (video, legacy))
    assert out[0].url == "/r2media/video:video.mp4"
    assert out[0].poster_url == "/r2media/image:bnail.jpg"
    # a piece generated before 2026-10-06, still on disk, keeps its local key
    assert (out[1].url, out[1].poster_url) == ("", "")


def test_the_generators_result_is_shown_and_downloaded_from_r2() -> None:
    # § 2026-10-08: one preview for every kind's media (video, image, template output)
    from .content_generator import _media_preview

    rendered = str(_media_preview(_media_var()))
    assert "?download=1" in rendered and '["url"]' in rendered
    assert '["poster_url"]' in rendered


def _media_var():  # noqa: ANN202 — a Var shaped like one `gen_draft.media` item
    from .creative_state import CreativeState

    return CreativeState.gen_draft.media[0]


def test_a_calendar_thumbnail_in_r2_becomes_a_viewable_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        planner_provider, "issue_view_path", lambda tenant_id, key, media_type: "/r2media/tok"
    )
    assert planner_provider._thumbnail_url(_TENANT_ID, _R2_IMAGE) == "/r2media/tok"
    # an http URL or a local key passes as it is; nothing stays nothing
    assert planner_provider._thumbnail_url(_TENANT_ID, "https://x/y.jpg") == "https://x/y.jpg"
    assert planner_provider._thumbnail_url(_TENANT_ID, "generated/t/d/a.jpg") == (
        "generated/t/d/a.jpg"
    )
    assert planner_provider._thumbnail_url(_TENANT_ID, None) is None

    def broken(*_a: object) -> str:
        raise RuntimeError("redis down")

    monkeypatch.setattr(planner_provider, "issue_view_path", broken)
    assert planner_provider._thumbnail_url(_TENANT_ID, _R2_IMAGE) is None  # placeholder


def test_the_calendar_loads_an_r2media_path_from_the_backend() -> None:
    from .post_card import thumbnail

    rendered = str(thumbnail(_var("/r2media/tok"), "2rem"))
    assert "/r2media" in rendered


@pytest.mark.parametrize(
    "url",
    ["/r2media/tok", f"generated/{_TENANT_ID}/d/a.jpg", "https://x/y.jpg"],
)
def test_the_gallery_fill_and_the_thumbnail_resolve_a_url_the_same_way(url: str) -> None:
    """PR #100 review: `media_fill` (the Creativo gallery and the Planificador cards)
    used to send a backend `/r2media/<token>` path through `rx.get_upload_url`, a URL
    under `/_upload/` that 404s, while `thumbnail` already served it from the backend.
    Both now render exactly the `viewable_src` expression for the same URL."""
    from .post_card import media_fill, thumbnail, viewable_src

    expected = str(viewable_src(_var(url)))
    assert expected in str(media_fill(_var(url), _var(""), _var("static_flyer")))
    assert expected in str(thumbnail(_var(url), "2rem"))


def test_viewable_src_serves_r2media_from_the_backend_and_the_rest_as_before() -> None:
    import reflex as rx

    from .post_card import viewable_src
    from .r2_media import BACKEND_BASE

    # the `/r2media` branch is BACKEND_BASE + path — the backend, not the upload store
    r2 = _var("/r2media/tok")
    assert str(BACKEND_BASE + r2) in str(viewable_src(r2))
    # a plain http URL is used as it is; a store key still goes through Reflex's own
    # upload URL — compared with what Reflex renders, not with a copy of its JavaScript
    assert '"https://x/y.jpg"' in str(viewable_src(_var("https://x/y.jpg")))
    key = _var("uploads/t/a.jpg")
    assert str(rx.get_upload_url(key)) in str(viewable_src(key))


def _var(value: str):  # noqa: ANN202
    import reflex as rx

    return rx.Var.create(value)
