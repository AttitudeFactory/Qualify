"""The persistent reels run (ADR 42 §2.5, §2.8, §4; slice R4, m-24854848).

Closes the two leaks of ADR 42 §1.2: **H5** (the vendor was read before the brief and the
Anthropic key were checked — credits spent, nothing shown) and **H6** (a failed Claude
review saved nothing, so every retry paid the whole read again).

Three doors, and only one of them pays:

- `enqueue_run(tenant, brand, trigger)` — leaves a run in the queue. Idempotent: the
  `UNIQUE (brand_id, trigger, run_date)` of 0117 means the scheduler and a double click
  never make two. `retry=True` puts a `check_failed` / `error` run back in the queue
  («Intentar de nuevo»); without it a finished run is returned as it is.
- `run(tenant, run_id)` — the ONLY thing that pays (ScrapeCreators credits and Claude
  calls); the `reels-worker` (R8) calls it. In order:
  1. claims the run (`queued` → `running`); a run another worker holds is left alone;
  2. builds the brand brief and finds the Anthropic key **before any paid call** — no
     brief or no key ends the run `check_failed` having called nobody;
  3. per account: page 1 again when older than `PAGE1_TTL` (24 h), the whole 30-day walk
     when older than `FULL_WALK_TTL` (72 h), nothing otherwise. `reel_accounts.
     refresh_lock_until` is taken first, so two businesses that follow the same account
     at once make ONE read — the second waits for the first and then finds it fresh.
     What is read lands in `public_reels` (global, monotonic on `metrics_at`);
  4. transcripts of the candidates that have none (`transcript_at IS NULL`): Instagram's
     paid speech-to-text (up to `reels.MAX_PAID_TRANSCRIPTS`), TikTok's free subtitles.
     Stored on the reel: a transcript is never paid twice;
  5. Claude's verdict of every candidate, reused when one exists for the same
     `brief_hash` and `input_hash` (what the model reads, the model, the prompt version
     and the effort), else asked for and stored with `model_id`, `prompt_version`,
     `effort` and `cost_usd`. A failed review ends the run `check_failed` WITHOUT
     deleting anything: the next run pays no list and no transcript again, only the
     review;
  6. the ideas: the `IDEAS_PER_RUN` most viewed reels the check kept, in
     `brand_reel_ideas`; the run ends `ok`;
  7. with the run `ok`, the analysis of each idea (`IdeaAnalyzer`, ADR 44): its cost is
     added to the run and a failure never changes the run's status.
- `view(tenant, brand)` — only reads: the latest run (its progress) and the latest `ok`
  run with its ideas. Never calls the vendor nor the model, never writes.

A gate refusal (ADR 42 R2: switch off, floor, 402) ends the run `budget_stopped`, with
what was read kept. Anything unexpected ends it `error` (logged), never stuck `running`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

import httpx

from qualify_api.claude_tools import ModelConfig
from qualify_api.referentes import ai as review_ai
from qualify_api.referentes import brand_brief as brief_builder
from qualify_api.referentes import reels, reels_ai
from qualify_api.referentes.reel_analysis_types import ReelSource
from qualify_api.referentes.reel_store import (
    ACCOUNT_ERROR,
    ACCOUNT_MISSING,
    ACCOUNT_OK,
    STATUS_BUDGET_STOPPED,
    STATUS_CHECK_FAILED,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_RUNNING,
    TRANSCRIPT_TIKTOK,
    TRANSCRIPT_VENDOR,
    TRIGGER_OPERATOR_90D,
    TRIGGERS,
    AccountState,
    Idea,
    NewIdea,
    NewVerdict,
    PostgresReelRunStore,
    PublicReel,
    ReelRunStore,
    RunRecord,
    StoredVerdict,
)
from qualify_api.vendors import scrapecreators

logger = logging.getLogger(__name__)

#: The run's own provenance (`brand_reel_runs.pipeline_version`). Raise it when what a run
#: reads, keeps or ranks changes.
PIPELINE_VERSION = "reels-run-1"
#: The version of the list parser that wrote a `public_reels` row (`parser_version`).
REEL_PARSER_VERSION = 1
#: ADR 42 §2.5: page 1 of an account again after 24 h, the whole 30-day walk after 72 h.
PAGE1_TTL = timedelta(hours=24)
FULL_WALK_TTL = timedelta(hours=72)
#: Timeout of one list request (`httpx`, applied per connect/read/write/pool phase).
READ_TIMEOUT_SECONDS = 20.0
#: The least a refresh holds an account (`refresh_lock_until`); a crashed run frees it.
LOCK_SECONDS = 10 * 60


def lock_seconds(pages: int) -> int:
    """How long a refresh of `pages` holds its account: an estimated worst case of the
    walk — every page spending its full timeout twice (connect + read, 40 s a page) — plus
    a minute, never less than `LOCK_SECONDS`. The 90-day walk (12 pages) gives 540 s,
    inside the 10 min; a deeper walk grows the lock with it, so another run never takes
    an account whose read is still in flight (and pays it again). Not measured: a normal
    page answers in a few seconds, far under the bound.

    Known limit: httpx's timeout applies per phase (connect, each read, …), not to the
    whole request, so a response that trickles in can outlive the lock. In that rare case
    another run may take the account and pay it a second time. That costs credits but
    breaks nothing: each run releases only its own lock (`lock_until`), and the reel
    upsert keeps the newest metrics."""
    return max(LOCK_SECONDS, int(pages * 2 * READ_TIMEOUT_SECONDS) + 60)


#: How long a run waits for another business's refresh of the same account, and how
#: often it looks. After that it uses what is stored rather than read it twice.
LOCK_WAIT_SECONDS = 5 * 60
LOCK_POLL_SECONDS = 2.0
#: ADR 42 §2.1(a): a run leaves between 6 and 8 ideas.
IDEAS_PER_RUN = 8

#: Why a run's check did not run (returned, not stored: the view rebuilds the brief).
CHECK_NO_BRIEF = reels.CHECK_NO_BRIEF
CHECK_UNAVAILABLE = reels.CHECK_UNAVAILABLE


def days_for(trigger: str) -> int:
    """How far back a run of `trigger` reads: the operator's 90 days, else the month."""
    if trigger not in TRIGGERS:
        raise ValueError(f"unknown reels run trigger: {trigger!r}")
    return reels.QUARTER_DAYS if trigger == TRIGGER_OPERATOR_90D else reels.MONTH_DAYS


