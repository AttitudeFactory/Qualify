"""m-24842966: the signup, the login and the brand wizard speak the owner's words.

Every string literal of these screens that is not a docstring, a log line or a bare
identifier (a state key such as ``"brandboard"`` or ``"detractor"``) is copy someone
may read, so none of them may carry the words the UX audit flagged
(`docs/ux-auditoria-2026-10/m1-acceso-marca-conexiones.md`, findings 4 and 11).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

HERE = Path(__file__).parent
SCREENS = (
    "auth_pages.py",
    "auth_state.py",
    "creative_wizard_pages.py",
    "brand_finish.py",
    "brand_documents.py",
    "brand_avatar_panel.py",
    "brand_kit_editor.py",
    # moved to the backend with no copy change (m-24852195); its strings still reach the owner
    "../packages/api/src/qualify_api/creative/logo_palette.py",
)
FORBIDDEN = re.compile(
    r"brand ?kit|brandboard|insights?|claims?\b|detractor|\bemail\b|claude|anthropic"
    r"|configurar|\bbrief\b|hashtag",
    re.IGNORECASE,
)
#: A bare identifier, path or key — never shown as a sentence.
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_./:-]*")
_LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})


def _copy_strings(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            skip.add(id(node.value))  # docstrings
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _LOG_METHODS
        ):
            skip.update(id(arg) for arg in ast.walk(node))  # log lines
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skip
        and not _IDENTIFIER.fullmatch(node.value)
    ]


def _path(name: str) -> Path:
    return (HERE / name).resolve()


@pytest.mark.parametrize("name", SCREENS)
def test_no_flagged_word_reaches_the_owner(name: str) -> None:
    found = [
        f"{name}:{line}: {text!r}"
        for line, text in _copy_strings(_path(name).read_text())
        if FORBIDDEN.search(text)
    ]
    assert found == []
