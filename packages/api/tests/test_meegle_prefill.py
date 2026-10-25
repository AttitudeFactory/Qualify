"""PB-4 (m-24852198): the Brand Kit prefill of an «Alta de cliente», offline.

Pins: off by default (the Alta works exactly as before), the cost cap → the Alta's
limits and its refusal below the minimum run (the dollar meter itself:
`test_alta_dollar_meter.py`), idempotency per item + username, exactly
one retry and only for a transient failure, the literal Meegle comments, and that nothing
the prefill does can turn a sent invitation into a retried event."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.auth.drafts import EmailHasAccount
from qualify_api.creative.brand_prefill import (
    DEFAULT_CAPS,
    CallCaps,
    PrefillOutcome,
    PrefillResult,
    PrefillUsage,
)
from qualify_api.meegle import prefill as mod
from qualify_api.meegle.client import MeegleApiError
from qualify_api.meegle.handlers import meegle_handlers
from qualify_api.meegle.onboarding import InvitationResult
from qualify_api.meegle.prefill import (
    COMMENT_NO_HANDLE,
    COMMENT_OK,
    COMMENT_PRIVATE,
    COMMENT_UNREADABLE,
    ENABLED_ENV,
    MAX_USD_ENV,
    AltaPrefillRunner,
    AltaPrefillScheduler,
    AltaPrefillSettings,
    limits_for_budget,
    minimum_run_usd,
    usage_cost,
)
from qualify_api.meegle.prefill_jobs import (
    STALE_AFTER,
    STATUS_DONE,
    STATUS_PENDING,
    InMemoryPrefillJobs,
)
from qualify_api.meegle.settings import MeegleNames
from qualify_api.webhooks.processor import Processor
from qualify_api.webhooks.repository import ClaimedEvent

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
ITEM = 24852198
EMAIL = "hlrd1993+alta@gmail.com"
CREDIT = mod.SCRAPECREATORS_USD_PER_CREDIT


def _on(max_usd: str = "1") -> AltaPrefillSettings:
    return AltaPrefillSettings.from_env({ENABLED_ENV: "1", MAX_USD_ENV: max_usd})


OFF = AltaPrefillSettings.from_env({})


# --------------------------------------------------------------------------------------
# The cap
# --------------------------------------------------------------------------------------


def test_below_the_minimum_run_the_cap_refuses() -> None:
    minimum = minimum_run_usd()
    # 2 credits + the first rubro turn (2,500 in x 2.5e-6 + 1,500 out x 1e-5) + the first
    # catalog turn (5,200 in x 2.5e-6 + 1,200 out x 1e-5), claude-sonnet-5 at (2, 10)
    assert minimum == Decimal("0.0038") + Decimal("0.02125") + Decimal("0.025")
    assert limits_for_budget(minimum - Decimal("0.000001")) is None
    limits = limits_for_budget(minimum)
    assert limits is not None and limits.caps == mod.ALTA_CAPS
    assert limits.budget_usd == minimum


def test_the_alta_limits_are_the_same_at_any_cap_only_the_meter_changes() -> None:
    for budget in ("0.06", "0.15", "50"):
        limits = limits_for_budget(Decimal(budget))
        assert limits is not None
        assert limits.caps == CallCaps(scrapecreators_requests=2, claude_calls=2)
        assert limits.budget_usd == Decimal(budget)


def test_usage_cost_is_what_the_meter_booked() -> None:
    metered = PrefillUsage(
        scrapecreators_credits=2, claude_calls=2, claude_cost_usd=0.01, metered_usd=Decimal("0.03")
    )
    assert usage_cost(metered) == Decimal("0.03")


def test_without_a_meter_lost_tokens_are_charged_at_the_worst_case() -> None:
    usage = PrefillUsage(scrapecreators_credits=2, claude_calls=2, claude_cost_usd=0.01)
    assert usage_cost(usage) == 2 * CREDIT + Decimal("0.01")
    lost = PrefillUsage(
        scrapecreators_credits=1, claude_calls=1, claude_cost_usd=0.0, claude_tokens_complete=False
    )
    worst = mod.worst_case()
    assert worst is not None
    assert usage_cost(lost) == CREDIT + worst.rubro + worst.catalog


# --------------------------------------------------------------------------------------
# Settings: off by default, no value in code
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "reason"),
    [
        ({}, "disabled"),
        ({ENABLED_ENV: "0", MAX_USD_ENV: "1"}, "disabled"),
        ({ENABLED_ENV: "on"}, "max_usd_not_set"),
        ({ENABLED_ENV: "true", MAX_USD_ENV: "diez"}, "max_usd_invalid"),
        ({ENABLED_ENV: "yes", MAX_USD_ENV: "-1"}, "max_usd_invalid"),
        ({ENABLED_ENV: "1", MAX_USD_ENV: "NaN"}, "max_usd_invalid"),
        ({ENABLED_ENV: "1", MAX_USD_ENV: "0.01"}, "max_usd_below_minimum_run"),
        ({ENABLED_ENV: "1", MAX_USD_ENV: "0.05"}, "max_usd_below_minimum_run"),
    ],
)
def test_the_prefill_is_inactive_unless_on_and_capped(env: dict[str, str], reason: str) -> None:
    settings = AltaPrefillSettings.from_env(env)
    assert not settings.active and settings.reason == reason


def test_the_process_environment_has_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENABLED_ENV, raising=False)
    monkeypatch.delenv(MAX_USD_ENV, raising=False)
    assert not AltaPrefillSettings.from_env().active


def test_on_with_a_cap_is_active() -> None:
    settings = _on("1")
    assert settings.active and settings.max_usd == 1
    assert settings.limits is not None and settings.limits.caps == mod.ALTA_CAPS


# --------------------------------------------------------------------------------------
# The scheduler
# --------------------------------------------------------------------------------------


@dataclass
class _Draft:
    tenant_id: UUID


class World:
    """The scheduler's and runner's seams, recorded."""

    def __init__(self, settings: AltaPrefillSettings) -> None:
        self.settings = settings
        self.jobs = InMemoryPrefillJobs()
        self.comments: list[tuple[int, str]] = []
        self.drafts: dict[int, UUID] = {}
        self.draft_calls: list[tuple[str, int]] = []
        self.brands: dict[UUID, UUID] = {}
        self.draft_raises: Exception | None = None
        self.comment_raises: Exception | None = None
        self.results: list[PrefillResult] = []
        self.prefill_calls: list[dict[str, Any]] = []
        self.clock = NOW

    def comment(self, work_item_id: int, text: str) -> None:
        if self.comment_raises is not None:
            raise self.comment_raises
        self.comments.append((work_item_id, text))

    def start_draft(self, email: str, work_item_id: int) -> _Draft:
        self.draft_calls.append((email, work_item_id))
        if self.draft_raises is not None:
            raise self.draft_raises
        tenant = self.drafts.setdefault(work_item_id, uuid4())
        self.brands.setdefault(tenant, uuid4())
        return _Draft(tenant)

    def prefill(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        network: str,
        handle: str,
        *,
        source: dict[str, Any] | None = None,
        caps: CallCaps = DEFAULT_CAPS,
        propose: bool = True,
        budget_usd: Decimal | None = None,
    ) -> PrefillResult:
        self.prefill_calls.append(
            {
                "tenant_id": tenant_id,
                "brand_id": brand_id,
                "network": network,
                "handle": handle,
                "source": source,
                "caps": caps,
                "propose": propose,
                "budget_usd": budget_usd,
            }
        )
        return self.results.pop(0)

    def scheduler(self) -> AltaPrefillScheduler:
        return AltaPrefillScheduler(
            self.jobs,
            self.comment,
            settings=lambda: self.settings,
            start_draft=self.start_draft,
            draft_brand=self.brands.get,
        )

    def runner(self) -> AltaPrefillRunner:
        return AltaPrefillRunner(
            self.jobs,
            self.comment,
            worker_id="w1",
            settings=lambda: self.settings,
            prefill=self.prefill,
            clock=lambda: self.clock,
        )


def _result(
    outcome: PrefillOutcome, *, written: bool | None = None, usage: PrefillUsage | None = None
) -> PrefillResult:
    return PrefillResult(
        outcome,
        "instagram",
        "bianki.ve",
        written=outcome is PrefillOutcome.OK if written is None else written,
        usage=usage or PrefillUsage(scrapecreators_requests=2, scrapecreators_credits=2),
    )


def test_off_the_scheduler_does_nothing_at_all() -> None:
    world = World(OFF)
    assert world.scheduler().schedule(ITEM, email=EMAIL, handle="bianki.ve") == ""
    assert world.scheduler().schedule(ITEM, email=EMAIL, handle=None) == ""
    assert (world.draft_calls, world.jobs.rows, world.comments) == ([], {}, [])


def test_misconfigured_is_the_same_as_off() -> None:
    world = World(AltaPrefillSettings.from_env({ENABLED_ENV: "1"}))  # no cap
    assert world.scheduler().schedule(ITEM, email=EMAIL, handle="bianki.ve") == ""
    assert (world.draft_calls, world.jobs.rows, world.comments) == ([], {}, [])


def test_no_handle_comments_once_per_item_even_when_replayed() -> None:
    world = World(_on())
    scheduler = world.scheduler()
    assert scheduler.schedule(ITEM, email=EMAIL, handle=None) == "no_handle"
    assert scheduler.schedule(ITEM, email=EMAIL, handle=None) == "duplicate"  # a replay
    assert world.comments == []  # the runner writes it, outside the event
    (row,) = world.jobs.rows.values()
    assert (row.job.handle, row.job.outcome, row.status) == ("", "no_handle", "commenting")
    for _ in range(3):
        world.runner().run_once()
        world.clock += timedelta(hours=1)
    assert world.comments == [(ITEM, COMMENT_NO_HANDLE)]
    assert world.prefill_calls == [] and row.status == STATUS_DONE
    # the account added later is a new key: that one does run
    assert scheduler.schedule(ITEM, email=EMAIL, handle="bianki.ve") == "enqueued"


def test_a_handle_prepares_the_draft_and_enqueues_one_job() -> None:
    world = World(_on("0.5"))
    assert world.scheduler().schedule(ITEM, email=EMAIL, handle="bianki.ve") == "enqueued"
    assert world.draft_calls == [(EMAIL, ITEM)]
    (row,) = world.jobs.rows.values()
    tenant = world.drafts[ITEM]
    assert (row.job.tenant_id, row.job.brand_id) == (tenant, world.brands[tenant])
    assert (row.job.meegle_work_item_id, row.job.network, row.job.handle) == (
        ITEM,
        "instagram",
        "bianki.ve",
    )
    assert row.job.max_usd == Decimal("0.5") and row.status == STATUS_PENDING
    assert row.pipeline_version.startswith("alta_prefill:2+brand_prefill:")
    assert world.comments == []  # the comment comes when the job is done


def test_datos_twice_is_one_job_and_a_new_username_is_a_new_one() -> None:
    world = World(_on())
    scheduler = world.scheduler()
    assert scheduler.schedule(ITEM, email=EMAIL, handle="bianki.ve") == "enqueued"
    assert scheduler.schedule(ITEM, email=EMAIL, handle="bianki.ve") == "duplicate"
    assert len(world.jobs.rows) == 1
    assert scheduler.schedule(ITEM, email=EMAIL, handle="bianki.oficial") == "enqueued"
    assert sorted(r.job.handle for r in world.jobs.rows.values()) == [
        "bianki.oficial",
        "bianki.ve",
    ]


def test_an_email_with_an_account_gets_no_job() -> None:
    world = World(_on())
    world.draft_raises = EmailHasAccount()
    assert world.scheduler().schedule(ITEM, email=EMAIL, handle="bianki.ve") == (
        "email_has_account"
    )
    assert world.jobs.rows == {} and world.comments == []


# --------------------------------------------------------------------------------------
# The runner
# --------------------------------------------------------------------------------------


def _enqueued(world: World, handle: str = "bianki.ve") -> None:
    assert world.scheduler().schedule(ITEM, email=EMAIL, handle=handle) == "enqueued"


def _status(world: World) -> str:
    (row,) = world.jobs.rows.values()
    return row.status


def test_ok_writes_the_proposal_and_comments_success() -> None:
    world = World(_on())
    _enqueued(world)
    world.results = [_result(PrefillOutcome.OK)]
    report = world.runner().run_once()
    assert report["done"] == 1
    (call,) = world.prefill_calls
    tenant = world.drafts[ITEM]
    assert call == {
        "tenant_id": tenant,
        "brand_id": world.brands[tenant],
        "network": "instagram",
        "handle": "bianki.ve",
        "source": {"kind": "alta", "meegle_work_item_id": ITEM},
        "caps": mod.ALTA_CAPS,
        "propose": True,
        "budget_usd": Decimal("1"),
    }
    assert world.comments == [(ITEM, COMMENT_OK)]
    assert _status(world) == STATUS_DONE
    # a second pass finds nothing: no second charge, no second comment
    world.clock += timedelta(hours=1)
    world.runner().run_once()
    assert len(world.prefill_calls) == 1 and len(world.comments) == 1


@pytest.mark.parametrize(
    ("outcome", "comment"),
    [
        (PrefillOutcome.PRIVATE_ACCOUNT, COMMENT_PRIVATE),
        (PrefillOutcome.NOT_FOUND, COMMENT_UNREADABLE),
        (PrefillOutcome.CAP_REACHED, COMMENT_UNREADABLE),
        (PrefillOutcome.ACCOUNT_TAKEN, COMMENT_UNREADABLE),
    ],
)
def test_final_failures_are_not_retried(outcome: PrefillOutcome, comment: str) -> None:
    world = World(_on())
    _enqueued(world)
    world.results = [_result(outcome)]
    world.runner().run_once()
    world.clock += timedelta(hours=1)
    world.runner().run_once()
    assert len(world.prefill_calls) == 1
    assert world.comments == [(ITEM, comment)]
    assert _status(world) == STATUS_DONE


def test_a_read_failure_is_retried_exactly_once() -> None:
    world = World(_on())
    _enqueued(world)
    world.results = [_result(PrefillOutcome.READ_FAILED), _result(PrefillOutcome.READ_FAILED)]
    assert world.runner().run_once()["retry"] == 1
    assert world.comments == [] and _status(world) == STATUS_PENDING
    world.runner().run_once()  # not due yet
    assert len(world.prefill_calls) == 1
    world.clock += mod.RETRY_AFTER
    world.runner().run_once()
    world.clock += timedelta(hours=1)
    world.runner().run_once()
    assert len(world.prefill_calls) == 2
    assert world.comments == [(ITEM, COMMENT_UNREADABLE)]
    (row,) = world.jobs.rows.values()
    assert [r["outcome"] for r in row.job.runs] == ["read_failed", "read_failed"]


def test_a_retry_after_a_read_failure_can_still_succeed() -> None:
    world = World(_on())
    _enqueued(world)
    world.results = [_result(PrefillOutcome.READ_FAILED), _result(PrefillOutcome.OK)]
    world.runner().run_once()
    world.clock += mod.RETRY_AFTER
    world.runner().run_once()
    assert world.comments == [(ITEM, COMMENT_OK)]


def test_the_retry_only_spends_what_the_first_attempt_left() -> None:
    world = World(_on("0.15"))
    _enqueued(world)
    spent = Decimal("0.11")  # what the first attempt's meter booked
    expensive = PrefillUsage(scrapecreators_credits=2, claude_calls=2, metered_usd=spent)
    world.results = [_result(PrefillOutcome.READ_FAILED, usage=expensive)]
    world.runner().run_once()
    world.clock += mod.RETRY_AFTER
    world.runner().run_once()
    # 0.04 left is under the minimum run, so no second prefill
    assert len(world.prefill_calls) == 1
    assert world.prefill_calls[0]["budget_usd"] == Decimal("0.15")
    assert world.comments == [(ITEM, COMMENT_UNREADABLE)]
    (row,) = world.jobs.rows.values()
    assert row.job.outcome == mod.OUTCOME_NO_BUDGET
    assert row.job.spent_usd == spent


def test_the_retry_gets_the_cap_minus_what_the_first_attempt_booked() -> None:
    world = World(_on("0.15"))
    _enqueued(world)
    first = PrefillUsage(scrapecreators_credits=1, claude_calls=0, metered_usd=Decimal("0.0019"))
    world.results = [
        _result(PrefillOutcome.READ_FAILED, usage=first),
        _result(PrefillOutcome.OK),
    ]
    world.runner().run_once()
    world.clock += mod.RETRY_AFTER
    world.runner().run_once()
    assert [c["budget_usd"] for c in world.prefill_calls] == [
        Decimal("0.15"),
        Decimal("0.15") - Decimal("0.0019"),
    ]
    assert world.comments == [(ITEM, COMMENT_OK)]


def test_an_unwritten_proposal_is_a_transient_failure() -> None:
    world = World(_on())
    _enqueued(world)
    world.results = [
        _result(PrefillOutcome.OK, written=False),
        _result(PrefillOutcome.OK, written=False),
    ]
    world.runner().run_once()
    world.clock += mod.RETRY_AFTER
    world.runner().run_once()
    assert len(world.prefill_calls) == 2
    assert world.comments == [(ITEM, COMMENT_UNREADABLE)]


def test_a_job_found_while_off_is_settled_quietly() -> None:
    world = World(_on())
    _enqueued(world)
    world.settings = OFF
    world.runner().run_once()
    assert world.prefill_calls == [] and world.comments == []
    (row,) = world.jobs.rows.values()
    assert row.status == STATUS_DONE and row.job.outcome == mod.OUTCOME_DISABLED


def test_a_refused_comment_is_retried_then_given_up_without_rerunning_the_prefill() -> None:
    world = World(_on())
    _enqueued(world)
    world.results = [_result(PrefillOutcome.OK)]
    world.comment_raises = MeegleApiError("Meegle refused (429)", code=429, status=200)
    for _ in range(5):
        world.runner().run_once()
        world.clock += timedelta(minutes=30)
    assert len(world.prefill_calls) == 1
    (row,) = world.jobs.rows.values()
    assert row.status == STATUS_DONE and row.last_error == "MeegleApiError"
    assert row.job.comment_attempts == mod.MAX_COMMENT_ATTEMPTS


@pytest.mark.parametrize(
    "error",
    [
        MeegleApiError("could not reach Meegle (comment)"),  # transport / timeout
        MeegleApiError("Meegle answered 502", status=502),
        RuntimeError("unexpected"),
    ],
)
def test_a_comment_that_may_have_been_saved_is_never_posted_again(error: Exception) -> None:
    world = World(_on())
    _enqueued(world)
    world.results = [_result(PrefillOutcome.OK)]
    world.comment_raises = error
    world.runner().run_once()
    world.comment_raises = None
    for _ in range(3):
        world.clock += timedelta(hours=1)
        world.runner().run_once()
    assert world.comments == []  # the one try may be on the item; none after it
    (row,) = world.jobs.rows.values()
    assert row.status == STATUS_DONE and row.last_error == mod.COMMENT_UNCONFIRMED
    assert row.job.comment_attempts == 1


class _FailingSettle(InMemoryPrefillJobs):
    """`comment_posted` / `finish_prefill` fail once after the side effect happened."""

    fail_finish: bool = False
    fail_posted: bool = False

    def finish_prefill(self, job, **kw):  # noqa: ANN001, ANN003, ANN201
        if self.fail_finish:
            self.fail_finish = False
            raise RuntimeError("database down")
        return super().finish_prefill(job, **kw)

    def comment_posted(self, job, **kw):  # noqa: ANN001, ANN003, ANN201
        if self.fail_posted:
            self.fail_posted = False
            raise RuntimeError("database down")
        return super().comment_posted(job, **kw)


def test_a_comment_posted_but_not_recorded_is_not_posted_again() -> None:
    world = World(_on())
    world.jobs = _FailingSettle()
    _enqueued(world)
    world.results = [_result(PrefillOutcome.OK)]
    world.jobs.fail_posted = True
    world.runner().run_once()
    assert world.comments == [(ITEM, COMMENT_OK)]
    world.clock += STALE_AFTER + timedelta(minutes=1)
    world.runner().run_once()  # reclaimed in its comment phase
    assert world.comments == [(ITEM, COMMENT_OK)]
    (row,) = world.jobs.rows.values()
    assert row.status == STATUS_DONE and row.last_error == mod.COMMENT_UNCONFIRMED


def test_a_crash_mid_run_is_closed_not_rerun_and_never_exceeds_the_cap() -> None:
    """The worker ran the vendor, then died before recording the spend: the reclaimed job
    must not get the whole cap again."""
    world = World(_on("0.15"))
    world.jobs = _FailingSettle()
    _enqueued(world)
    world.results = [_result(PrefillOutcome.OK)]
    world.jobs.fail_finish = True  # the run happened; its outcome and spend are lost
    assert world.runner().run_once()["error"] == 1
    assert len(world.prefill_calls) == 1
    world.runner().run_once()  # still locked: not due yet
    world.clock += STALE_AFTER + timedelta(minutes=1)
    world.runner().run_once()
    assert len(world.prefill_calls) == 1  # no second run, no second charge
    assert world.comments == [(ITEM, COMMENT_UNREADABLE)]
    (row,) = world.jobs.rows.values()
    assert row.job.outcome == mod.OUTCOME_INTERRUPTED and row.status == STATUS_DONE


def test_a_crash_after_the_retry_was_scheduled_keeps_the_one_retry() -> None:
    world = World(_on())
    _enqueued(world)
    world.results = [_result(PrefillOutcome.READ_FAILED)]
    world.runner().run_once()  # attempt 1 recorded, retry scheduled
    world.clock += mod.RETRY_AFTER
    (row,) = world.jobs.rows.values()
    world.jobs.claim(row.job.tenant_id, now=world.clock, worker_id="dead", limit=1)  # dies
    world.clock += STALE_AFTER + timedelta(minutes=1)
    world.runner().run_once()
    assert len(world.prefill_calls) == 1  # the retry's worker died: no third chance
    assert row.job.outcome == mod.OUTCOME_INTERRUPTED
    assert world.comments == [(ITEM, COMMENT_UNREADABLE)]


def test_a_live_run_is_never_taken_for_a_dead_one() -> None:
    assert mod.MAX_RUN_SECONDS < STALE_AFTER.total_seconds() * 0.8
    # 5 Claude turns (2 rubro attempts + 3 catalog turns) x 90 s + 2 credits x 20 s + the
    # picture's 4 hops x 8 s: ~8.7 min against a 30 min window (was 5 x 90 + 120 + 32)
    assert mod.CLAUDE_MAX_TURNS == 5
    assert mod.MAX_RUN_SECONDS == 5 * 90 + 2 * 20 + 32 == 522


def test_the_real_prefill_runs_claude_through_the_bounded_client() -> None:
    ports = mod.bounded_ports()
    assert ports.generate.keywords["client_factory"] is mod.bounded_claude_client
    assert ports.catalog.selector.keywords["client_factory"] is mod.bounded_claude_client
    metered = mod.bounded_ports(mod.DollarMeter(Decimal("0.15")))
    assert metered.generate.keywords["client_factory"] is mod.bounded_claude_client
    assert metered.catalog.selector.keywords["client_factory"] is mod.bounded_claude_client
    client = mod.bounded_claude_client("sk-test")
    assert client.max_retries == 0 and client.timeout == mod.CLAUDE_TIMEOUT_SECONDS


def test_jobs_of_one_tenant_are_claimed_only_under_that_tenant() -> None:
    world = World(_on())
    _enqueued(world)
    other = uuid4()
    assert world.jobs.claim(other, now=NOW, worker_id="w1", limit=5) == []
    assert world.jobs.due_tenants(now=NOW) == [world.drafts[ITEM]]


# --------------------------------------------------------------------------------------
# Inside the «Datos» handler
# --------------------------------------------------------------------------------------


class _Queue:
    def __init__(self, events: list[ClaimedEvent]) -> None:
        self.events = events
        self.settled: list[tuple[str, str | None]] = []
        self.failed: list[str] = []

    def claim(self, *, worker_id: str, now: datetime, limit: int) -> list[ClaimedEvent]:
        batch, self.events = self.events, []
        return batch

    def settle(self, *, event_id, worker_id, now, status, error=None) -> bool:  # noqa: ANN001
        self.settled.append((status, error))
        return True

    def fail(self, *, event_id, worker_id, now, attempts, error) -> str | None:  # noqa: ANN001
        self.failed.append(error)
        return "failed"


class _Engine:
    def __init__(self, handle: str | None) -> None:
        self.started = 0
        self.handle = handle

    def node_name(self, work_item_id: int, key: str) -> str | None:
        return "Datos"

    def start_invitation(self, work_item_id: int, **_: str) -> InvitationResult:
        self.started += 1
        return InvitationResult(
            ok=True, invite_id=uuid4(), instagram_handle=self.handle, email=EMAIL
        )


def _datos(meegle_events: Any) -> ClaimedEvent:
    return ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object="meegle",
        entry_id=str(ITEM),
        field="2001",
        value=meegle_events.value(nodes=["started"], work_item_id=ITEM),
        attempts=1,
    )


async def _process(engine: _Engine, scheduler: Any, *events: ClaimedEvent) -> _Queue:
    queue = _Queue(list(events))
    processor = Processor(
        queue=queue,
        handlers=meegle_handlers(
            engine,  # type: ignore[arg-type]
            work_item_type="alta_cliente",
            names=MeegleNames(),
            prefill=scheduler,
        ),
        worker_id="w1",
        clock=lambda: NOW,
    )
    await processor.run_once()
    return queue


async def test_off_the_datos_event_settles_exactly_as_before(meegle_events: Any) -> None:
    world = World(OFF)
    queue = await _process(_Engine("bianki.ve"), world.scheduler(), _datos(meegle_events))
    assert queue.settled == [("processed", None)]
    assert world.jobs.rows == {} and world.comments == []


async def test_on_the_datos_event_enqueues_and_names_it(meegle_events: Any) -> None:
    world = World(_on())
    engine = _Engine("bianki.ve")
    queue = await _process(
        engine, world.scheduler(), _datos(meegle_events), _datos(meegle_events)
    )  # a replay too
    assert queue.settled == [("processed", "prefill=enqueued"), ("processed", "prefill=duplicate")]
    assert len(world.jobs.rows) == 1
    assert world.prefill_calls == []  # never inside the event: the runner does it


async def test_on_without_a_handle_the_event_comments_the_reason(meegle_events: Any) -> None:
    world = World(_on())
    queue = await _process(_Engine(None), world.scheduler(), _datos(meegle_events))
    assert queue.settled == [("processed", "prefill=no_handle")]
    assert world.comments == []  # never a Meegle call inside the event
    world.runner().run_once()
    assert world.comments == [(ITEM, COMMENT_NO_HANDLE)]


async def test_a_prefill_that_raises_never_retries_the_invitation(meegle_events: Any) -> None:
    world = World(_on())
    world.draft_raises = RuntimeError("database down")
    engine = _Engine("bianki.ve")
    queue = await _process(engine, world.scheduler(), _datos(meegle_events))
    assert queue.settled == [("processed", "prefill=error")]
    assert queue.failed == [] and engine.started == 1