_store: ReelRunStore | None = None
_store_guard = threading.Lock()


def default_store() -> ReelRunStore:
    global _store
    with _store_guard:
        if _store is None:
            _store = PostgresReelRunStore()
        return _store


def _utc(moment: float) -> datetime:
    return datetime.fromtimestamp(moment, UTC)


# --------------------------------------------------------------------------------------
# enqueue_run
# --------------------------------------------------------------------------------------


def enqueue_run(
    tenant_id: UUID,
    brand_id: UUID,
    trigger: str,
    *,
    run_date: date | None = None,
    retry: bool = False,
    store: ReelRunStore | None = None,
    clock: Callable[[], float] = time.time,
) -> RunRecord:
    """The brand's run of `trigger` for `run_date` (today, UTC, by default), queued once.
    Calling it again returns the same run; `retry=True` re-queues it when it ended
    `check_failed` or `error`. Never calls the vendor nor the model."""
    now = _utc(clock())
    return (store or default_store()).enqueue(
        tenant_id,
        brand_id,
        trigger=trigger,
        run_date=run_date or now.date(),
        days=days_for(trigger),
        pipeline_version=PIPELINE_VERSION,
        now=now,
        retry=retry,
    )


# --------------------------------------------------------------------------------------
# view
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunView:
    """What the screen reads (R7 builds the cards from it)."""

    #: The brand's newest run, whatever its state: progress (`accounts_done /
    #: accounts_total`) while it runs, or how it ended.
    latest: RunRecord | None
    #: The newest run that ended `ok`, and its ideas, best first.
    shown: RunRecord | None
    ideas: list[Idea] = field(default_factory=list)


def view(tenant_id: UUID, brand_id: UUID, *, store: ReelRunStore | None = None) -> RunView:
    """Only reads the database: never the vendor, never the model, never a write."""
    active = store or default_store()
    shown = active.latest_run(tenant_id, brand_id, status=STATUS_OK)
    return RunView(
        latest=active.latest_run(tenant_id, brand_id),
        shown=shown,
        ideas=active.ideas(tenant_id, brand_id, shown.id) if shown is not None else [],
    )


