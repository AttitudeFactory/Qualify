"""m-25143240: the open chat never scrolls sideways on a phone.

The reply box's tool row scrolls on its own below 768 px; the Instagram row also holds
the two upload zones, whose 1×1 file inputs are absolutely positioned. Without a
positioned row they escaped its clipping and widened `.q-panel` by up to 228 px.

Seeded by `chat_fixtures.seed_chats` (`chats_page`); nothing reaches Meta or R2 and
nothing is sent or uploaded.
"""

from __future__ import annotations

import pytest

from .conftest import expect
from .test_reply_box import _instagram, _open, _whatsapp

pytestmark = pytest.mark.e2e

WIDTHS = ((360, 780), (390, 844), (700, 900))

_OVERFLOW = """
() => {
  const p = document.querySelector('.q-panel');
  const se = document.scrollingElement;
  return {panel: p.scrollWidth - p.clientWidth, page: se.scrollWidth - se.clientWidth};
}
"""

#: The last tool, scrolled into view inside its own row, ends up inside the row.
_LAST_TOOL_REACHABLE = """
() => {
  const row = document.querySelector('.q-chat-thread .q-reply-tools');
  if (!row) return null;
  const tools = row.querySelectorAll('.q-reply-tool');
  const last = tools[tools.length - 1];
  const start = row.scrollLeft;
  row.scrollLeft = row.scrollWidth;
  const r = row.getBoundingClientRect();
  const t = last.getBoundingClientRect();
  return {start, inside: t.left >= r.left - 1 && t.right <= r.right + 1,
          w: Math.round(t.width), h: Math.round(t.height)};
}
"""


@pytest.mark.parametrize("channel", ["instagram", "whatsapp"])
def test_open_chat_never_scrolls_sideways(chats_page, channel: str) -> None:  # noqa: ANN001
    page = chats_page
    ids = page._qualify_e2e_chats
    path = (
        _instagram(ids, "instagram_open")
        if channel == "instagram"
        else _whatsapp(ids, "whatsapp_open")
    )
    failures: list[str] = []
    for width, height in WIDTHS:
        page.set_viewport_size({"width": width, "height": height})
        _open(page, path)
        expect(page.locator(".q-chat-thread .q-reply-tool").first).to_be_visible()
        where = f"{channel} at {width} px"
        overflow = page.evaluate(_OVERFLOW)
        if overflow["panel"] > 1:
            failures.append(f"{where}: the panel scrolls sideways {overflow}")
        if overflow["page"] > 1:
            failures.append(f"{where}: the page scrolls sideways {overflow}")
        last = page.evaluate(_LAST_TOOL_REACHABLE)
        if last is None:
            failures.append(f"{where}: no tool row")
            continue
        if last["start"] != 0:
            failures.append(f"{where}: the tool row opens scrolled {last}")
        if not last["inside"]:
            failures.append(f"{where}: the last tool cannot be scrolled into view {last}")
        if last["h"] < 44:
            failures.append(f"{where}: the last tool is under 44 px {last}")
    assert not failures, "\n".join(failures)
