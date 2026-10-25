"""Seedance waits that outlive BytePlus's queue (m-24852154), offline over a MockTransport.

The render window counts from the first `running` answer, never from the task's
creation; a task this generation already created is resumed by id (no second POST); the
observer hears the id the moment ModelArk accepts the task — before any wait."""

from __future__ import annotations

from typing import Any

import pytest

httpx = pytest.importorskip("httpx")

from qualify_creative.adapters import ArkTaskFailed, ArkTaskTimeout, SeedanceVideoAdapter  # noqa: E402
from qualify_creative.adapters.byteplus_ark import RESUME_TASK_PARAM  # noqa: E402
from qualify_creative.enums import GenerationTask  # noqa: E402
from qualify_creative.providers import GenerationRequest, RenderedPrompt  # noqa: E402

API_KEY = "ark-key"
SUCCEEDED = {
    "id": "cgt-1",
    "status": "succeeded",
    "model": "seedance-1-0-pro-250528",
    "content": {"video_url": "https://ark/v.mp4"},
    "usage": {"completion_tokens": 102960},
    "duration": 5,
}


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class TimedVendor:
    """ModelArk answering by the clock: `queued` for `queued_for` seconds after the
    task exists, then `running` for `running_for`, then the final answer."""

    def __init__(
        self,
        clock: Clock,
        *,
        queued_for: float,
        running_for: float,
        final: dict[str, Any] | None = None,
    ) -> None:
        self.clock = clock
        self.queued_for = queued_for
        self.running_for = running_for
        self.final = final or SUCCEEDED
        self.posts = 0
        self.gets = 0
        self.created_at = 0.0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.posts += 1
            self.created_at = self.clock.now
            return httpx.Response(200, json={"id": "cgt-1"})
        self.gets += 1
        age = self.clock.now - self.created_at
        if age < self.queued_for:
            return httpx.Response(200, json={"id": "cgt-1", "status": "queued"})
        if age < self.queued_for + self.running_for:
            return httpx.Response(200, json={"id": "cgt-1", "status": "running"})
        return httpx.Response(200, json=self.final)


class Observer:
    def __init__(self, vendor: TimedVendor | None = None) -> None:
        self.events: list[tuple[str, str, str]] = []
        self._vendor = vendor

    def created(self, task_id: str) -> None:
        # the id is heard before the adapter has polled even once
        assert self._vendor is None or self._vendor.gets == 0
        self.events.append(("created", task_id, ""))

    def polled(self, task_id: str, status: str) -> None:
        self.events.append(("polled", task_id, status))


def _adapter(vendor: TimedVendor, clock: Clock, **kw: Any) -> SeedanceVideoAdapter:
    return SeedanceVideoAdapter(
        transport=httpx.MockTransport(vendor),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        **kw,
    )


def _request(observer: Observer | None = None, **params: object) -> GenerationRequest:
    return GenerationRequest(
        task=GenerationTask.SCENE_VIDEO,
        rendered_prompt=RenderedPrompt("", "", ""),
        params={"prompt": "Una hamburguesa girando.", **params},
        observer=observer,
    )


def test_ten_minutes_queued_and_two_running_ends_with_the_video() -> None:
    """The ticket's case: the old 8-minute window, counted from creation, gave up on
    this task (and BytePlus billed it anyway). Queue time no longer counts."""
    clock = Clock()
    vendor = TimedVendor(clock, queued_for=600, running_for=120)
    observer = Observer(vendor)
    result = _adapter(vendor, clock).generate(_request(observer), api_key=API_KEY)

    assert result.media_url == "https://ark/v.mp4"
    assert vendor.posts == 1
    assert observer.events[0] == ("created", "cgt-1", "")
    assert {status for kind, _, status in observer.events[1:]} == {
        "queued",
        "running",
        "succeeded",
    }
    assert clock.now > 480  # well past the old window


def test_a_render_still_running_past_its_window_stops_the_wait_not_the_task() -> None:
    clock = Clock()
    vendor = TimedVendor(clock, queued_for=60, running_for=10_000)
    with pytest.raises(ArkTaskTimeout) as info:
        _adapter(vendor, clock, poll_timeout_seconds=480).generate(_request(), api_key=API_KEY)
    assert info.value.task_id == "cgt-1" and info.value.status == "running"
    # the window opened at the first `running` answer (60 s), not at creation
    assert clock.now >= 60 + 480 - 5


def test_a_task_queued_past_the_queue_wait_is_left_to_be_resumed() -> None:
    clock = Clock()
    vendor = TimedVendor(clock, queued_for=10**6, running_for=60)
    observer = Observer(vendor)
    with pytest.raises(ArkTaskTimeout) as info:
        _adapter(vendor, clock, queue_timeout_seconds=900).generate(
            _request(observer), api_key=API_KEY
        )
    assert info.value.status == "queued" and info.value.task_id == "cgt-1"
    assert ("created", "cgt-1", "") in observer.events  # its id was kept first
    assert 890 <= clock.now <= 905


def test_a_task_with_an_id_is_resumed_never_submitted_again() -> None:
    clock = Clock()
    vendor = TimedVendor(clock, queued_for=0, running_for=0)
    observer = Observer()
    result = _adapter(vendor, clock).generate(
        _request(observer, **{RESUME_TASK_PARAM: "cgt-1"}), api_key=API_KEY
    )
    assert vendor.posts == 0 and vendor.gets == 1
    assert result.payload["task_id"] == "cgt-1"
    assert not any(kind == "created" for kind, _, _ in observer.events)


def test_a_resumed_task_the_vendor_expired_fails_unbilled() -> None:
    clock = Clock()
    expired = {"id": "cgt-1", "status": "expired", "error": {"code": "Expired"}}
    vendor = TimedVendor(clock, queued_for=0, running_for=0, final=expired)
    with pytest.raises(ArkTaskFailed) as info:
        _adapter(vendor, clock).generate(_request(**{RESUME_TASK_PARAM: "cgt-1"}), api_key=API_KEY)
    assert info.value.status == "expired" and vendor.posts == 0


def test_an_observer_that_breaks_never_breaks_the_task() -> None:
    class Broken:
        def created(self, task_id: str) -> None:
            raise RuntimeError("database away")

        def polled(self, task_id: str, status: str) -> None:
            raise RuntimeError("database away")

    clock = Clock()
    vendor = TimedVendor(clock, queued_for=10, running_for=10)
    result = _adapter(vendor, clock).generate(_request(Broken()), api_key=API_KEY)  # type: ignore[arg-type]
    assert result.media_url == "https://ark/v.mp4"
