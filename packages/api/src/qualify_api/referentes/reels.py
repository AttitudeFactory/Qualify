"""«Ideas para tus reels» (ADR 42; «Descubrir reels» in the code): what the persistent
run and the screen share — whose reels a brand follows, how its reels are read and
transcribed, which ones the product check reads, and the card the screen shows.

- **Whose reels** (`brand_referentes`): every account the operator labelled *referente*
  — found by the search or added by hand — on a network the vendor reads (Instagram,
  TikTok), in the operator's influence order, without the hand-added ones the AI review
  said are another rubro. At most `MAX_REFERENTES`.
- **Their reels and what they say**: `reel_pages` bounds a walk, `transcribe_one` reads
  one transcript (Instagram's paid speech-to-text, TikTok's free subtitles).
- **What the check reads** (`_candidates`): each window's most viewed, plus every
  account's own top in the widest one.
- **What the screen says** (`reel_card`, `account_lifts`, `check_failure_reason`).

The ONLY door that pays is `reel_runs.run`, called by the `reels-worker` (ADR 42 R4/R8);
it stores everything it paid for in Postgres. Opening the screen only reads that
(`reel_runs.view`, R7 m-24854854): the in-process read, its 6-hour memory and its
remembered verdicts and transcripts that lived here were deleted with it — every deploy
wiped them and every cold open paid again.

**Where it lives** (ADR 42 R1, m-24854844): in `qualify_api`, so the worker can run it
without the Reflex app; the card's signed cover path is the app's (`CoverFn`).
`run`, `view` and `enqueue_run` are `reel_runs`', reachable from here too.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from qualify_api.claude_tools import MissingAPIKey, api_key_from_env
from qualify_api.referentes import reels_ai
from qualify_api.referentes.formatting import compact_count
from qualify_api.referentes.repository import PostgresReferentesRepository
from qualify_api.vendors import scrapecreators

logger = logging.getLogger(__name__)

WEEK_DAYS = 7
MONTH_DAYS = 30
QUARTER_DAYS = 90
_DAY = 24 * 3600

#: The windows a run of `days` fills (`reel_runs`): the weekly and the manual run stop at
#: the month, the operator's 90-day run adds the quarter.
WINDOW_DAYS = {"week": WEEK_DAYS, "month": MONTH_DAYS, "quarter": QUARTER_DAYS}
#: Accounts read per brand — a bound on credits (each costs one to `reel_pages(days)`).
MAX_REFERENTES = 12
#: The most viewed reels sent to the rubro check: everything a window could show, plus
#: room for the ones the check drops.
REVIEWED_PER_WINDOW = 32
#: …plus each account's own most viewed in the window, so filtering to one referente
#: (or one network) still finds its checked reels when none of them made the brand top.
PER_ACCOUNT_REVIEWED = 3
#: What a card keeps of a transcript, and of a caption.
TRANSCRIPT_CARD_CHARS = 1200
CAPTION_CARD_CHARS = 160
#: Reels per review call (≤ `reels_ai.REVIEW_BATCH`), calls run in parallel.
_REVIEW_BATCH = 20

NETWORK_LABELS = {"instagram": "Instagram", "tiktok": "TikTok"}

#: Why the product check did not run: the brand never ran its referentes search (nothing
#: says what it sells), or the model could not be reached (no key, no balance, the
#: service down) — then «inténtalo más tarde».
CHECK_NO_BRIEF = "no_brief"
CHECK_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Referente:
    network: str
    handle: str
    #: What the account is (`marca` / `creador` / `medio`) and why it was kept — from
    #: its own review, context for the reel check.
    kind: str = ""
    note: str = ""


# --------------------------------------------------------------------------------------
# 1. whose reels
# --------------------------------------------------------------------------------------


#: The referentes store when the caller hands none (the Reflex app hands its own,
#: `referentes_provider.REPOSITORY`, the same Postgres repository). Built on first use.
_repository: PostgresReferentesRepository | None = None


def default_repository() -> PostgresReferentesRepository:
    """The Postgres referentes store, all access through `tenant_session` (RLS)."""
    global _repository
    if _repository is None:
        _repository = PostgresReferentesRepository()
    return _repository


def brand_referentes(tenant_id: UUID, brand_id: UUID, *, repository: Any = None) -> list[Referente]:
    """The brand's referentes the vendor can read, most influential first, without the
    hand-added ones the review said are another rubro. At most `MAX_REFERENTES`."""
    repo = repository or default_repository()
    labels = [
        label
        for label in repo.labels(tenant_id=tenant_id, brand_id=brand_id)
        if label.label == "referente" and label.network in NETWORK_LABELS
    ]
    labels.sort(key=lambda lb: (lb.position is None, lb.position or 0, lb.labeled_at))
    accounts = repo.latest_accounts(
        tenant_id=tenant_id,
        brand_id=brand_id,
        identities=[(label.network, label.handle) for label in labels],
    )
    out: list[Referente] = []
    for label in labels:
        stored = accounts.get((label.network, label.handle))
        card = {str(k): str(v) for k, v in (stored.card if stored else {}).items()}
        if card.get("fits") == "no":
            continue
        out.append(
            Referente(
                network=label.network,
                handle=label.handle,
                kind=card.get("kind", ""),
                note=card.get("review", ""),
            )
        )
    return out[:MAX_REFERENTES]


#: The path a card shows a reel's cover from — `reel → path`, "" for none. The Reflex
#: app's signed cover route (`Qualify/avatar_proxy.reel_cover_path`).
CoverFn = Callable[[dict[str, Any]], str]


# --------------------------------------------------------------------------------------
# 2. their reels
# --------------------------------------------------------------------------------------

FetchFn = Callable[..., list[dict[str, Any]]]


def reel_pages(days: int) -> int:
    """Pages a walk over `days` may read per account: `REEL_MAX_PAGES` covers a month of
    a daily poster, so the 90 days get three times that."""
    return math.ceil(scrapecreators.REEL_MAX_PAGES * days / MONTH_DAYS)


# --------------------------------------------------------------------------------------
# 3. what they say
# --------------------------------------------------------------------------------------

TranscribeFn = Callable[[dict[str, Any], httpx.Client], str]


def _reel_key(reel: dict[str, Any]) -> str:
    return f"{reel['network']}:{reel['id']}"


def transcribe_one(reel: dict[str, Any], client: httpx.Client) -> str:
    """One reel's transcript: Instagram's paid speech-to-text, TikTok's free subtitles."""
    if reel["network"] == "instagram":
        return scrapecreators.fetch_instagram_transcript(str(reel["url"]), client=client)
    if reel["network"] == "tiktok" and reel.get("captionUrl"):
        return scrapecreators.fetch_tiktok_captions(str(reel["captionUrl"]), client=client)
    return ""


