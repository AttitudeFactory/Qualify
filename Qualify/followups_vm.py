"""View models for «Consultas desde comentarios» (m-24789646, PR 3) — the cards a person
reviews in Conversaciones before a commercial query found in Interacciones is answered in
private.

Pure functions from `qualify_api.followups.workspace.FollowupCard` to frozen dataclasses
of display-ready strings: the state ships these to the browser, never a record. Time is
decided by the caller's `now` and shown in the tenant's zone.

What a card says, and where it comes from:
- **who and where**: the comment, its author, the post it was written on (with its link)
  and how the query was opened (an intent analysis, or by hand) — or, for a DM that
  replied to a story (PR 5), «Respondió a tu historia» with the story's link while Meta's
  URL lasts;
- **why**: the intents, highest confidence first, «revísalo» when the golden set does not
  back the class (same rule as Interacciones);
- **how it would go out right now**: the route the service would use (a normal DM while
  the person's 24 h window is open, else Meta's private reply to the comment) and how long
  it stays possible — or, when nothing can reach the person, the reason for each route,
  including an unverified capability's state («Por verificar») and switch;
- **the draft**: its text (the person edits it in place), «requiere revisión» and the
  claims the generator could not ground;
- **the public notice** (PR 4): only when `public_notice` is on and the origin is a
  comment, the default text the person may edit and approve together with the message.

**Three steps** (m-24842991, ATENDER-6, guide N3/N6): the card is walked as ① «Qué
preguntó» ② «Qué le respondes» ③ «Revisa y aprueba»; approving ends in «Listo. Le
escribiste a @ana. ¿Seguimos con la siguiente?» with «Siguiente» and «Volver a
comentarios». Every explanation is visible text, never a tooltip (a phone has no hover).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from qualify_api.followups.notice import DEFAULT_NOTICE_TEXT
from qualify_api.followups.repository import FollowupTrigger, SendRoute
from qualify_api.followups.service import RouteOption
from qualify_api.followups.workspace import FollowupCard, surface_label

from .nav_url import with_query

VIEW_MESSAGES: Final = "messages"
VIEW_QUERIES: Final = "queries"
VIEWS: Final = (VIEW_MESSAGES, VIEW_QUERIES)

# N5 (m-24842960): the active view lives in the address, in the owner's words.
CONVERSATIONS_ROUTE: Final = "/conversations"
VIEW_PARAM: Final = "vista"
VIEW_SLUGS: Final = {VIEW_MESSAGES: "mensajes", VIEW_QUERIES: "consultas"}


def view_from_param(slug: str) -> str:
    """`?vista=consultas` → `VIEW_QUERIES`; anything else (absent, junk) → `VIEW_MESSAGES`."""
    for view, known in VIEW_SLUGS.items():
        if slug == known:
            return view
    return VIEW_MESSAGES


def view_url(view: str) -> str:
    """The address of a view: `/conversations?vista=consultas`."""
    slug = VIEW_SLUGS.get(view, VIEW_SLUGS[VIEW_MESSAGES])
    return with_query(CONVERSATIONS_ROUTE, **{VIEW_PARAM: slug})


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
    FollowupTrigger.INTENT: "Quiere comprar",
    FollowupTrigger.MANUAL: "La abriste tú desde Comentarios",
}
CAPTION_CHARS: Final = 120

# -- the three steps (m-24842991) ----------------------------------------------------------
STEP_ASKED: Final = 1
STEP_REPLY: Final = 2
STEP_REVIEW: Final = 3
STEP_TITLES: Final[dict[int, str]] = {
    STEP_ASKED: "Qué preguntó",
    STEP_REPLY: "Qué le respondes",
    STEP_REVIEW: "Revisa y aprueba",
}
STEP_COUNT: Final = len(STEP_TITLES)
#: Where «Volver a comentarios» goes, after approving or with nobody left.
COMMENTS_HREF: Final = "/responder?tab=comentarios"
ANOTHER_IDEA: Final = "Otra idea"
SUGGEST_ONE: Final = "Sugerir un mensaje"
STORY_WHERE: Final = "tu historia"
STORY_ORIGIN_LABEL: Final = "Respondió a tu historia por mensaje directo"

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
    # «Comentó en tu Reel» / «Respondió a tu historia por mensaje directo».
    origin_label: str
    caption: str
    permalink: str
    trigger_label: str
    intents: list[FollowupIntentVM] = field(default_factory=list)
    # m-24842988: one of the intents is «· revísalo» — the card says why, once.
    intent_unsure: bool = False
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
    # The public notice under the comment: offered only with `public_notice` on.
    notice_available: bool = False
    notice_default: str = ""
    # Step 3, in words: «Le llega a @ana por mensaje privado.»
    recipient_line: str = ""


def step_label(step: int) -> str:
    """«Paso 2 de 3 · Qué le respondes» — M is real: the three steps always apply."""
    title = STEP_TITLES.get(step, STEP_TITLES[STEP_ASKED])
    number = step if step in STEP_TITLES else STEP_ASKED
    return f"Paso {number} de {STEP_COUNT} · {title}"


def recipient_line(author: str) -> str:
    if author.startswith("@"):
        return f"Le llega a {author} por mensaje privado."
    return "Le llega por mensaje privado."


def notice_line(text: str) -> str:
    """The notice offered in step 3: «También dejamos “Te escribimos al privado 💬” en su
    comentario.»"""
    return f"También dejamos “{text}” en su comentario."


def done_title(author: str, *, more_left: bool) -> str:
    """The confirmation once approved (N3): who got it, and the next step."""
    who = author if author.startswith("@") else "tu cliente"
    tail = "¿Seguimos con la siguiente?" if more_left else "No queda nadie más esperando."
    return f"Listo. Le escribiste a {who}. {tail}"


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
    # each reason already names its route: the card and the toast say the same thing
    return option.reason


def build_card_vm(card: FollowupCard, *, now: datetime, zone: ZoneInfo) -> FollowupCardVM:
    origin, followup, options = card.origin, card.followup, card.options
    username = (origin.author_username or "").strip()
    author = f"@{username}" if username else "Cliente"
    story = origin.is_story_reply
    caption = "" if story else (origin.media_caption or "").strip()
    if len(caption) > CAPTION_CHARS:
        caption = caption[: CAPTION_CHARS - 1].rstrip() + "…"
    where = STORY_WHERE if story else surface_label(origin.media_product_type)
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
        where_label=where,
        origin_label=STORY_ORIGIN_LABEL if story else f"Comentó en {where}",
        caption=caption,
        permalink=(origin.story_reply_url if story else origin.media_permalink) or "",
        trigger_label=TRIGGER_LABELS[followup.trigger],
        intents=[FollowupIntentVM(c.label, c.commercial, c.reliable) for c in card.intents],
        intent_unsure=any(not c.reliable for c in card.intents),
        has_draft=draft is not None,
        draft_id=str(draft.id) if draft else "",
        draft_text=draft.generated_text if draft else "",
        needs_review=bool(draft.needs_review) if draft else False,
        unsupported_claims=[str(c) for c in unsupported if str(c).strip()],
        notice_available=card.notice_available,
        notice_default=DEFAULT_NOTICE_TEXT if card.notice_available else "",
        recipient_line=recipient_line(author),
        **route_fields,  # type: ignore[arg-type]
    )
