"""m-24842989 ([ATENDER], épica m-24842956): on Comentarios (/inbox) the replies ready to
approve come first; which publications to review is folded behind «Más opciones».

Pinned structurally (same technique as `test_inbox_media_format.py`): the order of the
connected body, the accordion that hides the switches, the exact Spanish strings of the
ticket, the ≥ 44 px targets at 360 px (N12) and the assisted-only button (N13).
"""

from __future__ import annotations

import inspect
from pathlib import Path

from . import inbox_page

_CSS = Path(__file__).resolve().parent.parent / "assets" / "qualify-inbox.css"


def _src(fn: object) -> str:
    return inspect.getsource(fn)  # type: ignore[arg-type]


def test_the_replies_ready_to_approve_come_first() -> None:
    body = _src(inbox_page._connected_body)
    replies = body.index("_replies_section()")
    comments = body.index("_comments_section()")
    sync = body.index("_sync_section()")
    more = body.index("_more_options()")
    assert replies < comments < sync < more


def test_the_review_switches_only_live_behind_more_options() -> None:
    more = _src(inbox_page._more_options)
    assert "rx.accordion.root(" in more
    assert 'header="Más opciones: qué publicaciones revisar"' in more
    assert "_review_choice_section()" in more
    # Closed on arrival: no default open item.
    assert "default_value" not in more
    assert "_candidates_body()" in _src(inbox_page._review_choice_section)
    assert '"Qué publicaciones revisar"' in _src(inbox_page._review_choice_section)
    # Nowhere else renders the switches' list.
    assert "_candidates_body()" not in _src(inbox_page._body)
    assert "_candidates_body()" not in _src(inbox_page._connected_body)


def test_the_header_and_section_strings_are_the_tickets() -> None:
    header = _src(inbox_page.inbox_topbar)
    assert '"Comentarios"' in header
    subtitle = (
        "Lo que te comentaron en tus publicaciones de las últimas 2 semanas, con la "
        "respuesta lista para que la apruebes."
    )
    flat = header.replace('"\n        "', "")
    assert subtitle in flat
    assert "monitorear" not in header
    assert "Respuestas listas para aprobar ({RepliesState.drafts.length()})" in _src(
        inbox_page._replies_title
    )
    assert '"Comentarios por publicación"' in _src(inbox_page._comments_section)


def test_the_approve_button_says_what_happens_and_is_a_phone_target() -> None:
    for fn in (inbox_page._draft_view_mode, inbox_page._draft_edit_mode):
        source = _src(fn)
        assert '"Aprobar y responder"' in source
        assert '"Aceptar y enviar"' not in source and '"Guardar y enviar"' not in source
        assert 'size="1"' not in source
        assert 'size="3"' in source
        assert 'wrap="wrap"' in source


def test_a_reply_card_shows_no_internal_id() -> None:
    assert "source_id" not in _src(inbox_page._draft_card).split('"""', 2)[-1]


def test_the_empty_replies_state_has_a_way_out() -> None:
    assert "action=_generate_drafts_button()" in _src(inbox_page._replies_empty_state)


def test_pickers_and_search_are_fluid_with_a_cap() -> None:
    for fn in (
        inbox_page._connection_selector,
        inbox_page._sentiment_filter_select,
        inbox_page._intent_filter_select,
        inbox_page._comment_search_input,
    ):
        source = _src(fn)
        assert 'width="100%"' in source and "max_width=" in source
        assert 'class_name="q-inbox-tap"' in source


def test_the_unsure_intent_is_explained_in_visible_text() -> None:
    source = _src(inbox_page._intent_chip)
    assert "rx.tooltip(" not in source
    assert '" · revísalo"' in source
    assert "no fiable" not in source


def test_phone_targets_reach_44px() -> None:
    css = _CSS.read_text(encoding="utf-8")
    block = css[css.index("m-24842989") :]
    assert ".q-inbox-main :is(.rt-Button, .rt-IconButton)" in block
    assert ".q-inbox-tap" in block and "min-height: 44px" in block
    assert 'class_name="q-inbox-main"' in _src(inbox_page._connected_body)


def test_a_reply_card_shows_who_commented_and_the_publication() -> None:
    """Criterion 2 (m-24842989): the author line sits above the comment, next to a small
    thumbnail of the publication whose alt names it."""
    card = _src(inbox_page._draft_card)
    assert "_draft_publication_thumb(draft)" in card
    assert card.index('"@" + draft.author_username') < card.index("draft.comment_text")
    thumb = _src(inbox_page._draft_publication_thumb)
    assert "media_thumb(draft.media_thumbnail_url" in thumb
    assert "alt=draft.media_alt" in thumb


def test_the_replies_list_still_compiles_with_the_new_fields() -> None:
    assert inbox_page._replies_list() is not None
