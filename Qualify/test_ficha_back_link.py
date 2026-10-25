"""m-24854881 (N7, N8): «Revisar publicación» always has a way back — also when the
publication does not load. Offline: the compiled component tree of the ficha.

The ficha's states are client-side ternaries (`rx.cond`), so «shown in the error state»
means: the way back is not nested inside any branch of the ficha's own conditions
(loading, the loaded draft, the error), only inside the one that picks its two forms.
"""

from __future__ import annotations

import re

import pytest

from .creative_pages import draft_detail_index
from .planner_back import ficha_back_link
from .planner_vm import BACK_TO_DRAFTS, BACK_TO_WEEK

_WEEK_BACK_VAR = "week_back_state.href_rx_state_"


def _paren_map(js: str) -> dict[int, int]:
    stack: list[int] = []
    pairs: dict[int, int] = {}
    for i, ch in enumerate(js):
        if ch == "(":
            stack.append(i)
        elif ch == ")" and stack:
            j = stack.pop()
            pairs[j] = i
            pairs[i] = j
    assert not stack, "the compiled page has unbalanced parentheses"
    return pairs


def _enclosing_conditions(js: str, pos: int) -> list[str]:
    """The condition of every `(cond)?(a):(b)` branch that contains ``pos``."""
    pairs = _paren_map(js)
    found: list[str] = []
    for start, end in pairs.items():
        if js[start] != "(" or not (start < pos < end) or start < 2:
            continue
        if js[start - 1] not in "?:" or js[start - 2] != ")":
            continue
        cond_end = start - 2
        if js[start - 1] == ":":
            true_start = pairs[cond_end]
            if js[true_start - 1] != "?" or js[true_start - 2] != ")":
                continue
            cond_end = true_start - 2
        found.append(js[pairs[cond_end] : cond_end + 1])
    return found


def _back_link_positions(js: str, label: str) -> list[int]:
    """Where the ficha's way back (a 44 px button with ``label``) is drawn."""
    return [m.start() for m in re.finditer(r'"minHeight"\] : "44px".{0,200}?"' + label, js)]


@pytest.mark.parametrize("label", [BACK_TO_DRAFTS, BACK_TO_WEEK])
def test_the_way_back_is_outside_every_state_of_the_ficha(label: str) -> None:
    page = str(draft_detail_index())
    positions = _back_link_positions(page, label)
    assert positions, f"«‹ {label}» is not on the ficha"
    for pos in positions:
        conditions = _enclosing_conditions(page, pos)
        # Only the choice between «Tu semana» and «Por aprobar» — never the draft,
        # the loading or the error: so it shows when the publication does not load.
        assert conditions and all(_WEEK_BACK_VAR in c for c in conditions), conditions


def test_both_forms_say_where_they_go_and_are_thumb_sized() -> None:
    link = str(ficha_back_link())
    assert 'to:"/drafts"' in link
    assert f"to:reflex___state____state__qualify___planner_back____{_WEEK_BACK_VAR}" in link
    assert link.count('"minHeight"] : "44px"') == 2
    assert link.count("LucideChevronLeft") == 2
    assert f'"{BACK_TO_DRAFTS}"' in link and f'"{BACK_TO_WEEK}"' in link


def test_the_error_message_is_still_on_the_ficha() -> None:
    page = str(draft_detail_index())
    assert "creative_state.detail_error_rx_state_" in page


def test_the_fallback_names_the_list() -> None:
    assert BACK_TO_DRAFTS == "Por aprobar"