# --------------------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------------------


#: One idea as the analysis reads it: VE-04a's `ReelSource` (no metrics, no verdict, no
#: handle — V12 of the backend handoff).
IdeaSource = ReelSource


class IdeaAnalyzer(Protocol):
    """ADR 44: called once the run is `ok`, with the business that triggered it, to
    analyze its ideas. The implementation is
    `reel_analysis_worker.analyze_run_ideas` (VE-04a m-24921056); the `reels-worker` (R8)
    passes it as `run(..., analyze=analyze_run_ideas)`. Returns what it cost, in USD."""

    def __call__(
        self, tenant_id: UUID, brand_id: UUID, run_id: UUID, sources: Sequence[IdeaSource]
    ) -> Decimal: ...


@dataclass
class RunOutcome:
    run_id: UUID
    status: str
    #: False when the run was not `queued` (another worker has it, or it already ended).
    ran: bool = True
    #: `CHECK_NO_BRIEF` / `CHECK_UNAVAILABLE` when the check could not run.
    check: str = ""
    accounts_read: int = 0
    accounts_failed: list[str] = field(default_factory=list)
    credits: int = 0
    transcripts_paid: int = 0
    verdicts_new: int = 0
    verdicts_reused: int = 0
    ideas: int = 0
    cost_usd: Decimal = Decimal("0")


FetchFn = reels.FetchFn
TranscribeFn = reels.TranscribeFn
ReviewFn = reels.ReviewFn
BriefFn = Callable[[UUID, UUID], review_ai.BrandBrief | None]


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=list).encode()
    ).hexdigest()


def brief_hash(brief: review_ai.BrandBrief) -> str:
    """What changes when the brand's brief changes: a new hash → a new verdict."""
    return _hash(asdict(brief))


def input_hash(item: reels_ai.ReelToReview, config: ModelConfig) -> str:
    """Everything the model reads about the reel (not its caller id), plus the model, the
    prompt version and the effort: a verdict is redone only when one of them changes."""
    data = asdict(item)
    data.pop("id")
    return _hash(
        {
            "reel": data,
            "model": config.model_id,
            "effort": config.effort,
            "prompt": reels_ai.REVIEW_PROMPT_VERSION,
        }
    )


def _api_key(api_key: str | None) -> str | None:
    return api_key or reels._env_key()


class _Blocked(Exception):
    """The gate refused a paid list read: the run stops `budget_stopped`."""


@dataclass
class _Context:
    tenant_id: UUID
    brand_id: UUID
    run_id: UUID
    days: int
    now: datetime
    store: ReelRunStore
    clock: Callable[[], float]
    sleep: Callable[[float], None]
    credits: int = 0
    #: reel key → the TikTok subtitles URL of this run's read (not stored: it expires).
    caption_urls: dict[str, str] = field(default_factory=dict)
    #: The reels the run kept as ideas, best first (what the analysis reads).
    idea_reels: list[dict[str, Any]] = field(default_factory=list)


def _refresh_need(state: AccountState | None, days: int, now: datetime) -> str | None:
    """`"full"`, `"page1"` or None: what this account needs read for a run of `days`."""
    if (
        state is None
        or state.full_walk_at is None
        or state.covered_days < days
        or now - state.full_walk_at >= FULL_WALK_TTL
    ):
        return "full"
    if state.page1_at is None or now - state.page1_at >= PAGE1_TTL:
        return "page1"
    return None


def _handle(handle: str) -> str:
    return handle.strip().lstrip("@").lower()


def _public_reel(reel: dict[str, Any], now: datetime) -> PublicReel:
    seconds = reel.get("seconds")
    return PublicReel(
        network=reel["network"],
        reel_id=str(reel["id"]),
        handle=_handle(str(reel["handle"])),
        taken_at=_utc(float(reel["takenAt"])),
        metrics_at=now,
        parser_version=REEL_PARSER_VERSION,
        caption=str(reel.get("caption") or ""),
        duration_s=float(seconds) if isinstance(seconds, (int, float)) else None,
        sound=str(reel.get("sound") or ""),
        views=reel.get("views"),
        likes=reel.get("likes"),
        comments=reel.get("comments"),
        saves=reel.get("saves"),
        shares=reel.get("shares"),
        video_url=str(reel.get("video") or "") or None,
    )


