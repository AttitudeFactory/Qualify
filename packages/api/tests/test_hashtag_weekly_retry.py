"""m-25031643 — a transient vendor failure costs the weekly read a retry, not the day
nor the week (`qualify_api.hashtags.weekly`, D3 of 2026-11-15).

What it pins, offline (every vendor answer comes from an `httpx.MockTransport`; the gate's
ledger is the in-memory one, its clock moved by the test):

- a 503 or a request never sent (connect error/timeout, pool timeout) is marked
  unbilled (a 0-credit `:unbilled` row): it does not reduce the week's 5 reads and does
  not hold the day; any other failure (another 5xx, a read/write timeout or error, a
  protocol error) gets no marker — counted as billed and the day held;
- the next attempt waits `MIN_RETRY_WAIT` (3 h) — refused before, allowed at — and a
  business gets at most `MAX_UNBILLED_A_DAY` (4) unbilled failures in any 24 h;
- 5 billed reads a week holds when the owner changes the tags mid-week;
- refusals (4xx but 404, 402, a body without success), gate blocks and an answer not
  kept behave as before: counted, no marker, the day held (a block books nothing);
- a marker that cannot be written falls back to that stricter rule;
- the pilot's three rows of 2026-11-15 (no markers) keep the old strictness.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api.hashtags import MemoryHashtagRepository, weekly
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import usage

from .test_hashtag_weekly import (
    ON,
    _answer,
    _business,
    _Clock,
    _ClockedDatetime,
    _ledger,
    _markers,
    _spend,
    _weekly_events,
)

T0 = datetime(2030, 5, 6, 9, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(weekly.API_KEY_ENV, "test-key-not-real")


def _at(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> datetime:
    """Move the in-memory ledger's clock (`created_at` of every booking) to `moment`."""
    monkeypatch.setattr(usage, "datetime", _ClockedDatetime)
    _Clock.at = moment
    return moment


def _ledger_of(log: weekly.MemoryReadLog, tenant: UUID, now: datetime) -> weekly.WeeklyLedger:
    return weekly.summarize(log.bookings_since(tenant, now - weekly.REREAD_AFTER))


class Script:
    """A vendor that answers each request with the next of `steps` (then 200): an HTTP
    status, or an `httpx` exception to raise (a timeout, a network error)."""

    def __init__(self, *steps: int | Exception) -> None:
        self.steps = list(steps)
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        tag = request.url.params["hashtag"]
        self.requests.append(tag)
        step = self.steps.pop(0) if self.steps else 200
        if isinstance(step, Exception):
            raise step
        if step != 200:
            return httpx.Response(step, json={"success": False, "error": "service_unavailable"})
        return httpx.Response(200, json=_answer(tag))

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def _run(
    script: Script,
    rubro: weekly.BusinessRubro,
    log: weekly.MemoryReadLog,
    now: datetime,
) -> weekly.BusinessOutcome:
    report = weekly.run_tick(
        [rubro.tenant_id],
        source=weekly.MemoryRubroSource({rubro.tenant_id: rubro}),
        log=log,
        repository=MemoryHashtagRepository(),
        claims=weekly.MemoryClaims(),
        client_factory=script.client,
        now=now,
        env=ON,
    )
    return report.outcomes[0]


def test_the_brakes_fit_the_reels_worker_check() -> None:
    from qualify_api.referentes.reel_worker import HASHTAGS_EVERY  # noqa: PLC0415

    assert weekly.MIN_RETRY_WAIT == timedelta(hours=3) and weekly.MAX_UNBILLED_A_DAY == 4
    assert weekly.MIN_RETRY_WAIT < HASHTAGS_EVERY  # the next 6-hourly check qualifies
    assert weekly.UNBILLED_WINDOW == timedelta(hours=24)


# -- an unbilled failure ------------------------------------------------------------------


