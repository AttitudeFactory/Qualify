"""m-24842964 (NAV-7, docs/design-system.md §4.4): the phone's bottom bar.

Offline: the bar is the sidebar's own four entries + «Más» (same icon and route, N1;
«Crear» the one short form), its counts come from `NAV_COUNTERS`, it is rendered by
the shell only with the rail, after <main>, and the CSS keeps it to ≤ 640 px with
44 px targets and no hover-only rule (N12).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from Qualify.ui import layout

_CSS = (Path(__file__).parent.parent / "assets" / "qualify.css").read_text(encoding="utf-8")


def _has(rendered: str, text: str) -> bool:
    """Whether ``text`` is in a rendered tree, plain or with its accents escaped."""
    escaped = json.dumps(text)[1:-1]
    return any(form in rendered for form in (text, escaped, escaped.replace("\\", "\\\\")))


def _sidebar_entry(label: str) -> layout.Item:
    return next(item for item in layout.NAV_ITEMS if item[0] == label)


def test_four_accesses_then_more() -> None:
    assert [label for label, *_ in layout.NAV_BOTTOM] == [
        "Inicio",
        "Por responder",
        "Crear",
        "Tu semana",
    ]
    rendered = str(layout._bottom_bar().render())
    for label, *_ in [*layout.NAV_BOTTOM, (layout.MORE_LABEL,)]:
        assert _has(rendered, label)
    # Four links and one button — five cells, nothing more.
    assert rendered.count("q-bottom-cell") == 5


def test_same_icon_and_route_as_the_sidebar() -> None:
    for label, source, icon, route in layout.NAV_BOTTOM:
        _label, side_icon, side_route, enabled = _sidebar_entry(source)
        assert (icon, route) == (side_icon, side_route)
        assert enabled
        # Only one short form is allowed on the bar.
        assert label == layout.BOTTOM_BAR_SHORT_FORM.get(source, source)
    assert layout.BOTTOM_BAR_SHORT_FORM == {"Crear publicación": "Crear"}


def test_counts_come_from_the_menu() -> None:
    for _label, source, _icon, _route in layout.NAV_BOTTOM:
        if source in ("Por responder", "Tu semana"):
            assert source in layout.NAV_COUNTERS
    assert set(layout.MORE_COUNTED) <= set(layout.NAV_COUNTERS)
    # What «Más» counts is never on the bar itself (no pending counted twice).
    on_bar = {source for _l, source, _i, _r in layout.NAV_BOTTOM}
    assert not on_bar & set(layout.MORE_COUNTED)
    # WhatsApp chats are already inside «Por responder»: «Más» never repeats them.
    assert layout.MORE_COUNTED == ("Por aprobar",)
    rendered = str(layout._bottom_bar().render())
    assert "respond_badge" in rendered and "schedule_badge" in rendered
    assert "respond_aria" in rendered and "schedule_aria" in rendered


def test_more_opens_the_drawer_as_a_button() -> None:
    rendered = str(layout._bottom_bar().render())
    assert "toggle_mobile_nav" in rendered
    assert "aria-expanded" in rendered or "ariaExpanded" in rendered
    assert layout.SIDEBAR_ID in rendered
    assert layout.SIDEBAR_ID in str(layout.sidebar().render())


def test_nav_is_labelled_and_marks_the_current_page() -> None:
    rendered = str(layout._bottom_bar().render())
    assert _has(rendered, "Accesos rápidos")
    assert "page" in rendered  # aria-current
    # «Tu semana» stays active on its own views (/planner/…).
    assert '"/planner/"' in rendered


def test_shell_renders_the_bar_after_main_only_with_the_rail() -> None:
    import reflex as rx

    with_rail = str(layout.app_shell(rx.text("x")).render())
    assert "q-bottom-bar" in with_rail
    assert with_rail.index('"main"') < with_rail.index("q-bottom-bar")
    without = str(layout.app_shell(rx.text("x"), rail=False).render())
    assert "q-bottom-bar" not in without
    # The ☰ button it replaced is gone.
    assert "q-mobile-nav-toggle" not in with_rail
    assert not hasattr(layout, "_mobile_nav_toggle")


def _block(media: str) -> str:
    """Every CSS rule inside `@media (<media>)` blocks, concatenated."""
    out = []
    for match in re.finditer(re.escape(f"@media ({media})") + r"\s*\{", _CSS):
        depth, i = 1, match.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(_CSS[i], 0)
            i += 1
        out.append(_CSS[match.end() : i])
    return "\n@@\n".join(out)


def test_css_only_on_phones_with_thumb_targets() -> None:
    # Hidden by default (desktop), shown and fixed only at ≤ 640 px.
    assert re.search(r"\.q-bottom-bar \{\s*display: none;", _CSS)
    phone = _block("max-width: 640px")
    assert ".q-bottom-bar:not(.q-bottom-bar--demo)" in phone
    assert "position: fixed" in phone
    assert "env(safe-area-inset-bottom" in phone
    # The panel reserves the bar's height so it never covers content.
    assert ".q-page-body" in phone and "--q-bottom-bar-h" in phone
    # N12: the whole cell is at least 44 px tall (56 px).
    cell = re.search(r"\.q-bottom-link \{([^}]*)\}", _CSS)
    assert cell is not None
    height = re.search(r"min-height: (\d+)px", cell.group(1))
    assert height is not None and int(height.group(1)) >= 44
    # No hover-only rule outside `@media (hover: hover)`.
    outside_hover = _CSS
    for block in _block("hover: hover").split("\n@@\n"):
        outside_hover = outside_hover.replace(block, "")
    assert ".q-bottom-link:hover" not in outside_hover
    # Opaque, never glass.
    bar_rules = re.findall(r"\.q-bottom-[a-z-]+[^{]*\{([^}]*)\}", _CSS)
    assert not any("backdrop-filter" in rule for rule in bar_rules)


def test_viewport_declares_the_safe_area() -> None:
    source = (Path(__file__).parent / "Qualify.py").read_text(encoding="utf-8")
    assert "viewport-fit=cover" in source


def test_the_short_form_speaks_the_menu_name() -> None:
    # «Crear» is shown, «Crear publicación» is spoken: one name per place (N1).
    rendered = str(layout._bottom_bar().render())
    assert _has(rendered, "Crear publicación")
    assert "more_urgent" not in rendered


def test_labels_never_cut_a_word_in_half() -> None:
    rule = _CSS[_CSS.index(".q-bottom-label {") :]
    rule = rule[: rule.index("}")]
    assert "word-break: keep-all" in rule
    assert "break-word" not in rule
