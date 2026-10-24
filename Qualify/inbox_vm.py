"""View-models for the inbox content screen — Instagram Reels and feed posts (QUA-146)
from the last 2 weeks, with the monitoring toggle (Fase 1 Parte 4-B, B2 UI slice).

Same security boundary as `publishing_vm.py`/`connections_vm.py`: every Reflex var is
serialized to the client. `InboxService`/`qualify_api.inbox.composition` never see or
return a token, so nothing credential-bearing can reach this dataclass in the first
place — the whitelist test (`test_inbox_ui.py`) pins that this stays true as the module
grows.

Kept free of Reflex and network imports so the whitelist can be asserted by a plain unit
test, same convention as `publishing_vm.py`/`connections_vm.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from qualify_api.inbox.media_type import MediaType, known_media_type

from .nav_url import with_query

# N5 (m-24842960): a publication's comments have their own address,
# `/inbox?publicacion=<thread id>`; the list is plain `/inbox`.
INBOX_ROUTE: Final = "/inbox"
POST_PARAM: Final = "publicacion"


def inbox_url(thread_id: str = "") -> str:
    """The list (`thread_id` empty) or one publication's comments."""
    return with_query(INBOX_ROUTE, **{POST_PARAM: thread_id})


# QUA-149: the four values `ReelSummaryVM.monitoring_state` can take — one per visible
# label. Computed server-side (`inbox_provider`) from the shared rule
# (`qualify_api.inbox.monitoring.effective_state`); the page only matches on them.
MONITORING_ACTIVE: Final = "active"  # «Buscando comentarios»
MONITORING_PENDING: Final = "pending"  # «Buscando comentarios · fecha por confirmar»
MONITORING_EXPIRED: Final = "expired"  # «Ya no buscamos comentarios»
MONITORING_INACTIVE: Final = "inactive"  # «No buscamos comentarios»

# m-24842988: Spanish short month names for the dates the owner reads («23 oct»).
_MONTHS: Final = (
    "ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic",
)  # fmt: skip


# m-24842988: said once per card, as visible text under the intent chips (a phone has
# no hover — N12), whenever one of them is «· revísalo». Comments and «Consultas».
UNSURE_INTENT_NOTE: Final = "No estamos seguros: lee el comentario antes de responder."


def short_day_label(moment: datetime) -> str:
    """«23 oct» — day and Spanish short month, in whatever zone `moment` carries."""
    return f"{moment.day} {_MONTHS[moment.month - 1]}"


@dataclass(frozen=True)
class CandidateMediaVM:
    """Display-ready projection of one `qualify_api.inbox.service.CandidateMedia`.

    `caption`/`permalink`/`thumbnail_url` are pre-coerced to `""` when absent (never
    `None`) — same "no raw nullable reaching the client" convention `ConnectionVM.
    last_verified_at`/`PublishAttemptVM.reason` already use.
    """

    external_media_id: str
    posted_at: str  # PRE-FORMATTED server-side (never a raw datetime var)
    is_monitored: bool
    caption: str
    permalink: str
    thumbnail_url: str
    # QUA-146: what the row is — `media_format_label` below, pre-formatted server-side.
    # `""` shows no label (a candidate built without format data, e.g. older tests).
    format_label: str = ""
    # m-24842988: the day it was published («21 oct»), for «En tu publicación del 21 oct»
    # on the reply cards. `""` when unknown.
    posted_day: str = ""


# QUA-146: the label each candidate row shows, by surface and Meta's `media_type`. A
# Reel is always "Reel"; a feed post is labelled by its format, and a format this code
# does not know yet (`inbox.media_type`) still reads as a feed post, never as an error.
REEL_LABEL: Final = "Reel"
FEED_POST_LABEL: Final = "Publicación"
# m-24789644: a story's comments, once `story_comments` is enabled (never offered today).
STORY_LABEL: Final = "Historia"
_FEED_FORMAT_LABELS: Final = {
    MediaType.IMAGE: "Foto",
    MediaType.VIDEO: "Video",
    MediaType.CAROUSEL_ALBUM: "Carrusel",
}


# QUA-146: the formats whose Meta `media_url` IS a picture. For VIDEO it is the video
# file, which an <img> cannot show — a video's picture is its `thumbnail_url`.
_PICTURE_MEDIA_TYPES: Final = frozenset({MediaType.IMAGE, MediaType.CAROUSEL_ALBUM})


