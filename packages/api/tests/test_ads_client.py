"""Offline contract tests for m-24828973: real HTTP adapter and stateful fake."""

from __future__ import annotations

import json
import logging
import traceback
from typing import Any

import httpx
import pytest

from qualify_api.ads.client import MarketingClient, MarketingSettings, cooldown_seconds
from qualify_api.ads.errors import (
    CODE_MESSAGES,
    READ_ERROR_MESSAGE,
    SUBCODE_MESSAGES,
    UNKNOWN_WRITE_MESSAGE,
    MarketingError,
)
from qualify_api.ads.fake import FakeMarketingClient
from qualify_api.config import MetaOAuthSettings

pytestmark = pytest.mark.asyncio


async def test_update_write_guard_runs_after_cooldown_and_denial_never_posts() -> None:
    now = [0.0]
    calls = []
    guards = []

    async def sleep(seconds):
        now[0] += seconds

    def guard():
        guards.append(now[0])
        raise PermissionError("consent expired")

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"success": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = MarketingClient(
            client=http, account_id="12", sleep=sleep, monotonic=lambda: now[0]
        )
        client._not_before = 10.0
        with pytest.raises(PermissionError, match="expired"):
            await client.update("9", params={"status": "ACTIVE"}, before_write=guard)
    assert guards == [10.0] and not calls


