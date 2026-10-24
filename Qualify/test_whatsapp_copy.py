"""m-24842994: WhatsApp speaks the owner's words — no opt-in, leads, Marketing, Lanzar,
encola, Revocar, WhatsApp Manager, Sincronizar con Meta, Mediana or p90 on screen; the
chat badges say who answers and until when; the QR next step names no counter."""

from __future__ import annotations

import ast
import inspect
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from . import whatsapp_metrics_block, whatsapp_page, whatsapp_tab_campaigns
from .whatsapp_campaigns_vm import (
    AUDIENCE_NONE,
    audience_count_label,
    launch_message,
    send_error_note,
)
from .whatsapp_chats_state import _QUEUED
from .whatsapp_chats_vm import deadline_label, mode_pill, window_pill
from .whatsapp_contacts_vm import source_label
from .whatsapp_menu_vm import NEXT_STEP_QR
from .whatsapp_metrics_vm import _PRICING_CATEGORY
from .whatsapp_templates_vm import CATEGORIES

_SCREEN_FILES = sorted(Path(__file__).parent.glob("whatsapp_*.py"))

_FORBIDDEN = re.compile(
    r"opt-in|\bleads?\b|Marketing|Lanzar|encola|Revocar|WhatsApp Manager|"
    r"Sincronizar con Meta|Mediana|p90"
)
_IDENTIFIER = re.compile(r"[a-z0-9_\-]+|[A-Z0-9_]+")
_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}


def _visible_strings(path: Path) -> list[str]:
    """String literals a person could read: docstrings, log lines and identifiers out."""
    tree = ast.parse(path.read_text())
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
        and not _IDENTIFIER.fullmatch(node.value.strip())
    ]


@pytest.mark.parametrize("path", _SCREEN_FILES, ids=lambda p: p.stem)
def test_no_tool_words_on_the_whatsapp_screens(path: Path) -> None:
    offending = [s for s in _visible_strings(path) if _FORBIDDEN.search(s)]
    assert offending == []


def test_chat_badges_say_who_answers_and_until_when() -> None:
    assert mode_pill(False) == ("Responde el menú", "neutral")
    assert mode_pill(True) == ("Respondes tú", "info")
    now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    label, tone = window_pill(True, datetime(2026, 10, 14, 17, 0, tzinfo=UTC), now, UTC)
    assert (label, tone) == ("Puedes escribirle hasta las 5:00 p. m.", "ok")
    assert deadline_label(datetime(2026, 10, 14, 13, 30)) == "Puedes escribirle hasta la 1:30 p. m."


def test_follow_up_strings_are_exact() -> None:
    assert _QUEUED == "Tu mensaje sale en unos segundos."
    assert send_error_note("131047").startswith("Pasaron más de 24 horas desde su último mensaje")
    assert NEXT_STEP_QR == "Haz que te escriban: crea tu código QR para tu local o tus redes"
    for word in ("en cola", "ventana", "mostrador"):
        assert word not in NEXT_STEP_QR.lower()


def test_categories_and_sources_use_the_owners_names() -> None:
    labels = {key: label for key, label, _hint in CATEGORIES}
    assert labels["marketing"] == "Promociones"
    assert labels["utility"] == "Avisos de pedidos"
    assert _PRICING_CATEGORY["MARKETING"] == "Promociones"
    assert _PRICING_CATEGORY["UTILITY"] == "Avisos de pedidos"
    assert source_label("lead_form") == "Formulario de clientes interesados"


def test_audience_and_launch_copy() -> None:
    assert audience_count_label(0) == AUDIENCE_NONE
    assert audience_count_label(1) == "1 contacto que aceptó recibir tus mensajes"
    assert audience_count_label(3) == "3 contactos que aceptaron recibir tus mensajes"
    message = launch_message(enqueued=3, skipped=1, audience=4)
    assert "en cola" not in message and "lanzada" not in message


def test_screens_use_the_proposed_labels() -> None:
    campaigns = inspect.getsource(whatsapp_tab_campaigns)
    assert '"Enviar ahora"' in campaigns
    assert "Nada se envía hasta que toques «Enviar ahora»." in campaigns
    assert "rate_card_status" not in campaigns
    metrics = inspect.getsource(whatsapp_metrics_block)
    assert '"Cuánto tardas en responder (la mitad de las veces)"' in metrics
    assert (
        "Atiende y vende por WhatsApp: tus chats, tu menú automático y tus promociones."
        in inspect.getsource(whatsapp_page)
    )
