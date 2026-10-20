"""«Descubrir reels» (§ request 2026-10-15): the most viewed reels of a brand's
referentes, this week and this month, and only the ones of the brand's own PRODUCT
(§ founder 2026-10-15 night: «si es hamburguesas que solo traiga hamburguesas»).

The pipeline, all blocking (the state runs it in a thread):

1. **Whose reels** (`brand_referentes`): every account the operator labelled
   *referente* — found by the search or added by hand — on a network the vendor reads
   (Instagram, TikTok), in the operator's influence order. A hand-added account the AI
   review said does not fit the brand (`card["fits"] == "no"`, `referentes_review`) is
   left out: the operator kept it, but its reels would be another rubro's.
2. **Their reels** (`scrapecreators_client.fetch_reels`): ONE walk per account over the
   last `MONTH_DAYS` — the week is the month's newest days, so it costs nothing more.
3. **What they say** (`transcribe`, § 2026-10-15): the candidates of step 4 — the most
   viewed of each window, the only ones that can reach the screen — are transcribed
   BEFORE the rubro check, because judged by its caption alone a reel's rubro is often
   wrong (the on-demand-only version of the same day made the filter worse). TikTok
   from the video's own subtitles, free; Instagram through the vendor's speech-to-text,
   1 credit (0 from its cache), up to `MAX_PAID_TRANSCRIPTS` per read, most viewed
   first. A transcript never changes: remembered per reel for the life of the process,
   never paid twice. The card's «Ver transcripción» (`transcript_for`) shares that
   memory.
4. **Only the product** (`qualify_api.referentes.reels_ai.review_reels`): an account
   that fits says nothing about each of its videos (a food creator also posts make-up),
   so the most viewed reels are checked one by one against the brand — above all by
   what is SAID in them — with the same brand brief the referentes review reads, and
   only `afinidad: producto` or `categoria` (the same kind of offer, § 2026-10-20) is
   kept. ONLY checked reels are shown (§ founder
   2026-10-16): no brief, no key, a failed review or a reel the model skipped → not on
   screen, and the result says why (`check`), so the view can say «inténtalo más tarde».
5. **Ranked** by views (likes break ties; Instagram hides views on some posts), cut to
   `SHOWN_PER_WINDOW` per window.

The result is remembered in memory per brand for `CACHE_TTL_SECONDS` — every read of
the vendor costs credits and every review a model call — and «Actualizar» skips it. A
read whose check could not reach the model is NOT remembered.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from qualify_api.claude_tools import MissingAPIKey, ModelConfig, api_key_from_env
from qualify_api.referentes import ai as review_ai
from qualify_api.referentes import reels_ai

from . import creator_discovery, referentes_provider, referentes_review, scrapecreators_client
from .avatar_proxy import reel_cover_path

logger = logging.getLogger(__name__)

WEEK_DAYS = 7
MONTH_DAYS = 30
_DAY = 24 * 3600

#: Accounts read per brand — a bound on credits (each costs one to `REEL_MAX_PAGES`).
MAX_REFERENTES = 12
#: Reels each window shows.
SHOWN_PER_WINDOW = 24
#: The most viewed reels sent to the rubro check: everything a window could show, plus
#: room for the ones the check drops.
REVIEWED_PER_WINDOW = 32
#: What a card keeps of a transcript, and of a caption.
TRANSCRIPT_CARD_CHARS = 1200
CAPTION_CARD_CHARS = 160
#: Accounts read at once.
_FETCH_WORKERS = 6
#: Reels per review call (≤ `reels_ai.REVIEW_BATCH`), calls run in parallel.
_REVIEW_BATCH = 20

CACHE_TTL_SECONDS = 6 * 3600

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


@dataclass
class DiscoveredReels:
    """What «Descubrir reels» shows: the two windows' cards, newest read first."""

    week: list[dict[str, str]] = field(default_factory=list)
    month: list[dict[str, str]] = field(default_factory=list)
    fetched_at: float = 0.0
    #: Accounts read, reels found in the month, and the handles that could not be read
    #: (private, gone, vendor error).
    referentes: int = 0
    read: int = 0
    failed: list[str] = field(default_factory=list)
    #: Reels the check judged and left out, whether it ran, and why not when it did not
    #: (`CHECK_*`): without the check NOTHING is shown.
    dropped: int = 0
    reviewed: bool = False
    check: str = ""
    #: Why the check could not run, in a few words for the screen (`check_failure_reason`)
    #: — "" when it ran or when `check` already says it all.
    check_detail: str = ""
    #: Transcripts fetched for the rubro check in this read, and how many of them cost
    #: a credit (Instagram).
    transcribed: int = 0
    paid_transcripts: int = 0


