"""View models for «Consultas desde comentarios» (m-24789646, PR 3) — the cards a person
reviews in Conversaciones before a commercial query found in Interacciones is answered in
private.

Pure functions from `qualify_api.followups.workspace.FollowupCard` to frozen dataclasses
of display-ready strings: the state ships these to the browser, never a record. Time is
decided by the caller's `now` and shown in the tenant's zone.

What a card says, and where it comes from:
- **who and where**: the comment, its author, the post it was written on (with its link)
  and how the query was opened (an intent analysis, or by hand);
- **why**: the intents, highest confidence first, «no fiable» when the golden set does not
  back the class (same rule as Interacciones);
- **how it would go out right now**: the route the service would use (a normal DM while
  the person's 24 h window is open, else Meta's private reply to the comment) and how long
  it stays possible — or, when nothing can reach the person, the reason for each route,
  including an unverified capability's state («Por verificar») and switch;
- **the draft**: its text (the person edits it in place), «requiere revisión» and the
  claims the generator could not ground.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from qualify_api.followups.repository import FollowupTrigger, SendRoute
from qualify_api.followups.service import RouteOption
from qualify_api.followups.workspace import FollowupCard, surface_label

VIEW_MESSAGES: Final = "messages"
VIEW_QUERIES: Final = "queries"
VIEWS: Final = (VIEW_MESSAGES, VIEW_QUERIES)

ROUTE_LABELS: Final = {
    SendRoute.DM: "Mensaje directo",
    SendRoute.PRIVATE_REPLY: "Respuesta privada al comentario",
}
ROUTE_NOTES: Final = {
    SendRoute.DM: "La persona te escribió en las últimas 24 horas: va a su conversación.",
    SendRoute.PRIVATE_REPLY: (
        "Un solo mensaje por comentario. Le llega a «Mensajes» o a «Solicitudes»; la "
        "conversación sigue si responde."
    ),
}
TRIGGER_LABELS: Final = {
    FollowupTrigger.INTENT: "Intención comercial",
    FollowupTrigger.MANUAL: "Abierta desde Interacciones",
}
CAPTION_CHARS: Final = 120

_MONTHS: Final = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)


@dataclass(frozen=True)
class FollowupIntentVM:
    label: str
    commercial: bool
    reliable: bool


@dataclass(frozen=True)
class FollowupCardVM:
    followup_id: str
    author: str
    initial: str
    comment_text: str
    posted_label: str
    where_label: str
    caption: str
    permalink: str
    trigger_label: str
    intents: list[FollowupIntentVM] = field(default_factory=list)
    route_available: bool = False
    route_label: str = ""
    route_deadline: str = ""
    route_note: str = ""
    blocked_reasons: list[str] = field(default_factory=list)
    has_draft: bool = False
    draft_id: str = ""
    draft_text: str = ""
    needs_review: bool = False
    unsupported_claims: list[str] = field(default_factory=list)


def date_label(value: datetime | None, zone: ZoneInfo) -> str:
    if value is None:
        return ""
    local = value.astimezone(zone)
    return f"{local.day} {_MONTHS[local.month - 1]}, {local:%H:%M}"


def time_left(closes_at: datetime, now: datetime) -> str:
    """«quedan 6 d 4 h» / «quedan 3 h 20 min» / «quedan 12 min»."""
    left = closes_at - now
    if left <= timedelta(0):
        return "cerrada"
    minutes = int(left.total_seconds() // 60)
    days, rest = divmod(minutes, 24 * 60)
    hours, mins = divmod(rest, 60)
    if days:
        return f"quedan {days} d {hours} h"
    if hours:
        return f"quedan {hours} h {mins} min"
    return f"quedan {max(mins, 1)} min"


def _blocked(option: RouteOption) -> str:
    return f"{ROUTE_LABELS[option.route]}: {option.reason}"


def build_card_vm(card: FollowupCard, *, now: datetime, zone: ZoneInfo) -> FollowupCardVM:
    origin, followup, options = card.origin, card.followup, card.options
    username = (origin.author_username or "").strip()
    author = f"@{username}" if username else "Cliente"
    caption = (origin.media_caption or "").strip()
    if len(caption) > CAPTION_CHARS:
        caption = caption[: CAPTION_CHARS - 1].rstrip() + "…"
    chosen = options.chosen
    route_fields: dict[str, object]
    if chosen is not None:
        route_fields = {
            "route_available": True,
            "route_label": ROUTE_LABELS[chosen.route],
            "route_deadline": time_left(chosen.closes_at, now) if chosen.closes_at else "",
            "route_note": ROUTE_NOTES[chosen.route],
            "blocked_reasons": [],
        }
    else:
        route_fields = {
            "route_available": False,
            "blocked_reasons": [_blocked(options.dm), _blocked(options.private_reply)],
        }
    draft = card.draft
    unsupported = draft.grounding.get("unsupported_claims", []) if draft else []
    return FollowupCardVM(
        followup_id=str(followup.id),
        author=author,
        initial=(username[:1] or "C").upper(),
        comment_text=(origin.text or "").strip(),
        posted_label=date_label(origin.posted_at, zone),
        where_label=surface_label(origin.media_product_type),
        caption=caption,
        permalink=origin.media_permalink or "",
        trigger_label=TRIGGER_LABELS[followup.trigger],
        intents=[FollowupIntentVM(c.label, c.commercial, c.reliable) for c in card.intents],
        has_draft=draft is not None,
        draft_id=str(draft.id) if draft else "",
        draft_text=draft.generated_text if draft else "",
        needs_review=bool(draft.needs_review) if draft else False,
        unsupported_claims=[str(c) for c in unsupported if str(c).strip()],
        **route_fields,  # type: ignore[arg-type]
    )