def candidate_picture_url(
    media_type: str | None, thumbnail_url: str | None, media_url: str | None
) -> str:
    """The candidate row's picture: Meta's `thumbnail_url` when there is one (videos and
    Reels), else `media_url` for a photo or a carousel (Meta gives them no thumbnail), else
    `""` — the page then shows its generic frame. An unknown format never uses
    `media_url`: it might be a video file."""
    if thumbnail_url:
        return thumbnail_url
    if media_url and known_media_type(media_type) in _PICTURE_MEDIA_TYPES:
        return media_url
    return ""


def media_format_label(media_product_type: str | None, media_type: str | None) -> str:
    """The media's format label, or `""` when the surface is unknown (a legacy row whose
    metadata was never read). Stories are not monitorable yet (`MONITORABLE_MEDIA_
    PRODUCT_TYPES`); their label is here so the cards need no change when they are."""
    if media_product_type == "REELS":
        return REEL_LABEL
    if media_product_type == "STORY":
        return STORY_LABEL
    if media_product_type == "FEED":
        known = known_media_type(media_type)
        return _FEED_FORMAT_LABELS[known] if known is not None else FEED_POST_LABEL
    return ""


@dataclass(frozen=True)
class IntentChipVM:
    """One intent class of one comment, as the Interacciones screen shows it
    (m-24789644, B3). `label` is the Spanish name (`INTENT_CLASS_LABELS`); `commercial`
    picks the chip's tone (a commercial class vs «Comentario general»); `reliable` is
    `False` when the committed golden-set measurement for the current version does not
    back the class — the page then marks it «revísalo» instead of hiding it."""

    label: str
    commercial: bool
    reliable: bool


@dataclass(frozen=True)
class CommentVM:
    """Display-ready projection of one `qualify_api.sentiment.repository.AnalyzedComment`
    (QUA-92) — a synced comment (channel `comment`) plus its CURRENT-version sentiment,
    if any.

    `sentiment_label` is one of `"POS"`/`"NEG"`/`"NEU"`/`""` — `""` means no
    `comment_sentiment_results` row exists yet for the model version this deployment
    runs today, pre-coerced here (never a raw `None` reaching the client) so
    `ui.sentiment_badge` can match on the four states directly. The page renders `""`
    as «Sin revisar» — it must NEVER be shown as NEU (QUA-92's explicit requirement).
    `score_display` is pre-formatted (`"0.87"`) and empty exactly when
    `sentiment_label` is empty — same "no raw nullable reaching a `str` field"
    convention every other VM in this module follows.
    """

    message_id: str
    text: str
    author_username: str
    posted_at: str  # PRE-FORMATTED server-side (never a raw datetime var)
    external_thread_id: str
    sentiment_label: str
    score_display: str
    # m-24789644 (B3): `False` = no intent signal under the current version yet (the
    # page says «Aún no sabemos si quiere comprar»). The chips are the signal's classes, highest
    # confidence first; empty exactly when `intent_analyzed` is `False`.
    intent_analyzed: bool = False
    intent_chips: list[IntentChipVM] = field(default_factory=list)
    # m-24842988: at least one chip is not backed by the measurement — the card shows
    # the «No estamos seguros…» line once, not once per chip.
    intent_unsure: bool = False


@dataclass(frozen=True)
class SyncSummaryVM:
    """Display-ready projection of `qualify_api.inbox.service.SyncSummary` — the result of
    one manual "Sincronizar comentarios" click (temporary, see `inbox_page.py`'s module
    docstring). Fields are plain counts/flags; nothing here can carry a token or comment
    text, so this needs no whitelist scrutiny beyond what `test_inbox_ui.py` already
    applies uniformly to every VM in this module.

    `truncated` (QUA-88): the budget ran out mid-sync — still a success (whatever synced
    is real), just a partial one. Never conflated with an error.

    `skipped_missing_media` (bug fix, 2026-09-01): external media ids Meta confirmed no
    longer exist — each one was auto-unmonitored server-side and skipped, never an
    abort of the whole sync. A non-empty tuple here still means SUCCESS (`InboxState.
    sync_comments` never sets `sync_error` for this — see that module's docstring);
    `inbox_page.py` folds it into the success toast, not the error callout.

    `deleted_comments` (QUA-101): individual comments soft-deleted this pass because a
    COMPLETE walk of their (still-existing) media no longer returned them — the sibling
    case to `skipped_missing_media` above, one level down (a comment, not the whole
    Reel). Also always SUCCESS, folded into the same toast.

    `expired_skipped`/`metadata_*` (QUA-149): media past their 14-day window (never
    synced, no Meta call) and the legacy-metadata reads of this pass. Counts only, for the
    `inbox.sync.done` log; not rendered.
    """

    media_checked: int
    new_comments: int
    truncated: bool = False
    skipped_missing_media: tuple[str, ...] = ()
    deleted_comments: int = 0
    expired_skipped: int = 0
    metadata_backfilled: int = 0
    metadata_failed: int = 0
    metadata_deferred: int = 0