def _reel_dict(reel: PublicReel, ref: reels.Referente | None, caption_url: str) -> dict[str, Any]:
    """A stored reel in the shape the pipeline's helpers read (`reels._candidates`,
    `reels.transcribe_one`, `reels.account_lifts`)."""
    if reel.network == "instagram":
        url = f"https://www.instagram.com/reel/{reel.reel_id}/"
    else:
        url = f"https://www.tiktok.com/@{reel.handle}/video/{reel.reel_id}"
    return {
        "id": reel.reel_id,
        "network": reel.network,
        "handle": reel.handle,
        "url": url,
        "caption": reel.caption,
        "takenAt": reel.taken_at.timestamp(),
        "views": reel.views,
        "likes": reel.likes,
        "comments": reel.comments,
        "shares": reel.shares,
        "saves": reel.saves,
        "seconds": round(reel.duration_s) if reel.duration_s is not None else None,
        "sound": reel.sound,
        "video": reel.video_url or "",
        "captionUrl": caption_url,
        "transcript": reel.transcript or "",
        "transcriptKnown": reel.transcript_at is not None,
        "accountKind": ref.kind if ref else "",
        "accountNote": ref.note if ref else "",
    }


def _counting_client(ctx: _Context, timeout: float) -> httpx.Client:
    """An HTTP client that counts every answer of the vendor's API — the credits of this
    run (a cached answer is counted too: the vendor does not say which were free)."""

    def count(response: httpx.Response) -> None:
        if scrapecreators.is_vendor_host(response.request.url.host) and response.is_success:
            ctx.credits += 1

    return httpx.Client(timeout=timeout, event_hooks={"response": [count]})


def _refresh_account(
    ctx: _Context, ref: reels.Referente, fetch: FetchFn, client: httpx.Client
) -> bool:
    """Read the account if it needs it, holding its refresh lock. True when it is
    readable (fresh, read now, or read meanwhile by another run); False when it failed.
    Raises `_Blocked` when the gate refused."""
    network, handle = ref.network, _handle(ref.handle)
    waited = 0.0
    while True:
        now = _utc(ctx.clock())
        state = ctx.store.account(ctx.tenant_id, network, handle)
        need = _refresh_need(state, ctx.days, now)
        if need is None:
            return True
        pages = 1 if need == "page1" else reels.reel_pages(ctx.days)
        until = now + timedelta(seconds=lock_seconds(pages))
        if ctx.store.try_lock_account(ctx.tenant_id, network, handle, now=now, until=until):
            # re-check under the lock: another business's refresh may have finished
            # between the check above and taking the lock — then nothing is read again
            state = ctx.store.account(ctx.tenant_id, network, handle)
            need = _refresh_need(state, ctx.days, now)
            if need is None:
                ctx.store.release_account(ctx.tenant_id, network, handle, lock_until=until)
                return True
            break
        if waited >= LOCK_WAIT_SECONDS:
            # another run has held it too long: use what is stored, never read it twice
            logger.warning("reels of %s/%s: refresh lock held, using stored", network, handle)
            return state is not None and state.full_walk_at is not None
        ctx.sleep(LOCK_POLL_SECONDS)
        waited += LOCK_POLL_SECONDS
    before = ctx.credits
    status, http_status = ACCOUNT_ERROR, None
    read: list[dict[str, Any]] | None = None
    blocked = False
    try:
        read = fetch(
            network,
            handle,
            since=ctx.now.timestamp() - ctx.days * 24 * 3600,
            client=client,
            max_pages=1 if need == "page1" else reels.reel_pages(ctx.days),
        )
        status = ACCOUNT_OK
    except scrapecreators.ScrapeCreatorsBlocked as exc:
        blocked = True
        logger.warning("reels of %s/%s refused by the gate: %s", network, handle, exc.reason)
        raise _Blocked(exc.reason) from exc
    except scrapecreators.ScrapeCreatorsError as exc:
        http_status = exc.status_code
        status = ACCOUNT_MISSING if http_status == 404 else ACCOUNT_ERROR
        logger.warning("reels of %s/%s unreadable: %s", network, handle, exc)
    except ValueError as exc:
        logger.warning("reels of %s/%s unreadable: %s", network, handle, exc)
    finally:
        # always release the lock; a refused or crashed read keeps the account's status
        stamp = _utc(ctx.clock())
        rows = [_public_reel(r, stamp) for r in read or []]
        if rows:
            ctx.store.upsert_reels(ctx.tenant_id, rows)
        for reel in read or []:
            if reel.get("captionUrl"):
                ctx.caption_urls[f"{reel['network']}:{reel['id']}"] = str(reel["captionUrl"])
        ctx.store.finish_account(
            ctx.tenant_id,
            network,
            handle,
            now=stamp,
            status=(state.status if state else ACCOUNT_OK) if blocked else status,
            http_status=(state.last_http_status if state else None) if blocked else http_status,
            page1=read is not None,
            full_walk_days=ctx.days if read is not None and need == "full" else None,
            newest_taken_at=max((r.taken_at for r in rows), default=None),
            credits=ctx.credits - before,
            lock_until=until,
        )
    return read is not None