#: Instagram transcripts paid in one read, at most — a ceiling on credits per refresh
#: (TikTok's cost nothing and are always read).
MAX_PAID_TRANSCRIPTS = 40
#: Transcripts fetched at once (the vendor's route is synchronous and slow).
_TRANSCRIPT_WORKERS = 6


# --------------------------------------------------------------------------------------
# 4. only the rubro
# --------------------------------------------------------------------------------------

ReviewFn = Callable[..., tuple[list[reels_ai.ReelReview], Any]]

#: What the owner reads when the product check could not run, whatever the cause (UX
#: review of R4, m-24854854): plain Spanish and the next step — never a status code, a
#: question, an exception name or the name of a service. Why it failed is the log's
#: (`check_failure_cause`).
CHECK_FAILED_TEXT = "No pudimos revisar los videos ahora. Inténtalo de nuevo en unos minutos."


def check_failure_cause(exc: BaseException) -> str:
    """Why the product check could not run, for the LOG only (with the status code); the
    screen never shows it — `check_failure_reason` is what the owner reads."""
    status = getattr(exc, "status_code", None)
    text = str(exc).lower()
    name = type(exc).__name__
    if name == "APITimeoutError" or status in (408, 504):
        return "the model service timed out"
    if name == "APIConnectionError":
        return "could not connect to the model service"
    if status == 429:
        if "quota" in text or "cuota" in text:
            return "the model's usage quota is exhausted (429)"
        return "the model service is rate limiting (429)"
    if status in (401, 403):
        return f"the model service rejected the key ({status})"
    if status == 404:
        return "the configured model is no longer available (404)"
    if status == 400 and "credit balance" in text:
        return "the model account has no credit balance"
    if isinstance(status, int) and status >= 500:
        busy = ("high demand", "overloaded", "unavailable")
        if any(word in text for word in busy):
            return f"the model is overloaded or down ({status})"
        return f"the model service failed ({status})"
    if isinstance(status, int):
        return f"the model service refused the request ({status})"
    if isinstance(exc, reels_ai.ReelReviewError):
        return "the model answered without the expected format"
    return f"unexpected error ({name})"


def check_failure_reason(exc: BaseException | None = None) -> str:
    """What the screen says when the product check could not run: ONE plain sentence for
    every cause (`CHECK_FAILED_TEXT`, UX review of R4). It used to name the cause with
    its status code («(429)») or ask «¿está encendido?»; the cause now goes only to the
    log (`check_failure_cause`, and the `exc_info` every caller logs)."""
    del exc  # the owner gets the same sentence whatever failed
    return CHECK_FAILED_TEXT


def _views_rank(reel: dict[str, Any]) -> tuple[int, int]:
    return (reel.get("views") or 0, reel.get("likes") or 0)


