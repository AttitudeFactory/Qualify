"""m-24842983 (PUBLICAR-5, UX epic m-24842956, docs/ux-auditoria-2026-10/m4 H3, H4, H8):
Tu semana and Publicar ahora speak the owner's words.

Every string literal of the module's screens that a person can read is scanned for the
team's words — POST, Caption, Story/Stories, Cold, Hot, Likes, Ads, vendor, preview,
tenant, R2 — and, in `planner_vm.py`, Feed and evergreen too. Docstrings, log lines, CSS
class names, the client-side script and identifiers are not client text and are skipped.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_HERE = Path(__file__).parent

_FILES = (
    "planner_drawer.py",
    "planner_page.py",
    "planner_provider.py",
    "planner_state.py",
    "planner_vm.py",
    "publishing_page.py",
    "publishing_provider.py",
    "publishing_state.py",
    "publishing_vm.py",
    "stories_page.py",
    "stories_provider.py",
    "stories_state.py",
    "stories_vm.py",
    "trending_panel.py",
)

_BANNED = re.compile(
    r"POST|[Cc]aption|\b[Ss]tor(y|ies)\b|\bCold\b|\bHot\b|\bLikes\b|\bAds\b|\bvendor\b"
    r"|\b[Pp]review\b|\b[Tt]enant\b|\bR2\b"
)
#: The follow-up of wave 1: the planner's view model never says Feed nor evergreen either.
_BANNED_VM = re.compile(r"\b[Ff]eed\b|\bevergreen\b")

#: CSS class lists («q-story-bar q-story-bar--on») and the Web Share script of
#: `stories_page` (its comments are JavaScript, never rendered).
_NOT_CLIENT_TEXT = re.compile(r"^q-[\w-]+( q-[\w-]+)*$|^\s*\(function \(\)")

#: Keys, ports and routes («story», «preview_url», «/publish?flow=stories»): one lowercase
#: token or a path, never a sentence.
_IDENTIFIER = re.compile(r"^(/\S*|[a-z_][a-z0-9_-]*)$")


def _client_strings(name: str) -> list[tuple[int, str]]:
    tree = ast.parse((_HERE / name).read_text(encoding="utf-8"))
    skip: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            if isinstance(body[0].value, ast.Constant):
                skip.add(id(body[0].value))  # docstring
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"debug", "info", "warning", "error", "exception"}:
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "logger":
                    skip.update(id(n) for n in ast.walk(node))  # logger.*(…)
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skip
        and not _NOT_CLIENT_TEXT.search(node.value)
        and not _IDENTIFIER.match(node.value)
    ]


@pytest.mark.parametrize("name", _FILES)
def test_no_team_words_reach_the_owner(name: str) -> None:
    offending = [
        f"{name}:{line}: {text!r}"
        for line, text in _client_strings(name)
        if _BANNED.search(text) or (name == "planner_vm.py" and _BANNED_VM.search(text))
    ]
    assert not offending, "\n".join(offending)


def test_cold_and_hot_read_ya_probada_and_por_probar() -> None:
    from .planner_vm import temperature

    assert temperature(0) == ("hot", "Por probar", "Por probar: todavía no ha salido en tus redes.")
    assert temperature(1)[1] == "Por probar"
    key, label, hint = temperature(3)
    assert (key, label) == ("cold", "Ya probada")
    assert hint == "Ya probada: salió 3 veces y funcionó. Puedes repetirla."


def test_the_goals_use_the_owner_words() -> None:
    from .planner_vm import PLAN_GOALS

    labels = {g.key: g.label for g in PLAN_GOALS}
    assert labels["likes"] == "Me gusta"
    assert labels["ads"] == "Para anunciar pagando"
    assert {g.key: g.hint for g in PLAN_GOALS}["views"] == "Que la vea más gente"


def test_the_reel_is_named_as_decision_11_says_where_the_format_is_chosen() -> None:
    from .planner_vm import DESTINATION_LABELS, frame_shape, output_long_label

    assert DESTINATION_LABELS == {
        "post": "Publicación",
        "reel": "Reel (video corto)",
        "story": "Historia",
    }
    assert output_long_label("reel") == "Reel (video corto) 9:16"
    assert output_long_label("feed") == "Publicación 4:5"
    assert frame_shape("galeria", "feed") == ("Publicación (vertical)", "4 / 5")


def test_the_scheduled_confirmation_says_day_and_hour() -> None:
    from .planner_vm import scheduled_message

    assert scheduled_message(created=1, day_iso="2026-10-29", at="19:00", reschedule=False) == (
        "Publicación programada para el jueves 29 de octubre a las 7:00 p. m."
    )
    assert scheduled_message(created=1, day_iso="2026-10-29", at="13:30", reschedule=True) == (
        "Publicación reprogramada para el jueves 29 de octubre a la 1:30 p. m."
    )
    assert scheduled_message(created=3, day_iso="2026-10-29", at="09:00", reschedule=False) == (
        "3 publicaciones programadas. La primera sale el jueves 29 de octubre a las 9:00 a. m."
    )
    assert scheduled_message(created=1, day_iso="", at="09:00", reschedule=False) == (
        "Publicación programada"
    )


def test_publishing_errors_say_what_to_do_next() -> None:
    from . import publishing_state, stories_state

    for module in (publishing_state, stories_state):
        assert module._NO_TENANT == (
            "No encontramos tu negocio en esta sesión. Cierra sesión y vuelve a entrar."
        )
        assert module._NOT_CONFIGURED == (
            "No podemos subir archivos en este momento. Inténtalo en unos minutos; si sigue, "
            "escríbenos."
        )
        assert module._POLL_FAILED == (
            "No sabemos todavía si se publicó. Revisa tu Instagram en unos minutos antes de "
            "volver a intentarlo, para no publicarlo dos veces."
        )
        assert module._UNSUPPORTED_IMAGE_FORMAT == (
            "Esta foto no se puede usar tal cual. Desde tu celular, compártela como “JPG” o "
            "haz una captura de pantalla y súbela."
        )


def test_unsupported_files_and_waits_speak_of_instagram_not_meta() -> None:
    from . import publishing_state, stories_state

    assert publishing_state._UNSUPPORTED_FORMAT == (
        "Ese archivo no se puede publicar en Instagram. Sube una foto o un video tal como salen "
        "de la cámara de tu celular."
    )
    assert stories_state._UNSUPPORTED_FORMAT == (
        "Ese archivo no se puede publicar como historia. Sube una foto o un video tal como salen "
        "de la cámara de tu celular."
    )
    assert stories_state._WAIT_EXPLANATION == (
        "Instagram está preparando tu historia. Puede tardar unos minutos."
    )
    for name in (
        "publishing_page.py",
        "publishing_state.py",
        "stories_page.py",
        "stories_state.py",
    ):
        for _, text in _client_strings(name):
            assert "Meta" not in text, f"{name}: {text!r}"


def test_planner_says_publicacion_not_pieza_or_salida() -> None:
    for name in ("planner_drawer.py", "planner_state.py"):
        for _, text in _client_strings(name):
            assert not re.search(r"\bpiezas?\b|\bSalidas?\b|\bsalidas\b", text), f"{name}: {text!r}"


def test_join_es_reads_as_a_sentence() -> None:
    from .planner_vm import join_es

    assert join_es([]) == ""
    assert join_es(["me gusta"]) == "me gusta"
    assert join_es(["me gusta", "vistas"]) == "me gusta y vistas"
    assert join_es(["a", "b", "c"]) == "a, b y c"
