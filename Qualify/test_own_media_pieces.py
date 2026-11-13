"""m-25019217 (m-25019224): what the owner published from «Publicar» as a piece — it shows
in «Aprobados» (never «Por aprobar»), «Tipo» separates it from what Qualify generated,
nothing that makes, remakes or edits a piece is offered on it, and a published event of
«Tu semana» offers «Ver en Instagram» only with the publication's address.

Pure view models and the state's guards — no database, no Reflex runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .creative_vm import OWN_MEDIA_KIND, MediaVM, build_draft_vm
from .gallery_state import GalleryState, approved_posts, pending_posts
from .planner_vm import (
    GALLERY_FILTER_ALL,
    GENERATED_KINDS,
    GENERATED_OPTION,
    OWN_MEDIA_OPTION,
    VIEW_ON_INSTAGRAM,
    CardInput,
    build_card,
    build_post_option,
    filter_posts,
    instagram_link,
)

_PERMALINK = "https://www.instagram.com/p/C0dIg0/"


def _option(post_id: str, kind: str, *, approval: str = "approved", times: int = 0):
    return build_post_option(
        post_id=post_id,
        title=f"Pieza {post_id}",
        caption_excerpt="Hoy 2x1",
        thumbnail_url=f"t/00000000-0000-4000-8000-000000000001/media/c/{post_id}",
        category="galeria",
        approval=approval,
        detail_href=f"/drafts/{post_id}",
        is_publishable=True,
        unpublishable_reason="",
        gallery_state="schedulable" if approval == "approved" else "needs_action",
        lifecycle_status="approved" if approval == "approved" else "generated",
        times_published=times,
        content_kind=kind,
        media_types=("image",),
    )


def _posts():
    return [
        _option("own", OWN_MEDIA_KIND, times=1),
        _option("flyer", "static_flyer"),
        _option("carousel", "carousel"),
        _option("waiting", "static_flyer", approval="pending"),
    ]


# -- «Aprobados», never «Por aprobar» ------------------------------------------------------


def test_an_own_media_piece_is_approved_and_never_waits_for_approval() -> None:
    posts = _posts()
    assert [p.post_id for p in approved_posts(posts)].count("own") == 1
    assert "own" not in [p.post_id for p in pending_posts(posts)]
    assert [p.post_id for p in pending_posts(posts)] == ["waiting"]
    own = next(p for p in posts if p.post_id == "own")
    assert own.content_kind_label == "Subida por ti"
    assert own.schedulable  # it can be planned again from Tu semana
    assert own.used_count == 1  # it already went out once
    assert own.history_help == "Salió 1 vez en tus redes: todavía no sabemos si funciona."


def test_even_an_odd_state_never_puts_an_upload_in_por_aprobar() -> None:
    odd = _option("own", OWN_MEDIA_KIND, approval="pending")
    assert pending_posts([odd]) == []


# -- «Tipo» ---------------------------------------------------------------------------------


def test_tipo_offers_uploads_and_generated_first_then_each_kind() -> None:
    state = GalleryState()
    state.posts = _posts()
    options = [(o.value, o.label) for o in state.approved_kind_options]
    assert options[:2] == [(OWN_MEDIA_KIND, OWN_MEDIA_OPTION), (GENERATED_KINDS, GENERATED_OPTION)]
    assert (OWN_MEDIA_KIND, "Subida por ti") not in options  # the group already says it
    assert {value for value, _ in options[2:]} == {"static_flyer", "carousel"}


def test_tipo_separates_uploads_from_generated_pieces() -> None:
    approved = approved_posts(_posts())
    own = filter_posts(approved, state="all", category="all", content_kind=OWN_MEDIA_KIND)
    made = filter_posts(approved, state="all", category="all", content_kind=GENERATED_KINDS)
    every = filter_posts(approved, state="all", category="all", content_kind=GALLERY_FILTER_ALL)
    assert [p.post_id for p in own] == ["own"]
    assert {p.post_id for p in made} == {"flyer", "carousel"}
    assert len(every) == 3


def test_tipo_without_uploads_is_as_before_and_with_only_uploads_has_one_choice() -> None:
    state = GalleryState()
    state.posts = [_option("flyer", "static_flyer")]
    assert [o.value for o in state.approved_kind_options] == ["static_flyer"]
    state.posts = [_option("own", OWN_MEDIA_KIND, times=1)]
    assert [(o.value, o.label) for o in state.approved_kind_options] == [
        (OWN_MEDIA_KIND, OWN_MEDIA_OPTION)
    ]


def test_tipo_starts_on_every_type_and_accepts_the_generated_group() -> None:
    state = GalleryState()
    state.posts = _posts()
    assert state.approved_kind_filter == GALLERY_FILTER_ALL
    state.set_approved_kind_filter(GENERATED_KINDS)
    assert state.approved_kind_filter == GENERATED_KINDS
    assert {p.post_id for p in state.approved_visible} == {"flyer", "carousel"}
    state.set_approved_kind_filter(OWN_MEDIA_KIND)
    assert [p.post_id for p in state.approved_visible] == ["own"]
    state.set_approved_kind_filter("no-such-kind")
    assert state.approved_kind_filter == GALLERY_FILTER_ALL


# -- nothing that generates or edits on its own page -----------------------------------------


def _detail(kind: str, status: str = "approved"):
    return build_draft_vm(
        draft_id="d1",
        status=status,
        failure_reason=None,
        variants=(),
        image_url=None,
        total_cost_usd=None,
        voice_profile_version=None,
        model_ids=(),
        requires_ai_disclosure=False,
        created_label="",
        kind=kind,
        media=(MediaVM(key="t/x/media/c/1", media_type="video", position=0, label="Video"),),
    )


def test_an_own_media_piece_offers_no_generation_nor_edit() -> None:
    own = _detail(OWN_MEDIA_KIND)
    assert own.is_own_media
    assert own.kind_label == "Subida por ti"
    assert not own.can_edit  # editing would send it back to «Por aprobar»
    assert not own.can_regenerate and not own.can_reject and not own.can_approve
    assert not own.can_finish_gallery
    assert not own.requires_ai_disclosure
    generated = _detail("static_flyer")
    assert generated.can_edit and not generated.is_own_media


def test_start_edit_refuses_an_own_media_piece() -> None:
    from .creative_state import CreativeState  # noqa: PLC0415

    state = CreativeState()
    state.draft = _detail(OWN_MEDIA_KIND)
    assert state.start_edit() is None
    assert not state.edit_mode


# -- «Ver en Instagram» ------------------------------------------------------------------------


def _card(status: str, permalink: str = ""):
    return build_card(
        CardInput(
            event_id="e1",
            post_id="own",
            scheduled_at=datetime(2026, 11, 13, 15, 0, tzinfo=UTC),
            status=status,
            overdue=False,
            connection_id="c1",
            post_title="Hoy 2x1",
            approval="approved",
            permalink=permalink,
        ),
        zone=ZoneInfo("UTC"),
        connections={"c1": ("instagram", "@bianki")},
    )


def test_a_published_card_links_to_instagram_only_with_its_address() -> None:
    assert VIEW_ON_INSTAGRAM == "Ver en Instagram"
    assert _card("published", _PERMALINK).permalink == _PERMALINK
    assert _card("published").permalink == ""  # no address recorded yet
    assert _card("scheduled", _PERMALINK).permalink == ""  # not out yet


def test_only_an_https_instagram_address_is_ever_offered() -> None:
    assert instagram_link("published", _PERMALINK) == _PERMALINK
    assert instagram_link("published", "https://instagram.com/reel/x/") != ""
    assert instagram_link("published", "javascript:alert(1)") == ""
    assert instagram_link("published", "http://www.instagram.com/p/x/") == ""
    assert instagram_link("published", "https://evil.example/p/x/") == ""
    assert instagram_link("published", None) == ""
    assert instagram_link("failed", _PERMALINK) == ""


def test_a_failed_permalink_read_costs_only_the_links(monkeypatch) -> None:  # noqa: ANN001
    """`_permalinks` (the RLS-scoped read behind the week and the panel) never fails the
    week: a database error yields no links; nothing is read without an attempt."""
    from uuid import uuid4  # noqa: PLC0415

    from . import planner_provider as provider  # noqa: PLC0415

    def boom(_tenant):  # noqa: ANN001, ANN202
        raise RuntimeError("db down")

    monkeypatch.setattr(provider, "tenant_session", boom)
    assert provider._permalinks(uuid4(), [uuid4()]) == {}
    assert provider._permalinks(uuid4(), [None]) == {}
