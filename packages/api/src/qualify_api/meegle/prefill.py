"""The Brand Kit prefill of an «Alta de cliente» (PB-4, m-24852198; epic m-24852192,
`docs/epica-prellenado-brand-kit-alta.md` §2.4-§2.7, approved by the founder 2026-10-24).

Two halves, both inside the webhook-worker and never in the webhook request:

- **`AltaPrefillScheduler.schedule`** — called by the «Datos» handler right AFTER
  `OnboardingEngine.start_invitation` succeeded (the email is already sent). With a
  «Cuenta de Instagram» it prepares the reserved draft (`auth.drafts.
  start_alta_brand_kit_draft`, PB-0) and enqueues one job in `alta_prefill_jobs`
  (migration 0092) keyed by item + network + username. It is cheap (two database
  round-trips, no vendor call) and the handler swallows anything it raises: nothing here
  can retry the event, so nothing here can send a second invitation.
- **`AltaPrefillRunner.run_once`** — the worker loop (and `--once`) drains due jobs:
  `creative.brand_prefill.prefill_brand_kit(..., source={"kind": "alta",
  "meegle_work_item_id": <id>}, propose=True)` with `CallCaps` derived from the cost cap,
  then ONE comment on the Alta item with the outcome.

**Off by default.** `QUALIFY_ALTA_PREFILL_ENABLED` (`1`/`true`/`yes`/`on`) turns it on and
`QUALIFY_ALTA_PREFILL_MAX_USD` (a positive decimal, USD per Alta) must be set too: no
value lives in code (founder 2026-10-24: the cap is fixed after PB-6 measures). Off,
unset, invalid, or below the cheapest useful run → `schedule` does nothing at all — no
draft, no job, no comment — and the Alta works exactly as before PB-4. A job found while
the setting is off is settled `disabled` without a comment.

**The cost cap** (`caps_for_budget`). `prefill_brand_kit` budgets in CALLS, so the USD
cap becomes `CallCaps` through unit costs taken from what the repo versions:

    u_sc = SCRAPECREATORS_USD_PER_CREDIT                      (1 request = 1 credit)
    u_cl = (CLAUDE_RUN_INPUT_TOKENS  * p_in * w
          + CLAUDE_RUN_OUTPUT_TOKENS * p_out) / 1e6           (one Claude run)
           p_in / p_out = `claude_tools.PRICES` of the DEAREST model the prefill runs
           (`hashtags.from_profile.MODEL`, `hashtags.ai.SELECT_MODEL`)
           w = `claude_tools.CACHE_WRITE_MULTIPLIER` (1.25): the system prompt is sent
           cached, so a first turn bills it as a cache write — the dearest an input
           token can be; uncached or cache-read input only makes the run cheaper
    min  = MIN_RUN.sc * u_sc + MIN_RUN.claude * u_cl          (2 requests + 2 runs)
    cap < min                       → refuse (the prefill does not run)
    sc     = min(6, 2 + floor((cap - min) / u_sc))            (post pages first: cheap,
    claude = min(3, 2 + floor((cap - min - (sc-2)*u_sc) / u_cl))   and a short read fails)

so `sc * u_sc + claude * u_cl <= cap`, with 6 / 3 the most one run can use
(`brand_prefill.DEFAULT_CAPS`). The single retry gets `caps_for_budget(cap - spent)`,
`spent` = what the first attempt really cost (`usage_cost`), so the two together stay
within the cap; if what is left buys no minimum run, there is no retry. The token
envelope is an ESTIMATE (PB-6 measures the real one and replaces these two numbers); the
real cost of every attempt is stored in the job (`runs`, `spent_usd`).

**Outcomes → the comment** (one per Alta; Meegle Free allows 500 Open API calls a day):
`OK` with the proposal written → «Identidad de marca propuesta.»; `PRIVATE_ACCOUNT` →
«…la cuenta de Instagram es privada.»; `NOT_FOUND`, `READ_FAILED`, `CAP_REACHED`,
`ACCOUNT_TAKEN` and an unwritten proposal → «…no se pudo leer la cuenta de Instagram.».
An Alta without an account gets «…no hay cuenta de Instagram en el Alta.» — only while
the prefill is on and configured, so production stays silent while it is off. That case
is a job too (reserved draft + a row with `handle = ''`, enqueued straight to its
comment), so a replayed «Datos» never comments twice. Exactly one retry, only for a
transient failure (`READ_FAILED`, or a proposal that could not be saved), never for
private / not found / cap reached.

**Never twice.** A job taken back from a worker whose lock went stale (`reclaimed`: it
crashed, hung, or could not record what it did) is never run again: its spend is
unknown, so it is closed `interrupted` (the «no se pudo leer» comment). With the
recorded spend of every attempt subtracted before the next one, the estimated spend of a
job never exceeds its `max_usd`. A run is time-bounded so a live run is never mistaken
for a dead one: Claude through a client with `CLAUDE_TIMEOUT_SECONDS` and no SDK retries
(a timed-out turn degrades like any failed Claude call), worst case `MAX_RUN_SECONDS`,
under `prefill_jobs.STALE_AFTER`. The comment is at most once: it is retried only when
Meegle answered a refusal (it did not save it); a transport failure or timeout may have
saved it, and a reclaimed comment may have been posted, so both are closed without
posting again (`last_error = comment_unconfirmed`).
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from functools import partial
from typing import Any, Protocol
from uuid import UUID

from qualify_api.claude_tools import CACHE_WRITE_MULTIPLIER, PRICES
from qualify_api.creative.brand_prefill import (
    DEFAULT_CAPS,
    PREFILL_VERSION,
    CallCaps,
    PrefillOutcome,
    PrefillResult,
    PrefillUsage,
)
from qualify_api.hashtags import ai as hashtag_ai
from qualify_api.hashtags import from_profile
from qualify_api.meegle.client import MeegleApiError
from qualify_api.meegle.prefill_jobs import NewPrefillJob, PrefillJob, PrefillJobs

logger = logging.getLogger("qualify_api.meegle.prefill")

ENABLED_ENV = "QUALIFY_ALTA_PREFILL_ENABLED"
MAX_USD_ENV = "QUALIFY_ALTA_PREFILL_MAX_USD"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

NETWORK = "instagram"
#: This queue's version; the prefill's own rides with it (provenance of every job).
QUEUE_VERSION = 1
PIPELINE_VERSION = f"alta_prefill:{QUEUE_VERSION}+brand_prefill:{PREFILL_VERSION}"

#: ScrapeCreators, plan Freelance: US$47 for 25,000 credits = US$0.00188, rounded up
#: (`docs/plan-superadmin-alta-clientes.md` §172, from
#: `docs/scrapecreators-crecimiento-organico-y-contenido-ia.md`). One request on the
#: prefill's endpoints is one credit (`brand_prefill.PrefillUsage`). Unverified against
#: an invoice — PB-6 (m-24852200) verifies it.
SCRAPECREATORS_USD_PER_CREDIT = Decimal("0.0019")
#: The token envelope of ONE Claude run of the prefill, an estimate until PB-6 measures
#: it: the rubro run reads at most 12 captions x 280 chars + a 600-char bio
#: (`from_profile.MAX_*`, ~2.5k tokens with the system prompt) and the catalog run takes a
#: few tool turns over it; output is thinking + one tool call.
CLAUDE_RUN_INPUT_TOKENS = 6_000
CLAUDE_RUN_OUTPUT_TOKENS = 2_500
#: The cheapest run that can end in a proposal: the profile + one page of posts (a page
#: refused by the cap fails the read), the rubro run + the catalog run.
MIN_RUN = CallCaps(scrapecreators_requests=2, claude_calls=2)
#: The Claude models a prefill may run — priced at the dearest.
PREFILL_MODELS = (from_profile.MODEL, hashtag_ai.SELECT_MODEL)

#: The Claude client of a prefill run: one HTTP wait at most this long per turn and no SDK
#: retries (its defaults are 600 s and 2 retries — over half an hour per turn).
CLAUDE_TIMEOUT_SECONDS = 90.0
#: The turns a run can take at most: rubro (2) + catalog (`hashtag_ai.MAX_TURNS`) +
#: created hashtags (2), each bounded by the timeout above.
CLAUDE_MAX_TURNS = 2 + hashtag_ai.MAX_TURNS + 2
#: ScrapeCreators: `DEFAULT_CAPS` requests x the client's 20 s; the picture: 4 hops x 8 s.
_SCRAPECREATORS_SECONDS = 6 * 20.0
_PICTURE_SECONDS = 4 * 8.0
#: The slowest a run can be (~21 min) — `prefill_jobs.STALE_AFTER` stays above it.
MAX_RUN_SECONDS = (
    CLAUDE_MAX_TURNS * CLAUDE_TIMEOUT_SECONDS + _SCRAPECREATORS_SECONDS + _PICTURE_SECONDS
)

#: One run plus exactly one retry, for a transient failure only.
MAX_PREFILL_ATTEMPTS = 2
RETRY_AFTER = timedelta(minutes=5)
#: The comment is a Meegle call: retried a little, then given up (the job keeps the error).
MAX_COMMENT_ATTEMPTS = 3
COMMENT_BACKOFF = (timedelta(minutes=1), timedelta(minutes=10))

COMMENT_OK = "Identidad de marca propuesta."
COMMENT_NO_HANDLE = "No se precargó la identidad de marca: no hay cuenta de Instagram en el Alta."
COMMENT_PRIVATE = "No se precargó la identidad de marca: la cuenta de Instagram es privada."
COMMENT_UNREADABLE = "No se precargó la identidad de marca: no se pudo leer la cuenta de Instagram."

#: Job outcomes that are not a `PrefillOutcome`.
OUTCOME_NOT_WRITTEN = "not_written"  # OK, but the proposal could not be saved
OUTCOME_DISABLED = "disabled"  # the setting was off (or misconfigured) when the job ran
OUTCOME_NO_BUDGET = "no_budget"  # the retry's remaining budget buys no minimum run
OUTCOME_INTERRUPTED = "interrupted"  # reclaimed from a stale lock: never run again
OUTCOME_NO_HANDLE = "no_handle"  # the Alta names no Instagram account
#: `last_error` of a comment that may or may not be on the item: never posted again.
COMMENT_UNCONFIRMED = "comment_unconfirmed"

_TRANSIENT = frozenset({PrefillOutcome.READ_FAILED.value, OUTCOME_NOT_WRITTEN})


# --------------------------------------------------------------------------------------
# The cap
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class UnitCosts:
    """USD of one ScrapeCreators request and of one Claude run (the estimate above)."""

    scrapecreators_request: Decimal
    claude_run: Decimal
    claude_model: str

    def cost(self, caps: CallCaps) -> Decimal:
        return (
            caps.scrapecreators_requests * self.scrapecreators_request
            + caps.claude_calls * self.claude_run
        )

    def as_document(self) -> dict[str, Any]:
        return {
            "scrapecreators_request_usd": str(self.scrapecreators_request),
            "claude_run_usd": str(self.claude_run),
            "claude_model": self.claude_model,
            "claude_run_tokens": {
                "input": CLAUDE_RUN_INPUT_TOKENS,
                "output": CLAUDE_RUN_OUTPUT_TOKENS,
            },
        }


def unit_costs() -> UnitCosts | None:
    """From the versioned prices; None when a prefill model has no price (refuse to
    guess a zero)."""
    priced: list[tuple[Decimal, str]] = []
    for model in PREFILL_MODELS:
        if model not in PRICES:
            return None
        price_in, price_out = PRICES[model]
        # input at the cache-WRITE rate: the dearest any input token can bill (a run's
        # first turn writes its cached system prompt), so the estimate is a ceiling
        price_in_ceiling = Decimal(str(price_in)) * Decimal(str(CACHE_WRITE_MULTIPLIER))
        run = (
            Decimal(CLAUDE_RUN_INPUT_TOKENS) * price_in_ceiling
            + Decimal(CLAUDE_RUN_OUTPUT_TOKENS) * Decimal(str(price_out))
        ) / Decimal(1_000_000)
        priced.append((run, model))
    run, model = max(priced)
    return UnitCosts(SCRAPECREATORS_USD_PER_CREDIT, run, model)


def _floor_div(amount: Decimal, unit: Decimal) -> int:
    if unit <= 0:
        return 10**6
    return int((amount / unit).to_integral_value(rounding=ROUND_FLOOR))


def caps_for_budget(budget_usd: Decimal, units: UnitCosts) -> CallCaps | None:
    """The `CallCaps` a run may use within `budget_usd`; None when even `MIN_RUN` costs
    more. Post pages are added before the third Claude run (they cost ~1/20 of it)."""
    minimum = units.cost(MIN_RUN)
    if budget_usd < minimum:
        return None
    left = budget_usd - minimum
    extra_sc = min(
        DEFAULT_CAPS.scrapecreators_requests - MIN_RUN.scrapecreators_requests,
        _floor_div(left, units.scrapecreators_request),
    )
    left -= extra_sc * units.scrapecreators_request
    extra_cl = min(
        DEFAULT_CAPS.claude_calls - MIN_RUN.claude_calls, _floor_div(left, units.claude_run)
    )
    return CallCaps(
        scrapecreators_requests=MIN_RUN.scrapecreators_requests + extra_sc,
        claude_calls=MIN_RUN.claude_calls + extra_cl,
    )


def usage_cost(usage: PrefillUsage, units: UnitCosts) -> Decimal:
    """What an attempt really cost: credits at the unit price + Claude as measured. A run
    whose tokens were lost (`claude_tokens_complete` False) is charged at least the
    estimate per run, so a retry never gets budget it does not have."""
    claude = Decimal(str(round(usage.claude_cost_usd, 6)))
    if not usage.claude_tokens_complete:
        claude = max(claude, usage.claude_calls * units.claude_run)
    return usage.scrapecreators_credits * units.scrapecreators_request + claude


# --------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AltaPrefillSettings:
    """Read on every use, so a change of `.env` + restart is all it takes. `active` only
    when on AND the cap buys at least `MIN_RUN`; `reason` says why not (logs only)."""

    enabled: bool
    max_usd: Decimal | None = None
    units: UnitCosts | None = None
    caps: CallCaps | None = None
    reason: str = ""

    @property
    def active(self) -> bool:
        return self.enabled and self.caps is not None

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> AltaPrefillSettings:
        import os  # noqa: PLC0415

        env = os.environ if environ is None else environ
        if env.get(ENABLED_ENV, "").strip().lower() not in _TRUTHY:
            return cls(enabled=False, reason="disabled")
        raw = env.get(MAX_USD_ENV, "").strip()
        if not raw:
            return cls(enabled=True, reason="max_usd_not_set")
        try:
            max_usd = Decimal(raw)
        except InvalidOperation:
            return cls(enabled=True, reason="max_usd_invalid")
        if not max_usd.is_finite() or max_usd <= 0:
            return cls(enabled=True, reason="max_usd_invalid")
        units = unit_costs()
        if units is None:
            return cls(enabled=True, max_usd=max_usd, reason="model_price_unknown")
        caps = caps_for_budget(max_usd, units)
        if caps is None:
            return cls(
                enabled=True, max_usd=max_usd, units=units, reason="max_usd_below_minimum_run"
            )
        return cls(enabled=True, max_usd=max_usd, units=units, caps=caps)


def comment_for(outcome: str) -> str | None:
    """The comment a finished job writes on the Alta; None = no comment."""
    if outcome == PrefillOutcome.OK.value:
        return COMMENT_OK
    if outcome == PrefillOutcome.PRIVATE_ACCOUNT.value:
        return COMMENT_PRIVATE
    if outcome == OUTCOME_NO_HANDLE:
        return COMMENT_NO_HANDLE
    if outcome == OUTCOME_DISABLED:
        return None
    return COMMENT_UNREADABLE


# --------------------------------------------------------------------------------------
# The seams
# --------------------------------------------------------------------------------------

#: `MeegleClient.comment(work_item_id, markdown)`.
Commenter = Callable[[int, str], object]
SettingsSource = Callable[[], AltaPrefillSettings]


class DraftResult(Protocol):
    tenant_id: UUID


class PrefillFn(Protocol):
    def __call__(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        network: str,
        handle: str,
        *,
        source: dict[str, Any] | None = ...,
        caps: CallCaps = ...,
        propose: bool = ...,
    ) -> PrefillResult: ...


def _start_draft(email: str, work_item_id: int) -> DraftResult:
    from qualify_api.auth.drafts import start_alta_brand_kit_draft  # noqa: PLC0415

    return start_alta_brand_kit_draft(email, work_item_id)


def _draft_brand(tenant_id: UUID) -> UUID | None:
    """The draft tenant's brand (`drafts._provision` makes exactly one)."""
    from qualify_shared.db.session import tenant_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    with tenant_session(tenant_id) as session:
        return session.execute(
            text("SELECT id FROM brands WHERE tenant_id = :t ORDER BY created_at LIMIT 1"),
            {"t": tenant_id},
        ).scalar_one_or_none()