def _top(
    reels: Sequence[dict[str, Any]], since: float, count: int | None = None
) -> list[dict[str, Any]]:
    inside = [r for r in reels if r["takenAt"] >= since]
    return sorted(inside, key=_views_rank, reverse=True)[:count]


def _candidates(
    reels: Sequence[dict[str, Any]], since: float, *, per_account: bool
) -> list[dict[str, Any]]:
    """What the rubro check reads of one window: its `REVIEWED_PER_WINDOW` most viewed,
    plus — with `per_account`, only for the read's widest window, so a read pays for them
    once and not per tab — the `PER_ACCOUNT_REVIEWED` most viewed of every account in it
    (the ones already in the top count among them, so a big account adds nothing)."""
    ranked = _top(reels, since)
    picked = ranked[:REVIEWED_PER_WINDOW]
    if not per_account:
        return picked
    per_account_seen: dict[tuple[str, str], int] = {}
    for reel in ranked:
        account = (reel["network"], reel["handle"])
        per_account_seen[account] = per_account_seen.get(account, 0) + 1
        if per_account_seen[account] <= PER_ACCOUNT_REVIEWED:
            picked.append(reel)
    return picked


# --------------------------------------------------------------------------------------
# 5. the cards
# --------------------------------------------------------------------------------------


compact = compact_count