def test_a_503_does_not_reduce_the_weeks_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    business = _business("a1", "b1", "c1", "d1", "e1")
    log = weekly.MemoryReadLog(_ledger())
    script = Script(503)
    first = _run(script, business, log, _at(monkeypatch, T0))
    assert script.requests == ["a1"]  # the pass still stops at its first failure
    assert first.status == weekly.FAILED and first.reason == weekly.UNBILLED
    assert first.errors == 1 and log.answers == {}
    (call,) = _weekly_events(business.tenant_id)
    (marker,) = _markers(business.tenant_id, weekly.UNBILLED_SUFFIX)
    assert marker.request_key == call.request_key + weekly.UNBILLED_SUFFIX
    assert marker.credits == 0 and marker.usd_estimate == 0  # adds nothing to any cap
    assert marker.brand_id == business.brand_id
    ledger = _ledger_of(log, business.tenant_id, T0)
    assert ledger.billed == 0 and ledger.unknown_at is None

    later = T0 + weekly.MIN_RETRY_WAIT
    second = _run(script, business, log, _at(monkeypatch, later))
    assert second.status == weekly.DONE
    assert script.requests == ["a1", "a1", "b1", "c1", "d1", "e1"]  # all five, this week
    assert _ledger_of(log, business.tenant_id, later).billed == weekly.MAX_TAGS
    assert len(_markers(business.tenant_id, weekly.KEPT_SUFFIX)) == 5
    # the gate still booked six calls: the daily/monthly caps count the unbilled one too
    assert sum(e.credits for e in _weekly_events(business.tenant_id)) == 6


def test_a_success_then_a_503_reads_on_at_the_next_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production, 2026-11-15 17:15 UTC: one tag kept, the next one 503 — the next check
    (6 h later) reads on; it does not wait a day."""
    business = _business("shawarma", "falafel", "kebab")
    log = weekly.MemoryReadLog(_ledger())
    script = Script(200, 503)
    first = _run(script, business, log, _at(monkeypatch, T0))
    assert first.read == ["shawarma"] and first.reason == weekly.UNBILLED
    six_hours = T0 + timedelta(hours=6)
    second = _run(script, business, log, _at(monkeypatch, six_hours))
    assert second.status == weekly.DONE and second.read == ["falafel", "kebab"]
    assert second.fresh == ["shawarma"]
    assert _ledger_of(log, business.tenant_id, six_hours).billed == 3


@pytest.mark.parametrize("wait", [timedelta(hours=2, minutes=59), timedelta(minutes=10)])
def test_a_retry_before_the_minimum_wait_is_refused(
    monkeypatch: pytest.MonkeyPatch, wait: timedelta
) -> None:
    business = _business("a1")
    log = weekly.MemoryReadLog(_ledger())
    script = Script(503)
    _run(script, business, log, _at(monkeypatch, T0))
    early = _run(script, business, log, _at(monkeypatch, T0 + wait))  # a deploy restart
    assert early.status == weekly.RETRY_WAIT and script.requests == ["a1"]
    on_time = _run(script, business, log, _at(monkeypatch, T0 + weekly.MIN_RETRY_WAIT))
    assert on_time.status == weekly.DONE and script.requests == ["a1", "a1"]


def test_at_most_four_unbilled_failures_a_day(monkeypatch: pytest.MonkeyPatch) -> None:
    business = _business("a1")
    log = weekly.MemoryReadLog(_ledger())
    script = Script(*[503] * 20)
    for hours in (0, 3, 6, 9):
        outcome = _run(script, business, log, _at(monkeypatch, T0 + timedelta(hours=hours)))
        assert outcome.reason == weekly.UNBILLED
    assert len(script.requests) == 4
    for hours in (12, 18, 23):
        outcome = _run(script, business, log, _at(monkeypatch, T0 + timedelta(hours=hours)))
        assert outcome.status == weekly.FAILURES_TODAY
    assert len(script.requests) == 4
    # still inside at exactly 24 h (the window includes its start); just after, the first
    # failure has left the rolling 24 h: one more attempt
    edge = _run(script, business, log, _at(monkeypatch, T0 + weekly.UNBILLED_WINDOW))
    assert edge.status == weekly.FAILURES_TODAY
    next_day = T0 + weekly.UNBILLED_WINDOW + timedelta(minutes=1)
    _run(script, business, log, _at(monkeypatch, next_day))
    assert len(script.requests) == 5
    assert _ledger_of(log, business.tenant_id, next_day).billed == 0


@pytest.mark.parametrize(
    "failure",
    [
        503,
        httpx.ConnectError("refused"),
        httpx.ConnectTimeout("slow"),
        httpx.PoolTimeout("pool"),
    ],
    ids=["503", "connect-error", "connect-timeout", "pool-timeout"],
)
def test_a_503_and_a_request_never_sent_are_unbilled(
    monkeypatch: pytest.MonkeyPatch, failure: int | Exception
) -> None:
    business = _business("a1")
    log = weekly.MemoryReadLog(_ledger())
    script = Script(failure)
    outcome = _run(script, business, log, _at(monkeypatch, T0))
    assert outcome.status == weekly.FAILED and outcome.reason == weekly.UNBILLED
    assert len(_markers(business.tenant_id, weekly.UNBILLED_SUFFIX)) == 1
    assert _ledger_of(log, business.tenant_id, T0).billed == 0
    retry = _run(script, business, log, _at(monkeypatch, T0 + weekly.MIN_RETRY_WAIT))
    assert retry.status == weekly.DONE and script.requests == ["a1", "a1"]


@pytest.mark.parametrize(
    "failure",
    [
        500,
        502,
        504,
        524,
        httpx.ReadTimeout("slow"),
        httpx.ReadError("reset"),
        httpx.WriteTimeout("slow"),
        httpx.WriteError("broken"),
        httpx.RemoteProtocolError("disconnected"),
        httpx.CloseError("close"),
        httpx.ProxyError("proxy"),
    ],
    ids=[
        "500",
        "502",
        "504",
        "524",
        "read-timeout",
        "read-error",
        "write-timeout",
        "write-error",
        "remote-protocol",
        "close-error",
        "proxy-error",
    ],
)
def test_a_failure_the_vendor_may_have_billed_counts_and_holds_the_day(
    monkeypatch: pytest.MonkeyPatch, failure: int | Exception
) -> None:
    """Only what was measured as not billed (503) or never left is unbilled; anything
    else is of unknown outcome — counted as billed and held a day."""
    business = _business("a1")
    log = weekly.MemoryReadLog(_ledger())
    script = Script(failure)
    outcome = _run(script, business, log, _at(monkeypatch, T0))
    assert outcome.status == weekly.FAILED and outcome.reason is None
    assert _markers(business.tenant_id, weekly.UNBILLED_SUFFIX) == []
    ledger = _ledger_of(log, business.tenant_id, T0)
    assert ledger.billed == 1 and ledger.unknown_at == T0
    held = _run(script, business, log, _at(monkeypatch, T0 + weekly.MIN_RETRY_WAIT))
    assert held.status == weekly.TRIED_TODAY and script.requests == ["a1"]


def test_the_unbilled_statuses_are_only_the_measured_503() -> None:
    assert weekly.UNBILLED_STATUSES == frozenset({503})


# -- what is not transient keeps the rule from before ------------------------------------


def test_a_body_without_success_is_not_unbilled(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 200 with `success: false`: the vendor answered — not a transient failure."""
    business = _business("a1")
    log = weekly.MemoryReadLog(_ledger())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "error": "bad hashtag"})

    weekly.run_tick(
        [business.tenant_id],
        source=weekly.MemoryRubroSource({business.tenant_id: business}),
        log=log,
        repository=MemoryHashtagRepository(),
        claims=weekly.MemoryClaims(),
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
        now=_at(monkeypatch, T0),
        env=ON,
    )
    assert _markers(business.tenant_id, weekly.UNBILLED_SUFFIX) == []
    ledger = _ledger_of(log, business.tenant_id, T0)
    assert ledger.billed == 1 and ledger.unknown_at == T0


