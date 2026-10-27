from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from .reconnect_vm import reconnect_notice, reconnect_origin
from .responder_vm import legacy_target


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (
            "active",
            "Listo: @negocio está conectada otra vez. "
            "Estamos trayendo lo que llegó mientras tanto.",
        ),
        (
            "permission_missing",
            "@negocio se conectó, pero falta una casilla para ver tus comentarios. "
            "Vuelve a conectarla y déjalas todas marcadas.",
        ),
        (
            "denied",
            "No se conectó: saliste antes de terminar en Facebook. "
            "Puedes intentarlo cuando quieras.",
        ),
        (
            "account_access_required",
            "Esa cuenta de Facebook no administra @negocio. "
            "Entra con la que la administra o pide ayuda.",
        ),
    ],
)
def test_reconnect_outcomes_use_product_copy(code: str, expected: str) -> None:
    assert reconnect_notice(code, "@negocio").message == expected


def test_unknown_outcome_cannot_echo_query_text() -> None:
    assert reconnect_notice("arbitrary user input", "@negocio").message == ""


@pytest.mark.parametrize(
    ("tab", "origin"), [("comentarios", "/inbox"), ("mensajes", "/conversations")]
)
def test_canonical_responder_tabs_keep_correct_logical_reconnect_origin(
    tab: str, origin: str
) -> None:
    assert reconnect_origin("/responder", {"tab": tab}) == origin


def test_legacy_callback_preserves_result_and_target_in_actual_responder_tab() -> None:
    target = legacy_target("/inbox", {"connect": "permission_missing", "reconnect": "c-1"})
    parsed = urlsplit(target)
    assert parsed.path == "/responder"
    assert parse_qs(parsed.query) == {
        "tab": ["comentarios"],
        "connect": ["permission_missing"],
        "reconnect": ["c-1"],
    }
