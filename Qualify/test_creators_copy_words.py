"""Creadores speaks the owner's words (m-24946129, m-24946132; docs/ux-creadores.md §5,
`qualify-copy-es`, the banned list of `qualify-ux` §3).

Every string literal of the module's screens that a person can read is scanned for the
team's and the vendor's words: credits and money of a read, the vendor, «API»,
«engagement», «viral», «influencer», «mediana», «views»/«followers»/«reach» as words,
«post», «caption», «N/A». Docstrings, log lines, keys and routes are skipped. The owner
never sees credits (ADR 42 §2.9) nor a vendor.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_HERE = Path(__file__).parent

_FILES = (
    "creators_access.py",
    "creators_page.py",
    "creators_provider.py",
    "creators_state.py",
    "creators_vm.py",
    "creator_sheet_page.py",
    "creators_compare_page.py",
)

_BANNED = re.compile(
    r"cr[eé]dito|ScrapeCreators|scrap|\bAPI\b|engagement|\bviral|influencer|outlier"
    r"|\bmediana\b|\bviews\b|\bfollowers\b|\breach\b|\bposts?\b|\bcaption|\bN/A\b|\bnull\b"
    r"|\bUSD\b|\bcache\b|\bcaché\b|\bsincroniz",
    re.IGNORECASE,
)

#: Keys, routes and CSS («median_views», «/creadores/comparar», «q-nums»): one token or a
#: path, never a sentence.
_IDENTIFIER = re.compile(r"^(/\S*|[a-z_][a-z0-9_.-]*|[a-z-]+ [a-z-]+)$")


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
                    skip.update(id(n) for n in ast.walk(node))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skip
        and not _IDENTIFIER.match(node.value)
    ]


@pytest.mark.parametrize("name", _FILES)
def test_no_team_or_vendor_words_reach_the_owner(name: str) -> None:
    offending = [
        f"{name}:{line}: {text!r}" for line, text in _client_strings(name) if _BANNED.search(text)
    ]
    assert not offending, "\n".join(offending)


def test_mejor_is_a_word_next_to_the_figure_never_colour_alone() -> None:
    """P1: the best of a row is the bold figure AND the «Mejor» badge (a word)."""
    source = (_HERE / "creators_compare_page.py").read_text(encoding="utf-8")
    assert "tone_badge(BEST" in source
    assert 'weight=rx.cond(best, "bold"' in source


def test_no_tooltip_is_the_only_explanation() -> None:
    """A phone has no hover: the explanations are visible hints and tap popovers."""
    for name in ("creators_page.py", "creator_sheet_page.py", "creators_compare_page.py"):
        assert "rx.tooltip" not in (_HERE / name).read_text(encoding="utf-8")
