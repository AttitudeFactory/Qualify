"""MARCA-6 (m-24842969): «Tus redes» in the owner's words.

- the card says whether the account works in three states, in text;
- «Puedes:» / «Todavía no puedes:» come from the capability verdicts, and «Cómo
  activarlo» points at the guide step that fixes what is missing;
- nothing visible says «Degradada», «Revocada», «Verificada:» or mentions Meta's
  documentation;
- after a successful connection: «Instagram conectado» + «Crear una publicación» (N3),
  and `?volver=` brings the owner back where they came from (N4), internal paths only.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from . import brand_minimal_vm
from .capabilities import CAPABILITY_LABELS, Capability, ScopeKey, assess_capabilities
from .connections_provider import _format_health_checked_at, _format_verified_at
from .connections_state import ConnectionsState
from .connections_vm import (
    CONNECT_RESULT_NOTICES,
    CONNECTED_TITLE,
    OWNER_ABILITIES,
    STATUS_LABELS,
    build_connection_vm,
    continue_after_connect,
    safe_return_path,
)

_HERE = Path(__file__).parent
_SCREEN_FILES = (
    "connection_copy.py",
    "connections_page.py",
    "connections_vm.py",
    "connections_state.py",
)
_BANNED = (
    "Meta",
    "Conectar de nuevo",
    "Degradada",
    "Revocada",
    "Verificada:",
    "Verificar ahora",
    "documentación de Meta",
    "Reconectar",
    "sentiment",
    "listening",
    "stories",
    "tenant",
    "base de datos",
    "Infraestructura",
    "Sin reconocer",
)


def _visible_strings(path: Path) -> list[str]:
    """Every string literal of a module except docstrings — what can reach a screen."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


@pytest.mark.parametrize("name", _SCREEN_FILES)
def test_no_technical_or_fsm_words_reach_the_screen(name: str) -> None:
    for text in _visible_strings(_HERE / name):
        for word in _BANNED:
            assert word not in text, f"{name}: «{word}» in {text!r}"


@pytest.mark.parametrize("name", ("connections_provider.py", "capabilities.py"))
def test_no_raw_meta_permission_labels_reach_the_screen(name: str) -> None:
    for text in _visible_strings(_HERE / name):
        for word in ("Infraestructura", "Sin reconocer", "Acceso a datos"):
            assert word not in text, f"{name}: «{word}» in {text!r}"


def test_the_same_thing_has_one_name_on_the_card() -> None:
    assert CAPABILITY_LABELS[Capability.READ_COMMENTS] == "Ver comentarios"
    assert CAPABILITY_LABELS[Capability.MANAGE_DMS] == "Ver mensajes"
    assert CAPABILITY_LABELS[Capability.READ_INSIGHTS] == "Ver tus resultados"
    assert CAPABILITY_LABELS[Capability.CONNECT_ACCOUNT] == "Tu cuenta está conectada"


def test_the_three_states_are_words_with_a_tone() -> None:
    assert {key: label for key, (label, _t, _i) in STATUS_LABELS.items()} == {
        "active": "Conectada",
        "degraded": "Desconectada",
        "revoked": "Desconectada",
    }
    assert {tone for _l, tone, _i in STATUS_LABELS.values()} == {"ok", "warn"}


def test_every_capability_has_an_owner_word_entry() -> None:
    assert set(OWNER_ABILITIES) == set(Capability)


def _vm(granted: set[ScopeKey], *, status: str = "active", platform: str = "instagram"):
    return build_connection_vm(
        connection_id="c-1",
        platform=platform,
        brand="Bianki",
        external_username="@bianki",
        status=status,
        last_verified_at="21 ago 2026, 16:33",
        granted_scope_labels=[],
        verdicts=assess_capabilities(frozenset(granted), platform=platform),
    )


def test_a_fully_granted_account_lists_what_the_owner_can_do() -> None:
    vm = _vm(set(ScopeKey) - {ScopeKey.MANAGE_INSIGHTS})
    assert vm.can_do.startswith("publicar · ver comentarios")
    assert "ver mensajes" in vm.can_do
    assert "ver tus resultados" in vm.cannot_do
    assert vm.cannot_step_key == "permissions"


