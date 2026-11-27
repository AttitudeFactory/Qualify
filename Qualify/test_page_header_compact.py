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
from Qualify.ui.layout import SUBTITLE_ID, page_header

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


def test_the_bar_is_the_old_row_and_the_phone_copies_sit_outside_it() -> None:
    head = _header(badge=rx.badge("3"), kicker=rx.text("Paso 1"))
    assert _classes(head).split() == ["q-page-header", "q-page-head"]
    order = [_classes(child).split()[0] for child in head["children"]]
    assert order == ["q-page-head-top", "q-page-head-bar", "q-page-head-sub"]
    bar = _find(head, "q-page-head-bar")
    assert bar is not None
    # the old row, item for item: title column, spacer, actions, toggle
    items = [_classes(child).split()[0] for child in bar["children"]]
    assert items == [
        "q-page-head-main",
        "q-page-head-spacer",
        "q-page-head-actions",
        "q-page-head-toggle",
    ]
    main = _find(bar, "q-page-head-main")
    assert main is not None
    column = [_classes(child).split() for child in main["children"]]
    assert column[0] == ["q-page-head-kicker", "q-page-head-wide"]
    assert "q-page-head-title" in column[1]
    assert column[2] == ["q-page-head-desc", "q-page-head-wide"]
    # the chip and the kicker's phone copy live outside the bar (they scroll away)
    top = str(_find(head, "q-page-head-top"))
    assert "q-business-chip" in top and "q-page-head-kicker" in top
    assert "q-business-chip" not in str(bar)
    # still exactly one h1, described by the subtitle
    rendered = str(head)
    assert rendered.count('"h1"') == 1
    assert "aria-describedby" in str(_find(head, "q-page-head-title"))
    assert SUBTITLE_ID in str(_find(head, "q-page-head-title"))
    assert SUBTITLE_ID in str(_find(head, "q-page-head-desc"))
    # the phone's subtitle copy is not read a second time
    assert "aria-hidden" in str(_find(head, "q-page-head-sub"))


def test_no_actions_box_no_subtitle_and_no_description_when_none_are_given() -> None:
    head = page_header("Por responder").render()
    assert _find(head, "q-page-head-actions") is None
    assert _find(head, "q-page-head-sub") is None
    assert _find(head, "q-page-head-desc") is None
    assert "aria-describedby" not in str(head)
    assert _find(head, "q-theme-toggle") is not None


def test_a_var_subtitle_still_describes_the_title() -> None:
    head = page_header("Tus redes", rx.Var.create("Conecta tus cuentas")).render()
    rendered = str(head)
    assert "aria-describedby" in rendered and SUBTITLE_ID in rendered


def test_phone_pins_only_the_bar_as_the_one_glass_surface() -> None:
    phone = _phone_block()
    sheet = _rule(phone, ".q-page-head")
    assert "display: contents" in sheet and "position: static" in sheet
    bar = _rule(phone, "  .q-page-head-bar")
    assert "position: sticky" in bar and "top: 0" in bar
    assert "backdrop-filter: blur(18px)" in bar
    assert "env(safe-area-inset-top" in bar
    # the pinned line keeps the header's hairline over the content
    assert "box-shadow: inset 0 -1px 0 var(--q-card-edge)" in bar
    # the toggle is out of the flow in the top-right corner, never wrapped
    toggle = _rule(phone, ".q-page-head-toggle")
    assert "position: absolute" in toggle and "right: var(--q-page-x)" in toggle
    target = _rule(phone, ".q-page-head-toggle .rt-IconButton.q-theme-toggle")
    assert "width: 44px" in target and "height: 44px" in target
    # the title wraps, it is never cut
    title = _rule(phone, ".q-page-head-title h1")
    assert "ellipsis" not in title and "nowrap" not in title
    # a selector takes its whole row
    assert "width: 100%" in _rule(phone, ".q-page-head-actions > .rt-SelectTrigger")
    # the wide copies are not drawn on a phone
    assert "display: none" in _rule(phone, ".q-page-head-spacer")
    # one blurred surface for the header: nothing else in the phone rules blurs
    blurred = [
        sel.strip()
        for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", phone)
        if "q-page-head" in sel and "backdrop-filter" in body
    ]
    assert blurred == [".q-page-head-bar"]


def test_wide_screens_keep_the_old_wrapping_row() -> None:
    sheet = _rule(_CSS, "\n.q-page-head")
    # the old row's padding (T.PAD_HEADER) is the sheet's padding
    assert "padding: 1.5rem var(--q-page-x) 1rem" in sheet
    assert T.PAD_HEADER == "1.5rem var(--q-page-x) 1rem var(--q-page-x)"
    bar = _rule(_CSS, "\n.q-page-head-bar")
    assert "flex-wrap: wrap" in bar and "gap: var(--space-3)" in bar
    # actions and toggle are items of the row itself, as before (they wrap one by one)
    assert "display: contents" in _rule(_CSS, ".q-page-head-toggle")
    assert "display: none" in _rule(_CSS, ".q-page-head-sub")


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
