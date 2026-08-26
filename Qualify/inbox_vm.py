"""View-models for the inbox content screen — Instagram Reels from the last 2 weeks,
with the monitoring toggle (Fase 1 Parte 4-B, B2 UI slice).

Same security boundary as `publishing_vm.py`/`connections_vm.py`: every Reflex var is
serialized to the client. `InboxService`/`qualify_api.inbox.composition` never see or
return a token, so nothing credential-bearing can reach this dataclass in the first
place — the whitelist test (`test_inbox_ui.py`) pins that this stays true as the module
grows.

Kept free of Reflex and network imports so the whitelist can be asserted by a plain unit
test, same convention as `publishing_vm.py`/`connections_vm.py`.
"""

from __future__ import annotations

from dataclasses import dataclass


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


@dataclass(frozen=True)
class CommentVM:
    """Display-ready projection of one `qualify_api.sentiment.repository.AnalyzedComment`
    (QUA-92) — a synced comment (channel `comment`) plus its CURRENT-version sentiment,
    if any.

    `sentiment_label` is one of `"POS"`/`"NEG"`/`"NEU"`/`""` — `""` means no
    `comment_sentiment_results` row exists yet for the model version this deployment
    runs today, pre-coerced here (never a raw `None` reaching the client) so
    `ui.sentiment_badge` can match on the four states directly. The page renders `""`
    as "Sin analizar" — it must NEVER be shown as NEU (QUA-92's explicit requirement).
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


@dataclass(frozen=True)
class SyncSummaryVM:
    """Display-ready projection of `qualify_api.inbox.service.SyncSummary` — the result of
    one manual "Sincronizar comentarios" click (temporary, see `inbox_page.py`'s module
    docstring). Fields are plain counts/flags; nothing here can carry a token or comment
    text, so this needs no whitelist scrutiny beyond what `test_inbox_ui.py` already
    applies uniformly to every VM in this module.

    `truncated` (QUA-88): the budget ran out mid-sync — still a success (whatever synced
    is real), just a partial one. Never conflated with an error.
    """

    media_checked: int
    new_comments: int
    truncated: bool = False


@dataclass(frozen=True)
class ReelSummaryVM:
    """Display-ready projection of one `qualify_api.sentiment.repository.ReelSummary`
    (QUA-93) — one Reel's comment-sentiment roll-up, for the summary-card list. Replaces
    QUA-92's flat `CommentVM` list at the top level of `/inbox`; `CommentVM` itself is
    unchanged and now lives one level down, in the Reel detail view.

    `thumbnail_url`/`caption`/`permalink` are opción A's one deliberate widening: cross-
    referenced from `CandidateMediaVM` (already loaded for the Reels-monitoring list, ZERO
    extra Meta calls) when this Reel is still inside that list's 2-week window — `""` for
    a Reel monitored longer ago, same "no raw nullable reaching a `str` field" convention
    every VM in this module follows.

    `is_monitored` (QUA-94) mirrors `qualify_api.sentiment.repository.ReelSummary.
    is_monitored` verbatim — a DECORATION, never a filter: this Reel is still listed and
    its historical comments/sentiment are still fully visible when `False`, only the
    badge in `inbox_page.py` changes. `False` means "not currently monitored", which
    covers both "explicitly turned off" and "no `monitored_media` row at all".
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