def bounded_claude_client(api_key: str) -> Any:
    """`claude_tools.default_client` with a wall-clock bound per turn and no SDK retries."""
    import anthropic  # noqa: PLC0415 — lazy, like `claude_tools.default_client`

    return anthropic.Anthropic(api_key=api_key, timeout=CLAUDE_TIMEOUT_SECONDS, max_retries=0)


def bounded_ports() -> Any:
    """The prefill's real ports, with both Claude callers on `bounded_claude_client`."""
    from qualify_api.creative.brand_prefill import CatalogHashtags, PrefillPorts  # noqa: PLC0415

    return PrefillPorts(
        generate=partial(from_profile.generate, client_factory=bounded_claude_client),
        catalog=CatalogHashtags(
            selector=partial(hashtag_ai.select_hashtags, client_factory=bounded_claude_client)
        ),
    )


def _prefill(*args: Any, **kwargs: Any) -> PrefillResult:
    from qualify_api.creative.brand_prefill import prefill_brand_kit  # noqa: PLC0415

    return prefill_brand_kit(*args, ports=bounded_ports(), **kwargs)


# --------------------------------------------------------------------------------------
# Enqueue (inside the «Datos» handler)
# --------------------------------------------------------------------------------------

SKIP_OFF = ""  # the prefill is off: the handler's outcome stays exactly as before PB-4
SKIP_NO_HANDLE = "no_handle"
SKIP_EMAIL_HAS_ACCOUNT = "email_has_account"
SKIP_DRAFT_EMAIL_INVALID = "draft_email_invalid"
SKIP_NO_BRAND = "no_brand"
ENQUEUED = "enqueued"
DUPLICATE = "duplicate"