def test_a_402_is_not_unbilled_and_the_gate_still_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    business = _business("a1")
    log = weekly.MemoryReadLog(_ledger())
    outcome = _run(Script(402), business, log, _at(monkeypatch, T0))
    assert outcome.status == weekly.FAILED and outcome.reason is None
    assert _markers(business.tenant_id, weekly.UNBILLED_SUFFIX) == []
    assert _ledger_of(log, business.tenant_id, T0).billed == 1
    assert sc.halted()  # the gate's own 402 stop is unchanged


def test_a_gate_block_books_nothing_and_marks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    business = _business("a1")
    _spend(business.tenant_id, usage.DAILY_CAP, at=_at(monkeypatch, T0))
    monkeypatch.setattr(weekly, "has_headroom", lambda tenant, now: True)
    log = weekly.MemoryReadLog(_ledger())
    script = Script()
    outcome = _run(script, business, log, T0)
    assert outcome.status == weekly.CAPPED and script.requests == []
    weekly_rows = [
        e for e in _ledger().of(business.tenant_id) if e.feature == sc.FEATURE_HASHTAG_WEEKLY
    ]
    assert weekly_rows == []


class _UnkeptLog(weekly.MemoryReadLog):
    def keep(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("vendor_payloads unwritable")


def test_an_answer_not_kept_counts_and_holds_the_day(monkeypatch: pytest.MonkeyPatch) -> None:
    business = _business("a1", "b1")
    log = _UnkeptLog(_ledger())
    script = Script()
    outcome = _run(script, business, log, _at(monkeypatch, T0))
    assert outcome.status == weekly.FAILED and outcome.reason is None
    assert script.requests == ["a1"]
    assert _markers(business.tenant_id, weekly.KEPT_SUFFIX) == []
    assert _markers(business.tenant_id, weekly.UNBILLED_SUFFIX) == []
    assert _ledger_of(log, business.tenant_id, T0).billed == 1
    held = _run(script, business, log, _at(monkeypatch, T0 + timedelta(hours=6)))
    assert held.status == weekly.TRIED_TODAY and script.requests == ["a1"]


class _NoMarkLog(weekly.MemoryReadLog):
    def mark(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("ledger unwritable")


def test_a_marker_not_written_falls_back_to_the_stricter_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    business = _business("a1")
    log = _NoMarkLog(_ledger())
    script = Script(503)
    outcome = _run(script, business, log, _at(monkeypatch, T0))
    assert outcome.reason == weekly.UNBILLED  # the pass itself is unchanged
    ledger = _ledger_of(log, business.tenant_id, T0)
    assert ledger.billed == 1 and ledger.unknown_at == T0  # counted, and holds the day
    held = _run(script, business, log, _at(monkeypatch, T0 + weekly.MIN_RETRY_WAIT))
    assert held.status == weekly.TRIED_TODAY and script.requests == ["a1"]


# -- the week stays hard -------------------------------------------------------------------


def test_five_billed_a_week_holds_when_the_owner_changes_the_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound is a sum over the ledger, not over the current pills: three kept and one
    unbilled failure, then five new pills — only two more are read this week."""
    tenant, brand = uuid4(), uuid4()
    log = weekly.MemoryReadLog(_ledger())
    old = weekly.BusinessRubro(tenant, ("o1", "o2", "o3"), "CO", brand)
    _run(Script(), old, log, _at(monkeypatch, T0))
    assert _ledger_of(log, tenant, T0).billed == 3

    new = weekly.BusinessRubro(tenant, ("n1", "n2", "n3", "n4", "n5"), "CO", brand)
    script = Script(503)
    _run(script, new, log, _at(monkeypatch, T0 + timedelta(hours=6)))
    outcome = _run(script, new, log, _at(monkeypatch, T0 + timedelta(hours=9)))
    assert outcome.read == ["n1", "n2"] and outcome.status == weekly.DONE
    assert _ledger_of(log, tenant, T0 + timedelta(hours=9)).billed == weekly.MAX_TAGS
    spent = _run(script, new, log, _at(monkeypatch, T0 + timedelta(days=2)))
    assert spent.status == weekly.WEEK_SPENT
    assert script.requests == ["n1", "n1", "n2"]
    # a week after the first reads the old three leave the window: three more
    back = _run(script, new, log, _at(monkeypatch, T0 + weekly.REREAD_AFTER + timedelta(hours=1)))
    assert back.read == ["n3", "n4", "n5"]


def test_re_marking_a_call_writes_nothing_twice() -> None:
    business = _business("a1")
    log = weekly.MemoryReadLog(_ledger())
    for _ in range(2):
        log.mark(business.tenant_id, business.brand_id, "hashtag_weekly:x", weekly.KEPT_SUFFIX)
    assert len(_markers(business.tenant_id, weekly.KEPT_SUFFIX)) == 1
    with pytest.raises(ValueError):
        weekly.marker_event(business.tenant_id, None, "hashtag_weekly:x", ":extra")


def test_summarize_reads_markers_extras_and_orphans() -> None:
    rows = [
        weekly.Booking("hashtag_weekly:a", 1, T0),
        weekly.Booking("hashtag_weekly:a:extra", 2, T0),
        weekly.Booking("hashtag_weekly:a:kept", 0, T0),
        weekly.Booking("hashtag_weekly:b", 1, T0 + timedelta(hours=1)),
        weekly.Booking("hashtag_weekly:b:unbilled", 0, T0 + timedelta(hours=1)),
        weekly.Booking("hashtag_weekly:c", 1, T0 + timedelta(hours=2)),  # unknown outcome
        weekly.Booking("hashtag_weekly:z:unbilled", 0, T0),  # its call left the window
    ]
    ledger = weekly.summarize(rows)
    assert ledger.billed == 1 + 2 + 1  # a, a's extra, c — never b
    assert ledger.unknown_at == T0 + timedelta(hours=2)
    assert ledger.unbilled_at == (T0, T0 + timedelta(hours=1))
    assert ledger.last_unbilled == T0 + timedelta(hours=1)
    assert weekly.summarize([]) == weekly.WeeklyLedger()


# -- the rows production already holds --------------------------------------------------


def _legacy(tenant: UUID, brand: UUID | None, at: datetime) -> None:
    """A booking as the gate made it before the markers: `hashtag_weekly:<uuid>`, 1."""
    event = usage.UsageEvent(
        tenant,
        brand,
        usage.SCRAPECREATORS,
        sc.FEATURE_HASHTAG_WEEKLY,
        1,
        usage.usd_per_credit(),
        usage.PRICING_TABLE_VERSION,
        f"{sc.FEATURE_HASHTAG_WEEKLY}:{uuid4()}",
        created_at=at,
    )
    assert _ledger().book(event, capped=False) is None


def test_the_2026_11_15_ledger_is_read_with_the_old_strictness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pilot's three rows of 2026-11-15 (a failure at 04:59, a 200 at 17:15:14, a 503
    at 17:15:34; all `credits = 1`, no marker: booked before the markers existed). With
    no marker each is of unknown outcome: all three count as billed, and the newest holds
    the business until 2026-11-16 17:15:34 UTC. Then two reads are left until the 04:59
    row leaves the window on 2026-11-22. Deliberate: a row whose outcome the ledger
    cannot tell is never given back."""
    day = datetime(2026, 11, 15, tzinfo=UTC)
    tenant, brand = uuid4(), uuid4()
    rows = [
        day + timedelta(hours=4, minutes=59),
        day + timedelta(hours=17, minutes=15, seconds=14),
        day + timedelta(hours=17, minutes=15, seconds=34),
    ]
    for at in rows:
        _legacy(tenant, brand, at)
    log = weekly.MemoryReadLog(_ledger())
    # the 200 of 17:15:14 kept its answer
    log.keep(
        tenant, {"hashtag": "shawarma", "region": "CO"}, {}, status=200, credits=1, now=rows[1]
    )
    rubro = weekly.BusinessRubro(tenant, ("shawarma", "falafel", "kebab", "wrap"), "CO", brand)

    deploy = day + timedelta(hours=22)
    ledger = _ledger_of(log, tenant, deploy)
    assert ledger.billed == 3 and ledger.unknown_at == rows[2] and ledger.unbilled_at == ()
    script = Script()
    held = _run(script, rubro, log, _at(monkeypatch, deploy))
    assert held.status == weekly.TRIED_TODAY and script.requests == []
    still = _run(script, rubro, log, _at(monkeypatch, rows[2] + timedelta(hours=23, minutes=59)))
    assert still.status == weekly.TRIED_TODAY

    free = rows[2] + weekly.RETRY_AFTER + timedelta(seconds=1)
    outcome = _run(script, rubro, log, _at(monkeypatch, free))
    assert outcome.fresh == ["shawarma"] and outcome.read == ["falafel", "kebab"]
    assert _ledger_of(log, tenant, free).billed == weekly.MAX_TAGS
    spent = _run(script, rubro, log, _at(monkeypatch, datetime(2026, 11, 22, 4, 58, tzinfo=UTC)))
    assert spent.status == weekly.WEEK_SPENT
    after = _run(script, rubro, log, _at(monkeypatch, datetime(2026, 11, 22, 5, 0, tzinfo=UTC)))
    assert after.read == ["wrap"]


# -- the gate invariant `_booked_key` rests on -------------------------------------------


@pytest.mark.parametrize("failure", [503, 500, httpx.ConnectError("refused")])
def test_a_gate_error_comes_after_its_booking_and_its_key(failure: int | Exception) -> None:
    """`metered_get` raises `ScrapeCreatorsError` only after it booked the call and set
    `last_request_key` to that booking's key; a refusal before booking is
    `ScrapeCreatorsBlocked` and leaves the key unchanged."""
    business = _business("a1")
    client = usage.bind(Script(failure).client(), usage.UsageCharge(business.tenant_id))
    before = sc.last_request_key()
    with pytest.raises(sc.ScrapeCreatorsError) as raised:
        sc.metered_get(client, weekly.PATH, {"hashtag": "a1"}, feature=sc.FEATURE_HASHTAG_WEEKLY)
    assert not isinstance(raised.value, sc.ScrapeCreatorsBlocked)
    key = sc.last_request_key()
    assert key is not None and key != before
    assert [e.request_key for e in _weekly_events(business.tenant_id)] == [key]


def test_a_gate_refusal_books_nothing_and_keeps_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    business = _business("a1")
    monkeypatch.setenv(sc.PAID_SWITCH_ENV, "0")
    client = usage.bind(Script().client(), usage.UsageCharge(business.tenant_id))
    before = sc.last_request_key()
    with pytest.raises(sc.ScrapeCreatorsBlocked):
        sc.metered_get(client, weekly.PATH, {"hashtag": "a1"}, feature=sc.FEATURE_HASHTAG_WEEKLY)
    assert sc.last_request_key() == before and _weekly_events(business.tenant_id) == []
