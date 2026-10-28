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
  "meegle_work_item_id": <id>}, propose=True)` with the Alta's limits and a dollar meter,
  then ONE comment on the Alta item with the outcome.

**Off by default.** `QUALIFY_ALTA_PREFILL_ENABLED` (`1`/`true`/`yes`/`on`) turns it on and
`QUALIFY_ALTA_PREFILL_MAX_USD` (a positive decimal, USD per Alta) must be set too: no
value lives in code (founder 2026-10-24: the cap is fixed after PB-6 measures). Off,
unset, invalid, or below the cheapest useful run → `schedule` does nothing at all — no
draft, no job, no comment — and the Alta works exactly as before PB-4. A job found while
the setting is off is settled `disabled` without a comment.

**The cost cap: a dollar meter per turn** (m-24854322, `limits_for_budget`). PB6-001
measured that counting calls bounds nothing: one catalog turn at 16,000 output tokens
costs more than the whole cap. So every run carries ONE `claude_tools.DollarMeter` of
`cap - spent` USD:

- every ScrapeCreators request books `SCRAPECREATORS_USD_PER_CREDIT` in it before it is
  sent (one that does not fit is not made);
- every Claude turn is priced before it is sent at its worst — input bound
  (`claude_tools.turn_input_ceiling`) x p_in x 1.25 (cache write) + `max_tokens` x p_out
  — and goes as asked, with a lower `max_tokens` that fits, or not at all
  (`BudgetExhausted`); it is then booked as billed (its reservation when no answer came);
- the Alta's own limits make a full run fit the cap: profile + at most one post page
  (`ALTA_SCRAPECREATORS_CREDITS`), the rubro run at `ALTA_RUBRO_MAX_TOKENS` x
  `ALTA_RUBRO_ATTEMPTS`, the catalog run at `ALTA_CATALOG_MAX_TURNS` x
  `ALTA_CATALOG_MAX_TOKENS` with effort `ALTA_CATALOG_EFFORT` and a «choose now» hint
  before its last turn, and no creation run (`ALTA_CAPS.claude_calls = 2`).
  `worst_case_usd()` is that run with every turn's `max_tokens` full over the measured
  input envelopes (a test pins it under US$0.15); `minimum_run_usd()` (credits + the
  first turn of each Claude run) is the least cap that runs at all.

A refused or cut Claude turn degrades its step — the rubro falls to the profile's
category, the catalog to the account's own tags or the rubro run's — and the run still
ends `OK`: the meter never turns a readable account into a failed Alta. The single retry
gets `cap - spent` (`usage_cost` = what the meter booked), so the two together stay
within the cap; if what is left is under the minimum run, there is no retry. The web
wizard has no meter and keeps its own limits.

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
from decimal import Decimal, InvalidOperation
from functools import partial
from typing import Any, Protocol
from uuid import UUID

from qualify_api.claude_tools import DollarMeter, ModelConfig, worst_turn_usd
from qualify_api.creative.brand_prefill import (
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


#: This queue's version; the prefill's own rides with it (provenance of every job).
#: 3: explicit channel/identifier normalization; no inferred network (m-24882931).
QUEUE_VERSION = 3
PIPELINE_VERSION = f"alta_prefill:{QUEUE_VERSION}+brand_prefill:{PREFILL_VERSION}"

#: ScrapeCreators, plan Freelance: US$47 for 25,000 credits = US$0.00188, rounded up
#: (PB6-001, `docs/modelos-generativos/pruebas.md`; the CLI balance matched the requests
#: counted one to one). One request on the prefill's endpoints is one credit.
SCRAPECREATORS_USD_PER_CREDIT = Decimal("0.0019")

# --------------------------------------------------------------------------------------
# The Alta's limits (m-24854322)
# --------------------------------------------------------------------------------------

#: Snapshot 5 (#348): the Alta reads Instagram's profile alone — 1 credit — and pays
#: for the post list only when the profile's 12 posts do not cover the week
#: (`scrapecreators_client.needs_post_list`); then ONE page at most (`alta_read_profile`
#: passes `max_post_pages`), so a very active account reads a shorter week instead of
#: failing at the ceiling. Was 6 (profile + 5 pages) before snapshot 5.
ALTA_SCRAPECREATORS_CREDITS = 2
#: The rubro run (`from_profile.generate`): PB6-001 measured 245-280 output tokens; the
#: wizard's 4,000 left a 15x unused margin the cap pays for. Two attempts (the second
#: only when the first answered without the tool).
ALTA_RUBRO_MAX_TOKENS = 1_500
ALTA_RUBRO_ATTEMPTS = 2
#: The catalog run (`hashtag_ai.select_hashtags`): PB6-001 measured 3-4 turns and
#: 383-986 output tokens per RUN at effort medium; the wizard allows 8 x 16,000. Three
#: turns, not four: a fourth adds ~US$0.04 to the worst case and breaks the US$0.15 cap.
#: Effort low, and the last turn is told to choose now (`hashtag_ai.LAST_TURN_HINT`).
ALTA_CATALOG_MAX_TURNS = 3
ALTA_CATALOG_MAX_TOKENS = 1_200
ALTA_CATALOG_EFFORT = "low"
#: The rubro run + the catalog run; the third (creating tags when the rubro run gave
#: none) is off in the Alta — PB6-001 never needed it, and the proposal falls to the
#: account's own tags instead.
ALTA_CLAUDE_CALLS = 2
ALTA_CAPS = CallCaps(
    scrapecreators_requests=ALTA_SCRAPECREATORS_CREDITS, claude_calls=ALTA_CLAUDE_CALLS
)
#: The cheapest run that can end in a proposal: the profile + one post page (the
#: structural ceiling), and the first turn of each Claude run.
MIN_RUN_CREDITS = ALTA_SCRAPECREATORS_CREDITS

#: Input envelopes of the computed worst case (tokens; PB6-001's maxima with margin).
#: The meter does not trust them: every real turn is bounded by its own request bytes.
#: Rubro: <= 2,311 measured (bio + 12 captions + system); its retry carries the first
#: answer back (+ its output) and a one-line nudge.
ALTA_RUBRO_INPUT_TOKENS = 2_500
_NUDGE_TOKENS = 100
#: Catalog: the first turn (system + tools + brand + starting candidates) and what each
#: later turn adds besides the previous output (one tool result of <= 25 tags): 5,200 +
#: 7,200 + 9,200 = 21,600 cumulative input, under the 22k PB6-001 allows.
ALTA_CATALOG_INPUT_TOKENS = 5_200
ALTA_CATALOG_RESULT_TOKENS = 800

#: The Claude client of a prefill run: one HTTP wait at most this long per turn and no SDK
#: retries (its defaults are 600 s and 2 retries — over half an hour per turn).
CLAUDE_TIMEOUT_SECONDS = 90.0
#: The turns a run can take at most: the rubro's attempts + the catalog's turns (no
#: creation run in the Alta), each bounded by the timeout above.
CLAUDE_MAX_TURNS = ALTA_RUBRO_ATTEMPTS + ALTA_CATALOG_MAX_TURNS
#: ScrapeCreators: the Alta's credits x the client's 20 s; the picture: 4 hops x 8 s.
_SCRAPECREATORS_SECONDS = ALTA_SCRAPECREATORS_CREDITS * 20.0
_PICTURE_SECONDS = 7 * 4 * 8.0  # profile photo + up to six observed thumbnails
#: The slowest a run can be (~11.9 min) — `prefill_jobs.STALE_AFTER` stays above it.
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
COMMENT_NO_HANDLE = "No se precargó la identidad de marca: no hay cuenta en el Alta."
COMMENT_NO_CHANNEL = "No se precargó la identidad de marca: falta elegir el canal en el Alta."
COMMENT_INVALID_CHANNEL = "No se precargó la identidad de marca: el canal del Alta no es válido."
COMMENT_INVALID_HANDLE = (
    "No se precargó la identidad de marca: la cuenta no es válida para el canal."
)
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
class WorstCase:
    """The dearest run the Alta's limits allow, by part (USD)."""

    credits: Decimal
    rubro: Decimal
    catalog: Decimal

    @property
    def total(self) -> Decimal:
        return self.credits + self.rubro + self.catalog


def _turns(model: str, first_input: int, max_tokens: int, turns: int, added: int) -> Decimal | None:
    """Every turn with its `max_tokens` full: each carries the last one's prompt, its
    output and `added` tokens more (`claude_tools.turn_input_ceiling`'s own rule)."""
    total = Decimal(0)
    prompt = first_input
    for _ in range(turns):
        cost = worst_turn_usd(model, prompt, max_tokens)
        if cost is None:
            return None
        total += cost
        prompt += max_tokens + added
    return total


def worst_case() -> WorstCase | None:
    """The dearest Alta run: every credit, every rubro attempt and every catalog turn
    with its `max_tokens` full over the input envelopes. None when a model has no
    price (refuse to guess a zero)."""
    rubro = _turns(
        from_profile.MODEL,
        ALTA_RUBRO_INPUT_TOKENS,
        ALTA_RUBRO_MAX_TOKENS,
        ALTA_RUBRO_ATTEMPTS,
        _NUDGE_TOKENS,
    )
    catalog = _turns(
        hashtag_ai.SELECT_MODEL,
        ALTA_CATALOG_INPUT_TOKENS,
        ALTA_CATALOG_MAX_TOKENS,
        ALTA_CATALOG_MAX_TURNS,
        ALTA_CATALOG_RESULT_TOKENS,
    )
    if rubro is None or catalog is None:
        return None
    return WorstCase(ALTA_SCRAPECREATORS_CREDITS * SCRAPECREATORS_USD_PER_CREDIT, rubro, catalog)


def worst_case_usd() -> Decimal | None:
    worst = worst_case()
    return worst.total if worst is not None else None


def minimum_run_usd() -> Decimal | None:
    """The least cap worth running: the structural credits and the first turn of each
    Claude run, full. Below it the prefill does not run at all."""
    rubro = worst_turn_usd(from_profile.MODEL, ALTA_RUBRO_INPUT_TOKENS, ALTA_RUBRO_MAX_TOKENS)
    catalog = worst_turn_usd(
        hashtag_ai.SELECT_MODEL, ALTA_CATALOG_INPUT_TOKENS, ALTA_CATALOG_MAX_TOKENS
    )
    if rubro is None or catalog is None:
        return None
    return MIN_RUN_CREDITS * SCRAPECREATORS_USD_PER_CREDIT + rubro + catalog


@dataclass(frozen=True)
class AltaLimits:
    """What one attempt may use: `budget_usd` for its dollar meter and the Alta's call
    counts and per-run Claude limits."""

    budget_usd: Decimal
    caps: CallCaps = ALTA_CAPS

    def as_document(self) -> dict[str, Any]:
        worst = worst_case()
        return {
            "budget_usd": str(self.budget_usd),
            "scrapecreators_requests": self.caps.scrapecreators_requests,
            "claude_calls": self.caps.claude_calls,
            "scrapecreators_usd_per_credit": str(SCRAPECREATORS_USD_PER_CREDIT),
            "rubro": {"max_tokens": ALTA_RUBRO_MAX_TOKENS, "attempts": ALTA_RUBRO_ATTEMPTS},
            "catalog": {
                "max_turns": ALTA_CATALOG_MAX_TURNS,
                "max_tokens": ALTA_CATALOG_MAX_TOKENS,
                "effort": ALTA_CATALOG_EFFORT,
            },
            "worst_case_usd": str(worst.total) if worst is not None else None,
        }


def limits_for_budget(budget_usd: Decimal) -> AltaLimits | None:
    """The limits of an attempt with `budget_usd` left; None when it is under the
    minimum run (or a model has no price)."""
    minimum = minimum_run_usd()
    if minimum is None or budget_usd < minimum:
        return None
    return AltaLimits(budget_usd=budget_usd)


def usage_cost(usage: PrefillUsage) -> Decimal:
    """What an attempt really cost: what its dollar meter booked (credits + every turn
    as billed, a turn with no answer at its reservation). Without a meter (a fake, an
    older row): credits at the unit price + Claude as measured, and a run whose tokens
    were lost charged its worst case — a retry never gets budget it does not have."""
    if usage.metered_usd is not None:
        return usage.metered_usd
    claude = Decimal(str(round(usage.claude_cost_usd, 6)))
    if not usage.claude_tokens_complete:
        worst = worst_case()
        claude = max(claude, (worst.rubro + worst.catalog) if worst else claude)
    return usage.scrapecreators_credits * SCRAPECREATORS_USD_PER_CREDIT + claude


# --------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AltaPrefillSettings:
    """Read on every use, so a change of `.env` + restart is all it takes. `active` only
    when on AND the cap pays at least the minimum run; `reason` says why not (logs only)."""

    enabled: bool
    max_usd: Decimal | None = None
    limits: AltaLimits | None = None
    reason: str = ""

    @property
    def active(self) -> bool:
        return self.enabled and self.limits is not None

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
        if minimum_run_usd() is None:
            return cls(enabled=True, max_usd=max_usd, reason="model_price_unknown")
        limits = limits_for_budget(max_usd)
        if limits is None:
            return cls(enabled=True, max_usd=max_usd, reason="max_usd_below_minimum_run")
        return cls(enabled=True, max_usd=max_usd, limits=limits)


def comment_for(outcome: str, network: str = "instagram") -> str | None:
    """The comment a finished job writes on the Alta; None = no comment."""
    if outcome == PrefillOutcome.OK.value:
        return COMMENT_OK
    if outcome == PrefillOutcome.PRIVATE_ACCOUNT.value:
        return COMMENT_PRIVATE.replace(
            "Instagram", "TikTok" if network == "tiktok" else "Instagram"
        )
    if outcome == OUTCOME_NO_HANDLE:
        return COMMENT_NO_HANDLE
    if outcome in {"no_channel", "invalid_channel", "invalid_handle"}:
        return {
            "no_channel": COMMENT_NO_CHANNEL,
            "invalid_channel": COMMENT_INVALID_CHANNEL,
            "invalid_handle": COMMENT_INVALID_HANDLE,
        }[outcome]
    if outcome == OUTCOME_DISABLED:
        return None
    return COMMENT_UNREADABLE.replace("Instagram", "TikTok" if network == "tiktok" else "Instagram")


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
        budget_usd: Decimal = ...,
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


def alta_read_profile(network: str, handle: str, client: Any) -> dict[str, Any]:
    """The Alta's account read: snapshot 5's 1-credit Instagram read (no AI labels: the
    Alta records no growth history) with at most ONE post-list page, so the read never
    asks for more than `ALTA_SCRAPECREATORS_CREDITS`."""
    from qualify_api.referentes import scrapecreators_client  # noqa: PLC0415

    return scrapecreators_client.fetch_profile_and_posts(
        network,
        handle,
        client=client,
        ai_labels=False,
        max_post_pages=ALTA_SCRAPECREATORS_CREDITS - 1,
    )


def bounded_ports(meter: DollarMeter | None = None) -> Any:
    """The prefill's real ports, with both Claude callers on `bounded_claude_client`.
    With the run's `meter` (the Alta): the Alta's read and Claude limits, every turn
    booked in it, and a failed catalog run answering no tags (not the rule path)."""
    from qualify_api.creative.brand_prefill import (  # noqa: PLC0415
        CatalogHashtags,
        PrefillPorts,
        catalog_prompt_version,
    )

    if meter is None:
        return PrefillPorts(
            generate=partial(from_profile.generate, client_factory=bounded_claude_client),
            catalog=CatalogHashtags(
                selector=partial(hashtag_ai.select_hashtags, client_factory=bounded_claude_client)
            ),
        )
    return PrefillPorts(
        read_profile=alta_read_profile,
        generate=partial(
            from_profile.generate,
            client_factory=bounded_claude_client,
            max_tokens=ALTA_RUBRO_MAX_TOKENS,
            attempts=ALTA_RUBRO_ATTEMPTS,
            budget=meter,
        ),
        catalog=CatalogHashtags(
            selector=partial(
                hashtag_ai.select_hashtags,
                client_factory=bounded_claude_client,
                config=ModelConfig(hashtag_ai.SELECT_MODEL, ALTA_CATALOG_EFFORT),
                max_turns=ALTA_CATALOG_MAX_TURNS,
                max_tokens=ALTA_CATALOG_MAX_TOKENS,
                budget=meter,
                last_turn_hint=True,
            ),
            rule_fallback=False,
            prompt_version=catalog_prompt_version(
                ALTA_CATALOG_EFFORT, max_turns=ALTA_CATALOG_MAX_TURNS, last_turn_hint=True
            ),
        ),
    )


def metered_prefill(
    *args: Any,
    budget_usd: Decimal,
    ports: Callable[[DollarMeter], Any] = bounded_ports,
    **kwargs: Any,
) -> PrefillResult:
    """One metered Alta attempt: a fresh `DollarMeter` of `budget_usd`, the Alta's ports
    on it (`ports(meter)`; tests wrap `bounded_ports` with fakes), the credits booked in
    it, and no creation run."""
    from qualify_api.creative.brand_prefill import prefill_brand_kit  # noqa: PLC0415

    meter = DollarMeter(budget_usd)
    return prefill_brand_kit(
        *args,
        ports=ports(meter),
        meter=meter,
        credit_usd=SCRAPECREATORS_USD_PER_CREDIT,
        create_hashtags=False,
        **kwargs,
    )


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

    def schedule(
        self,
        work_item_id: int,
        *,
        email: str,
        network: str | None,
        handle: str | None,
        account_reason: str = "",
    ) -> str:
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
        from qualify_api.meegle.handles import normalize_channel, normalize_handle

        network = normalize_channel(network)
        if network is None:
            account_reason = (
                "invalid_channel" if account_reason == "invalid_channel" else "no_channel"
            )
            handle = None
        else:
            normalized = normalize_handle(network, handle)
            if handle and not normalized:
                account_reason = "invalid_handle"
            handle = normalized
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
                network=network or "",
                handle=handle or "",
                max_usd=settings.max_usd,
                pipeline_version=PIPELINE_VERSION,
                # no account: nothing to read, only the comment — still once per item
                outcome=None if handle else (account_reason or OUTCOME_NO_HANDLE),
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
        return ENQUEUED if handle else (account_reason or SKIP_NO_HANDLE)


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
        prefill: PrefillFn = metered_prefill,
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
        if not settings.active:
            return finish(OUTCOME_DISABLED)
        limits = limits_for_budget(job.max_usd - job.spent_usd)
        if limits is None:
            return finish(OUTCOME_NO_BUDGET)
        result = self._prefill(
            job.tenant_id,
            job.brand_id,
            job.network,
            job.handle,
            source={"kind": "alta", "meegle_work_item_id": job.meegle_work_item_id},
            caps=limits.caps,
            propose=True,
            budget_usd=limits.budget_usd,
        )
        outcome = result.outcome.value
        if result.ok and not result.written:
            outcome = OUTCOME_NOT_WRITTEN
        cost = usage_cost(result.usage)
        run = {
            "attempt": job.attempts,
            "at": now.isoformat(),
            "outcome": outcome,
            "limits": limits.as_document(),
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
        text = comment_for(job.outcome or "", job.network)
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
