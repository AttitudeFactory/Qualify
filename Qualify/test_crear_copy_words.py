"""m-24842979 (UX epic m-24842956, docs/ux-auditoria-2026-10/m3-crear-piezas.md B1-B3):
Crear publicación / Por aprobar / Revisar publicación speak the owner's words.

Every string literal of the module's screens that a person can read is scanned for the
team's words — POST, caption, CTA, Flyer, story, UGC, HITL, Bandeja, Copy, Brand Kit,
vendor names, server variables, «base de datos». Docstrings, log lines and the few
machine strings listed below are not client text and are skipped.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_HERE = Path(__file__).parent

_FILES = (
    "content_generator.py",
    "creative_pages.py",
    "creative_state.py",
    "creative_vm.py",
    "gallery_state.py",
    "variations_view.py",
    "voice_lab.py",
    "download_buttons.py",
)

_BANNED = re.compile(
    r"POST|[Cc]aption|\bCTA\b|Flyer|\b[Ss]tor(y|ies)\b|UGC|HITL|Bandeja|\bCopy\b|Brand Kit"
    r"|Claude|QUALIFY_|base de datos|\b[Pp]osts?\b|\b[Pp]iezas?\b"
)

#: Machine strings: env var names, the English fidelity messages the view-model parses,
#: and log formats.
_NOT_CLIENT_TEXT = re.compile(
    r"^QUALIFY_[A-Z_]+$|^caption is |^caption hashtags|^rejected from HITL"
)

#: Keys, ports and routes («story», «caption_length», «/planner?post=»): one lowercase
#: token or a path, never a sentence.
_IDENTIFIER = re.compile(r"^(/\S*|[a-z_][a-z0-9_]*)$")

#: `creative_pages` keeps the pre-wizard Brand Kit accordion and the gated /create form
#: unrouted (see `create_index`); nobody reads them, so they are not scanned.
_UNROUTED = frozenset(
    {
        "readiness_panel",
        "_kit_accordion",
        "brand_index",
        "_voice_profile_card",
        "_voice_empty_state",
        "_voice_section",
        "_route_option",
        "_create_form",
        "_create_blocked",
    }
)


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
                skip.update(id(n) for n in ast.walk(node))  # logger.*(…)
        if isinstance(node, ast.FunctionDef) and node.name in _UNROUTED:
            skip.update(id(n) for n in ast.walk(node))
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
    offending = [f"{name}:{line}: {text!r}" for line, text in _client_strings(name)]
    offending = [o for o in offending if _BANNED.search(o.split(": ", 1)[1])]
    assert not offending, "\n".join(offending)


def test_the_format_options_say_reel_video_corto_and_historia() -> None:
    """Founder decision 11: «Reel (video corto)», «Historia», never «story»."""
    from .creative_state import _FORMAT_LABELS

    assert _FORMAT_LABELS == {
        "feed_4_5": "Publicación 4:5",
        "feed_1_1": "Publicación cuadrada 1:1",
        "reels_9_16": "Reel (video corto) 9:16",
        "story_9_16": "Historia 9:16",
    }


def test_the_review_progress_names_texto_imagen_revision() -> None:
    from .creative_state import GENERATION_STAGES

    assert GENERATION_STAGES == ("Texto", "Imagen", "Revisión")


def test_the_brand_warning_on_create_goes_to_the_kit() -> None:
    from .content_generator import BRAND_KIT_ROUTE, _brand_flag

    rendered = str(_brand_flag())
    assert BRAND_KIT_ROUTE == "/brand/kit" and "/brand/kit" in rendered
    assert "Completar mi marca" in rendered