def test_only_messages_missing_points_at_the_messages_step() -> None:
    vm = _vm(
        {
            ScopeKey.BASIC,
            ScopeKey.CONTENT_PUBLISH,
            ScopeKey.MANAGE_COMMENTS,
            ScopeKey.MANAGE_INSIGHTS,
        }
    )
    assert vm.cannot_do == "ver mensajes"
    assert vm.cannot_step_key == "messages"
    assert "ver mensajes" not in vm.can_do


def test_a_card_that_needs_reconnecting_shows_no_ability_lines() -> None:
    for status in ("degraded", "revoked"):
        vm = _vm(set(ScopeKey), status=status)
        assert (vm.can_do, vm.cannot_do, vm.cannot_step_key) == ("", "", "")


def test_dates_read_in_spanish_with_plain_fallbacks() -> None:
    when = datetime(2026, 8, 21, 16, 33, tzinfo=UTC)
    assert _format_verified_at(when) == "21 ago 2026, 16:33"
    assert _format_verified_at(None) == "Sin fecha"
    assert _format_health_checked_at(None) == "Todavía no"


# -- N3 / N4: after connecting --------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "kept"),
    [
        ("/create", "/create"),
        ("/publish", "/publish"),
        ("/brand/kit", "/brand/kit"),
        ("https://evil.example", ""),
        ("//evil.example", ""),
        ("/create?x=1", ""),
        ("javascript:alert(1)", ""),
        ("/connections", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_volver_accepts_only_internal_paths(raw: object, kept: str) -> None:
    assert safe_return_path(raw) == kept


def test_the_next_step_after_connecting() -> None:
    assert continue_after_connect("") == ("Crear una publicación", "/create")
    assert continue_after_connect("/create") == ("Crear una publicación", "/create")
    assert continue_after_connect("/publish") == ("Seguir publicando", "/publish")
    assert continue_after_connect("https://evil.example") == ("Crear una publicación", "/create")


def test_volver_survives_the_round_trip_to_meta() -> None:
    state = ConnectionsState()
    # The owner arrives from Crear…
    state.apply_connect_result({"volver": "/create"})
    assert state.return_to == "/create" and state.connected_ok is False
    # …goes to Meta and comes back on the callback URL, which carries only `connect`.
    state.apply_connect_result({"connect": "active"})
    assert state.connected_ok is True
    assert state.return_to == "/create"
    assert state.continue_label == "Crear una publicación"
    assert CONNECT_RESULT_NOTICES["active"][0].startswith(CONNECTED_TITLE)


def test_a_plain_visit_forgets_an_old_origin_and_a_failure_shows_no_success() -> None:
    state = ConnectionsState()
    state.apply_connect_result({"volver": "/publish"})
    state.apply_connect_result({})
    assert state.return_to == ""
    state.apply_connect_result({"connect": "denied"})
    assert state.connected_ok is False


def test_continue_clears_the_panel_and_goes_back() -> None:
    state = ConnectionsState()
    state.apply_connect_result({"volver": "/publish"})
    state.apply_connect_result({"connect": "active"})
    ConnectionsState.continue_after_connect.fn(state)
    assert state.connected_ok is False and state.return_to == ""


def test_details_toggle_is_per_card() -> None:
    state = ConnectionsState()
    ConnectionsState.toggle_details.fn(state, "a")
    ConnectionsState.toggle_details.fn(state, "b")
    ConnectionsState.toggle_details.fn(state, "a")
    assert state.open_detail_ids == ["b"]


def test_the_profile_read_says_it_is_not_the_connection() -> None:
    assert brand_minimal_vm.PUBLIC_READ_NOTE == (
        "Solo miramos lo que ya es público en tu perfil. Para publicar desde Qualify, "
        "conecta tu Instagram después en Tus redes."
    )