def age_label(taken_at: float, now: float) -> str:
    days = int(max(now - taken_at, 0) // _DAY)
    if days == 0:
        return "hoy"
    if days == 1:
        return "ayer"
    return f"hace {days} días"


def engagement_label(reel: dict[str, Any]) -> str:
    """Interactions over views, as a percentage — "" when views are unknown. Shares and
    saves count where the network gives them (TikTok); Instagram exposes neither."""
    views = reel.get("views") or 0
    if not views:
        return ""
    acts = sum(reel.get(k) or 0 for k in ("likes", "comments", "shares", "saves"))
    return f"{acts / views * 100:.1f}%".replace(".0%", "%")


def daily_views_label(reel: dict[str, Any], now: float) -> str:
    """Views per day since it was published — a 25-day-old reel always has more views
    than yesterday's, so this is how two of them compare. "" when views are unknown."""
    views = reel.get("views")
    if not views:
        return ""
    days = max((now - reel["takenAt"]) / _DAY, 1.0)
    return f"{compact(round(views / days))}/día"


def cover_path(reel: dict[str, Any], cover: CoverFn | None = None) -> str:
    """The path the card shows the cover from: `cover(reel)` — the Reflex app's signed
    route — or "" when the reel has none or no `cover` was handed in."""
    if not reel.get("cover") or cover is None:
        return ""
    return cover(reel)


def public_url(network: str, handle: str, reel_id: str) -> str:
    """The reel's own page on its network — what a stored reel (`public_reels`, which
    keeps no URL) opens with «Abrir en Instagram/TikTok»."""
    reel = quote(str(reel_id), safe="")
    if network == "instagram":
        return f"https://www.instagram.com/reel/{reel}/"
    if network == "tiktok":
        return f"https://www.tiktok.com/@{quote(handle.lstrip('@'), safe='')}/video/{reel}"
    return ""


def embed_url(reel: dict[str, Any]) -> str:
    """The network's own player for the reel, to show it inside Qualify in an iframe —
    the video is streamed by Instagram/TikTok, never downloaded or stored by us.
    Verified 2026-10-15 from `localhost:3000`: Instagram's `/reel/<code>/embed/` answers
    a browser iframe without `X-Frame-Options` (it only sends `DENY` to a request that
    is not an iframe), and TikTok's `/player/v1/<id>` sends no frame restriction at all."""
    reel_id = quote(str(reel.get("id") or ""), safe="")
    if not reel_id:
        return ""
    if reel["network"] == "instagram":
        return f"https://www.instagram.com/reel/{reel_id}/embed/"
    if reel["network"] == "tiktok":
        return f"https://www.tiktok.com/player/v1/{reel_id}?music_info=1&description=1"
    return ""


#: A reel is shown as an outlier of its account from this many times its typical views.
LIFT_HIGHLIGHT = 2.0
#: An account needs at least this many reels with views for "its typical" to mean much.
LIFT_MIN_SAMPLE = 3


def account_lifts(reels: Sequence[dict[str, Any]]) -> dict[str, float]:
    """reel key → its views over the MEDIAN views of its own account's reels in the
    month read (§ request 2026-10-15, card «C»: «x3.2 sobre su media»). The median, not
    the mean: one viral reel must not make every other reel of the account look weak.
    Free — it reads the reels already fetched. A reel without views, or of an account
    with fewer than `LIFT_MIN_SAMPLE` measured reels, gets no lift."""
    by_account: dict[tuple[str, str], list[int]] = {}
    for reel in reels:
        if reel.get("views"):
            by_account.setdefault((reel["network"], reel["handle"]), []).append(reel["views"])
    medians: dict[tuple[str, str], float] = {}
    for account, views in by_account.items():
        if len(views) >= LIFT_MIN_SAMPLE:
            ordered = sorted(views)
            mid = len(ordered) // 2
            medians[account] = (
                ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
            )
    return {
        _reel_key(r): r["views"] / medians[(r["network"], r["handle"])]
        for r in reels
        if r.get("views") and medians.get((r["network"], r["handle"]))
    }


def lift_label(lift: float | None) -> tuple[str, str]:
    """`(label, tone)` of a lift: «x3.2 sobre su media» (ok from `LIFT_HIGHLIGHT`,
    neutral above 1), "" at or under the account's typical reel."""
    if lift is None or lift < 1.1:
        return "", ""
    figure = f"x{lift:.1f}".replace(".0", "") if lift < 10 else f"x{round(lift)}"
    return f"{figure} sobre su media", ("ok" if lift >= LIFT_HIGHLIGHT else "neutral")


def reel_card(
    reel: dict[str, Any],
    rank: int,
    now: float,
    reason: str = "",
    *,
    lift: float | None = None,
    review: reels_ai.ReelReview | None = None,
    cover: CoverFn | None = None,
) -> dict[str, str]:
    seconds = reel.get("seconds")
    lift_text, lift_tone = lift_label(lift)
    return {
        "key": _reel_key(reel),
        "rank": str(rank),
        "network": reel["network"],
        "network_label": NETWORK_LABELS.get(reel["network"], reel["network"]),
        "handle": f"@{reel['handle']}",
        "url": str(reel.get("url") or ""),
        "embed": embed_url(reel),
        "caption": _clip_text(str(reel.get("caption") or ""), CAPTION_CARD_CHARS),
        "cover": cover_path(reel, cover),
        "views": compact(reel.get("views")),
        "likes": compact(reel.get("likes")),
        "comments": compact(reel.get("comments")),
        "engagement": engagement_label(reel),
        "per_day": daily_views_label(reel, now),
        "saves": compact(reel.get("saves")) if reel.get("saves") is not None else "",
        "age": age_label(reel["takenAt"], now),
        "seconds": f"{seconds} s" if seconds else "",
        "sound": str(reel.get("sound") or ""),
        "transcript": _clip_text(str(reel.get("transcript") or ""), TRANSCRIPT_CARD_CHARS),
        # "said" once known, "none" for a video without speech, "" never transcribed
        "transcript_state": "said" if reel.get("transcript") else "",
        # the reel's id on its network (a replica names its source with it)
        "id": str(reel["id"]),
        "reason": reason or (review.reason if review else ""),
        # card «C» (§ 2026-10-15): the reel's own MP4 (streamed, just the video), how it
        # does against its account, and what it is
        "video": str(reel.get("video") or ""),
        "lift": lift_text,
        "lift_tone": lift_tone,
        "format": review.format if review and review.format != "otro" else "",
        "hook": review.hook if review and review.hook != "otro" else "",
        "affinity": review.affinity if review else "",
    }


def _clip_text(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


# --------------------------------------------------------------------------------------
# the key the run's check calls with, and the run's own doors
# --------------------------------------------------------------------------------------


def _env_key() -> str | None:
    """The Anthropic key the check calls with, or None when there is none."""
    try:
        return api_key_from_env()
    except MissingAPIKey:
        return None


#: The persistent run of ADR 42 R4 (m-24854848) — `run()`, the only door that pays,
#: `view()`, that only reads, and `enqueue_run()` — lives in `reel_runs` (it builds on
#: this module) and is reachable from here too, as the ADR names it.
_RUN_DOORS = frozenset({"enqueue_run", "run", "view"})


def __getattr__(name: str) -> Any:
    if name in _RUN_DOORS:
        from qualify_api.referentes import reel_runs  # lazy: reel_runs imports this module

        return getattr(reel_runs, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CHECK_FAILED_TEXT",
    "CHECK_NO_BRIEF",
    "CHECK_UNAVAILABLE",
    "MAX_PAID_TRANSCRIPTS",
    "MAX_REFERENTES",
    "MONTH_DAYS",
    "NETWORK_LABELS",
    "QUARTER_DAYS",
    "WEEK_DAYS",
    "WINDOW_DAYS",
    "CoverFn",
    "FetchFn",
    "Referente",
    "ReviewFn",
    "TranscribeFn",
    "account_lifts",
    "age_label",
    "brand_referentes",
    "check_failure_cause",
    "check_failure_reason",
    "default_repository",
    "embed_url",
    "lift_label",
    "public_url",
    "reel_card",
    "reel_pages",
    "transcribe_one",
]