def _transcribe(ctx: _Context, ranked: Sequence[dict[str, Any]], fetch: TranscribeFn) -> int:
    """Transcribe the candidates that never were, store each one, return how many
    Instagram ones were paid. Only the `reels.MAX_PAID_TRANSCRIPTS` most viewed Instagram
    candidates are eligible, transcribed or not — so a retry (Claude down) never reaches
    further down the ranking and pays nothing already-eligible again. A failed one is left
    unknown (a later run retries); a gate refusal stops the paid ones and the review goes
    on with what is known."""
    todo: list[dict[str, Any]] = []
    instagram = 0
    for reel in ranked:
        if reel["network"] == "instagram":
            if instagram >= reels.MAX_PAID_TRANSCRIPTS:
                continue
            instagram += 1
        if reel["transcriptKnown"]:
            continue
        if reel["network"] == "tiktok" and not reel.get("captionUrl"):
            continue  # a TikTok without subtitles of this read has nothing to fetch
        todo.append(reel)
    if not todo:
        return 0
    blocked = threading.Event()

    def one(reel: dict[str, Any]) -> bool:
        if blocked.is_set():
            return False
        try:
            text = " ".join(fetch(reel, client).split())
        except scrapecreators.ScrapeCreatorsBlocked as exc:
            blocked.set()
            logger.warning("reel transcripts refused by the gate: %s", exc.reason)
            return False
        except (scrapecreators.ScrapeCreatorsError, httpx.HTTPError) as exc:
            logger.info("transcript of %s:%s unavailable: %s", reel["network"], reel["id"], exc)
            return False
        reel["transcript"] = text
        reel["transcriptKnown"] = True
        ctx.store.save_transcript(
            ctx.tenant_id,
            reel["network"],
            reel["id"],
            text=text,
            source=TRANSCRIPT_VENDOR if reel["network"] == "instagram" else TRANSCRIPT_TIKTOK,
            now=_utc(ctx.clock()),
        )
        return True

    with _counting_client(ctx, scrapecreators.TRANSCRIPT_TIMEOUT_SECONDS) as client:
        with ThreadPoolExecutor(max_workers=reels._TRANSCRIPT_WORKERS) as pool:
            done = list(pool.map(one, todo))
    return sum(ok for ok, r in zip(done, todo, strict=True) if r["network"] == "instagram")


def _to_review(reel: dict[str, Any]) -> reels_ai.ReelToReview:
    return reels_ai.ReelToReview(
        id=f"{reel['network']}:{reel['id']}",
        network=reel["network"],
        handle=reel["handle"],
        caption=str(reel.get("caption") or ""),
        sound=str(reel.get("sound") or ""),
        transcript=str(reel.get("transcript") or ""),
        account_kind=str(reel.get("accountKind") or ""),
        account_note=str(reel.get("accountNote") or ""),
    )


class _CheckFailed(Exception):
    def __init__(self, reason: str, cost: Decimal) -> None:
        super().__init__(reason)
        self.reason = reason
        self.cost = cost


