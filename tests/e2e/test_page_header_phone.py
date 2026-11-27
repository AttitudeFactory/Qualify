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


def test_the_whole_sheet_stays_pinned_on_a_desk(chats_page) -> None:  # noqa: ANN001
    page = chats_page
    page.set_viewport_size(DESKTOP)
    page.goto(_origin(page) + "/responder")
    header = page.locator(".q-page-header")
    expect(header.get_by_role("heading", level=1)).to_be_visible()
    assert header.evaluate("el => getComputedStyle(el).position") == "sticky"
    assert header.evaluate("el => getComputedStyle(el).display") == "grid"