class AltaPrefillScheduler:
    def __init__(
        self,
        jobs: PrefillJobs,
        commenter: Commenter,
        *,
        settings: SettingsSource = AltaPrefillSettings.from_env,
        start_draft: Callable[[str, int], DraftResult] = _start_draft,
        draft_brand: Callable[[UUID], UUID | None] = _draft_brand,
    ) -> None:
        self._jobs = jobs
        self._comment = commenter
        self._settings = settings
        self._start_draft = start_draft
        self._draft_brand = draft_brand

    def schedule(self, work_item_id: int, *, email: str, handle: str | None) -> str:
        """Prepare the draft and enqueue the job; returns a short log-safe label. Called
        only after the invitation went out. Never calls Meegle or a vendor itself (the
        runner does). May raise (database): the caller swallows it. Without an account
        the job only carries the «no hay cuenta» comment."""
        from qualify_api.auth.drafts import DraftEmailInvalid, EmailHasAccount  # noqa: PLC0415

        settings = self._settings()
        if not settings.active:
            if settings.enabled:
                logger.warning(
                    "alta prefill: work_item=%s not run, %s (%s)",
                    work_item_id,
                    settings.reason,
                    MAX_USD_ENV,
                )
            return SKIP_OFF
        assert settings.max_usd is not None  # active implies a cap
        try:
            draft = self._start_draft(email, work_item_id)
        except EmailHasAccount:
            # The person already has an account: nothing to prepare before a first login.
            logger.info("alta prefill: work_item=%s email already has an account", work_item_id)
            return SKIP_EMAIL_HAS_ACCOUNT
        except DraftEmailInvalid:
            logger.warning("alta prefill: work_item=%s email refused for a draft", work_item_id)
            return SKIP_DRAFT_EMAIL_INVALID
        brand_id = self._draft_brand(draft.tenant_id)
        if brand_id is None:
            logger.error("alta prefill: work_item=%s draft has no brand", work_item_id)
            return SKIP_NO_BRAND
        inserted = self._jobs.enqueue(
            NewPrefillJob(
                tenant_id=draft.tenant_id,
                brand_id=brand_id,
                meegle_work_item_id=work_item_id,
                network=NETWORK,
                handle=handle or "",
                max_usd=settings.max_usd,
                pipeline_version=PIPELINE_VERSION,
                # no account: nothing to read, only the comment — still once per item
                outcome=None if handle else OUTCOME_NO_HANDLE,
            )
        )
        logger.info(
            "alta prefill: work_item=%s tenant=%s job %s",
            work_item_id,
            draft.tenant_id,
            "enqueued" if inserted else "already queued",
        )
        if not inserted:
            return DUPLICATE
        return ENQUEUED if handle else SKIP_NO_HANDLE


