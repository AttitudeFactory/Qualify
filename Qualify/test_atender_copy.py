"""m-24842988: Comentarios, Conversaciones (incl. «Consultas desde comentarios») and
Clientes interesados speak the owner's words — no tool words, no internal ids or codes,
and the reply confirmations say who got the answer."""

from __future__ import annotations

import ast
import inspect
import re
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from qualify_api.replies.repository import DraftRecord

from . import (
    conversations_page,
    conversations_state,
    conversations_vm,
    followups_page,
    followups_state,
    followups_vm,
    inbox_page,
    inbox_state,
    inbox_vm,
    leads_page,
    leads_state,
    replies_provider,
    replies_state,
)
from .conversations_vm import UNKNOWN_PERSON, reply_sent_message
from .followups_state import queued_message
from .inbox_state import InboxState
from .inbox_vm import UNSURE_INTENT_NOTE, CandidateMediaVM, short_day_label

_SCREENS: tuple[ModuleType, ...] = (
    inbox_page,
    inbox_state,
    inbox_vm,
    replies_provider,
    replies_state,
    conversations_page,
    conversations_state,
    conversations_vm,
    followups_page,
    followups_state,
    followups_vm,
    leads_page,
    leads_state,
)

# The ticket's list: what a shop owner would have to ask about.
_FORBIDDEN = re.compile(
    r"monitore|\bDM\b|caption|sincroniz|\bsentimiento|intenci[oó]n|borradores asistidos|"
    r"funnel|\bleads?\b|en cola|no fiable",
    re.IGNORECASE,
)
_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}


def _visible_strings(module: ModuleType) -> list[str]:
    """Every string literal a person could read: docstrings, log lines and plain
    identifiers (no space) left out."""
    tree = ast.parse(Path(inspect.getfile(module)).read_text())
    skip: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            if isinstance(body[0].value, ast.Constant):
                skip.add(id(body[0].value))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _LOG_METHODS
        ):
            skip.update(id(n) for n in ast.walk(node))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skip
        and " " in node.value.strip()
    ]


