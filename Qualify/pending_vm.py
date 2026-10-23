"""The menu's pending counters and the browser tab's «(N)» (m-24842963, NAV-6, N11).

Pure view model — no Reflex, no database — so every rule is tested directly.

Four menu entries carry a number, each counted with the rule of the list it opens:

- **Por responder** — everyone waiting for an answer, as «Por responder» counts them
  (`qualify_api.attention`, the single count of ATENDER-1, m-24842990): Instagram
  messages pending, people who want to buy, comment replies ready to approve and
  WhatsApp chats with an unanswered message.
- **WhatsApp** — the WhatsApp chats of that same count (its «Sin leer» filter).
- **Por aprobar** — publications generated and waiting for the owner's approval
  (`ApprovalStatus.PENDING`). Only those: approving one always takes it out of the
  number, which is the story's second criterion.
- **Tu semana** — approved publications that still have no day and time (the planner's
  «Sin programar» list, `PlannerService.list_unscheduled`).

With 0 an entry shows nothing. The tab title starts with «(N)», N being every pending
thing once: WhatsApp is already inside Por responder, so it is not added twice.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from qualify_api.planner.gallery import GalleryState, gallery_state
from qualify_api.planner.post_reader import ApprovalStatus, PostSummary

#: Past this a badge reads «99+»: the exact figure is on the screen it opens.
BADGE_CAP = 99


@dataclass(frozen=True)
class MenuCounts:
    """What waits for the owner, per menu entry. Never negative."""

    respond: int = 0
    whatsapp: int = 0
    approve: int = 0
    schedule: int = 0

    @property
    def total(self) -> int:
        """Every pending thing once (WhatsApp is part of `respond`)."""
        return self.respond + self.approve + self.schedule

    @property
    def more(self) -> int:
        """What «Más» counts on the phone's bottom bar (m-24842964, NAV-7): only what
        waits behind the drawer and is not already on the bar — Por aprobar. WhatsApp
        chats are already inside «Por responder», and «Tu semana» carries its own
        count, so nothing is counted twice (docs/design-system.md §4.4)."""
        return self.approve


def clamp(value: object) -> int:
    """A count as a non-negative int; anything unreadable reads as 0."""
    try:
        number = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def badge_text(count: int) -> str:
    """The badge next to a menu entry: nothing at 0, «99+» past the cap."""
    count = clamp(count)
    if count == 0:
        return ""
    return f"{BADGE_CAP}+" if count > BADGE_CAP else str(count)


# What each counted entry announces to a screen reader (N10: a number never goes alone).
# (singular, plural) — the plural carries «{n}».
_ENTRY_SPOKEN: dict[str, tuple[str, str]] = {
    "Por responder": ("1 persona espera tu respuesta", "{n} personas esperan tu respuesta"),
    "WhatsApp": ("1 chat sin responder", "{n} chats sin responder"),
    "Por aprobar": (
        "1 publicación espera tu aprobación",
        "{n} publicaciones esperan tu aprobación",
    ),
    "Tu semana": ("1 publicación aprobada sin día", "{n} publicaciones aprobadas sin día"),
}


def entry_aria_label(label: str, count: int) -> str:
    """The spoken name of a menu entry: «Por aprobar: 3 publicaciones esperan tu
    aprobación», or just the entry's name at 0 (or for an entry without a count)."""
    count = clamp(count)
    spoken = _ENTRY_SPOKEN.get(label)
    if spoken is None or count == 0:
        return label
    one, many = spoken
    return f"{label}: {one if count == 1 else many.format(n=badge_text(count))}"


def more_button_aria_label(count: int) -> str:
    """The spoken name of «Más», the bottom bar's button that opens the menu drawer
    (m-24842964). It starts with the visible word, then says what it does and what
    waits inside: «Más: abrir el menú. 2 publicaciones por aprobar»."""
    count = clamp(count)
    if count == 0:
        return "Más: abrir el menú"
    if count == 1:
        return "Más: abrir el menú. 1 publicación por aprobar"
    return f"Más: abrir el menú. {badge_text(count)} publicaciones por aprobar"


def count_to_approve(posts: Iterable[PostSummary]) -> int:
    """Publications waiting for the owner's approval — a generated draft not yet
    approved or rejected. An approved one that still lacks something is not counted
    here: it is no longer the owner's approval that it waits for."""
    return sum(
        1
        for post in posts
        if post.approval is ApprovalStatus.PENDING
        and gallery_state(post) is GalleryState.NEEDS_ACTION
    )


def title_prefix(total: int) -> str:
    """«(3) » before the page title when something waits; empty otherwise."""
    text = badge_text(total)
    return f"({text}) " if text else ""


def titled(title: str, total: int) -> str:
    """The page title with the pending prefix — the same rule the browser script
    applies (`title_script`), kept here so it can be tested in Python."""
    base = _strip_prefix(title)
    return f"{title_prefix(total)}{base}"


def _strip_prefix(title: str) -> str:
    if title.startswith("("):
        end = title.find(") ")
        inner = title[1:end] if end > 0 else ""
        if inner and inner.rstrip("+").isdigit():
            return title[end + 2 :]
    return title


# The browser side of `titled`. One MutationObserver per document re-applies the prefix
# whenever a navigation swaps the page's <title>, so the «(N)» survives moving between
# screens without waiting for the next count. `window.__qPending` is the latest total.
_TITLE_JS = """(function (n) {
  window.__qPending = n;
  function apply() {
    var p = window.__qPending || 0;
    var base = document.title.replace(/^\\(\\d+\\+?\\) /, '');
    var want = p > 0 ? '(' + (p > %(cap)d ? '%(cap)d+' : p) + ') ' + base : base;
    if (document.title !== want) document.title = want;
  }
  if (!window.__qTitleObserver && document.head) {
    window.__qTitleObserver = new MutationObserver(apply);
    window.__qTitleObserver.observe(document.head, {
      subtree: true, childList: true, characterData: true
    });
  }
  apply();
})(%(total)d);"""


def title_script(total: int) -> str:
    """The script that writes «(N) » at the start of the tab title (or removes it).
    `total` is formatted as an int, never interpolated as text."""
    return _TITLE_JS % {"cap": BADGE_CAP, "total": clamp(total)}


__all__ = [
    "BADGE_CAP",
    "MenuCounts",
    "badge_text",
    "clamp",
    "count_to_approve",
    "entry_aria_label",
    "more_button_aria_label",
    "title_prefix",
    "title_script",
    "titled",
]