# --------------------------------------------------------------------------------------
# Run (the worker loop)
# --------------------------------------------------------------------------------------

DEFAULT_BATCH = 5


class AltaPrefillRunner:
    def __init__(
        self,
        jobs: PrefillJobs,
        commenter: Commenter,
        *,
        worker_id: str,
        settings: SettingsSource = AltaPrefillSettings.from_env,
        prefill: PrefillFn = _prefill,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._jobs = jobs
        self._comment = commenter
        self._worker = worker_id
        self._settings = settings
        self._prefill = prefill
        self._clock = clock

    def run_once(self, *, limit: int = DEFAULT_BATCH) -> Counter[str]:
        """Drain due jobs, at most `limit` per tenant and round. Two rounds per tenant: the
        prefills, then the comments they just made due — so a job usually ends in one
        pass. Never raises for one job: a job whose step raised keeps its lock and is
        reclaimed after `STALE_AFTER`."""
        report: Counter[str] = Counter()
        for tenant_id in self._jobs.due_tenants(now=self._clock()):
            for _round in range(2):
                jobs = self._jobs.claim(
                    tenant_id, now=self._clock(), worker_id=self._worker, limit=limit
                )
                if not jobs:
                    break
                for job in jobs:
                    try:
                        label = (
                            self._run_prefill(job) if job.needs_prefill else self._post_comment(job)
                        )
                    except Exception:  # noqa: BLE001 — one job never stops the others
                        logger.exception("alta prefill: job=%s failed", job.id)
                        label = "error"
                    report[label] += 1
        return report

    def _run_prefill(self, job: PrefillJob) -> str:
        now = self._clock()
        settings = self._settings()

        def finish(outcome: str, *, written: bool = False, run: dict | None = None) -> str:
            spent = job.spent_usd + (Decimal(str(run["cost_usd"])) if run else Decimal(0))
            comment = comment_for(outcome) is not None
            self._jobs.finish_prefill(
                job,
                worker_id=self._worker,
                now=now,
                outcome=outcome,
                written=written,
                spent_usd=spent,
                run=run,
                comment=comment,
            )
            return "finished" if comment else outcome

        if job.reclaimed or job.attempts > MAX_PREFILL_ATTEMPTS:
            # A worker took it and never recorded what it spent (crash, hang, a failed
            # settlement): running it again could exceed the cap or race that worker.
            logger.warning("alta prefill: job=%s reclaimed, closed without a rerun", job.id)
            return finish(OUTCOME_INTERRUPTED)
        if not settings.active or settings.units is None:
            return finish(OUTCOME_DISABLED)
        caps = caps_for_budget(job.max_usd - job.spent_usd, settings.units)
        if caps is None:
            return finish(OUTCOME_NO_BUDGET)
        result = self._prefill(
            job.tenant_id,
            job.brand_id,
            job.network,
            job.handle,
            source={"kind": "alta", "meegle_work_item_id": job.meegle_work_item_id},
            caps=caps,
            propose=True,
        )
        outcome = result.outcome.value
        if result.ok and not result.written:
            outcome = OUTCOME_NOT_WRITTEN
        cost = usage_cost(result.usage, settings.units)
        run = {
            "attempt": job.attempts,
            "at": now.isoformat(),
            "outcome": outcome,
            "caps": {
                "scrapecreators_requests": caps.scrapecreators_requests,
                "claude_calls": caps.claude_calls,
                "budget_usd": str(job.max_usd - job.spent_usd),
                "units": settings.units.as_document(),
            },
            "usage": result.usage.as_document(),
            "cost_usd": str(cost),
            "detail": result.detail[:200],
        }
        logger.info(
            "alta prefill: job=%s work_item=%s attempt=%d outcome=%s cost_usd=%s",
            job.id,
            job.meegle_work_item_id,
            job.attempts,
            outcome,
            cost,
        )
        if outcome in _TRANSIENT and job.attempts < MAX_PREFILL_ATTEMPTS:
            self._jobs.retry(
                job,
                worker_id=self._worker,
                now=now,
                next_at=now + RETRY_AFTER,
                spent_usd=job.spent_usd + cost,
                run=run,
            )
            return "retry"
        return finish(outcome, written=result.written, run=run)

    def _post_comment(self, job: PrefillJob) -> str:
        now = self._clock()
        text = comment_for(job.outcome or "")
        if text is None:  # nothing to say: settle quietly
            self._jobs.comment_posted(job, worker_id=self._worker, now=now)
            return "done"
        if job.reclaimed:
            # The worker before may have posted it and failed to record it: never twice.
            self._jobs.comment_failed(
                job, worker_id=self._worker, now=now, next_at=None, error=COMMENT_UNCONFIRMED
            )
            return "comment_unconfirmed"
        try:
            self._comment(job.meegle_work_item_id, text)
        except Exception as exc:  # noqa: BLE001 — classified below
            if not _refused(exc):
                # A timeout or a dropped connection may come after Meegle saved it.
                self._jobs.comment_failed(
                    job, worker_id=self._worker, now=now, next_at=None, error=COMMENT_UNCONFIRMED
                )
                logger.warning(
                    "alta prefill: job=%s comment unconfirmed (%s), not retried",
                    job.id,
                    type(exc).__name__,
                )
                return "comment_unconfirmed"
            attempt = max(job.comment_attempts, 1)
            next_at = (
                now + COMMENT_BACKOFF[min(attempt, len(COMMENT_BACKOFF)) - 1]
                if attempt < MAX_COMMENT_ATTEMPTS
                else None
            )
            self._jobs.comment_failed(
                job, worker_id=self._worker, now=now, next_at=next_at, error=type(exc).__name__
            )
            logger.warning(
                "alta prefill: job=%s comment not posted (%s)%s",
                job.id,
                type(exc).__name__,
                "" if next_at else ", given up",
            )
            return "comment_failed"
        self._jobs.comment_posted(job, worker_id=self._worker, now=now)
        return "done"


def _refused(exc: Exception) -> bool:
    """Meegle answered and did not save the comment: its `err_code`, or a 4xx. Anything
    else (transport failure, timeout, 5xx, an unexpected error) may have saved it."""
    if not isinstance(exc, MeegleApiError):
        return False
    if exc.code is not None:  # Meegle's own err_code: it read the request and said no
        return True
    return exc.status is not None and 400 <= exc.status < 500