def _check(
    ctx: _Context,
    brief: review_ai.BrandBrief,
    b_hash: str,
    ranked: Sequence[dict[str, Any]],
    *,
    api_key: str,
    review: ReviewFn,
    config: ModelConfig,
    outcome: RunOutcome,
) -> tuple[dict[str, StoredVerdict], Decimal]:
    """reel key → its verdict, stored ones reused. Raises `_CheckFailed` when every call
    failed and nothing was judged before (the run then ends `check_failed`)."""
    items = {f"{r['network']}:{r['id']}": _to_review(r) for r in ranked}
    hashes = {key: input_hash(item, config) for key, item in items.items()}
    stored = ctx.store.verdicts(
        ctx.tenant_id, ctx.brand_id, brief_hash=b_hash, reel_ids=[r["id"] for r in ranked]
    )
    known: dict[str, StoredVerdict] = {}
    missing: list[reels_ai.ReelToReview] = []
    for key, item in items.items():
        verdict = stored.get((item.network, key.split(":", 1)[1], hashes[key]))
        if verdict is None:
            missing.append(item)
        else:
            known[key] = verdict
    outcome.verdicts_reused = len(known)
    if not missing:
        return known, Decimal("0")
    size = reels._REVIEW_BATCH
    batches = [missing[i : i + size] for i in range(0, len(missing), size)]
    failures: list[BaseException] = []

    def one(batch: list[reels_ai.ReelToReview]) -> list[NewVerdict] | None:
        try:
            answers, stats = review(brief, batch, api_key=api_key, config=config)
        except Exception as exc:  # noqa: BLE001 — a model call; the batch stays unchecked
            failures.append(exc)
            logger.warning(
                "reel rubro check failed for %d reels: %s",
                len(batch),
                reels.check_failure_reason(exc),
                exc_info=exc,
            )
            return None
        by_id = {item.id: item for item in batch}
        answered = [a for a in answers if a.id in by_id]
        cost = Decimal(str(getattr(stats, "cost_usd", 0.0) or 0.0))
        each = (cost / len(answered)).quantize(Decimal("0.000001")) if answered else cost
        model_id = str(getattr(stats, "model_id", "") or config.model_id)
        return [
            NewVerdict(
                network=by_id[a.id].network,
                reel_id=a.id.split(":", 1)[1],
                brief_hash=b_hash,
                input_hash=hashes[a.id],
                fits=a.fits,
                model_id=model_id,
                prompt_version=reels_ai.REVIEW_PROMPT_VERSION,
                affinity=a.affinity,
                format=a.format,
                hook=a.hook,
                reason=a.reason,
                effort=config.effort,
                cost_usd=each,
            )
            for a in answered
        ]

    with ThreadPoolExecutor(max_workers=min(len(batches), 4)) as pool:
        answered = list(pool.map(one, batches))
    fresh = [v for batch in answered if batch for v in batch]
    cost = sum((v.cost_usd for v in fresh), Decimal("0"))
    if all(a is None for a in answered) and not known:
        last = failures[-1] if failures else None
        reason = reels.check_failure_reason(last) if last else "sin respuesta del modelo de IA"
        raise _CheckFailed(reason, cost)
    saved = ctx.store.save_verdicts(ctx.tenant_id, ctx.brand_id, fresh)
    outcome.verdicts_new = len(saved)
    for verdict in saved.values():
        known[f"{verdict.network}:{verdict.reel_id}"] = verdict
    return known, cost


def _window_days(taken_at: float, now: float, days: int) -> int:
    """The narrowest window (7, 30, 90 days) of the run the reel falls in."""
    for span in sorted(reels.WINDOW_DAYS.values()):
        if span <= days and taken_at >= now - span * 24 * 3600:
            return span
    return days


def _ideas(
    ctx: _Context, ranked: Sequence[dict[str, Any]], verdicts: dict[str, StoredVerdict]
) -> list[tuple[NewIdea, dict[str, Any]]]:
    kept = [r for r in ranked if (v := verdicts.get(f"{r['network']}:{r['id']}")) and v.fits]
    now = ctx.now.timestamp()
    return [
        (
            NewIdea(
                network=r["network"],
                reel_id=r["id"],
                rank=n,
                window_days=_window_days(r["takenAt"], now, ctx.days),
                verdict_id=verdicts[f"{r['network']}:{r['id']}"].id,
            ),
            r,
        )
        for n, r in enumerate(kept[:IDEAS_PER_RUN], 1)
    ]


