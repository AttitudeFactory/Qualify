"""The balance alerts of the ScrapeCreators gate (ADR 42 R2, m-24854847) — offline.

Acceptance: «Bajo 2.000 sale un solo aviso a Lark por cruce (test con el notificador
simulado)». A recording notifier stands in for Lark; sends run synchronously so each test
can count them. Every sequence of writes uses explicit timestamps (`_Feed`), never the
clock, so the order is the one written here on any OS. The cross-process half (concurrent
writers, one claim) is proven against Postgres in `test_scrapecreators_balance_db.py`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from qualify_api.support.webhook import TextWebhook
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors.balance import (
    ALERT_EMPTY,
    ALERT_FLOOR,
    ALERT_LOW,
    FLOOR_THRESHOLD,
    LOW_BALANCE_THRESHOLD,
    REARM_MARGIN,
    SCRAPECREATORS,
    BalanceChange,
    InMemoryBalanceStore,
    next_alert,
)
from qualify_api.vendors.balance_alert import (
    ALERTS_SWITCH_ENV,
    LowBalanceAlert,
    NullTeamNotifier,
    alert_message,
    alerts_switch_on,
    production_alert,
    production_notifier,
)

PROFILE = "/v1/tiktok/profile"


class _Lark:
    def __init__(self, *, accept: bool = True, raises: bool = False) -> None:
        self.messages: list[str] = []
        self._accept = accept
        self._raises = raises
        self._lock = threading.Lock()

    def send(self, text: str) -> bool:
        if self._raises:
            raise RuntimeError("lark down")
        with self._lock:
            self.messages.append(text)
        return self._accept


def _now(job: Callable[[], None]) -> None:
    job()


class _Feed:
    """Writes to an in-memory store at explicit, strictly increasing instants and hands
    every change to the alert — what the gate does, without the wall clock."""

    def __init__(self, initial: int | None = None) -> None:
        self.store = InMemoryBalanceStore()
        self.lark = _Lark()
        self.alert = LowBalanceAlert(self.lark, dispatch=_now)
        self._at = datetime(2026, 11, 4, tzinfo=UTC)
        if initial is not None:
            self.store.record(SCRAPECREATORS, initial, self._at)  # the starting row, silent

    def write(
        self,
        credits: int,
        *,
        seconds: int = 1,
        authoritative: bool = False,
        exhausted: bool = False,
    ) -> BalanceChange | None:
        self._at += timedelta(seconds=seconds)
        return self._apply(credits, self._at, authoritative=authoritative, exhausted=exhausted)

    def late(self, credits: int, seconds_ago: int) -> BalanceChange | None:
        return self._apply(credits, self._at - timedelta(seconds=seconds_ago))

    def _apply(self, credits: int, at: datetime, **flags: bool) -> BalanceChange | None:
        change = self.store.record(SCRAPECREATORS, credits, at, **flags)
        self.alert.observe(change)
        return change

    @property
    def kinds(self) -> list[str]:
        out = []
        for text in self.lark.messages:
            if text.startswith("Se acabaron"):
                out.append(ALERT_EMPTY)
            elif "deja de buscar" in text:
                out.append(ALERT_FLOOR)
            else:
                out.append(ALERT_LOW)
        return out


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_alert")


# --- the rule -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("after", "alert"),
    [
        (1_999, ALERT_LOW),
        (2_000, None),  # 2,000 itself is not under
        (499, ALERT_FLOOR),  # straight past both: only the more severe one
        (0, ALERT_FLOOR),  # a reported 0 that is not a 402
    ],
)
def test_next_alert_on_a_fresh_episode(after: int, alert: str | None) -> None:
    assert next_alert(frozenset(), after)[0] == alert


def test_a_402_claims_empty_and_silences_the_milder_ones() -> None:
    alert, sent = next_alert(frozenset(), 0, exhausted=True)
    assert alert == ALERT_EMPTY and sent == {ALERT_EMPTY, ALERT_FLOOR, ALERT_LOW}


def test_a_200_reporting_zero_then_an_in_flight_402_sends_empty_once() -> None:
    feed = _Feed(2_100)
    feed.write(0)  # a 200 that spent the last credit: floor
    feed.write(0, exhausted=True)  # a call already in flight meets the 402
    feed.write(0, exhausted=True)  # and another one
    assert feed.kinds == [ALERT_FLOOR, ALERT_EMPTY]


def test_the_floor_matches_the_gate() -> None:
    assert sc.CREDIT_FLOOR == FLOOR_THRESHOLD == 500
    assert LOW_BALANCE_THRESHOLD == 2_000


# --- one alert per crossing ---------------------------------------------------------------


def test_the_crossing_sends_exactly_one_alert() -> None:
    feed = _Feed(2_001)
    feed.write(1_999)
    assert feed.lark.messages == [
        "Quedan 1.999 créditos de ScrapeCreators (menos de 2.000). Recargar antes de "
        "llegar a 500, donde las búsquedas se frenan."
    ]


def test_staying_below_sends_nothing_more() -> None:
    feed = _Feed(2_100)
    for credits in (1_990, 1_980, 1_500, 900, 501):
        feed.write(credits)
    assert feed.kinds == [ALERT_LOW]


def test_back_above_then_below_again_sends_one_more() -> None:
    feed = _Feed(2_100)
    feed.write(1_999)
    feed.write(25_000, authoritative=True)  # the top-up, read by the operator
    feed.write(24_999)
    feed.write(1_900, seconds=3600)  # spent again, much later
    feed.write(1_800)
    assert feed.kinds == [ALERT_LOW, ALERT_LOW]


def test_an_out_of_order_answer_near_the_line_does_not_rearm() -> None:
    """A 200 is dated when its request left, the vendor counts at charge time: 1,999 then
    a later-written 2,000 is not a top-up, and must not cost a second alert."""
    feed = _Feed(2_100)
    feed.write(1_999)
    feed.write(2_000)
    feed.write(1_998)
    feed.write(LOW_BALANCE_THRESHOLD + REARM_MARGIN - 1)
    feed.write(1_997)
    assert feed.kinds == [ALERT_LOW]


def test_an_answer_well_over_the_line_rearms_without_the_operator() -> None:
    feed = _Feed(2_100)
    feed.write(1_999)
    feed.write(LOW_BALANCE_THRESHOLD + REARM_MARGIN)  # topped up, nobody ran the refresh
    feed.write(1_999)
    assert feed.kinds == [ALERT_LOW, ALERT_LOW]


def test_a_top_up_that_stays_under_does_not_alert_again() -> None:
    feed = _Feed(2_100)
    feed.write(1_999)
    feed.write(1_500, authoritative=True)
    assert feed.kinds == [ALERT_LOW]


def test_an_operator_read_that_finds_it_low_is_a_crossing_too() -> None:
    feed = _Feed(3_000)
    feed.write(1_000, authoritative=True)
    assert feed.kinds == [ALERT_LOW]


def test_a_late_answer_that_changed_nothing_does_not_alert() -> None:
    feed = _Feed(2_500)
    feed.write(2_400)
    assert feed.late(1_000, seconds_ago=5) is None
    assert feed.lark.messages == []


# --- the floor and the 402 ----------------------------------------------------------------


def test_reaching_the_floor_alerts_once_even_after_the_low_alert() -> None:
    feed = _Feed(2_100)
    feed.write(1_999)  # low
    feed.write(499)  # floor: the gate refuses from here on
    feed.write(480)
    assert feed.kinds == [ALERT_LOW, ALERT_FLOOR]
    assert "Quedan 499 créditos" in feed.lark.messages[1]


def test_a_402_alerts_even_after_low_and_floor() -> None:
    feed = _Feed(2_100)
    feed.write(1_999)
    feed.write(499)
    feed.write(0, exhausted=True)
    feed.write(0, exhausted=True)  # another process meets the same 402
    assert feed.kinds == [ALERT_LOW, ALERT_FLOOR, ALERT_EMPTY]


def test_each_episode_is_rearmed_by_the_operators_refresh() -> None:
    feed = _Feed(2_100)
    feed.write(0, exhausted=True)
    feed.write(25_000, authoritative=True)
    feed.write(1_999)
    feed.write(499)
    feed.write(0, exhausted=True)
    assert feed.kinds == [ALERT_EMPTY, ALERT_LOW, ALERT_FLOOR, ALERT_EMPTY]


def test_a_refresh_under_the_floor_rearms_nothing_it_does_not_clear() -> None:
    feed = _Feed(2_100)
    feed.write(0, exhausted=True)
    feed.write(300, authoritative=True)  # recharged a little: still under the floor
    feed.write(0, exhausted=True)  # a new 402: a new episode of `empty`
    assert feed.kinds == [ALERT_EMPTY, ALERT_EMPTY]


def test_concurrent_writers_send_one_alert() -> None:
    feed = _Feed(2_100)
    start = threading.Barrier(8)
    base = datetime(2026, 11, 5, tzinfo=UTC)

    def writer(index: int) -> None:
        start.wait()
        feed._apply(1_990 - index, base + timedelta(seconds=index))

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert feed.kinds == [ALERT_LOW]


# --- through the gate (one call each: no ordering on the clock) ---------------------------


def _gate(initial: int | None, lark: _Lark, *, dispatch: Callable = _now) -> None:
    store = InMemoryBalanceStore({SCRAPECREATORS: initial} if initial is not None else None)
    sc.configure_balance_store(store)
    sc.configure_balance_alert(LowBalanceAlert(lark, dispatch=dispatch))


def _call(credits_remaining: int | None = None, *, status: int = 200) -> None:
    body: dict = {"success": status == 200}
    if credits_remaining is not None:
        body["credits_remaining"] = credits_remaining
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))
    with httpx.Client(transport=transport) as client:
        try:
            sc.metered_get(client, PROFILE, {"handle": "x"}, feature=sc.FEATURE_PROFILE)
        except sc.ScrapeCreatorsError:
            if status == 200:
                raise


def test_the_gate_sends_the_low_alert() -> None:
    lark = _Lark()
    _gate(2_100, lark)
    _call(1_999)
    assert len(lark.messages) == 1


def test_the_gate_sends_the_402_alert() -> None:
    lark = _Lark()
    _gate(5_000, lark)
    _call(status=402)
    assert lark.messages and lark.messages[0].startswith("Se acabaron")


def test_the_operator_refresh_sends_what_it_claims() -> None:
    lark = _Lark()
    _gate(3_000, lark)
    answer = httpx.Response(200, json={"success": True, "creditCount": 1_000})
    with httpx.Client(transport=httpx.MockTransport(lambda request: answer)) as client:
        sc.refresh_balance(client=client)
    assert len(lark.messages) == 1


def test_a_notifier_that_raises_does_not_break_the_call() -> None:
    _gate(2_100, _Lark(raises=True))
    _call(1_999)  # returns normally


def test_a_rejected_alert_does_not_break_the_call() -> None:
    lark = _Lark(accept=False)
    _gate(2_100, lark)
    _call(1_999)
    assert len(lark.messages) == 1


def test_a_dispatcher_that_fails_does_not_break_the_call() -> None:
    def broken(job: Callable[[], None]) -> None:
        raise RuntimeError("can't start new thread")

    _gate(2_100, _Lark(), dispatch=broken)
    _call(1_999)


def test_the_default_dispatch_does_not_wait_for_lark() -> None:
    release, sent = threading.Event(), threading.Event()

    class SlowLark:
        def send(self, text: str) -> bool:
            release.wait(5)
            sent.set()
            return True

    sc.configure_balance_store(InMemoryBalanceStore({SCRAPECREATORS: 2_100}))
    sc.configure_balance_alert(LowBalanceAlert(SlowLark()))  # its own thread
    _call(1_999)  # would hang 5 s if the send were inline
    assert not sent.is_set()
    release.set()
    assert sent.wait(5)


def _exit_right_after_the_write(out: Path, *, send_seconds: float, deadline: float) -> float:
    """Run a process that claims an alert and exits at once, like `just sc-balance-refresh`;
    its fake Lark takes `send_seconds`. Returns how long the process took."""
    script = textwrap.dedent(
        f"""
        import time
        from qualify_api.vendors import balance_alert
        from qualify_api.vendors.balance import BalanceChange

        balance_alert.EXIT_DEADLINE_SECONDS = {deadline!r}

        class SlowLark:
            def send(self, text):
                time.sleep({send_seconds!r})
                open({str(out)!r}, "w", encoding="utf-8").write(text)
                return True

        balance_alert.LowBalanceAlert(SlowLark()).observe(BalanceChange(2100, 1999, "low"))
        """
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    started = time.monotonic()
    subprocess.run([sys.executable, "-c", script], env=env, check=True, timeout=60)
    return time.monotonic() - started


def test_a_cli_that_exits_right_after_the_write_still_sends(tmp_path: Path) -> None:
    """The claim is committed before the send: a send killed at exit is lost for good."""
    out = tmp_path / "sent.txt"
    _exit_right_after_the_write(out, send_seconds=0.5, deadline=10.0)
    assert out.read_text(encoding="utf-8").startswith("Quedan 1.999")


def test_exit_never_waits_past_the_deadline(tmp_path: Path) -> None:
    """A webhook that hangs (per-phase timeouts add up; DNS has none) cannot hold exit."""
    out = tmp_path / "sent.txt"
    baseline = _exit_right_after_the_write(tmp_path / "quick.txt", send_seconds=0, deadline=1.0)
    took = _exit_right_after_the_write(out, send_seconds=30, deadline=1.0)
    assert not out.exists()
    assert took < baseline + 5  # ~1 s deadline, nowhere near the 30 s send


# --- messages and destination -------------------------------------------------------------


def test_the_messages() -> None:
    assert alert_message(ALERT_EMPTY, 0).startswith("Se acabaron los créditos de ScrapeCreators")
    assert alert_message(ALERT_FLOOR, 499).startswith("Quedan 499 créditos de ScrapeCreators")
    assert "«just sc-balance-refresh»" in alert_message(ALERT_FLOOR, 499)
    with pytest.raises(ValueError):
        alert_message("other", 1)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "QUALIFY_DEVOPS_WEBHOOK_URL",
        "QUALIFY_DEVOPS_WEBHOOK_SECRET",
        "QUALIFY_SUPPORT_WEBHOOK_URL",
        "QUALIFY_SUPPORT_WEBHOOK_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)


def test_the_devops_bot_is_preferred(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("QUALIFY_DEVOPS_WEBHOOK_URL", "https://open.larksuite.com/hook/devops")
    monkeypatch.setenv("QUALIFY_SUPPORT_WEBHOOK_URL", "https://open.larksuite.com/hook/support")
    notifier = production_notifier()
    assert isinstance(notifier, TextWebhook)
    assert notifier._url == "https://open.larksuite.com/hook/devops"


def test_the_internal_channel_is_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("QUALIFY_SUPPORT_WEBHOOK_URL", "https://open.larksuite.com/hook/support")
    monkeypatch.setenv("QUALIFY_SUPPORT_WEBHOOK_SECRET", "s3cret")
    notifier = production_notifier()
    assert isinstance(notifier, TextWebhook)
    assert notifier._url == "https://open.larksuite.com/hook/support"
    assert notifier._secret == "s3cret"


def test_no_channel_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    assert isinstance(production_notifier(), NullTeamNotifier)


def test_the_message_is_signed_lark_text() -> None:
    seen: list[httpx.Request] = []

    def lark(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"code": 0})

    webhook = TextWebhook(
        "https://open.larksuite.com/open-apis/bot/v2/hook/fixture",
        secret="s3cret",
        transport=httpx.MockTransport(lark),
    )
    assert webhook.send(alert_message(ALERT_LOW, 1_999)) is True
    body = seen[0].read().decode()
    assert '"msg_type":"text"' in body.replace(" ", "") and '"sign"' in body


# --- the switch (founder, 2026-11-04: shipped off) ----------------------------------------


@pytest.fixture
def _webhook_spy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every channel configured, and any real send recorded instead of made."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("QUALIFY_DEVOPS_WEBHOOK_URL", "https://open.larksuite.com/hook/devops")
    monkeypatch.setenv("QUALIFY_SUPPORT_WEBHOOK_URL", "https://open.larksuite.com/hook/support")
    sent: list[str] = []

    def spy(self: TextWebhook, text: str) -> bool:
        sent.append(text)
        return True

    monkeypatch.setattr(TextWebhook, "send", spy)
    return sent


@pytest.mark.parametrize("value", [None, "", "0", "off", "false", "no", "maybe"])
def test_the_switch_is_off_unless_turned_on(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv(ALERTS_SWITCH_ENV, raising=False)
    else:
        monkeypatch.setenv(ALERTS_SWITCH_ENV, value)
    assert alerts_switch_on() is False


@pytest.mark.parametrize("value", ["1", "true", "on", "yes", " TRUE "])
def test_the_switch_turns_on(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(ALERTS_SWITCH_ENV, value)
    assert alerts_switch_on() is True


def test_off_nothing_reaches_any_channel_but_the_claim_is_kept_and_logged(
    monkeypatch: pytest.MonkeyPatch, _webhook_spy: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv(ALERTS_SWITCH_ENV, raising=False)
    store = InMemoryBalanceStore({SCRAPECREATORS: 2_100})
    sc.configure_balance_store(store)
    sc.configure_balance_alert(None)  # the production alert, as in the app
    with caplog.at_level("WARNING", logger="qualify_api.vendors.balance_alert"):
        _call(1_999)
    time.sleep(0.2)  # nothing in the background either
    assert _webhook_spy == []
    assert store.alerts_sent[SCRAPECREATORS] == {ALERT_LOW}
    logged = [r.getMessage() for r in caplog.records]
    assert any("low at 1999 credits (not sent" in m for m in logged)


def test_claims_made_while_off_are_consumed(
    monkeypatch: pytest.MonkeyPatch, _webhook_spy: list[str]
) -> None:
    """Turning the switch on later does not replay old crossings."""
    monkeypatch.delenv(ALERTS_SWITCH_ENV, raising=False)
    off = production_alert()
    store = InMemoryBalanceStore({SCRAPECREATORS: 2_100})
    at = datetime(2026, 11, 4, tzinfo=UTC)
    off.observe(store.record(SCRAPECREATORS, 1_999, at))
    monkeypatch.setenv(ALERTS_SWITCH_ENV, "1")
    on = LowBalanceAlert(production_notifier(), dispatch=_now)
    on.observe(store.record(SCRAPECREATORS, 1_900, at + timedelta(seconds=1)))
    assert _webhook_spy == []


def test_on_the_production_alert_delivers(
    monkeypatch: pytest.MonkeyPatch, _webhook_spy: list[str]
) -> None:
    monkeypatch.setenv(ALERTS_SWITCH_ENV, "on")
    sc.configure_balance_store(InMemoryBalanceStore({SCRAPECREATORS: 2_100}))
    sc.configure_balance_alert(None)
    _call(1_999)
    deadline = time.monotonic() + 5
    while not _webhook_spy and time.monotonic() < deadline:
        time.sleep(0.02)
    assert _webhook_spy and _webhook_spy[0].startswith("Quedan 1.999")
