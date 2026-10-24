"""m-24842989 ([ATENDER], épica m-24842956): on Comentarios (/inbox) the replies ready to
approve come first; which publications to review is folded behind «Más opciones».

Pinned structurally (same technique as `test_inbox_media_format.py`): the order of the
connected body, the accordion that hides the switches, the exact Spanish strings of the
ticket, the ≥ 44 px targets at 360 px (N12) and the assisted-only button (N13).
"""

from __future__ import annotations

import inspect
from pathlib import Path

from . import inbox_page, replies_state
from .replies_state import RepliesState
from .replies_vm import generation_message

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
    title = _src(inbox_page._replies_title)
    assert "Respuestas listas para aprobar ({RepliesState.drafts.length()})" in title
    # «(n)» only when there is something to approve.
    assert "RepliesState.has_pending_drafts" in title
    assert '"Comentarios por publicación"' in _src(inbox_page._comments_section)


def test_the_approve_button_says_what_happens_and_is_a_phone_target() -> None:
    for fn in (inbox_page._draft_view_mode, inbox_page._draft_edit_mode):
        source = _src(fn)
        assert "_approve_label(draft)" in source
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
    assert "_draft_comment_block(draft)" in _src(inbox_page._draft_card)
    card = _src(inbox_page._draft_comment_block)
    assert "_draft_publication_thumb(draft)" in card
    assert card.index('"@" + draft.author_username') < card.index("draft.comment_text")
    thumb = _src(inbox_page._draft_publication_thumb)
    assert "media_thumb(draft.media_thumbnail_url" in thumb
    assert "alt=draft.media_alt" in thumb


def test_the_replies_list_still_compiles_with_the_new_fields() -> None:
    assert inbox_page._replies_list() is not None


def test_the_approve_button_names_who_gets_the_answer() -> None:
    source = _src(inbox_page._approve_label)
    assert '"Aprobar y responder a @" + draft.author_username' in source
    assert '"Aprobar y responder",' in source


def test_the_replies_description_says_the_answer_is_public() -> None:
    flat = _src(inbox_page._replies_section).replace('"\n            "', "")
    assert (
        "Cada una sale en Instagram, debajo del comentario y a la vista de todos, solo "
        "cuando tú la apruebas."
    ) in flat


def test_without_drafts_only_the_empty_state_button_shows() -> None:
    source = _src(inbox_page._replies_section)
    gate = source.index("RepliesState.has_pending_drafts")
    assert gate < source.index("_refresh_drafts_button()")
    assert gate < source.index("_generate_drafts_button()")


def test_the_empty_comments_state_offers_the_search() -> None:
    source = _src(inbox_page._reel_summaries_empty_state)
    assert '"Todavía no tienes comentarios"' in source
    assert '"Cuando te comenten, aparecerán aquí agrupados por publicación."' in source
    assert "action=_sync_now_button()" in source


def test_a_reply_card_names_the_publication_by_day_else_by_caption() -> None:
    """m-24842988: «En tu publicación del 21 oct»; without the day, its caption in
    Latin quotes; with neither, nothing (the fallback alt says nothing)."""
    source = _src(inbox_page._draft_comment_block)
    assert '"En tu publicación del " + draft.media_day' in source
    assert '"En tu publicación «" + draft.media_alt + "»"' in source
    assert '(draft.media_day == "") & (draft.media_alt != PUBLICATION_ALT_FALLBACK)' in source
    assert 'text_overflow="ellipsis"' in source
    assert '"En: "' not in source


def test_the_reply_editor_is_labelled() -> None:
    assert 'aria_label="Tu respuesta"' in _src(inbox_page._draft_edit_mode)


def test_the_sent_message_names_the_person_when_known() -> None:
    assert replies_state.sent_message("ana") == "Listo, le respondiste a @ana en Instagram."
    assert replies_state.sent_message("") == "Listo, tu respuesta ya está en Instagram."


def test_only_a_sent_reply_gets_the_success_toast() -> None:
    """A refusal or transport failure at Meta does not raise — the service returns the
    draft as `send_failed`/`send_ambiguous`. The «Listo» toast must sit behind
    `status == "sent"`, never after the bare `await send_draft(...)`."""
    source = _src(RepliesState._decide_and_send)
    after = source[source.index("await send_draft(") :]
    assert after.index('if sent.status != "sent":') < after.index("sent_message(author)")
    assert "self._report_failure(sent)" in after
    report = _src(RepliesState._report_failure)
    assert "_SEND_REFUSED" in report and "_SEND_FAILED" in report


def test_the_reply_messages_are_plain_and_truthful() -> None:
    assert replies_state._GENERATE_FAILED == (
        "No pudimos preparar las respuestas. Intenta de nuevo en unos minutos."
    )
    # Founder's decision 2026-10-23: short failure texts.
    assert replies_state._SEND_REFUSED == "Tu respuesta no salió. Respóndela en Instagram."
    assert replies_state._SEND_FAILED == "No sabemos si salió. Revísalo en Instagram."
    # A decided draft leaves the queue before the Meta call: never promise it «sigue aquí».
    for message in (replies_state._SEND_FAILED, replies_state._SEND_REFUSED):
        assert "Sigue aquí" not in message and "Meta" not in message and "borrador" not in message
    # The generation toast says only what waits for the owner (counts go to the log).
    source = _src(RepliesState.generate_drafts.fn)
    assert "generation_message(summary.drafts_created)" in source and "la puerta" not in source
    for created in (0, 1, 3):
        assert "borrador" not in generation_message(created).lower()
    assert '"Respuesta descartada."' in _src(RepliesState.discard_draft.fn)
