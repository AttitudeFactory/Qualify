"""m-24852495: an OmniHuman render that outlives the wait is kept by id and resumed —
never submitted twice, never lost while BytePlus bills it. The adapter's side, against
`httpx.MockTransport` and a scripted clock (no key, no network)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from qualify_creative.adapters.byteplus_omnihuman import (
    RESUME_TASK_PARAM,
    OmniHumanTaskFailed,
    OmniHumanTimeout,
    OmniHumanVideoAdapter,
)
from qualify_creative.enums import GenerationTask
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationRequest, RenderedPrompt

MINUTE = 60.0


class Clock:
    """Monotonic time that advances by the poll interval on every sleep."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class Observer:
    def __init__(self, *, explode: bool = False) -> None:
        self.created_ids: list[str] = []
        self.statuses: list[str] = []
        self.explode = explode

    def created(self, task_id: str) -> None:
        self.created_ids.append(task_id)
        if self.explode:
            raise RuntimeError("the store is down")

    def polled(self, task_id: str, status: str) -> None:
        self.statuses.append(status)
        if self.explode:
            raise RuntimeError("the heartbeat is down")


def _timeline(clock: Clock, phases: list[tuple[str, float]]) -> Any:
    """A task whose status is decided by the clock: each (status, until-seconds)."""

    def status_at(now: float) -> str:
        for status, until in phases:
            if now < until:
                return status
        return phases[-1][0]

    return status_at


