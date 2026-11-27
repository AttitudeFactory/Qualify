"""m-25142793: on a phone the page header collapses to one pinned line.

Offline: `page_header` renders one DOM in reading order (top → bar → subtitle) with the
title, the actions and the toggle in the bar; the stylesheet pins only the bar at
≤ 640 px (the sheet gives up its box), keeps one blurred surface, clears the notch and
keeps the toggle a 44 px target; `glass-nav.js` measures the bar when the sheet has no
box; the JS that aligns content under the header reads the same pinned element.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import reflex as rx

from Qualify.test_route_history import _node
from Qualify.test_sticky_header_offsets import _HARNESS, _SCRIPT
from Qualify.ui import tokens as T
from Qualify.ui.layout import page_header

_ASSETS = Path(__file__).parent.parent / "assets"
_CSS = (_ASSETS / "qualify.css").read_text(encoding="utf-8")


def _classes(node: dict[str, Any]) -> str:
    for prop in node.get("props", []):
        match = re.match(r'className:"([^"]*)"', prop)
        if match:
            return match.group(1)
    return ""


def _find(node: dict[str, Any], cls: str) -> dict[str, Any] | None:
    if cls in _classes(node).split():
        return node
    for child in node.get("children", []):
        found = _find(child, cls)
        if found is not None:
            return found
    return None


def _phone_block() -> str:
    out = []
    for match in re.finditer(r"@media \(max-width: 640px\)\s*\{", _CSS):
        depth, i = 1, match.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(_CSS[i], 0)
            i += 1
        out.append(_CSS[match.end() : i])
    return "\n".join(out)


def _rule(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match is not None, selector
    return match.group(1)


def _header(**kwargs: Any) -> dict[str, Any]:
    return page_header(
        "Tu semana",
        "Tus publicaciones de la semana.",
        rx.button("Nueva publicación"),
        **kwargs,
    ).render()


def test_one_dom_in_reading_order_with_the_toggle_on_the_title_line() -> None:
    head = _header(badge=rx.badge("3"), kicker=rx.text("Paso 1"))
    assert _classes(head).split() == ["q-page-header", "q-page-head"]
    order = [_classes(child).split()[-1] for child in head["children"]]
    assert order == ["q-page-head-top", "q-page-head-bar", "q-page-head-sub"]
    bar = _find(head, "q-page-head-bar")
    assert bar is not None
    rendered_bar = str(bar)
    # title (+ badge), the actions, then the toggle — all in the pinned line
    assert rendered_bar.index('"h1"') < rendered_bar.index("q-page-head-actions")
    assert rendered_bar.index("q-page-head-actions") < rendered_bar.index("q-theme-toggle")
    assert "Nueva publicaci" in rendered_bar
    # the chip and the kicker scroll away: they live outside the bar
    top = str(_find(head, "q-page-head-top"))
    assert "q-business-chip" in top and "q-page-head-kicker" in top
    assert "q-business-chip" not in rendered_bar
    # still exactly one h1
    assert str(head).count('"h1"') == 1


def test_no_actions_box_and_no_subtitle_when_none_are_given() -> None:
    head = page_header("Por responder").render()
    assert _find(head, "q-page-head-actions") is None
    assert _find(head, "q-page-head-sub") is None
    assert _find(head, "q-theme-toggle") is not None


def test_phone_pins_only_the_bar_as_the_one_glass_surface() -> None:
    phone = _phone_block()
    sheet = _rule(phone, ".q-page-head")
    assert "display: contents" in sheet and "position: static" in sheet
    bar = _rule(phone, "  .q-page-head-bar")
    assert "position: sticky" in bar and "top: 0" in bar
    assert "backdrop-filter: blur(18px)" in bar
    assert "env(safe-area-inset-top" in bar
    # the toggle is out of the flow in the top-right corner, never wrapped
    toggle = _rule(phone, ".q-page-head-toggle")
    assert "position: absolute" in toggle and "right: var(--q-page-x)" in toggle
    assert "env(safe-area-inset-top" in toggle
    target = _rule(phone, ".q-page-head-toggle .rt-IconButton.q-theme-toggle")
    assert "width: 44px" in target and "height: 44px" in target
    # the title ends in «…» before it pushes anything
    title = _rule(phone, ".q-page-head-title h1")
    assert "text-overflow: ellipsis" in title and "white-space: nowrap" in title
    # one blurred surface for the header: nothing else in the phone rules blurs
    blurred = [
        sel.strip()
        for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", phone)
        if "q-page-head" in sel and "backdrop-filter" in body
    ]
    assert blurred == [".q-page-head-bar"]


def test_wide_screens_keep_the_sheet_and_place_the_pieces_in_a_grid() -> None:
    sheet = _rule(_CSS, "\n.q-page-head")
    assert "display: grid" in sheet
    assert '". end" "top end" "title end" "sub end" ". end"' in sheet
    # the old row's padding (T.PAD_HEADER) is the sheet's padding
    assert "padding: 1.5rem var(--q-page-x) 1rem" in sheet
    assert T.PAD_HEADER == "1.5rem var(--q-page-x) 1rem var(--q-page-x)"


def test_sticky_height_measures_the_bar_when_the_sheet_has_no_box() -> None:
    result = _node(
        _HARNESS
        + r"""
const bar = header(panel, 60.2);
pageHead.getClientRects = () => [];
pageHead.querySelector = (sel) => sel === '.q-page-head-bar' ? bar : null;
"""
        + _SCRIPT
        + r"""
flush();const phone=panel.values['--q-sticky-header-height'];
bar.height=104;resizeCallback();flush();
console.log(JSON.stringify({phone, wrapped: panel.values['--q-sticky-header-height'],
 watched: watched.has(bar) && watched.has(pageHead)}));
"""
    )
    assert result == {"phone": "61px", "wrapped": "104px", "watched": True}


def test_scripts_align_under_the_pinned_part_of_the_header() -> None:
    script = T.pinned_header_js("panel")
    assert "panel?.querySelector('.q-page-header')" in script
    assert "getClientRects().length" in script and ".q-page-head-bar" in script
    result = _node(
        "const bar={id:'bar'};"
        "const phone={getClientRects:()=>[],querySelector:()=>bar};"
        "const wide={id:'wide',getClientRects:()=>[{}],querySelector:()=>bar};"
        "const pick=(h)=>{const panel={querySelector:()=>h};return " + script + ";};"
        "console.log(JSON.stringify([pick(phone).id, pick(wide).id, pick(null)]));"
    )
    assert result == ["bar", "wide", None]