async def test_update_guard_is_local_not_serialized_and_fake_denial_matches_transport() -> None:
    calls = []
    guards = []

    def handler(request):
        calls.append(request)
        assert request.content == b"status=ACTIVE"
        return httpx.Response(200, json={"success": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = MarketingClient(client=http, account_id="12")
        await client.update(
            "9", params={"status": "ACTIVE"}, before_write=lambda: guards.append(True)
        )
    assert guards == [True] and len(calls) == 1
    fake = FakeMarketingClient()
    identifier = await fake.create("campaigns", params={"status": "PAUSED"})
    previous = len(fake.calls)

    def deny():
        raise PermissionError("removed")

    with pytest.raises(PermissionError):
        await fake.update(identifier, params={"status": "ACTIVE"}, before_write=deny)
    assert len(fake.calls) == previous and fake.objects[identifier]["status"] == "PAUSED"


@pytest.mark.parametrize("resource", ["campaigns", "adsets", "adcreatives", "ads"])
async def test_fake_object_lifecycle(resource: str) -> None:
    fake = FakeMarketingClient()
    params = {"name": "Ejemplo", "status": "PAUSED", "targeting": {"geo_locations": {}}}
    identifier = await fake.create(resource, params=params)
    params["targeting"]["geo_locations"]["countries"] = ["CO"]
    page = await fake.list(resource)
    assert len(page.data) == 1
    assert page.data[0]["status"] == "PAUSED"
    assert page.data[0]["targeting"] == {"geo_locations": {}}
    await fake.update(identifier, params={"status": "ACTIVE"})
    assert (await fake.status(identifier))["status"] == "ACTIVE"


READS = [
    ("targetingsearch", {"params": {"q": "Comida"}}, "act_1/targetingsearch"),
    ("adpreviews", {"ad_id": "9", "params": {"ad_format": "INSTAGRAM_STANDARD"}}, "9/previews"),
    ("minimum_budgets", {}, "act_1/minimum_budgets"),
    (
        "reachestimate",
        {"targeting_spec": {"geo_locations": {"countries": ["CO"]}}},
        "act_1/reachestimate",
    ),
    ("search_locations", {"query": "Cúcuta"}, "search"),
    ("search_interests", {"query": "Comida"}, "search"),
    ("insights", {}, "act_1/insights"),
    ("insights", {"object_id": "9", "params": {"fields": "spend"}}, "9/insights"),
]


@pytest.mark.parametrize("method,kwargs,path", READS)
async def test_each_read_against_fake(method: str, kwargs: dict, path: str) -> None:
    fake = FakeMarketingClient()
    fake.responses["GET", path] = {"data": [{"id": "7"}]}
    page = await getattr(fake, method)(**kwargs)
    assert page.data == ({"id": "7"},)
    assert fake.calls[-1][1] == path


@pytest.mark.parametrize("method,kwargs,path", READS)
async def test_each_read_transport(method: str, kwargs: dict, path: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v26.0/" + path
        if method == "reachestimate":
            assert json.loads(request.url.params["targeting_spec"]) == kwargs["targeting_spec"]
        if method.startswith("search_"):
            assert request.url.params["type"] == (
                "adgeolocation" if method == "search_locations" else "adinterest"
            )
            assert request.url.params["q"] == kwargs["query"]
        return httpx.Response(
            200,
            json={
                "data": [{"id": "7"}],
                "paging": {
                    "cursors": {"after": "cursor"},
                    "next": "https://graph.facebook.com/?access_token=do-not-expose",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = MarketingClient(client=http, account_id="act_1")
        page = await getattr(client, method)(**kwargs)
    assert page.data == ({"id": "7"},)
    assert page.after == "cursor"
    assert "do-not-expose" not in repr(page)


@pytest.mark.parametrize("resource", ["campaigns", "adsets", "adcreatives", "ads"])
async def test_write_list_status_transport(resource: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            assert "access_token" not in str(request.url)
            assert request.headers["authorization"] == "Bearer test-secret"
            if request.url.path.endswith(resource):
                form = dict(httpx.QueryParams(request.content.decode()))
                assert json.loads(form["object_story_spec"]) == {"instagram_user_id": "2"}
                return httpx.Response(200, json={"id": "4"})
            assert request.url.path == "/v26.0/4"
            assert dict(httpx.QueryParams(request.content.decode())) == {"status": "PAUSED"}
            return httpx.Response(200, json={"success": True})
        if request.url.path.endswith(resource):
            assert request.url.params["after"] == "abc"
            return httpx.Response(200, json={"data": [{"id": "4"}]})
        assert request.url.params["fields"] == "id,status,effective_status,issues_info"
        return httpx.Response(200, json={"id": "4", "status": "PAUSED"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer test-secret"}
    ) as http:
        client = MarketingClient(client=http, account_id="1")
        assert (
            await client.create(resource, params={"object_story_spec": {"instagram_user_id": "2"}})
            == "4"
        )
        assert (await client.list(resource, params={"after": "abc"})).data == ({"id": "4"},)
        await client.update("4", params={"status": "PAUSED"})
        assert (await client.status("4"))["status"] == "PAUSED"
    assert len(seen) == 4


async def test_settings_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_META_API_VERSION", "v21.0")
    monkeypatch.setenv("QUALIFY_META_ADS_API_VERSION", "v25.0")
    assert MetaOAuthSettings.from_env().api_version == "v21.0"
    assert MarketingSettings.from_env().graph_url == "https://graph.facebook.com/v25.0"
    monkeypatch.delenv("QUALIFY_META_ADS_API_VERSION")
    assert MarketingSettings.from_env().api_version == "v26.0"
    with pytest.raises(ValueError):
        MarketingSettings(api_version="https://evil.invalid/?access_token=secret")


ERROR_CASES = [(code, None, text) for code, text in CODE_MESSAGES.items()] + [
    (100, subcode, text) for subcode, text in SUBCODE_MESSAGES.items()
]


async def test_ticket_error_inventory_is_complete() -> None:
    assert {17, 613, 80004, 294, 2654} <= set(CODE_MESSAGES)
    assert {
        1885183,
        1815199,
        2238055,
        2446149,
        1885272,
        1885650,
        1885621,
        1885029,
        1885557,
        1713092,
        4841018,
        1373054,
        2446383,
    } <= set(SUBCODE_MESSAGES)


async def test_redirects_do_not_forward_authenticated_client() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(302, headers={"Location": "https://evil.invalid/"}, json={"id": "4"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as http:
        client = MarketingClient(client=http, account_id="1")
        with pytest.raises(MarketingError):
            await client.create("ads", params={})
    assert seen == ["graph.facebook.com"]


@pytest.mark.parametrize("code,subcode,message", ERROR_CASES)
async def test_every_numeric_error_and_fake_failure(code: int, subcode: int, message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": code,
                    "error_subcode": subcode,
                    "message": "localized-private-token",
                    "error_user_msg": "not safe",
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = MarketingClient(client=http, account_id="1")
        with pytest.raises(MarketingError) as caught:
            await client.create("ads", params={"status": "PAUSED"})
    assert str(caught.value) == message
    assert caught.value.code == code
    assert caught.value.subcode == subcode
    assert caught.value.http_status == 400
    assert "localized-private-token" not in repr(caught.value)
    fake = FakeMarketingClient()
    fake.failures.append(caught.value)
    with pytest.raises(MarketingError) as simulated:
        await fake.create("ads", params={})
    assert str(simulated.value) == message
    assert not fake.objects


async def test_subcode_takes_precedence_and_unknown_fallback() -> None:
    replies = [
        {"error": {"code": 17, "error_subcode": 1815199}},
        {"error": {"code": 999, "error_subcode": 999, "message": "private"}},
        {"error": {"code": "17", "error_subcode": True}},
    ]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(400, json=replies.pop(0)))
    ) as http:
        for index in range(3):
            client = MarketingClient(client=http, account_id="1")
            with pytest.raises(MarketingError) as caught:
                await client.status("4")
            if index == 0:
                assert str(caught.value) == SUBCODE_MESSAGES[1815199]
            if index == 2:
                assert caught.value.code is None and caught.value.subcode is None
            assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    "params",
    [
        {"instagram_user_id": "1", "instagram_actor_id": "2"},
        {"object_story_spec": {"instagram_user_id": "1"}, "instagram_actor_id": "2"},
        {"nested": [{"instagram_user_id": "1"}, {"instagram_actor_id": "2"}]},
        {"object_story_spec": '{"instagram_user_id":"1","instagram_actor_id":"2"}'},
        {"access_token": "private"},
        {"nested": {"Authorization": "private"}},
    ],
)
async def test_conflicting_identity_and_credentials_rejected_before_transport(params: dict) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("invalid request reached transport")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = MarketingClient(client=http, account_id="1")
        with pytest.raises(ValueError):
            await client.create("adcreatives", params=params)
    fake = FakeMarketingClient()
    with pytest.raises(ValueError):
        await fake.create("adcreatives", params=params)
    assert not fake.calls


async def test_tokens_never_logged_and_timeout_not_retried(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("private-token in unsafe upstream message", request=request)

    with caplog.at_level(logging.DEBUG):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            headers={"Authorization": "Bearer private-token"},
        ) as http:
            client = MarketingClient(client=http, account_id="1")
            with pytest.raises(MarketingError) as caught:
                await client.create("ads", params={"name": "Ejemplo"})
    assert calls == 1
    assert caught.value.outcome_unknown
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    assert "private-token" not in "".join(traceback.format_exception(caught.value))
    assert "private-token" not in caplog.text


@pytest.mark.parametrize(
    "status,payload",
    [
        (200, {"error": {"code": 190, "message": "private-token"}}),
        (503, {"error": {"code": 2, "message": "private-token"}}),
        (200, {}),
        (200, {"id": 4}),
        (502, None),
    ],
)
async def test_bad_write_responses_safe_no_retry(status: int, payload: Any) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return (
            httpx.Response(status, json=payload)
            if payload is not None
            else httpx.Response(status, text="private-token <html>")
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = MarketingClient(client=http, account_id="1")
        with pytest.raises(MarketingError) as caught:
            await client.create("ads", params={})
    assert calls == 1
    assert "private-token" not in str(caught.value)
    assert caught.value.outcome_unknown == (status != 200 or "error" not in payload)


class Clock:
    def __init__(self) -> None:
        self.now = 10.0
        self.waits: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds


@pytest.mark.parametrize(
    "header,value,expected",
    [
        ("X-Business-Use-Case-Usage", {"42": [{"estimated_time_to_regain_access": 2}]}, 120),
        ("X-Business-Use-Case", {"42": [{"total_time": 95}]}, 60),
        ("X-Ad-Account-Usage", {"acc_id_util_pct": 91, "reset_time_duration": 45}, 60),
        ("X-Ad-Account-Usage", {"acc_id_util_pct": 99, "reset_time_duration": 180}, 180),
    ],
)
async def test_cooldown_before_next_request(header: str, value: dict, expected: float) -> None:
    clock = Clock()
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if count == 2:
            assert clock.now == 10 + expected
        return httpx.Response(
            200,
            json={"id": "4", "status": "PAUSED"},
            headers={header: json.dumps(value) if count == 1 else "{}"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = MarketingClient(
            client=http, account_id="1", sleep=clock.sleep, monotonic=lambda: clock.now
        )
        await client.status("4")
        await client.status("4")
    assert clock.waits == [expected]


@pytest.mark.parametrize(
    "code,subcode,headers,status,expected",
    [
        (17, None, {}, 400, 60),
        (613, None, {}, 400, 60),
        (80004, None, {}, 400, 60),
        (100, 4841018, {}, 400, 30),
        (1, None, {"Retry-After": "125"}, 429, 125),
    ],
)
async def test_error_headers_and_codes_throttle_next_call(
    code: int, subcode: int | None, headers: dict, status: int, expected: float
) -> None:
    clock = Clock()
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(
                status, json={"error": {"code": code, "error_subcode": subcode}}, headers=headers
            )
        return httpx.Response(200, json={"id": "4"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = MarketingClient(
            client=http, account_id="1", sleep=clock.sleep, monotonic=lambda: clock.now
        )
        with pytest.raises(MarketingError) as caught:
            await client.status("4")
        assert caught.value.retry_after == expected
        assert count == 1
        await client.status("4")
    assert clock.waits == [expected]


async def test_malformed_usage_ignored() -> None:
    for value in ("bad-json", "[]", '"oops"', '{"call_count":"nan"}', '{"total_time":-4}'):
        assert cooldown_seconds(httpx.Headers({"X-Ad-Account-Usage": value}), status=200) == 0
    assert cooldown_seconds(httpx.Headers({"Retry-After": "infinity"}), status=429) == 60


async def test_unknown_write_outcome_does_not_invite_retry_but_reads_can_retry() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, json={"error": {"code": 999}})
        )
    ) as http:
        client = MarketingClient(client=http, account_id="1")
        with pytest.raises(MarketingError) as write:
            await client.create("ads", params={})
        assert write.value.outcome_unknown
        assert str(write.value) == UNKNOWN_WRITE_MESSAGE
        assert "antes de repetirlo" in str(write.value)
        with pytest.raises(MarketingError) as read:
            await client.status("4")
        assert not read.value.outcome_unknown
        assert str(read.value) == READ_ERROR_MESSAGE


async def test_http_debug_logs_and_logged_platform_error_redact_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "test-credential-that-must-not-escape"
    replies = [{"id": "4"}, {"error": {"code": 190, "message": secret}}]
    with caplog.at_level(logging.DEBUG):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=replies.pop(0))),
            headers={"Authorization": "Bearer " + secret},
        ) as http:
            client = MarketingClient(client=http, account_id="1")
            assert await client.create("ads", params={"status": "PAUSED"}) == "4"
            try:
                await client.status("4")
            except MarketingError:
                logging.getLogger("test.ads").exception("Safe advertising error")
    assert secret not in caplog.text
    assert "HTTP Request" in caplog.text


@pytest.mark.parametrize("value", ["../4", "4?access_token=secret", "https://evil.invalid", ""])
async def test_object_ids_cannot_inject_urls(value: str) -> None:
    fake = FakeMarketingClient()
    with pytest.raises(ValueError):
        await fake.status(value)
    assert not fake.calls