@dataclass(frozen=True)
class ReelSummaryVM:
    """Display-ready projection of one `qualify_api.sentiment.repository.ReelSummary`
    (QUA-93) — one Reel's comment-sentiment roll-up, for the summary-card list. Replaces
    QUA-92's flat `CommentVM` list at the top level of `/inbox`; `CommentVM` itself is
    unchanged and now lives one level down, in the Reel detail view.

    `caption`/`permalink` (QUA-149) come first from the PERSISTED `monitored_media`
    metadata, so they survive the 14-day window; the live `CandidateMediaVM` (opción A,
    ZERO extra Meta calls) is only a fallback, e.g. for a legacy row not read yet.
    `thumbnail_url` comes only from that live list (Meta's CDN URLs expire, so it is not
    stored) — `""` once the Reel leaves it, and the page shows its generic icon. Same "no
    raw nullable reaching a `str` field" convention every VM in this module follows.

    `monitoring_state` (QUA-149) is what the badge shows — one of the `MONITORING_*`
    constants above, computed from `is_monitored` AND the persisted publication date by
    the shared rule, never from `is_monitored` alone: a monitored Reel past its window is
    `expired` (no longer synced). `pending` is a monitored legacy Reel whose date is not
    read yet — it IS still synced, so it reads as monitored, with a hint.

    `is_monitored` (QUA-94) still mirrors the raw `monitored_media.is_monitored` flag —
    a DECORATION, never a filter: this Reel is still listed and its historical
    comments/sentiment stay fully visible whatever its state.
    """

    thread_id: str
    external_thread_id: str
    last_message_at: str  # PRE-FORMATTED server-side (never a raw datetime var)
    total: int
    positive: int
    neutral: int
    negative: int
    not_analyzed: int
    thumbnail_url: str
    caption: str
    permalink: str
    is_monitored: bool
    monitoring_state: str = MONITORING_INACTIVE
    # m-24789644 (B2): "Reel", "Foto", "Video", "Carrusel", "Publicación" or "Historia"
    # (`media_format_label`); `""` when the type is unknown and the card shows none.
    format_label: str = ""


@dataclass(frozen=True)
class GlobalSentimentSummaryVM:
    """Display-ready projection of `qualify_api.sentiment.repository.
    GlobalSentimentSummary` (QUA-93) — the 5-number widget at the top of `/inbox`,
    across every Reel in the connection, never a per-comment list."""

    positive: int
    neutral: int
    negative: int
    not_analyzed: int
    total: int


@dataclass(frozen=True)
class ReelPageCursorVM:
    """Opaque cursor for the NEXT page of `reel_summaries` (QUA-93) — keyset, never
    `OFFSET`. `last_message_at` is an ISO-8601 string (Reflex state never holds a raw
    `datetime`, same convention every VM's `*_at` field already follows); the provider
    parses it back before calling the repository."""

    last_message_at: str
    thread_id: str


@dataclass(frozen=True)
class CommentPageCursorVM:
    """Opaque cursor for the NEXT page of `thread_comments` (QUA-93). `sort_key` is an
    ISO-8601 string standing in for `COALESCE(posted_at, NULL_POSTED_AT_SENTINEL)` — see
    `qualify_api.sentiment.repository`'s module docstring for why a comment's `posted_at`
    being `NULL` needs this explicit handling, not an assumption it never happens."""

    sort_key: str
    message_id: str


@dataclass(frozen=True)
class AnalysisSummaryVM:
    """Display-ready projection of one "Analizar sentimiento" click (QUA-92) — the
    result of `POST /api/sentiment/analyze`, QUA-21's existing mechanism reused as-is
    (never a second analysis engine). Fields mirror `qualify_api.sentiment.service.
    AnalysisSummary`/the route's `AnalyzeResponse` field-for-field.

    `comments_checked == 0` is the caller's signal to render "No hay comentarios
    pendientes de análisis" instead of a generic zero-count summary — see
    `inbox_state.py::InboxState.analyze_sentiment`.
    """

    comments_checked: int
    new_results: int
    skipped_empty: int


@dataclass(frozen=True)
class IntentAnalysisSummaryVM:
    """Display-ready projection of one "Analizar intención" click (m-24789644) —
    `qualify_api.intent.IntentAnalysisSummary` field-for-field. `unclassified` counts
    the comments the model gave no usable answer for; they stay pending for the next
    click, so the toast says so instead of hiding them."""

    comments_checked: int
    new_results: int
    skipped_empty: int
    unclassified: int
    # m-24789646 (B1): commercial queries this pass sent to Conversaciones.
    followups_opened: int = 0
