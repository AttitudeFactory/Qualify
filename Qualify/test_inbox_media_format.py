"""QUA-146 phase 3: what the inbox screen says about feed posts and unsupported surfaces.

- `media_format_label`: each candidate row's label — "Reel" for every Reel (whatever
  Meta's `media_type`), the format for a feed post, "Publicación" for a feed format this
  code does not know yet, nothing for a surface the picker never offers.
- `inbox_provider.candidate_media` carries that label into `CandidateMediaVM` and leaves
  every other field of a Reel exactly as before.
- `InboxState.toggle_monitored`'s refusal messages: `unsupported_surface` gets its own,
  `too_old` and every other reason keep theirs.

Needs pytest (constructing `InboxState` requires `is_testing_env()`, see
`test_inbox_state.py`); `toggle_monitored` itself calls `get_state`, so its use of the
mapping is pinned structurally, same technique that file uses.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime
from uuid import UUID

import pytest
from qualify_api.inbox.service import CandidateMedia

from . import inbox_page, inbox_provider, inbox_state
from .inbox_state import InboxState
from .inbox_vm import (
    FEED_POST_LABEL,
    REEL_LABEL,
    SyncSummaryVM,
    candidate_picture_url,
    media_format_label,
)

_TENANT = UUID("a0000000-0000-4000-8000-000000000146")
_CONNECTION = UUID("c0000000-0000-4000-8000-000000000146")


# --- media_format_label -----------------------------------------------------------------


@pytest.mark.parametrize("media_type", ["VIDEO", None, "IMAGE", "FUTURE_FORMAT"])
def test_a_reel_is_always_labelled_reel(media_type: str | None) -> None:
    assert media_format_label("REELS", media_type) == REEL_LABEL == "Reel"


@pytest.mark.parametrize(
    ("media_type", "label"),
    [("IMAGE", "Foto"), ("VIDEO", "Video"), ("CAROUSEL_ALBUM", "Carrusel")],
)
def test_a_feed_post_is_labelled_by_its_format(media_type: str, label: str) -> None:
    assert media_format_label("FEED", media_type) == label


@pytest.mark.parametrize("media_type", ["FUTURE_FORMAT", "video", None])
def test_an_unknown_or_missing_feed_format_still_reads_as_a_feed_post(
    media_type: str | None,
) -> None:
    assert media_format_label("FEED", media_type) == FEED_POST_LABEL == "Publicación"


# STORY has a label since m-24789644 ("Historia", ready for `story_comments`); it is still
# never offered by the picker (`MONITORABLE_MEDIA_PRODUCT_TYPES`).
@pytest.mark.parametrize("surface", ["AD", None, "FUTURE_SURFACE"])
def test_a_surface_the_picker_never_offers_has_no_label(surface: str | None) -> None:
    assert media_format_label(surface, "IMAGE") == ""


# --- candidate_picture_url ---------------------------------------------------------------


def test_a_thumbnail_always_wins() -> None:
    assert candidate_picture_url("VIDEO", "https://t/v.jpg", "https://m/v.mp4") == "https://t/v.jpg"
    assert candidate_picture_url("IMAGE", "https://t/i.jpg", "https://m/i.jpg") == "https://t/i.jpg"


@pytest.mark.parametrize("media_type", ["IMAGE", "CAROUSEL_ALBUM"])
def test_a_photo_or_carousel_without_thumbnail_uses_media_url(media_type: str) -> None:
    assert candidate_picture_url(media_type, None, "https://m/x.jpg") == "https://m/x.jpg"


@pytest.mark.parametrize("media_type", ["VIDEO", "FUTURE_FORMAT", None])
def test_media_url_is_never_used_as_a_picture_unless_it_is_an_image(
    media_type: str | None,
) -> None:
    """A video's `media_url` is the video file; an unknown format's might be too."""
    assert candidate_picture_url(media_type, None, "https://m/x.mp4") == ""


def test_no_picture_at_all_falls_back_to_the_generic_frame() -> None:
    assert candidate_picture_url("IMAGE", None, None) == ""


# --- inbox_provider.candidate_media -----------------------------------------------------


def _candidate(media_id: str, product: str | None, media_type: str | None) -> CandidateMedia:
    return CandidateMedia(
        external_media_id=media_id,
        timestamp=datetime(2026, 10, 8, 10, 0, tzinfo=UTC),
        is_monitored=media_id == "reel",
        caption=f"caption {media_id}",
        permalink=f"https://www.instagram.com/p/{media_id}/",
        thumbnail_url=f"https://cdn/{media_id}.jpg",
        media_product_type=product,
        media_type=media_type,
    )


def test_candidate_media_labels_every_row_and_keeps_a_reel_s_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (
        _candidate("reel", "REELS", "VIDEO"),
        _candidate("photo", "FEED", "IMAGE"),
        _candidate("video", "FEED", "VIDEO"),
        _candidate("carousel", "FEED", "CAROUSEL_ALBUM"),
        _candidate("future", "FEED", "FUTURE_FORMAT"),
    )

    async def _fake(**kwargs: object) -> tuple[CandidateMedia, ...]:
        return rows

    monkeypatch.setattr(inbox_provider, "list_candidate_media", _fake)

    vms = asyncio.run(inbox_provider.candidate_media(tenant_id=_TENANT, connection_id=_CONNECTION))

    labels = {vm.external_media_id: vm.format_label for vm in vms}
    assert labels == {
        "reel": "Reel",
        "photo": "Foto",
        "video": "Video",
        "carousel": "Carrusel",
        "future": "Publicación",
    }
    reel = next(vm for vm in vms if vm.external_media_id == "reel")
    assert reel.is_monitored
    assert reel.caption == "caption reel"
    assert reel.permalink == "https://www.instagram.com/p/reel/"
    assert reel.thumbnail_url == "https://cdn/reel.jpg"
    # m-24842988: Spanish month and 12-hour clock (the offline zone is UTC, conftest).
    assert reel.posted_at == "8 oct, 10:00 a. m."


def test_candidate_media_gives_photos_and_carousels_their_picture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _row(media_id: str, media_type: str, thumb: str | None, url: str | None):
        return CandidateMedia(
            external_media_id=media_id,
            timestamp=datetime(2026, 10, 8, tzinfo=UTC),
            is_monitored=False,
            thumbnail_url=thumb,
            media_product_type="REELS" if media_type == "VIDEO" else "FEED",
            media_type=media_type,
            media_url=url,
        )

    async def _fake(**kwargs: object) -> tuple[CandidateMedia, ...]:
        return (
            _row("reel", "VIDEO", "https://t/reel.jpg", "https://m/reel.mp4"),
            _row("photo", "IMAGE", None, "https://m/photo.jpg"),
            _row("carousel", "CAROUSEL_ALBUM", None, "https://m/carousel.jpg"),
        )

    monkeypatch.setattr(inbox_provider, "list_candidate_media", _fake)

    vms = asyncio.run(inbox_provider.candidate_media(tenant_id=_TENANT, connection_id=_CONNECTION))

    assert {vm.external_media_id: vm.thumbnail_url for vm in vms} == {
        "reel": "https://t/reel.jpg",
        "photo": "https://m/photo.jpg",
        "carousel": "https://m/carousel.jpg",
    }


def test_a_candidate_without_format_data_shows_no_label(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(**kwargs: object) -> tuple[CandidateMedia, ...]:
        return (
            CandidateMedia(
                external_media_id="m",
                timestamp=datetime(2026, 10, 8, tzinfo=UTC),
                is_monitored=False,
            ),
        )

    monkeypatch.setattr(inbox_provider, "list_candidate_media", _fake)

    (vm,) = asyncio.run(
        inbox_provider.candidate_media(tenant_id=_TENANT, connection_id=_CONNECTION)
    )
    assert vm.format_label == ""


# --- refusal messages --------------------------------------------------------------------


def test_unsupported_surface_has_its_own_message() -> None:
    message = inbox_state._NOT_ELIGIBLE_BY_REASON["unsupported_surface"]
    assert message == inbox_state._UNSUPPORTED_SURFACE
    assert "Reels" in message and "publicaciones de tu perfil" in message
    assert "feed" not in message and "monitore" not in message
    assert "historias" in message and "anuncios" in message
    assert message != inbox_state._NOT_ELIGIBLE


def test_too_old_keeps_its_existing_message() -> None:
    assert inbox_state._NOT_ELIGIBLE_BY_REASON["too_old"] == inbox_state._TOO_OLD
    assert inbox_state._TOO_OLD == (
        "Esta publicación tiene más de 2 semanas: ya no buscamos sus comentarios."
    )


def test_any_other_reason_keeps_the_generic_message() -> None:
    assert "not_found_or_inaccessible" not in inbox_state._NOT_ELIGIBLE_BY_REASON
    assert (
        inbox_state._NOT_ELIGIBLE_BY_REASON.get(
            "not_found_or_inaccessible", inbox_state._NOT_ELIGIBLE
        )
        == inbox_state._NOT_ELIGIBLE
    )


def test_toggle_monitored_maps_every_refusal_through_the_reason_table() -> None:
    source = inspect.getsource(InboxState.toggle_monitored.fn)
    assert "_NOT_ELIGIBLE_BY_REASON.get(exc.reason, _NOT_ELIGIBLE)" in source
    assert 'exc.reason == "too_old"' not in source


# --- page copy ----------------------------------------------------------------------------


def test_the_candidate_row_renders_the_format_label() -> None:
    source = inspect.getsource(inbox_page._candidate_card_content)
    assert "candidate.format_label" in source


def test_the_sync_toast_counts_publications_in_plain_words() -> None:
    """m-24842988: the sync toast says «publicaciones» for Reels and posts alike (the
    screen's own word), with no «sincroniz-» and never «1 comentarios»."""
    source = inspect.getsource(InboxState.sync_comments.fn)
    assert "sync_result_message(result)" in source
    one = inbox_state.sync_result_message(
        SyncSummaryVM(media_checked=1, new_comments=1, truncated=False)
    )
    assert one == "Revisamos 1 publicación: 1 comentario nuevo."
    many = inbox_state.sync_result_message(
        SyncSummaryVM(
            media_checked=3,
            new_comments=0,
            truncated=True,
            skipped_missing_media=("a", "b"),
            deleted_comments=2,
        )
    )
    assert many.startswith("Revisamos 3 publicaciones: 0 comentarios nuevos.")
    assert "2 publicaciones ya no están en Instagram" in many
    assert "2 comentarios se borraron en Instagram" in many
    assert "sincroniz" not in many.lower() and "monitore" not in many.lower()


def test_the_sync_strip_lives_inside_the_body_not_between_header_and_body() -> None:
    # m-24842989: the strip moved down, into the connected body `_body()` renders.
    assert "_connected_body()" in inspect.getsource(inbox_page._body)
    assert "_sync_section()" in inspect.getsource(inbox_page._connected_body)
    assert "_sync_section()" not in inspect.getsource(inbox_page.inbox_index)


def test_every_inbox_card_takes_the_full_body_width() -> None:
    for fn in (
        inbox_page._candidate_card_content,
        inbox_page._reel_summary_card,
        inbox_page._sync_section,
    ):
        assert 'width="100%",' in inspect.getsource(fn).split("padding=")[-1]


def test_the_drafts_refresh_control_is_a_labelled_secondary_icon_button() -> None:
    source = inspect.getsource(inbox_page._refresh_drafts_button)
    assert "rx.icon_button(" in source
    assert 'variant="soft"' in source and 'color_scheme="gray"' in source
    assert 'aria_label="Actualizar respuestas"' in source
    assert 'variant="ghost"' not in source


def test_the_picker_copy_no_longer_says_reels_only() -> None:
    source = inspect.getsource(inbox_page)
    assert "tus publicaciones de las últimas 2 semanas" in source
    assert "Sin Reels ni publicaciones en las últimas 2 semanas" in source
    assert '"Reels de las últimas 2 semanas' not in source


def test_the_body_keeps_its_first_block_off_the_header_line() -> None:
    """System-wide (every page uses `page_body`): the body's top padding is no longer 0,
    so the first card never touches the header's bottom hairline."""
    from .ui import tokens as T

    top = T.PAD_BODY.split()[0]
    assert top != "0" and top.endswith("rem")


@pytest.mark.parametrize(
    ("path", "on_inbox"),
    [("/inbox", True), ("/inbox/", True), ("/", False), ("/login/", False), ("", False)],
)
def test_is_inbox_path(path: str, on_inbox: bool) -> None:
    assert inbox_state.is_inbox_path(path) is on_inbox


def test_a_sync_that_ends_after_leaving_the_inbox_shows_no_toast() -> None:
    source = inspect.getsource(InboxState.sync_comments.fn)
    guard = source.index("is_inbox_path(self.router.url.path)")
    assert guard < source.index("rx.toast.success(message")


def test_logout_dismisses_open_toasts_before_redirecting() -> None:
    from .auth_state import AuthState

    source = inspect.getsource(AuthState.logout.fn)
    assert source.index("rx.toast.dismiss()") < source.index("rx.redirect(BRAND_START_ROUTE)")