@pytest.mark.parametrize("module", _SCREENS, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_no_tool_words_on_screen(module: ModuleType) -> None:
    offending = [s for s in _visible_strings(module) if _FORBIDDEN.search(s)]
    assert offending == []


def test_no_internal_id_is_rendered_on_the_comment_screens() -> None:
    source = inspect.getsource(inbox_page)
    assert "mono(" not in source
    assert "external_thread_id" not in inspect.getsource(inbox_page._comment_card)
    assert "score_display" not in inspect.getsource(inbox_page._comment_card)
    assert "mono(" not in inspect.getsource(conversations_page)


def test_the_monitoring_labels_are_the_owners_words() -> None:
    source = inspect.getsource(inbox_page._reel_monitoring_badge)
    for label in (
        '"Buscando comentarios"',
        '"Ya no buscamos comentarios"',
        '"No buscamos comentarios"',
    ):
        assert label in source


def test_one_prioritize_button_chains_both_passes() -> None:
    source = inspect.getsource(inbox_page._prioritize_button)
    assert '"Ordenar por prioridad"' in source
    assert "on_click=[InboxState.analyze_sentiment, InboxState.analyze_intent]" in source
    assert not hasattr(inbox_page, "_analyze_now_button")
    assert not hasattr(inbox_page, "_analyze_intent_button")


def test_prioritizing_is_busy_while_either_pass_runs() -> None:
    state = InboxState()
    state.selected_connection_id = "c"
    assert state.can_prioritize and not state.is_prioritizing
    state.is_analyzing_intent = True
    assert state.is_prioritizing and not state.can_prioritize


def test_the_filters_and_summary_use_the_new_words() -> None:
    assert ("PENDING", "Sin revisar") in inbox_page._SENTIMENT_FILTER_OPTIONS
    assert [label for _, label in inbox_page._INTENT_FILTER_OPTIONS] == [
        "Todos",
        "Quieren comprar",
    ]
    assert '"Resumen de tus comentarios"' in inspect.getsource(inbox_page._global_summary_widget)


def test_the_unsure_note_is_said_once_per_card() -> None:
    assert UNSURE_INTENT_NOTE == "No estamos seguros: lee el comentario antes de responder."
    assert "rx.text(UNSURE_INTENT_NOTE" not in inspect.getsource(inbox_page._intent_chip)
    assert "comment.intent_unsure" in inspect.getsource(inbox_page._comment_intent)
    assert "rx.text(UNSURE_INTENT_NOTE" not in inspect.getsource(followups_page._intent_chip)
    assert "c.intent_unsure" in inspect.getsource(followups_page._origin)


# --- dates ----------------------------------------------------------------------------


def test_moment_label_is_spanish_and_in_the_business_zone() -> None:
    moment = datetime(2026, 10, 23, 19, 5, tzinfo=UTC)
    assert replies_provider.moment_label(moment, ZoneInfo("America/Bogota")) == (
        "23 oct, 2:05 p. m."
    )
    assert short_day_label(datetime(2026, 1, 4, tzinfo=UTC)) == "4 ene"


def _draft(**overrides: object) -> DraftRecord:
    fields: dict[str, object] = {
        "id": UUID(int=1),
        "tenant_id": UUID(int=2),
        "connection_id": UUID(int=3),
        "message_id": UUID(int=4),
        "source_id": "17900000000000001",
        "sentiment_result_id": UUID(int=5),
        "sentiment_label": "POS",
        "gate_reason": "pos",
        "generator_version": "v1",
        "generated_text": "¡Gracias!",
        "final_text": None,
        "status": "proposed",
        "comment_text": "Qué rico",
        "created_at": datetime(2026, 10, 23, 19, 5, tzinfo=UTC),
        "decided_at": None,
        "decided_by_user_id": None,
        "sent_at": None,
        "external_reply_id": None,
        "send_error_code": None,
        "settled_at": None,
        "author_username": "ana",
        "external_media_id": "m1",
    }
    fields.update(overrides)
    return DraftRecord(**fields)  # type: ignore[arg-type]


def test_a_reply_card_dates_in_the_business_zone_and_names_the_publication_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(replies_provider, "_list_pending_drafts", lambda **_: (_draft(),))
    monkeypatch.setattr(replies_provider, "_tenant_zone", lambda _t: ZoneInfo("America/Caracas"))
    candidate = CandidateMediaVM(
        external_media_id="m1",
        posted_at="",
        is_monitored=True,
        caption="Shawarma",
        permalink="",
        thumbnail_url="",
        posted_day="21 oct",
    )
    (vm,) = replies_provider.pending_drafts(
        tenant_id=UUID(int=2), connection_id=UUID(int=3), candidates=[candidate]
    )
    assert vm.created_at == "23 oct, 3:05 p. m."
    assert vm.media_day == "21 oct"


def test_the_zone_never_breaks_the_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        def timezone(self, _tenant_id: UUID) -> str:
            raise RuntimeError("db down")

    monkeypatch.setattr(replies_provider, "conversations_gateway", lambda: Broken())
    assert replies_provider._tenant_zone(UUID(int=2)) == ZoneInfo("UTC")  # noqa: SLF001


# --- confirmations name who got it ---------------------------------------------------


def test_the_chat_reply_toast_names_the_person() -> None:
    assert reply_sent_message("@ana") == "Listo, le respondiste a @ana. Sale en unos segundos."
    assert reply_sent_message("María") == "Listo, le respondiste a María. Sale en unos segundos."
    assert reply_sent_message(UNKNOWN_PERSON) == "Listo, respondiste. Sale en unos segundos."
    assert reply_sent_message("") == "Listo, respondiste. Sale en unos segundos."
    source = inspect.getsource(conversations_state.ConversationsState.send_reply.fn)
    assert "reply_sent_message(who)" in source


def test_the_private_message_toast_names_the_person() -> None:
    assert queued_message("@ana") == (
        "Listo, le escribiste a @ana en privado. Sale en unos segundos."
    )
    assert queued_message("Cliente") == "Listo, le escribiste en privado. Sale en unos segundos."


def test_no_model_key_tells_the_owner_to_write_it() -> None:
    assert followups_state._DRAFT_UNAVAILABLE == (  # noqa: SLF001
        "Ahora no podemos sugerirte un mensaje. Escríbelo tú y apruébalo."
    )
    assert conversations_state._SUGGEST_UNAVAILABLE == (  # noqa: SLF001
        "Ahora no podemos sugerirte una respuesta. Escríbela tú."
    )


def test_followup_trigger_labels() -> None:
    labels = set(followups_vm.TRIGGER_LABELS.values())
    assert labels == {"Quiere comprar", "La abriste tú desde Comentarios"}


def test_leads_screen_copy() -> None:
    source = inspect.getsource(leads_page)
    assert '"Clientes interesados"' in source
    assert (
        '"Personas que dejaron sus datos para que las contactes, con su permiso guardado."'
        in source
    )
    assert '"Lo que te contaron"' in source
    assert "Datos extra" not in source