def run(
    tenant_id: UUID,
    run_id: UUID,
    *,
    store: ReelRunStore | None = None,
    repository: Any = None,
    brief: BriefFn | None = None,
    api_key: str | None = None,
    fetch: FetchFn = scrapecreators.fetch_reels,
    transcribe_fetch: TranscribeFn = reels.transcribe_one,
    review: ReviewFn = reels_ai.review_reels,
    config: ModelConfig | None = None,
    analyze: IdeaAnalyzer | None = None,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> RunOutcome:
    """Run one queued run (see the module docstring). The only door that pays."""
    active = store or default_store()
    claimed = active.claim(tenant_id, run_id, now=_utc(clock()))
    if claimed is None:
        record = active.get_run(tenant_id, run_id)
        if record is None:
            raise LookupError(f"no reels run {run_id} for this tenant")
        return RunOutcome(run_id=run_id, status=record.status, ran=False)
    outcome = RunOutcome(run_id=run_id, status=STATUS_RUNNING)
    ctx = _Context(
        tenant_id=tenant_id,
        brand_id=claimed.brand_id,
        run_id=run_id,
        days=claimed.days,
        now=_utc(clock()),
        store=active,
        clock=clock,
        sleep=sleep,
    )
    b_hash: str | None = None
    try:
        status, b_hash = _run_claimed(
            ctx,
            outcome,
            repository=repository,
            brief=brief,
            api_key=api_key,
            fetch=fetch,
            transcribe_fetch=transcribe_fetch,
            review=review,
            config=config or ModelConfig(reels_ai.REVIEW_MODEL, reels_ai.REVIEW_EFFORT),
        )
    except Exception:
        logger.exception("reels run %s failed", run_id)
        status = STATUS_ERROR
    outcome.status = status
    outcome.credits = ctx.credits
    active.finish(
        tenant_id,
        run_id,
        status=status,
        now=_utc(clock()),
        credits=ctx.credits,
        cost_usd=outcome.cost_usd,
        brief_hash=b_hash,
    )
    if status == STATUS_OK and analyze is not None and outcome.ideas:
        _analyze(ctx, analyze, outcome)
    logger.info(
        "reels run %s: %s (accounts %d read, %d credits, %d transcripts paid, "
        "%d verdicts new / %d reused, %d ideas)",
        run_id,
        status,
        outcome.accounts_read,
        outcome.credits,
        outcome.transcripts_paid,
        outcome.verdicts_new,
        outcome.verdicts_reused,
        outcome.ideas,
    )
    return outcome


def _run_claimed(
    ctx: _Context,
    outcome: RunOutcome,
    *,
    repository: Any,
    brief: BriefFn | None,
    api_key: str | None,
    fetch: FetchFn,
    transcribe_fetch: TranscribeFn,
    review: ReviewFn,
    config: ModelConfig,
) -> tuple[str, str | None]:
    """Steps 2-6 of `run`; returns `(status, brief_hash)`."""
    # 2. the brief and the key, BEFORE anything is paid (H5)
    build = brief or (
        lambda tenant, brand: brief_builder.brand_brief(tenant, brand, repository=repository)
    )
    brand = build(ctx.tenant_id, ctx.brand_id)
    if brand is None:
        outcome.check = CHECK_NO_BRIEF
        logger.info("reels run %s: no brief, nothing read", ctx.run_id)
        return STATUS_CHECK_FAILED, None
    b_hash = brief_hash(brand)
    key = _api_key(api_key)
    if key is None:
        outcome.check = CHECK_UNAVAILABLE
        logger.warning("reels run %s: no Anthropic key configured, nothing read", ctx.run_id)
        return STATUS_CHECK_FAILED, b_hash

    # 3. the accounts, each refreshed at most once across every business
    referentes = reels.brand_referentes(ctx.tenant_id, ctx.brand_id, repository=repository)
    ctx.store.progress(ctx.tenant_id, ctx.run_id, accounts_total=len(referentes), accounts_done=0)
    readable: list[reels.Referente] = []
    try:
        with _counting_client(ctx, READ_TIMEOUT_SECONDS) as client:
            for done, ref in enumerate(referentes, 1):
                if _refresh_account(ctx, ref, fetch, client):
                    readable.append(ref)
                else:
                    outcome.accounts_failed.append(f"@{ref.handle}")
                ctx.store.progress(
                    ctx.tenant_id,
                    ctx.run_id,
                    accounts_total=len(referentes),
                    accounts_done=done,
                )
    except _Blocked:
        return STATUS_BUDGET_STOPPED, b_hash
    outcome.accounts_read = len(readable)

    # the candidates, from what is STORED (this read and every earlier one)
    by_account = {(ref.network, _handle(ref.handle)): ref for ref in referentes}
    stored = ctx.store.reels_of(
        ctx.tenant_id,
        list(by_account),
        since=ctx.now - timedelta(days=ctx.days),
    )
    reel_dicts = [
        _reel_dict(
            r,
            by_account.get((r.network, r.handle)),
            ctx.caption_urls.get(f"{r.network}:{r.reel_id}", ""),
        )
        for r in stored
    ]
    moment = ctx.now.timestamp()
    windows = {
        name: moment - span * 24 * 3600
        for name, span in reels.WINDOW_DAYS.items()
        if span <= ctx.days
    }
    widest = moment - ctx.days * 24 * 3600
    candidates = {
        f"{r['network']}:{r['id']}": r
        for since in windows.values()
        for r in reels._candidates(reel_dicts, since, per_account=since == widest)
    }
    if not candidates:
        return STATUS_OK, b_hash
    ranked = sorted(candidates.values(), key=reels._views_rank, reverse=True)

    # 4. what they say — stored, never paid twice
    outcome.transcripts_paid = _transcribe(ctx, ranked, transcribe_fetch)

    # 5. the check — stored verdicts reused; a failure keeps everything read
    try:
        verdicts, cost = _check(
            ctx, brand, b_hash, ranked, api_key=key, review=review, config=config, outcome=outcome
        )
    except _CheckFailed as exc:
        outcome.check = CHECK_UNAVAILABLE
        outcome.cost_usd += exc.cost
        logger.warning("reels run %s: check unavailable: %s", ctx.run_id, exc.reason)
        return STATUS_CHECK_FAILED, b_hash
    outcome.cost_usd += cost

    # 6. the ideas
    ideas = _ideas(ctx, ranked, verdicts)
    ctx.store.save_ideas(ctx.tenant_id, ctx.brand_id, ctx.run_id, [i for i, _ in ideas])
    outcome.ideas = len(ideas)
    ctx.idea_reels = [r for _, r in ideas]
    return STATUS_OK, b_hash


def _analyze(ctx: _Context, analyze: IdeaAnalyzer, outcome: RunOutcome) -> None:
    """Step 7 (ADR 44): analyze the ideas of an `ok` run; add its cost; a failure is
    logged and never changes the run's status."""
    sources = [
        IdeaSource(
            network=r["network"],
            post_id=r["id"],
            post_url=r["url"],
            video_url=r.get("video") or "",
            caption=r.get("caption") or "",
            transcript=r.get("transcript") or "",
        )
        for r in ctx.idea_reels
    ]
    try:
        cost = Decimal(analyze(ctx.tenant_id, ctx.brand_id, ctx.run_id, sources) or 0)
    except Exception:
        logger.exception("reels run %s: the analysis of its ideas failed", ctx.run_id)
        return
    if cost > 0:
        ctx.store.add_cost(ctx.tenant_id, ctx.run_id, cost)
        outcome.cost_usd += cost


__all__ = [
    "CHECK_NO_BRIEF",
    "CHECK_UNAVAILABLE",
    "FULL_WALK_TTL",
    "IDEAS_PER_RUN",
    "PAGE1_TTL",
    "PIPELINE_VERSION",
    "IdeaAnalyzer",
    "IdeaSource",
    "RunOutcome",
    "RunView",
    "brief_hash",
    "days_for",
    "default_store",
    "enqueue_run",
    "input_hash",
    "run",
    "view",
]
