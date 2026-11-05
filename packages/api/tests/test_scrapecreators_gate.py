"""The metered gate `metered_get` (ADR 42 §4, slice R2, m-24854847) — fully offline:
`httpx.MockTransport` over a real client and an `InMemoryBalanceStore`. Never the vendor.

Acceptance (ADR 42, Anexo F1, R2): with a simulated balance of 499 the call is not made;
a 402 leaves the switch stopped; the static half lives in
`test_scrapecreators_gate_sanctity.py`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import scrapecreators_trending as trending
from qualify_api.vendors.balance import SCRAPECREATORS, Balance, InMemoryBalanceStore

#: ADR 42 R5: these tests exercise the vendor module itself, not who pays — every
#: paid read is charged to the conftest's placeholder business.
pytestmark = pytest.mark.usefixtures("paid_reads_charged")


PROFILE = "/v1/tiktok/profile"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_gate")


def _store(credits: int | None = None) -> InMemoryBalanceStore:
    store = InMemoryBalanceStore({SCRAPECREATORS: credits} if credits is not None else None)
    sc.configure_balance_store(store)
    return store


class _Vendor:
    """A fake vendor: answers `status` with `body`, counts the requests it received."""

    def __init__(self, status: int = 200, body: dict | None = None) -> None:
        self.status = status
        self.body = body if body is not None else {"success": True, "credits_remaining": 1200}
        self.calls: list[httpx.Request] = []

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return httpx.Response(self.status, json=self.body)


def _get(vendor: _Vendor, feature: str = sc.FEATURE_PROFILE) -> dict:
    with vendor.client() as client:
        return sc.metered_get(client, PROFILE, {"handle": "x"}, feature=feature)


# --- floor ------------------------------------------------------------------------------


def test_a_balance_of_499_does_not_make_the_call() -> None:
    _store(499)
    vendor = _Vendor()
    with pytest.raises(sc.ScrapeCreatorsBlocked) as caught:
        _get(vendor)
    assert caught.value.reason == "below_floor"
    assert vendor.calls == []


def test_a_balance_at_the_floor_calls() -> None:
    _store(sc.CREDIT_FLOOR)
    vendor = _Vendor()
    assert _get(vendor)["success"] is True
    assert len(vendor.calls) == 1


def test_an_unknown_balance_calls_and_records_what_the_vendor_reports() -> None:
    store = _store()
    vendor = _Vendor(body={"success": True, "credits_remaining": 1446, "credits_charged": 1})
    _get(vendor)
    recorded = store.read(SCRAPECREATORS)
    assert recorded is not None and recorded.credits_remaining == 1446


def test_the_answer_that_crosses_the_floor_stops_the_next_call() -> None:
    store = _store(501)
    vendor = _Vendor(body={"success": True, "credits_remaining": 499})
    _get(vendor)
    assert store.read(SCRAPECREATORS).credits_remaining == 499
    with pytest.raises(sc.ScrapeCreatorsBlocked):
        _get(vendor)
    assert len(vendor.calls) == 1


def test_an_answer_without_credits_keeps_the_last_balance() -> None:
    store = _store(900)
    _get(_Vendor(body={"success": True}))
    assert store.read(SCRAPECREATORS).credits_remaining == 900


def test_a_balance_that_cannot_be_read_fails_closed() -> None:
    class Broken:
        def read(self, vendor: str) -> Balance | None:
            raise OSError("db down")

        def record(
            self, vendor: str, credits_remaining: int, observed_at: datetime, **_: object
        ) -> None:
            raise AssertionError("never reached")

    sc.configure_balance_store(Broken())
    vendor = _Vendor()
    with pytest.raises(sc.ScrapeCreatorsBlocked) as caught:
        _get(vendor)
    assert caught.value.reason == "balance_unreadable"
    assert vendor.calls == []


def test_a_failed_balance_write_still_returns_the_paid_answer() -> None:
    class WriteFails(InMemoryBalanceStore):
        def record(
            self, vendor: str, credits_remaining: int, observed_at: datetime, **_: object
        ) -> None:
            raise OSError("db down")

    sc.configure_balance_store(WriteFails())
    assert _get(_Vendor())["success"] is True


def test_the_store_keeps_the_newest_observation() -> None:
    store = InMemoryBalanceStore()
    now = datetime.now(UTC)
    store.record(SCRAPECREATORS, 800, now)
    store.record(SCRAPECREATORS, 900, now - timedelta(seconds=5))  # a late answer
    assert store.read(SCRAPECREATORS).credits_remaining == 800


# --- 402 --------------------------------------------------------------------------------


def test_a_402_leaves_the_switch_stopped() -> None:
    store = _store(5000)
    out = _Vendor(status=402, body={"success": False, "error": "Out of credits"})
    with pytest.raises(sc.ScrapeCreatorsError) as caught:
        _get(out)
    assert caught.value.status_code == 402
    assert sc.halted()
    # every other process sees 0 — under the floor — through `vendor_balance`
    assert store.read(SCRAPECREATORS).credits_remaining == 0

    healthy = _Vendor()
    with pytest.raises(sc.ScrapeCreatorsBlocked) as again:
        _get(healthy)
    assert again.value.reason == "halted"
    assert healthy.calls == []


def test_a_402_stops_this_process_even_when_the_balance_write_fails() -> None:
    class WriteFails(InMemoryBalanceStore):
        def record(
            self, vendor: str, credits_remaining: int, observed_at: datetime, **_: object
        ) -> None:
            raise OSError("db down")

    sc.configure_balance_store(WriteFails())
    with pytest.raises(sc.ScrapeCreatorsError):
        _get(_Vendor(status=402, body={"success": False}))
    healthy = _Vendor()
    with pytest.raises(sc.ScrapeCreatorsBlocked):
        _get(healthy)
    assert healthy.calls == []


def test_another_process_sees_the_402_through_the_shared_balance() -> None:
    store = _store(5000)
    with pytest.raises(sc.ScrapeCreatorsError):
        _get(_Vendor(status=402, body={"success": False}))
    sc.reset_halt()  # a different process: no in-memory flag, same `vendor_balance`
    healthy = _Vendor()
    with pytest.raises(sc.ScrapeCreatorsBlocked) as caught:
        _get(healthy)
    assert caught.value.reason == "below_floor"
    assert store.read(SCRAPECREATORS).credits_remaining == 0


def test_refresh_balance_is_the_way_back_after_a_top_up() -> None:
    store = _store(5000)
    with pytest.raises(sc.ScrapeCreatorsError):
        _get(_Vendor(status=402, body={"success": False}))
    seen: list[str] = []

    def balance(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"success": True, "creditCount": 25_000})

    with httpx.Client(transport=httpx.MockTransport(balance)) as client:
        assert sc.refresh_balance(client=client) == 25_000
    assert seen == ["/v1/credit-balance"]
    assert not sc.halted()
    assert store.read(SCRAPECREATORS).credits_remaining == 25_000
    assert _get(_Vendor())["success"] is True


def test_a_top_up_recorded_by_another_process_lifts_the_stop() -> None:
    store = _store(5000)
    with pytest.raises(sc.ScrapeCreatorsError):
        _get(_Vendor(status=402, body={"success": False}))
    # an older observation does not lift it...
    store.rows[SCRAPECREATORS] = Balance(9000, datetime.now(UTC) - timedelta(hours=1))
    with pytest.raises(sc.ScrapeCreatorsBlocked):
        _get(_Vendor())
    # ...a newer one at or over the floor does (`just sc-balance-refresh` elsewhere)
    store.record(SCRAPECREATORS, 25_000, datetime.now(UTC) + timedelta(seconds=1))
    assert _get(_Vendor())["success"] is True
    assert not sc.halted()


def test_a_slow_answer_that_left_before_a_402_does_not_reopen_the_floor() -> None:
    store = _store(5000)

    def slow(request: httpx.Request) -> httpx.Response:
        # while this request is in flight, another call meets the 402
        with pytest.raises(sc.ScrapeCreatorsError):
            _get(_Vendor(status=402, body={"success": False}))
        return httpx.Response(200, json={"success": True, "credits_remaining": 3000})

    with httpx.Client(transport=httpx.MockTransport(slow)) as client:
        sc.metered_get(client, PROFILE, {"handle": "x"}, feature=sc.FEATURE_PROFILE)
    assert store.read(SCRAPECREATORS).credits_remaining == 0
    sc.reset_halt()  # another process: only the shared balance speaks
    with pytest.raises(sc.ScrapeCreatorsBlocked):
        _get(_Vendor())


def test_refresh_balance_fails_loudly_when_it_cannot_record() -> None:
    class WriteFails(InMemoryBalanceStore):
        def record(
            self, vendor: str, credits_remaining: int, observed_at: datetime, **_: object
        ) -> None:
            raise OSError("db down")

    sc.configure_balance_store(WriteFails())

    def balance(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "creditCount": 25_000})

    with (
        httpx.Client(transport=httpx.MockTransport(balance)) as client,
        pytest.raises(OSError),
    ):
        sc.refresh_balance(client=client)


def test_refresh_balance_under_the_floor_keeps_the_stop() -> None:
    _store(5000)
    with pytest.raises(sc.ScrapeCreatorsError):
        _get(_Vendor(status=402, body={"success": False}))

    def balance(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "creditCount": 12})

    with httpx.Client(transport=httpx.MockTransport(balance)) as client:
        assert sc.refresh_balance(client=client) == 12
    assert sc.halted()


# --- kill switch ------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["0", "false", "OFF", " no "])
def test_the_kill_switch_stops_every_call(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    _store(10_000)
    monkeypatch.setenv(sc.PAID_SWITCH_ENV, value)
    vendor = _Vendor()
    with pytest.raises(sc.ScrapeCreatorsBlocked) as caught:
        _get(vendor)
    assert caught.value.reason == "switch_off"
    assert vendor.calls == []


@pytest.mark.parametrize("value", ["", "1", "true", "on"])
def test_the_switch_is_on_unless_turned_off(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(sc.PAID_SWITCH_ENV, value)
    assert sc.paid_switch_on()


def test_a_blocked_call_is_a_scrapecreators_error_for_existing_callers() -> None:
    assert issubclass(sc.ScrapeCreatorsBlocked, sc.ScrapeCreatorsError)
    assert sc.ScrapeCreatorsBlocked("x", reason="halted").status_code is None


def test_an_unknown_feature_is_refused_before_anything() -> None:
    vendor = _Vendor()
    with pytest.raises(ValueError):
        _get(vendor, feature="whatever")
    assert vendor.calls == []


# --- the fetch_* functions go through the gate --------------------------------------------


def test_every_reader_is_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    _store(499)
    vendor = _Vendor()
    readers = [
        lambda c: sc.fetch_profile("tiktok", "x", client=c),
        lambda c: sc.fetch_profile_and_posts("instagram", "x", client=c),
        lambda c: sc.fetch_recent_posts("tiktok", "x", since=0, client=c),
        lambda c: sc.fetch_reels("instagram", "x", since=0, client=c),
        lambda c: sc.fetch_instagram_transcript("https://www.instagram.com/reel/A/", client=c),
        lambda c: trending.fetch_tiktok_trending_feed(client=c),
        lambda c: trending.fetch_instagram_trending_reels(client=c),
        lambda c: trending.fetch_tiktok_song(clip_id="1", client=c),
    ]
    for read in readers:
        with vendor.client() as client, pytest.raises(sc.ScrapeCreatorsBlocked):
            read(client)
    assert vendor.calls == []


def test_the_transcript_is_metered_as_reels_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    features: list[str] = []
    real = sc.metered_get

    def spy(client: httpx.Client, path: str, params: dict, *, feature: str) -> dict:
        features.append(feature)
        return real(client, path, params, feature=feature)

    monkeypatch.setattr(sc, "metered_get", spy)
    vendor = _Vendor(body={"success": True, "transcripts": [{"text": "hola"}]})
    with vendor.client() as client:
        assert sc.fetch_instagram_transcript("https://www.instagram.com/reel/A/", client=client)
    assert features == [sc.FEATURE_REELS_TRANSCRIPT]


def test_is_vendor_host() -> None:
    assert sc.is_vendor_host("api.scrapecreators.com")
    assert sc.is_vendor_host("API.ScrapeCreators.com")
    assert not sc.is_vendor_host("scontent.cdninstagram.com")
