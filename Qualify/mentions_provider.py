"""The seam between the Dashboard de Menciones and the real `mentions` backend (QUA-49,
reworked for QUA-152).

Same split `inbox_provider.py`/`publishing_provider.py` establish: a thin, in-process
projection over `qualify_api.mentions.composition`'s published read seams — no HTTP hop.
This module owns exactly one thing: turning a `MentionRecord` (a service shape) into a
`MentionVM` (a display-ready row).

## One row, one meaning per column (QUA-152, founder review 2026-10-13)

- **Fecha** — the date of the mention itself: when the post or the comment was published
  on Instagram; the reception time only when Meta did not give one.
- **Canal** / **Tipo** — where (Instagram) and what (Publicación / Comentario), apart.
- **Autor** — who mentioned the account: the publication's author for a mention in a
  caption; for a comment on one of the account's OWN posts, the commenter (the `comments`
  webhook carries it). Instagram does not share who wrote a comment on SOMEONE ELSE's post
  that mentions the account, so that comment mention reads "No disponible" with that
  reason; the publication's author is NEVER shown as the comment's.
- **Mención** — the caption or the comment text, full text on hover.
- **Likes** — of that mention (the post or the comment). Absent is never a 0: "Ocultos"
  when the owner hid them, "—" when Meta gave nothing.
- **Ver** — the link to the content on Instagram, only when Meta returned one
  (`permalink`, best-effort, migration 0052). Never built from an id.

The connected account the mention was made TO is not a column: a tenant has one account
almost always, and it is offered as a filter when there are several.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from qualify_api.mentions.composition import (
    ContentRefreshReport,
    has_new_mentions_for_tenant,
    list_mentions_page_for_tenant,
    refresh_mentions_content,
    refresh_mentions_in_scope,
    summarize_mentions_for_tenant,
)
from qualify_api.mentions.repository import (
    ENRICHMENT_FAILED,
    MentionCounts,
    MentionQuery,
    MentionRecord,
)

from .connections_provider import connections_for
from .mentions_paging import pages_label
from .planner_vm import CALENDAR_DEFAULT_TZ

NOT_AVAILABLE = "No disponible"
UNKNOWN_ACCOUNT = "Cuenta desconocida"
CONTENT_UNAVAILABLE = "Contenido no disponible en la red social"
NO_TEXT = "Sin texto"
NO_VALUE = "—"
LIKES_NOTE_HIDDEN = "El autor ocultó el número de Me gusta."
LIKES_NOTE_MISSING = "La red social no devolvió los Me gusta de esta mención."

AUTHOR_NOTE_COMMENT = "La red social no comparte quién escribe un comentario que te menciona."
AUTHOR_NOTE_POST = "La red social no devolvió el autor de esta publicación."
AUTHOR_NOTE_UNREAD = "No se pudo leer esta mención en la red social."

_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
# The product's display zone — the same one the Planificador shows times in.
DISPLAY_ZONE = ZoneInfo(CALENDAR_DEFAULT_TZ)


@dataclass(frozen=True)
class MentionVM:
    """Display-ready projection of one mention — exactly what `components.mention_row`
    renders. Every field is text (or a flag); nothing is left for the UI to infer."""

    id: str
    platform: str
    kind: str  # "post" / "comment"
    kind_label: str  # "Publicación" / "Comentario"
    author: str  # "@username" or "No disponible"
    author_note: str  # why the author is not available; "" when it is
    text: str  # the caption or the comment text, in full
    text_unavailable: bool
    date: str  # the mention's own date and time, '13 oct 2026, 09:15'
    day: str  # the same date alone, '13 oct 2026' (stacked layout)
    time: str  # the same time alone, '09:15' ('' when there is no date)
    sentiment_state: str  # POS/NEU/NEG/PENDING/NO_TEXT/ERROR
    likes: str  # a number, or "—" — never a made-up 0
    likes_note: str  # why the likes are "—"; "" when they are a number
    permalink: str  # "" when Instagram gave no link


@dataclass(frozen=True)
class MentionCountsVM:
    total: int = 0
    positive: int = 0
    neutral: int = 0
    negative: int = 0
    pending: int = 0
    no_text: int = 0
    error: int = 0


@dataclass(frozen=True)
class MentionPageVM:
    rows: list[MentionVM]
    # The summary cards: the SCOPE only (account + period) — a search, an origin or a
    # sentiment filter never moves them (founder review 2026-10-13).
    summary: MentionCountsVM
    # What the table shows: the fully filtered set (paging, empty states, list changes).
    filtered_total: int
    page: int
    total_pages: int
    pages_label: str
    as_of: str  # ISO-8601, round-trips through Reflex state as text


def _day_and_time(value: datetime | None) -> tuple[str, str]:
    """('13 oct 2026', '09:15') in the display zone, or ('No disponible', '')."""
    if value is None:
        return NOT_AVAILABLE, ""
    local = value.astimezone(DISPLAY_ZONE)
    return f"{local.day} {_MONTHS[local.month - 1]} {local.year}", f"{local:%H:%M}"


def format_moment(value: datetime | None) -> str:
    """'13 oct 2026, 09:15' in the display zone, or 'No disponible'."""
    day, time = _day_and_time(value)
    return f"{day}, {time}" if time else day


def account_labels(tenant_id: UUID) -> dict[UUID, str]:
    """Every Instagram connection of the tenant -> '@username'. Any status: a mention keeps
    naming its account after a disconnect. Blocking DB call."""
    return {
        # `ConnectionVM.id` is text; mention records carry a UUID.
        UUID(connection.id): (
            f"@{connection.external_username}" if connection.external_username else UNKNOWN_ACCOUNT
        )
        for connection in connections_for(tenant_id)
        if connection.platform == "instagram"
    }


def _author(record: MentionRecord, *, is_comment: bool, unread: bool) -> tuple[str, str]:
    if unread:
        return NOT_AVAILABLE, AUTHOR_NOTE_UNREAD
    # A comment row's author can only be the commenter: it is written solely from the
    # `comments` webhook's `from` (comments on the account's own posts); no read ever puts
    # the publication's owner there.
    if record.author_username:
        return f"@{record.author_username}", ""
    if is_comment:
        return NOT_AVAILABLE, AUTHOR_NOTE_COMMENT
    return NOT_AVAILABLE, AUTHOR_NOTE_POST


def to_vm(record: MentionRecord) -> MentionVM:
    is_comment = record.comment_id is not None
    unread = record.enrichment_status == ENRICHMENT_FAILED
    content = record.text if is_comment else record.caption

    if unread:
        text, text_unavailable = CONTENT_UNAVAILABLE, True
    elif content is None or not content.strip():
        text, text_unavailable = NO_TEXT, True
    else:
        text, text_unavailable = content, False

    if record.like_count is not None and not unread:
        likes, likes_note = str(record.like_count), ""
    elif unread or is_comment:
        likes, likes_note = NO_VALUE, LIKES_NOTE_MISSING
    else:
        # Meta omits a media's like_count when its owner hid the count on Instagram.
        likes, likes_note = NO_VALUE, LIKES_NOTE_HIDDEN

    author, author_note = _author(record, is_comment=is_comment, unread=unread)
    moment = record.content_posted_at or record.received_at
    day, time = _day_and_time(moment)
    return MentionVM(
        id=str(record.id),
        platform=record.platform,
        kind="comment" if is_comment else "post",
        kind_label="Comentario" if is_comment else "Publicación",
        author=author,
        author_note=author_note,
        text=text,
        text_unavailable=text_unavailable,
        date=format_moment(moment),
        day=day,
        time=time,
        sentiment_state=record.sentiment_state,
        likes=likes,
        likes_note=likes_note,
        permalink=record.permalink or "",
    )


def _parse(iso: str) -> datetime | None:
    return datetime.fromisoformat(iso) if iso else None


def _counts_vm(counts: MentionCounts) -> MentionCountsVM:
    return MentionCountsVM(
        total=counts.total,
        positive=counts.positive,
        neutral=counts.neutral,
        negative=counts.negative,
        pending=counts.pending,
        no_text=counts.no_text,
        error=counts.error,
    )


def load_page(
    tenant_id: UUID,
    *,
    query: MentionQuery,
    page: int,
    as_of: str = "",
) -> MentionPageVM:
    """One page of 12 under the snapshot `as_of` ('' = take a new one), plus the summary
    for the scope (account + period) under the SAME snapshot. Blocking DB call — run it
    off-thread."""
    result = list_mentions_page_for_tenant(
        tenant_id=tenant_id, query=query, page=page, as_of=_parse(as_of)
    )
    summary = summarize_mentions_for_tenant(
        tenant_id=tenant_id,
        query=MentionQuery(connection_id=query.connection_id, since=query.since),
        as_of=result.as_of,
    )
    return MentionPageVM(
        rows=[to_vm(r) for r in result.rows],
        summary=_counts_vm(summary),
        filtered_total=result.counts.total,
        page=result.page,
        total_pages=result.total_pages,
        pages_label=pages_label(result.total_pages),
        as_of=result.as_of.isoformat(),
    )


def has_new(tenant_id: UUID, *, query: MentionQuery, as_of: str) -> bool:
    """Whether any mention matching `query` arrived after the snapshot — what tells the
    tick to take new mentions in (never shown). Blocking DB call."""
    if not as_of:
        return False
    return has_new_mentions_for_tenant(tenant_id=tenant_id, query=query, after=_parse(as_of))


async def refresh_content(tenant_id: UUID, mention_ids: list[str]) -> ContentRefreshReport:
    """Re-read these (visible) mentions from their network right away and store what
    changed (QUA-152). A failed read keeps the stored data."""
    return await refresh_mentions_content(
        tenant_id=tenant_id, mention_ids=tuple(UUID(m) for m in mention_ids)
    )


async def refresh_scope(tenant_id: UUID, *, scope: MentionQuery) -> ContentRefreshReport:
    """One bounded run over the scope (account + period of `scope`) — the rest of
    "Actualizar menciones", after the visible page. Never raises."""
    return await refresh_mentions_in_scope(tenant_id=tenant_id, scope=scope)


def account_options(tenant_id: UUID) -> dict[str, str]:
    """'@username' -> connection id, for the account filter. Labels are made unique (two
    connections without a username would otherwise collapse into one option). Blocking
    DB call."""
    options: dict[str, str] = {}
    for connection_id, label in account_labels(tenant_id).items():
        unique, n = label, 2
        while unique in options:
            unique, n = f"{label} ({n})", n + 1
        options[unique] = str(connection_id)
    return options


__all__ = [
    "MentionCountsVM",
    "MentionPageVM",
    "MentionVM",
    "account_labels",
    "account_options",
    "format_moment",
    "has_new",
    "load_page",
    "to_vm",
]