# --------------------------------------------------------------------------------------
# 1. whose reels
# --------------------------------------------------------------------------------------


def brand_referentes(tenant_id: UUID, brand_id: UUID, *, repository: Any = None) -> list[Referente]:
    """The brand's referentes the vendor can read, most influential first, without the
    hand-added ones the review said are another rubro. At most `MAX_REFERENTES`."""
    repo = repository or referentes_provider.REPOSITORY
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


#: Hashtags the brief carries: the brand's own, the operator's pills and the catalog's,
#: in that order — all of them, not the search's three (§ request 2026-10-15).
BRIEF_HASHTAGS = 12
KitLoader = Callable[[UUID, UUID], Any]
ProductsLoader = Callable[[UUID, UUID], Sequence[dict[str, str]]]


def _kit_form(tenant_id: UUID, brand_id: UUID) -> Any:
    from .creative_provider import load_kit_form  # the Brand Kit's door; lazy: heavy

    return load_kit_form(tenant_id, brand_id)


def _products(tenant_id: UUID, brand_id: UUID) -> Sequence[dict[str, str]]:
    from .creative_provider import catalog_products

    return catalog_products(tenant_id, brand_id)


def brand_brief(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    repository: Any = None,
    kit_form: KitLoader | None = None,
    products: ProductsLoader | None = None,
) -> review_ai.BrandBrief | None:
    """What the rubro check reads about the brand (§ request 2026-10-15: «mejorar el
    filtrado con el Brand Kit, los hashtags y todo ello»): the seed the brand's search
    last ran on (rubro in the operator's words, niche, city, EVERY hashtag) plus the
    Brand Kit (positioning, audience, examples of what it publishes) and the catalog
    (product names). None when the brand never ran the search — then nothing says what
    its rubro is. A kit or catalog that cannot be read only thins the brief."""
    repo = repository or referentes_provider.REPOSITORY
    phases = {
        phase.phase_key: phase
        for phase in repo.current_phases(tenant_id=tenant_id, brand_id=brand_id)
    }
    seed = None
    for key in creator_discovery.PHASES:
        phase = phases.get(key)
        if phase is not None and phase.seed:
            candidate = referentes_provider.rebuild_seed(phase.seed)
            if (
                candidate.terms
                or candidate.niches
                or candidate.hashtags
                or candidate.catalog_hashtags
            ):
                seed = candidate
                break
    if seed is None:
        return None
    # resolved here, not in the signature, so a test can swap the module's doors
    kit_form = kit_form or _kit_form
    products = products or _products
    positioning = audience = ""
    publishes: tuple[str, ...] = ()
    try:
        kit = kit_form(tenant_id, brand_id)
    except Exception as exc:  # noqa: BLE001 — a kit that cannot be read only thins the brief
        logger.warning("brand kit unreadable for the reel brief: %s", type(exc).__name__)
        kit = None
    if kit is not None:
        positioning = str(getattr(kit, "positioning", "") or "")
        audience = str(getattr(kit, "audience", "") or "")
        publishes = tuple(
            line.strip()
            for line in str(getattr(kit, "do_examples", "") or "").splitlines()
            if line.strip()
        )
    try:
        names = tuple(str(p.get("name") or "").strip() for p in products(tenant_id, brand_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog unreadable for the reel brief: %s", type(exc).__name__)
        names = ()
    base = referentes_review.brand_brief(seed, positioning=positioning, audience=audience)
    hashtags = tuple(
        dict.fromkeys(
            t for t in (*seed.hashtags, *seed.chosen_hashtags, *seed.catalog_hashtags) if t
        )
    )[:BRIEF_HASHTAGS]
    return replace(
        base,
        hashtags=hashtags or base.hashtags,
        products=tuple(n for n in names if n),
        publishes=publishes,
    )


# --------------------------------------------------------------------------------------
# 2. their reels
# --------------------------------------------------------------------------------------

FetchFn = Callable[..., list[dict[str, Any]]]


def read_reels(
    referentes: Sequence[Referente],
    *,
    since: float,
    fetch: FetchFn = scrapecreators_client.fetch_reels,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Every reel of `referentes` since `since`, and the handles that could not be read.
    Each reel carries its account's `kind`/`note` for the rubro check."""
    if not referentes:
        return [], []

    def one(ref: Referente) -> tuple[Referente, list[dict[str, Any]] | None]:
        try:
            return ref, fetch(ref.network, ref.handle, since=since, client=client)
        except (scrapecreators_client.ScrapeCreatorsError, ValueError) as exc:
            logger.warning("reels of %s/%s unreadable: %s", ref.network, ref.handle, exc)
            return ref, None

    reels: list[dict[str, Any]] = []
    failed: list[str] = []
    with httpx.Client(timeout=20.0) as client:
        with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
            for ref, found in pool.map(one, referentes):
                if found is None:
                    failed.append(f"@{ref.handle}")
                    continue
                for reel in found:
                    reels.append({**reel, "accountKind": ref.kind, "accountNote": ref.note})
    return reels, failed


# --------------------------------------------------------------------------------------
# 3. what they say
# --------------------------------------------------------------------------------------

TranscribeFn = Callable[[dict[str, Any], httpx.Client], str]

#: reel key → its transcript ("" = no speech). A transcript never changes: kept for the
#: life of the process, so «Actualizar» never pays for one twice.
_transcripts: dict[str, str] = {}
_transcripts_guard = threading.Lock()


def _reel_key(reel: dict[str, Any]) -> str:
    return f"{reel['network']}:{reel['id']}"


def transcribe_one(reel: dict[str, Any], client: httpx.Client) -> str:
    """One reel's transcript: Instagram's paid speech-to-text, TikTok's free subtitles."""
    if reel["network"] == "instagram":
        return scrapecreators_client.fetch_instagram_transcript(str(reel["url"]), client=client)
    if reel["network"] == "tiktok" and reel.get("captionUrl"):
        return scrapecreators_client.fetch_tiktok_captions(str(reel["captionUrl"]), client=client)
    return ""


#: Instagram transcripts paid in one read, at most — a ceiling on credits per refresh
#: (TikTok's cost nothing and are always read).
MAX_PAID_TRANSCRIPTS = 40
#: Transcripts fetched at once (the vendor's route is synchronous and slow).
_TRANSCRIPT_WORKERS = 6


def transcribe(
    reels: Sequence[dict[str, Any]], *, fetch: TranscribeFn = transcribe_one
) -> tuple[int, int]:
    """Fill `reel["transcript"]` on `reels` for the rubro check: from memory when the
    reel was transcribed before, else fetched — every TikTok one (free, its own
    subtitles), and up to `MAX_PAID_TRANSCRIPTS` Instagram ones per call (`reels` comes
    most viewed first, so the ceiling cuts the least likely to be shown). A reel that
    cannot be transcribed is left with "" and NOT remembered, so a later read retries.
    Returns `(fetched, paid)`: transcripts actually read, and how many of them were
    Instagram ones (a failed call is in neither)."""
    todo: list[dict[str, Any]] = []
    instagram = 0
    for reel in reels:
        with _transcripts_guard:
            known = _transcripts.get(_reel_key(reel))
        if known is not None:
            reel["transcript"] = known
            continue
        reel["transcript"] = ""
        if reel["network"] == "instagram":
            if instagram >= MAX_PAID_TRANSCRIPTS:
                continue
            instagram += 1
        elif not reel.get("captionUrl"):
            continue  # a TikTok without subtitles has nothing to fetch
        todo.append(reel)
    if not todo:
        return 0, 0

    def one(reel: dict[str, Any]) -> bool:
        try:
            text = " ".join(fetch(reel, client).split())
        except (scrapecreators_client.ScrapeCreatorsError, httpx.HTTPError) as exc:
            logger.info("transcript of %s unavailable: %s", _reel_key(reel), exc)
            return False
        reel["transcript"] = text
        with _transcripts_guard:
            _transcripts[_reel_key(reel)] = text
        return True

    with httpx.Client(timeout=scrapecreators_client.TRANSCRIPT_TIMEOUT_SECONDS) as client:
        with ThreadPoolExecutor(max_workers=_TRANSCRIPT_WORKERS) as pool:
            done = list(pool.map(one, todo))
    fetched = sum(done)
    paid = sum(ok for ok, r in zip(done, todo, strict=True) if r["network"] == "instagram")
    logger.info(
        "reel transcripts: %d of %d fetched, %d of them Instagram (paid)",
        fetched,
        len(todo),
        paid,
    )
    return fetched, paid


def transcript_for(reel: dict[str, Any], *, fetch: TranscribeFn = transcribe_one) -> str:
    """What is said in ONE reel, on demand (the card's «Ver transcripción», and «Replicar»
    when it lands): from memory, else fetched — Instagram 1 credit (0 from the vendor's
    cache), TikTok free — and remembered for the life of the process. `reel` needs
    `network`, `id`, `url` and, for TikTok, `captionUrl`. "" = the video has no speech.
    Raises `ScrapeCreatorsError` / `httpx.HTTPError` when it cannot be read (and then
    remembers nothing, so asking again retries)."""
    key = _reel_key(reel)
    with _transcripts_guard:
        known = _transcripts.get(key)
    if known is not None:
        return known
    with httpx.Client(timeout=scrapecreators_client.TRANSCRIPT_TIMEOUT_SECONDS) as client:
        text = " ".join(fetch(reel, client).split())
    with _transcripts_guard:
        _transcripts[key] = text
    logger.info("reel transcript fetched on demand: %s (%d chars)", key, len(text))
    return text


# --------------------------------------------------------------------------------------
# 4. only the rubro
# --------------------------------------------------------------------------------------

ReviewFn = Callable[..., tuple[list[reels_ai.ReelReview], Any]]


def check_failure_reason(exc: BaseException) -> str:
    """Why the product check could not run, in a few words for the operator (the log
    keeps the whole error). Spanish: it is shown on screen."""
    status = getattr(exc, "status_code", None)
    text = str(exc).lower()
    name = type(exc).__name__
    if name == "APITimeoutError" or status in (408, 504):
        return "el servicio de IA tardó demasiado en responder"
    if name == "APIConnectionError":
        return "no pudimos conectar con el servicio de IA (¿está encendido?)"
    if status == 429:
        if "quota" in text or "cuota" in text:
            return "el modelo de IA agotó su cuota de uso (429)"
        return "el servicio de IA recibe demasiadas peticiones (429)"
    if status in (401, 403):
        return f"el servicio de IA rechazó la clave ({status})"
    if status == 404:
        return "el modelo de IA configurado ya no está disponible (404)"
    if status == 400 and "credit balance" in text:
        return "la cuenta del servicio de IA no tiene saldo"
    if isinstance(status, int) and status >= 500:
        busy = ("high demand", "overloaded", "unavailable")
        if any(word in text for word in busy):
            return f"el modelo de IA está saturado o caído ({status})"
        return f"el servicio de IA falló ({status})"
    if isinstance(status, int):
        return f"el servicio de IA rechazó la petición ({status})"
    if isinstance(exc, reels_ai.ReelReviewError):
        return "el modelo de IA respondió sin el formato esperado"
    return f"error inesperado ({name})"


class ReelCheckUnavailable(reels_ai.ReelReviewError):
    """Every batch of the product check failed; `reason` says why, for the screen."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"every reel rubro check failed: {reason}")
        self.reason = reason


def _views_rank(reel: dict[str, Any]) -> tuple[int, int]:
    return (reel.get("views") or 0, reel.get("likes") or 0)


def _top(reels: Sequence[dict[str, Any]], since: float, count: int) -> list[dict[str, Any]]:
    inside = [r for r in reels if r["takenAt"] >= since]
    return sorted(inside, key=_views_rank, reverse=True)[:count]


def check_rubro(
    brief: review_ai.BrandBrief,
    reels: Sequence[dict[str, Any]],
    *,
    api_key: str,
    review: ReviewFn = reels_ai.review_reels,
    config: ModelConfig | None = None,
) -> dict[str, reels_ai.ReelReview]:
    """The rubro check of `reels`, as parallel calls of `_REVIEW_BATCH` to Anthropic:
    reel key → verdict. Raises `ReelCheckUnavailable` (with the last failure's reason)
    when every call fails; a batch that fails alone is left unreviewed. § 2026-10-19:
    Anthropic only — the OmniRoute gateway path was reverted."""
    model = config or ModelConfig(reels_ai.REVIEW_MODEL, reels_ai.REVIEW_EFFORT)
    items = [
        reels_ai.ReelToReview(
            id=_reel_key(r),
            network=r["network"],
            handle=r["handle"],
            caption=str(r.get("caption") or ""),
            sound=str(r.get("sound") or ""),
            transcript=str(r.get("transcript") or ""),
            account_kind=str(r.get("accountKind") or ""),
            account_note=str(r.get("accountNote") or ""),
        )
        for r in reels
    ]
    batches = [items[i : i + _REVIEW_BATCH] for i in range(0, len(items), _REVIEW_BATCH)]
    failures: list[BaseException] = []

    def one(batch: list[reels_ai.ReelToReview]) -> list[reels_ai.ReelReview] | None:
        try:
            answers, stats = review(brief, batch, api_key=api_key, config=model)
        except Exception as exc:  # noqa: BLE001 — a model call; the batch stays unchecked
            failures.append(exc)
            logger.warning(
                "reel rubro check failed for %d reels: %s",
                len(batch),
                check_failure_reason(exc),
                exc_info=exc,
            )
            return None
        logger.info(
            "reel rubro check: %d reels, %d answered, $%.4f",
            len(batch),
            len(answers),
            getattr(stats, "cost_usd", 0.0) or 0.0,
        )
        return answers

    if not batches:
        return {}
    with ThreadPoolExecutor(max_workers=min(len(batches), 4)) as pool:
        answered = list(pool.map(one, batches))
    if all(a is None for a in answered):
        last = failures[-1] if failures else None
        reason = check_failure_reason(last) if last else "sin respuesta del modelo de IA"
        raise ReelCheckUnavailable(reason) from last
    return {r.id: r for answers in answered if answers for r in answers}


# --------------------------------------------------------------------------------------
# 4. the cards
# --------------------------------------------------------------------------------------


compact = creator_discovery.compact_count


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


def cover_path(reel: dict[str, Any]) -> str:
    """The backend path the card shows the cover from (`avatar_proxy.reel_cover`),
    signed: the route serves only the covers this module handed out."""
    if not reel.get("cover"):
        return ""
    return reel_cover_path(reel["network"], str(reel["id"]), str(reel["cover"]))


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
        "cover": cover_path(reel),
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
        # "said" once known, "none" for a video without speech, "" not asked yet
        "transcript_state": "said" if reel.get("transcript") else "",
        # what `transcript_for_card` needs to fetch it on demand
        "id": str(reel["id"]),
        "caption_url": str(reel.get("captionUrl") or ""),
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


def transcript_for_card(card: dict[str, str], *, fetch: TranscribeFn = transcribe_one) -> str:
    """`transcript_for` from a card (`reel_card`), cut to what a card shows."""
    reel = {
        "network": card.get("network", ""),
        "id": card.get("id", ""),
        "url": card.get("url", ""),
        "captionUrl": card.get("caption_url", ""),
    }
    if reel["network"] not in NETWORK_LABELS or not reel["id"]:
        raise ValueError("not a reel card")
    return _clip_text(transcript_for(reel, fetch=fetch), TRANSCRIPT_CARD_CHARS)


def _clip_text(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


# --------------------------------------------------------------------------------------
# the whole pipeline, and its memory
# --------------------------------------------------------------------------------------


def discover(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    now: float | None = None,
    repository: Any = None,
    fetch: FetchFn = scrapecreators_client.fetch_reels,
    review: ReviewFn = reels_ai.review_reels,
    api_key: str | None = None,
    kit_form: KitLoader | None = None,
    products: ProductsLoader | None = None,
    transcribe_fetch: TranscribeFn = transcribe_one,
) -> DiscoveredReels:
    """Steps 1-5 for one brand (see the module docstring)."""
    moment = now if now is not None else time.time()
    referentes = brand_referentes(tenant_id, brand_id, repository=repository)
    result = DiscoveredReels(fetched_at=moment, referentes=len(referentes))
    reels, result.failed = read_reels(referentes, since=moment - MONTH_DAYS * _DAY, fetch=fetch)
    result.read = len(reels)
    week_since = moment - WEEK_DAYS * _DAY
    candidates = {
        _reel_key(r): r
        for r in (
            *_top(reels, week_since, REVIEWED_PER_WINDOW),
            *_top(reels, moment - MONTH_DAYS * _DAY, REVIEWED_PER_WINDOW),
        )
    }
    # what the candidates SAY, before the rubro check (§ 2026-10-15, restored the same
    # day: without it the check judges a new reel by its caption alone and the filter
    # got worse) — TikTok's subtitles are free, Instagram's are paid up to a ceiling,
    # most viewed first; a transcript is remembered, so «Actualizar» never pays twice
    # Only when the check will run: without a brief or a key nothing reads them, and an
    # Instagram transcript costs a credit.
    brief = brand_brief(
        tenant_id, brand_id, repository=repository, kit_form=kit_form, products=products
    )
    key = api_key or _env_key()
    if brief is None:
        result.check = CHECK_NO_BRIEF
    elif key is None:
        result.check = CHECK_UNAVAILABLE
        result.check_detail = "no hay una clave configurada para el servicio de IA"
        logger.warning("reel product check unavailable: no API key configured")
    verdicts: dict[str, reels_ai.ReelReview] = {}
    if brief is not None and key is not None and candidates:
        ranked = sorted(candidates.values(), key=_views_rank, reverse=True)
        result.transcribed, result.paid_transcripts = transcribe(ranked, fetch=transcribe_fetch)
        try:
            verdicts = check_rubro(brief, ranked, api_key=key, review=review)
            result.reviewed = True
        except reels_ai.ReelReviewError as exc:
            logger.warning("reel product check unavailable: %s", exc)
            result.check = CHECK_UNAVAILABLE
            result.check_detail = getattr(exc, "reason", "") or check_failure_reason(exc)
    # Only what the check SAW and kept (§ founder 2026-10-16: «si no puede filtrar, que
    # diga inténtalo más tarde»): an unchecked reel — the check did not run, or its batch
    # failed — is never shown, so another product's promo cannot slip through.
    kept = [r for r in candidates.values() if (v := verdicts.get(_reel_key(r))) and v.fits]
    result.dropped = sum(1 for v in verdicts.values() if not v.fits)
    lifts = account_lifts(reels)  # over every reel read, not only the candidates

    def cards(since: float) -> list[dict[str, str]]:
        top = _top(kept, since, SHOWN_PER_WINDOW)
        return [
            reel_card(
                r,
                n,
                moment,
                lift=lifts.get(_reel_key(r)),
                review=verdicts.get(_reel_key(r)),
            )
            for n, r in enumerate(top, 1)
        ]

    result.week = cards(week_since)
    result.month = cards(moment - MONTH_DAYS * _DAY)
    return result


def _env_key() -> str | None:
    """The Anthropic key the check calls with, or None when there is none."""
    try:
        return api_key_from_env()
    except MissingAPIKey:
        return None


_cache: dict[tuple[str, str], DiscoveredReels] = {}
_cache_guard = threading.Lock()
#: One lock per brand: two loads of the same brand at once (two tabs, a double click on
#: «Actualizar») wait for one read instead of paying ScrapeCreators and Claude twice.
_brand_locks: dict[tuple[str, str], threading.Lock] = {}
#: Reads finished per brand — how a load that waited knows one finished meanwhile.
_reads: dict[tuple[str, str], int] = {}


def cached_discover(
    tenant_id: UUID, brand_id: UUID, *, refresh: bool = False, **kwargs: Any
) -> DiscoveredReels:
    """`discover`, remembered per brand for `CACHE_TTL_SECONDS` (memory only: a restart
    reads again). `refresh=True` reads again now — unless another load of the same brand
    finished a read while this one waited for it, which is then as fresh as asked. A
    fresh hit is answered at once, even while another load of the brand is reading."""
    key = (str(tenant_id), str(brand_id))
    with _cache_guard:
        brand_lock = _brand_locks.setdefault(key, threading.Lock())
        reads_before = _reads.get(key, 0)
        hit = _cache.get(key)
    if hit is not None and not refresh and time.time() - hit.fetched_at < CACHE_TTL_SECONDS:
        return hit
    with brand_lock:
        with _cache_guard:
            hit = _cache.get(key)
            read_meanwhile = _reads.get(key, 0) != reads_before
        if hit is not None:
            fresh = time.time() - hit.fetched_at < CACHE_TTL_SECONDS
            if read_meanwhile or (fresh and not refresh):
                return hit
        found = discover(tenant_id, brand_id, **kwargs)
        with _cache_guard:
            _reads[key] = _reads.get(key, 0) + 1
            # a read whose check could not run is not remembered: the next load (or
            # «Actualizar» a minute later) tries again instead of 6 h of «más tarde»
            if found.check != CHECK_UNAVAILABLE:
                _cache[key] = found
            else:
                _cache.pop(key, None)
        return found


__all__ = [
    "CACHE_TTL_SECONDS",
    "CHECK_NO_BRIEF",
    "CHECK_UNAVAILABLE",
    "MONTH_DAYS",
    "WEEK_DAYS",
    "DiscoveredReels",
    "Referente",
    "brand_brief",
    "brand_referentes",
    "cached_discover",
    "check_failure_reason",
    "check_rubro",
    "discover",
    "read_reels",
    "reel_card",
]
