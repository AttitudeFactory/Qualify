"""m-25142793: on a phone the page header collapses to one pinned line.

At the top of «Por responder» the chip, the title and the subtitle show; scrolled, only
the line with the title and the colour toggle (top-right corner) stays pinned, ≤ 64 px,
and `--q-sticky-header-height` follows it. On a desk the whole sheet stays pinned, as
before. The CSS and the DOM order are covered offline by
`Qualify/test_page_header_compact.py`.
"""

from __future__ import annotations

import re

from .conftest import expect

PHONES = ({"width": 390, "height": 844}, {"width": 360, "height": 780})
DESKTOP = {"width": 1280, "height": 800}

_PINNED = """
() => {
  const panel = document.querySelector('main.q-panel');
  const bar = panel.querySelector('.q-page-head-bar');
  const toggle = bar.querySelector('.q-theme-toggle').getBoundingClientRect();
  const title = bar.querySelector('h1').getBoundingClientRect();
  const box = bar.getBoundingClientRect();
  return {
    position: getComputedStyle(bar).position,
    height: box.height,
    offset: box.top - panel.getBoundingClientRect().top,
    toggle: {w: toggle.width, h: toggle.height, right: box.right - toggle.right,
             sameLine: Math.abs((toggle.top + toggle.bottom) - (title.top + title.bottom)) < 4},
    sticky: parseFloat(getComputedStyle(panel).getPropertyValue('--q-sticky-header-height')),
    overflow: document.documentElement.scrollWidth > window.innerWidth,
  };
}
"""


def _origin(page) -> str:  # noqa: ANN001
    match = re.match(r"https?://[^/]+", page.url)
    assert match is not None
    return match.group(0)


def test_only_the_title_line_stays_pinned_on_a_phone(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    for size in PHONES:
        page.set_viewport_size(size)
        page.goto(_origin(page) + "/responder")
        expect(page.get_by_role("heading", level=1, name="Por responder")).to_be_visible()
        expect(page.locator(".q-business-chip")).to_be_visible()
        expect(page.locator(".q-page-head-sub")).to_be_visible()
        top = page.evaluate(_PINNED)
        assert top["position"] == "sticky"
        assert top["toggle"]["w"] >= 44 and top["toggle"]["h"] >= 44
        assert top["toggle"]["sameLine"]
        assert not top["overflow"]
        moved = page.evaluate(
            "() => { const p = document.querySelector('main.q-panel');"
            " p.scrollTop = 400; return p.scrollTop; }"
        )
        page.wait_for_timeout(300)
        scrolled = page.evaluate(_PINNED)
        assert scrolled["offset"] <= 1  # pinned to the top of the panel
        assert scrolled["height"] <= 64
        assert abs(scrolled["sticky"] - scrolled["height"]) <= 1
        if moved >= 120:  # the page is long enough for the chip to leave
            expect(page.locator(".q-business-chip")).not_to_be_in_viewport()


_INSIDE = """
() => {
  const panel = document.querySelector('main.q-panel').getBoundingClientRect();
  const out = [...document.querySelectorAll(
      '.q-page-header h1, .q-page-header .rt-Button, .q-page-header .rt-SelectTrigger,'
      + ' .q-page-header .rt-SegmentedControlRoot, .q-theme-toggle')]
    .filter((el) => el.getClientRects().length)
    .filter((el) => { const b = el.getBoundingClientRect();
      return b.left < panel.left - 0.5 || b.right > panel.right + 0.5; })
    .map((el) => el.textContent.trim().slice(0, 20) || el.className);
  return {out, overflow: document.documentElement.scrollWidth > window.innerWidth};
}
"""


def test_a_page_with_actions_keeps_them_in_the_pinned_bar(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    page.set_viewport_size(PHONES[1])
    page.goto(_origin(page) + "/planner")
    expect(page.get_by_role("heading", level=1, name="Tu semana")).to_be_visible()
    page.evaluate("document.querySelector('main.q-panel').scrollTop = 400")
    page.wait_for_timeout(300)
    pinned = page.evaluate(_PINNED)
    assert pinned["offset"] <= 1 and pinned["toggle"]["sameLine"]
    # the actions are in the pinned bar, on the title's row or on rows of their own
    bar = page.locator(".q-page-head-bar").bounding_box()
    for box in page.locator(".q-page-head-actions > *").evaluate_all(
        "els => els.filter(e => e.getClientRects().length)"
        ".map(e => { const b = e.getBoundingClientRect(); return [b.top, b.bottom]; })"
    ):
        assert bar is not None and bar["y"] - 1 <= box[0] and box[1] <= bar["y"] + bar["height"] + 1
    assert page.evaluate(_INSIDE) == {"out": [], "overflow": False}


def test_between_phone_and_desk_nothing_leaves_the_panel(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    for width in (641, 700, 768, 900):
        page.set_viewport_size({"width": width, "height": 900})
        for path in ("/planner", "/responder", "/aprobados"):
            page.goto(_origin(page) + path)
            expect(page.get_by_role("heading", level=1)).to_be_visible()
            assert page.evaluate(_INSIDE) == {"out": [], "overflow": False}, (width, path)


def test_the_whole_sheet_stays_pinned_on_a_desk(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    page.set_viewport_size(DESKTOP)
    page.goto(_origin(page) + "/responder")
    header = page.locator(".q-page-header")
    expect(header.get_by_role("heading", level=1)).to_be_visible()
    assert header.evaluate("el => getComputedStyle(el).position") == "sticky"
    # the old row: the actions and the toggle are items of the bar, which wraps
    assert (
        page.locator(".q-page-head-bar").evaluate("el => getComputedStyle(el).flexWrap") == "wrap"
    )