def _handler(status_at: Any, clock: Clock, seen: list[httpx.Request]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith(("submit_task", "submit_task_v2")):
            return httpx.Response(200, json={"code": 10000, "data": {"task_id": "oh-1"}})
        status = status_at(clock.now)
        data: dict[str, Any] = {"status": status}
        if status == "done":
            data["resp_data"] = json.dumps({"video_url": "https://cdn/v.mp4"})
        return httpx.Response(200, json={"code": 10000, "data": data})

    return handler


def _adapter(handler: Any, clock: Clock) -> OmniHumanVideoAdapter:
    return OmniHumanVideoAdapter(
        transport=httpx.MockTransport(handler), sleep=clock.sleep, monotonic=clock
    )


def _request(observer: Any = None, **params: Any) -> GenerationRequest:
    base: dict[str, Any] = {
        "image_url": "https://q/img.jpg",
        "audio_url": "https://q/voice.mp3",
        "audio_seconds": 30,
    }
    base.update(params)
    return GenerationRequest(
        task=GenerationTask.AVATAR_VIDEO,
        rendered_prompt=RenderedPrompt("", "", ""),
        params=base,
        observer=observer,
    )


def _submits(seen: list[httpx.Request]) -> int:
    return sum(1 for r in seen if r.url.path.endswith("submit_task"))


def test_30_min_queued_then_15_min_generating_lands_the_video_without_a_timeout() -> None:
    """AC: the render window counts from `generating`, never from the submit."""
    clock, seen, heard = Clock(), [], Observer()
    status_at = _timeline(
        clock, [("in_queue", 30 * MINUTE), ("generating", 45 * MINUTE), ("done", 1e9)]
    )
    result = _adapter(_handler(status_at, clock, seen), clock).generate(
        _request(heard), api_key="k"
    )
    assert result.media_url == "https://cdn/v.mp4"
    assert result.payload["task_id"] == "oh-1"  # type: ignore[index]
    assert heard.created_ids == ["oh-1"]  # heard before any poll
    assert heard.statuses[0] == "in_queue" and heard.statuses[-1] == "done"
    assert clock.now >= 45 * MINUTE


def test_the_id_is_heard_before_the_first_poll() -> None:
    clock, seen = Clock(), []
    order: list[str] = []

    class Ordered(Observer):
        def created(self, task_id: str) -> None:
            order.append(f"created after {len(seen)} requests")

    status_at = _timeline(clock, [("done", 1e9)])
    _adapter(_handler(status_at, clock, seen), clock).generate(_request(Ordered()), api_key="k")
    assert order == ["created after 1 requests"]  # only the submit had been sent


def test_still_queued_past_the_queue_window_times_out_keeping_the_id() -> None:
    clock, seen = Clock(), []
    status_at = _timeline(clock, [("in_queue", 1e9)])
    with pytest.raises(OmniHumanTimeout) as exc:
        _adapter(_handler(status_at, clock, seen), clock).generate(_request(), api_key="k")
    assert exc.value.task_id == "oh-1"
    assert 59 * MINUTE <= clock.now <= 60 * MINUTE


def test_generating_past_the_render_window_times_out_keeping_the_id() -> None:
    clock, seen = Clock(), []
    status_at = _timeline(clock, [("in_queue", 10 * MINUTE), ("generating", 1e9)])
    with pytest.raises(OmniHumanTimeout) as exc:
        _adapter(_handler(status_at, clock, seen), clock).generate(_request(), api_key="k")
    assert exc.value.task_id == "oh-1"
    # 10 min queued + the 40-min render window from the first `generating`
    assert 49 * MINUTE <= clock.now <= 50 * MINUTE


@pytest.mark.parametrize("status", ["expired", "not_found", "canceled"])
def test_a_task_omnihuman_ended_fails_as_task_failed(status: str) -> None:
    clock, seen = Clock(), []
    status_at = _timeline(clock, [("generating", 5 * MINUTE), (status, 1e9)])
    with pytest.raises(OmniHumanTaskFailed) as exc:
        _adapter(_handler(status_at, clock, seen), clock).generate(_request(), api_key="k")
    assert exc.value.task_id == "oh-1" and exc.value.status == status
    assert not isinstance(exc.value, OmniHumanTimeout)


def test_an_error_code_on_the_tasks_result_fails_it() -> None:
    clock = Clock()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("submit_task"):
            return httpx.Response(200, json={"code": 10000, "data": {"task_id": "oh-1"}})
        return httpx.Response(200, json={"code": 50511, "message": "post-filter"})

    with pytest.raises(OmniHumanTaskFailed) as exc:
        _adapter(handler, clock).generate(_request(), api_key="k")
    assert exc.value.code == 50511 and "code 50511" in str(exc.value)


def test_omnihuman_not_answering_stops_the_wait_as_a_timeout_not_a_failure() -> None:
    """A 5xx / dropped poll says nothing about the render: keep the id, recover later."""
    clock, answers = Clock(), iter([503, 200, 502, 503, 500])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("submit_task"):
            return httpx.Response(200, json={"code": 10000, "data": {"task_id": "oh-1"}})
        code = next(answers)
        if code == 200:
            return httpx.Response(200, json={"code": 10000, "data": {"status": "in_queue"}})
        return httpx.Response(code)

    with pytest.raises(OmniHumanTimeout) as exc:
        _adapter(handler, clock).generate(_request(), api_key="k")
    assert exc.value.task_id == "oh-1" and "unreachable" in str(exc.value)


def test_a_resume_waits_for_the_same_task_and_never_submits() -> None:
    clock, seen, heard = Clock(), [], Observer()
    status_at = _timeline(clock, [("generating", 2 * MINUTE), ("done", 1e9)])
    result = _adapter(_handler(status_at, clock, seen), clock).generate(
        GenerationRequest(
            task=GenerationTask.AVATAR_VIDEO,
            rendered_prompt=RenderedPrompt("", "", ""),
            # a resume needs neither the URLs nor the length: it orders nothing
            params={RESUME_TASK_PARAM: "oh-earlier"},
            observer=heard,
        ),
        api_key="k",
    )
    assert _submits(seen) == 0
    assert {json.loads(r.content)["task_id"] for r in seen} == {"oh-earlier"}
    assert result.payload["task_id"] == "oh-earlier"  # type: ignore[index]
    assert heard.created_ids == []  # nothing new to record


def test_a_resume_is_priced_at_zero_and_a_new_render_at_its_length() -> None:
    adapter = OmniHumanVideoAdapter()
    pricing = JsonPricingTable("v5")
    assert adapter.estimate_cost_usd(_request(audio_seconds=30), pricing) == Decimal("3.6000")
    assert adapter.estimate_cost_usd(_request(**{RESUME_TASK_PARAM: "oh-1"}), pricing) == Decimal(0)


def test_an_observer_that_fails_never_breaks_the_render() -> None:
    clock, seen = Clock(), []
    status_at = _timeline(clock, [("in_queue", MINUTE), ("done", 1e9)])
    result = _adapter(_handler(status_at, clock, seen), clock).generate(
        _request(Observer(explode=True)), api_key="k"
    )
    assert result.media_url == "https://cdn/v.mp4"


def test_get_task_reads_one_tasks_state_without_submitting() -> None:
    clock, seen = Clock(), []
    status_at = _timeline(clock, [("generating", 1e9)])
    data = _adapter(_handler(status_at, clock, seen), clock).get_task("oh-9", api_key="k")
    assert data["status"] == "generating"
    assert _submits(seen) == 0
    assert json.loads(seen[0].content) == {
        "req_key": "realman_avatar_picture_omni15_cv",
        "task_id": "oh-9",
    }


@pytest.mark.parametrize(
    ("status_code", "body"),
    [
        (200, {"code": 50400, "message": "access denied"}),
        (401, {"code": 50401, "message": "bad key"}),
        (403, {}),
    ],
)
def test_a_refused_key_on_a_poll_is_not_the_tasks_failure(
    status_code: int, body: dict[str, Any]
) -> None:
    """A key or account problem says nothing about the render: keep the id (pending)."""
    clock = Clock()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("submit_task"):
            return httpx.Response(200, json={"code": 10000, "data": {"task_id": "oh-1"}})
        return httpx.Response(status_code, json=body)

    with pytest.raises(OmniHumanTimeout) as exc:
        _adapter(handler, clock).generate(_request(), api_key="k")
    assert exc.value.task_id == "oh-1"
