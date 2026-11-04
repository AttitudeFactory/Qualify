"""m-24852159: Seedance's task as two public steps — `submit` (the id, at once) and `poll`
(one query) — with a busy vendor raised as `VendorBusy`, an adaptive wait between queries
and the queue fields (`priority`, `execution_expires_after`) on the POST. All offline over
an httpx MockTransport; the blocking `generate` keeps its own tests unchanged."""

import json
from typing import Any

import pytest

httpx = pytest.importorskip("httpx")

from qualify_creative.adapters import (  # noqa: E402
    ArkAPIError,
    ArkTaskFailed,
    QueryRateLimiter,
    SeedanceVideoAdapter,
    SeedreamImageAdapter,
    TaskState,
    VendorBusy,
)
from qualify_creative.adapters.byteplus_ark import (  # noqa: E402
    ADOPT_LIST_DELAYS_SECONDS,
    ADOPT_MARK_RANGE,
    EXPIRES_AFTER_RANGE_SECONDS,
    MAX_QUEUED_POLL_INTERVAL_SECONDS,
    QUEUED_FAST_POLL_SECONDS,
    RESUME_TASK_PARAM,
    SEEDANCE_POST_TIMEOUT_SECONDS,
    VENDOR_TASK_EXPIRY_SECONDS,
    _sent_by,
    poll_delay_seconds,
)
from qualify_creative.enums import GenerationTask  # noqa: E402
from qualify_creative.providers import GenerationRequest, RenderedPrompt  # noqa: E402

API_KEY = "ark-key"
V25 = "dreamina-seedance-2-5-260628"
V20 = "dreamina-seedance-2-0-260128"


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Vendor:
    """Scripted ModelArk: POST answers in order, then GET answers in order (each list's
    last answer repeats). Every request is kept."""

    def __init__(self, posts: list[httpx.Response], gets: list[httpx.Response]) -> None:
        self._posts = posts
        self._gets = gets
        self.requests: list[httpx.Request] = []

    @staticmethod
    def _next(answers: list[httpx.Response]) -> httpx.Response:
        return answers.pop(0) if len(answers) > 1 else answers[0]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._next(self._posts if request.method == "POST" else self._gets)

    @property
    def posts(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == "POST"]

    @property
    def gets(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == "GET"]


class Observer:
    def __init__(self) -> None:
        self.events: list[tuple[str, ...]] = []

    def created(self, task_id: str) -> None:
        self.events.append(("created", task_id))

    def polled(self, task_id: str, status: str) -> None:
        self.events.append(("polled", task_id, status))


CREATED = httpx.Response(200, json={"id": "cgt-1"})


def state(status: str, **extra: Any) -> httpx.Response:
    return httpx.Response(200, json={"id": "cgt-1", "status": status, **extra})


SUCCEEDED = state(
    "succeeded",
    model="seedance-1-0-pro-250528",
    content={"video_url": "https://ark/v.mp4", "last_frame_url": "https://ark/last.jpg"},
    usage={"completion_tokens": 102960},
    duration=5,
    ratio="9:16",
    resolution="720p",
)


def busy(code: str, status: int = 429, retry_after: str | None = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return httpx.Response(
        status, json={"error": {"code": code, "message": "slow down"}}, headers=headers
    )


def request(observer: Observer | None = None, **params: object) -> GenerationRequest:
    return GenerationRequest(
        task=GenerationTask.SCENE_VIDEO,
        rendered_prompt=RenderedPrompt("", "", ""),
        params={"prompt": "Una hamburguesa girando.", **params},
        observer=observer,
    )


def adapter(vendor: Vendor, clock: Clock | None = None, **kw: Any) -> SeedanceVideoAdapter:
    clock = clock or Clock()
    return SeedanceVideoAdapter(
        transport=httpx.MockTransport(vendor), sleep=clock.sleep, monotonic=clock.monotonic, **kw
    )


# -- submit / poll --------------------------------------------------------------------


def test_submit_returns_the_id_without_waiting_and_the_observer_has_it() -> None:
    vendor = Vendor([CREATED], [state("queued")])
    clock, observer = Clock(), Observer()
    task_id = adapter(vendor, clock).submit(request(observer), api_key=API_KEY)

    assert task_id == "cgt-1"
    assert len(vendor.posts) == 1 and vendor.gets == []  # not a single query
    assert clock.sleeps == []
    assert observer.events == [("created", "cgt-1")]


@pytest.mark.parametrize("status", ["queued", "running", "succeeded", "failed", "expired"])
def test_poll_reflects_the_vendors_status_in_one_query(status: str) -> None:
    answer = SUCCEEDED if status == "succeeded" else state(status)
    vendor = Vendor([CREATED], [answer])
    observer = Observer()
    result = adapter(vendor).poll("cgt-1", api_key=API_KEY, observer=observer)

    assert isinstance(result, TaskState)
    assert result.task_id == "cgt-1" and result.status == status
    assert result.terminal is (status in {"succeeded", "failed", "expired"})
    assert result.succeeded is (status == "succeeded")
    assert len(vendor.gets) == 1 and vendor.posts == []
    assert vendor.gets[0].url.path == "/api/v3/contents/generations/tasks/cgt-1"
    assert observer.events == [("polled", "cgt-1", status)]


def test_a_failed_poll_is_a_state_and_its_result_raises_unbilled() -> None:
    failed = state("failed", error={"code": "OutputVideoSensitiveContentDetected", "message": "x"})
    seedance = adapter(Vendor([CREATED], [failed]))
    seen = seedance.poll("cgt-1", api_key=API_KEY)
    assert seen.error_code == "OutputVideoSensitiveContentDetected"
    with pytest.raises(ArkTaskFailed) as info:
        seedance.result(request(), seen)
    assert info.value.status == "failed" and info.value.task_id == "cgt-1"


def test_a_task_still_going_has_no_result_yet() -> None:
    seedance = adapter(Vendor([CREATED], [state("running")]))
    with pytest.raises(ValueError, match="still running"):
        seedance.result(request(), seedance.poll("cgt-1", api_key=API_KEY))


def test_submit_then_poll_gives_the_same_result_as_the_blocking_call() -> None:
    blocking = adapter(Vendor([CREATED], [state("queued"), SUCCEEDED])).generate(
        request(), api_key=API_KEY
    )
    seedance = adapter(Vendor([CREATED], [state("queued"), SUCCEEDED]))
    task_id = seedance.submit(request(), api_key=API_KEY)
    first = seedance.poll(task_id, api_key=API_KEY)
    assert first.status == "queued"
    stepped = seedance.result(request(), seedance.poll(task_id, api_key=API_KEY))
    assert stepped == blocking


def test_submit_refuses_a_request_whose_task_already_exists() -> None:
    vendor = Vendor([CREATED], [state("queued")])
    with pytest.raises(ValueError, match="poll it"):
        adapter(vendor).submit(request(**{RESUME_TASK_PARAM: "cgt-1"}), api_key=API_KEY)
    assert vendor.requests == []


# -- busy vendor ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "wait"),
    [
        (busy("ModelAccountRpmRateLimitExceeded"), 15.0),
        (busy("QuotaExceeded"), 60.0),
        (busy("ServerOverloaded"), 30.0),
        (busy("ModelAccountRpmRateLimitExceeded", retry_after="7"), 7.0),
        # the code alone marks it busy, whatever the status
        (busy("ServerOverloaded", status=503), 30.0),
    ],
)
def test_a_busy_submit_raises_vendor_busy_with_its_wait_and_no_blind_retry(
    answer: httpx.Response, wait: float
) -> None:
    vendor = Vendor([answer, CREATED], [state("queued")])
    clock, observer = Clock(), Observer()
    with pytest.raises(VendorBusy) as info:
        adapter(vendor, clock).submit(request(observer), api_key=API_KEY)

    assert info.value.retry_after_seconds == wait
    assert isinstance(info.value, ArkAPIError)  # the status and «HTTP 429» stay readable
    assert len(vendor.posts) == 1  # sent once: no retry spent
    assert clock.sleeps == []
    assert observer.events == []  # nothing was created


def test_the_blocking_call_waits_what_a_busy_vendor_suggests_then_creates_once() -> None:
    vendor = Vendor(
        [busy("ModelAccountRpmRateLimitExceeded", retry_after="12"), CREATED], [SUCCEEDED]
    )
    clock, observer = Clock(), Observer()
    result = adapter(vendor, clock).generate(request(observer), api_key=API_KEY)

    assert result.media_url == "https://ark/v.mp4"
    assert len(vendor.posts) == 2 and clock.sleeps[0] == 12.0
    assert observer.events[0] == ("created", "cgt-1")


def test_the_blocking_call_gives_up_on_a_busy_vendor_past_its_budget() -> None:
    vendor = Vendor([busy("QuotaExceeded")], [SUCCEEDED])
    clock = Clock()
    with pytest.raises(VendorBusy) as info:
        adapter(vendor, clock, busy_budget_seconds=90).generate(request(), api_key=API_KEY)
    assert info.value.code == "QuotaExceeded"
    assert clock.sleeps == [60.0]  # one 60 s wait fits in 90 s, a second does not
    assert len(vendor.posts) == 2


def test_a_busy_poll_raises_vendor_busy_and_the_wait_honours_it() -> None:
    vendor = Vendor([CREATED], [busy("ModelAccountRpmRateLimitExceeded", retry_after="9")])
    with pytest.raises(VendorBusy):
        adapter(vendor).poll("cgt-1", api_key=API_KEY)

    vendor = Vendor([CREATED], [busy("ServerOverloaded", retry_after="9"), SUCCEEDED])
    clock = Clock()
    result = adapter(vendor, clock).generate(request(), api_key=API_KEY)
    assert result.media_url == "https://ark/v.mp4" and clock.sleeps == [9.0]


def test_seedream_keeps_its_bounded_retry_on_a_busy_answer() -> None:
    import base64

    image = base64.b64encode(b"\xff\xd8jpeg").decode()
    answers = [busy("ModelAccountIpmRateLimitExceeded"), busy("ServerOverloaded")]
    answers.append(httpx.Response(200, json={"data": [{"b64_json": image}]}))
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return answers.pop(0)

    clock = Clock()
    seedream = SeedreamImageAdapter(transport=httpx.MockTransport(handler), sleep=clock.sleep)
    seedream.generate(
        GenerationRequest(
            task=GenerationTask.PRODUCT_IMAGE,
            rendered_prompt=RenderedPrompt("", "", ""),
            params={"prompt": "Una hamburguesa."},
        ),
        api_key=API_KEY,
    )
    assert len(calls) == 3 and clock.sleeps == [2.0, 4.0]


# -- queue fields ---------------------------------------------------------------------


def test_priority_and_expiry_travel_in_the_post_body() -> None:
    vendor = Vendor([CREATED], [state("queued")])
    adapter(vendor, model=V25).submit(
        request(), api_key=API_KEY, priority=7, execution_expires_after=3600
    )
    body = json.loads(vendor.posts[0].content)
    # m-24820842: the caller's expiry plus the random adopt mark (under 1 h)
    assert body["priority"] == 7
    assert 3600 < body["execution_expires_after"] <= 3600 + ADOPT_MARK_RANGE


def test_priority_and_expiry_ride_the_params_too_and_the_arguments_win() -> None:
    vendor = Vendor([CREATED], [SUCCEEDED])
    adapter(vendor, model=V20).generate(
        request(priority=2, execution_expires_after=86400), api_key=API_KEY
    )
    body = json.loads(vendor.posts[0].content)
    assert body["priority"] == 2
    assert 86400 < body["execution_expires_after"] <= 86400 + ADOPT_MARK_RANGE

    vendor = Vendor([CREATED], [state("queued")])
    adapter(vendor, model=V20).submit(request(priority=2), api_key=API_KEY, priority=9)
    assert json.loads(vendor.posts[0].content)["priority"] == 9


def test_a_draft_final_carries_the_queue_fields_beside_the_draft_id() -> None:
    vendor = Vendor([CREATED], [state("queued")])
    adapter(vendor, model=V25).submit(
        request(draft_task_id="cgt-draft"), api_key=API_KEY, priority=9
    )
    body = json.loads(vendor.posts[0].content)
    assert body["content"] == [{"type": "draft_task", "draft_task": {"id": "cgt-draft"}}]
    assert body["priority"] == 9
    # m-24820842: a final is marked too, so a timed-out final POST adopts only its own task
    mark = body["execution_expires_after"]
    assert VENDOR_TASK_EXPIRY_SECONDS < mark <= VENDOR_TASK_EXPIRY_SECONDS + ADOPT_MARK_RANGE


def test_without_them_the_post_body_is_what_it_always_was() -> None:
    vendor = Vendor([CREATED], [state("queued")])
    adapter(vendor, model=V25).submit(request(), api_key=API_KEY)
    body = json.loads(vendor.posts[0].content)
    assert "priority" not in body
    # m-24820842: ModelArk's default 48 h plus a random mark that tells this task apart
    # in the task list should the POST time out (`ADOPT_MARK_RANGE`, under 1 h)
    mark = body["execution_expires_after"]
    assert VENDOR_TASK_EXPIRY_SECONDS < mark <= VENDOR_TASK_EXPIRY_SECONDS + ADOPT_MARK_RANGE


@pytest.mark.parametrize(
    ("model", "params", "match"),
    [
        ("seedance-1-0-pro-250528", {"priority": 3}, "takes no priority"),
        (V25, {"priority": 10}, "0-9"),
        (V25, {"priority": True}, "0-9"),
        (V25, {"execution_expires_after": 600}, "execution_expires_after"),
        (V25, {"execution_expires_after": 300000}, "execution_expires_after"),
    ],
)
def test_out_of_range_queue_fields_fail_before_any_call(
    model: str, params: dict[str, object], match: str
) -> None:
    vendor = Vendor([CREATED], [state("queued")])
    with pytest.raises(ValueError, match=match):
        adapter(vendor, model=model).submit(request(**params), api_key=API_KEY)
    assert vendor.requests == []


# -- adaptive wait --------------------------------------------------------------------


def test_the_poll_delay_grows_while_the_task_stays_queued() -> None:
    base = 5.0
    assert poll_delay_seconds("queued", 0, base) == base
    assert poll_delay_seconds("queued", QUEUED_FAST_POLL_SECONDS - 1, base) == base
    later = [poll_delay_seconds("queued", QUEUED_FAST_POLL_SECONDS + s, base) for s in (30, 90)]
    assert base < later[0] < later[1]
    assert poll_delay_seconds("queued", 10_000, base) == MAX_QUEUED_POLL_INTERVAL_SECONDS
    # a running render is polled at the base interval however long it queued
    assert poll_delay_seconds("running", 10_000, base) == base


def test_the_wait_between_queries_grows_while_queued_and_resets_once_running() -> None:
    clock = Clock()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return CREATED
        if clock.now < 600:
            return state("queued")
        if clock.now < 700:
            return state("running")
        return SUCCEEDED

    seedance = SeedanceVideoAdapter(
        transport=httpx.MockTransport(handler), sleep=clock.sleep, monotonic=clock.monotonic
    )
    seedance.generate(request(), api_key=API_KEY)

    queued = [s for s, t in zip(clock.sleeps, _times(clock.sleeps), strict=True) if t < 600]
    running = [s for s, t in zip(clock.sleeps, _times(clock.sleeps), strict=True) if t >= 600]
    assert queued[0] == 5.0
    assert queued == sorted(queued) and queued[-1] > 5.0  # grew while queued
    assert set(running) == {5.0}  # back to the base once rendering
    # fewer queries than a fixed 5 s cadence (120 in 600 s)
    assert len(queued) < 80


def _times(sleeps: list[float]) -> list[float]:
    """The clock time at which each sleep began."""
    out, now = [], 0.0
    for s in sleeps:
        out.append(now)
        now += s
    return out


def test_the_rate_limiter_holds_queries_to_twenty_a_second() -> None:
    clock = Clock()
    limiter = QueryRateLimiter(20, monotonic=clock.monotonic, sleep=clock.sleep)
    waits = [limiter.acquire() for _ in range(25)]
    assert waits[:20] == [0.0] * 20  # the burst the account allows
    assert all(w > 0 for w in waits[20:])
    assert clock.now == pytest.approx(5 / 20)  # the five past the burst waited 0.05 s each


def test_every_query_goes_through_the_shared_limiter() -> None:
    clock = Clock()
    limiter = QueryRateLimiter(1, monotonic=clock.monotonic, sleep=clock.sleep)
    seedance = adapter(Vendor([CREATED], [state("queued")]), clock, query_limiter=limiter)
    seedance.poll("cgt-1", api_key=API_KEY)
    seedance.poll("cgt-1", api_key=API_KEY)
    assert clock.sleeps == [pytest.approx(1.0)]  # the second waited its turn


# -- m-24820842: a task POST that times out or drops is adopted, never sent twice ---------


class SlowPostVendor:
    """ModelArk that creates the task but answers the POST too late (`ReadTimeout`) or
    drops it; the task list then shows what it created — `listed` tasks plus, when
    `created` is set, the one this POST made (with the mark the POST carried)."""

    def __init__(
        self,
        *,
        error: type[Exception] = httpx.ReadTimeout,
        created: str | None = "cgt-adopted",
        listed: list[dict[str, Any]] | None = None,
        visible_after: int = 1,
    ) -> None:
        self.error = error
        self.created = created
        self.listed = listed or []
        self.visible_after = visible_after
        self.requests: list[httpx.Request] = []
        self.lists = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "POST":
            raise self.error("too slow", request=request)
        if request.url.path.endswith("/contents/generations/tasks"):
            self.lists += 1
            items = list(self.listed)
            if self.created and self.lists >= self.visible_after:
                body = json.loads(self.posts[0].content)
                items.insert(
                    0,
                    {
                        "id": self.created,
                        "model": body["model"],
                        "status": "queued",
                        "created_at": 1_000_001,
                        "execution_expires_after": body.get("execution_expires_after"),
                        "ratio": body.get("ratio"),
                        "resolution": body.get("resolution"),
                        "duration": body.get("duration"),
                    },
                )
            return httpx.Response(200, json={"items": items, "total": len(items)})
        return httpx.Response(200, json={"id": self.created, "status": "queued"})

    @property
    def posts(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == "POST"]


def slow_adapter(vendor: SlowPostVendor, model: str = V25) -> SeedanceVideoAdapter:
    clock = Clock()
    return SeedanceVideoAdapter(
        model=model,
        transport=httpx.MockTransport(vendor),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        wall_clock=lambda: 1_000_000.0,
    )


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.RemoteProtocolError])
def test_a_post_that_times_out_or_drops_adopts_the_task_it_created(
    error: type[Exception],
) -> None:
    vendor = SlowPostVendor(error=error, visible_after=2)
    observer = Observer()
    task_id = slow_adapter(vendor).submit(request(observer), api_key=API_KEY)
    assert task_id == "cgt-adopted"
    assert len(vendor.posts) == 1  # never sent twice
    assert observer.events == [("created", "cgt-adopted")]
    listing = [r for r in vendor.requests if r.method == "GET"]
    assert listing[0].url.params["filter.model"] == V25


def test_the_task_post_waits_longer_than_a_status_query() -> None:
    vendor = Vendor([CREATED], [state("queued")])
    a = adapter(vendor, model=V25)
    a.submit(request(), api_key=API_KEY)
    a.poll("cgt-1", api_key=API_KEY)
    assert vendor.posts[0].extensions["timeout"]["read"] == SEEDANCE_POST_TIMEOUT_SECONDS == 180
    assert vendor.gets[0].extensions["timeout"]["read"] == 60


def test_nothing_found_raises_the_posts_error_without_a_second_post() -> None:
    vendor = SlowPostVendor(created=None)
    with pytest.raises(httpx.ReadTimeout):
        slow_adapter(vendor).submit(request(), api_key=API_KEY)
    assert len(vendor.posts) == 1
    assert vendor.lists == len(ADOPT_LIST_DELAYS_SECONDS)


def test_a_task_of_another_post_is_never_adopted() -> None:
    """Same model, same moment, but not this POST's mark — or created before it started."""
    others = [
        {"id": "cgt-other", "model": V25, "status": "queued", "created_at": 1_000_002,
         "execution_expires_after": 172800},
        {"id": "cgt-old", "model": V25, "status": "queued", "created_at": 999_000},
    ]  # fmt: skip
    vendor = SlowPostVendor(created=None, listed=others)
    with pytest.raises(httpx.ReadTimeout):
        slow_adapter(vendor).submit(request(), api_key=API_KEY)
    assert len(vendor.posts) == 1


def test_two_look_alikes_without_a_mark_are_never_guessed() -> None:
    twin = {"model": V25, "status": "queued", "created_at": 1_000_003, "duration": 5}
    vendor = SlowPostVendor(created=None, listed=[{"id": "cgt-a", **twin}, {"id": "cgt-b", **twin}])
    with pytest.raises(httpx.ReadTimeout):
        slow_adapter(vendor).submit(
            request(execution_expires_after=7200, duration_seconds=5), api_key=API_KEY
        )
    assert len(vendor.posts) == 1


LOOK_ALIKE_CASES = [
    # (model, params): a 2.5 clip, a caller-set expiry, a 1.x clip, a 2.5 draft's final
    (V25, {}),
    (V25, {"execution_expires_after": 7200}),
    (V25, {"execution_expires_after": 259200}),
    ("seedance-1-0-pro-250528", {}),
    (V25, {"draft_task_id": "cgt-draft"}),
]


@pytest.mark.parametrize(("model", "params"), LOOK_ALIKE_CASES)
def test_a_single_look_alike_without_the_mark_is_never_adopted(
    model: str, params: dict[str, object]
) -> None:
    """m-24820842 B1: the task list spans the whole BytePlus account, every tenant
    included. One task of the same model created meanwhile, matching every field but
    carrying no mark, may be another tenant's: the POST's error goes up instead."""
    # no ratio/resolution/duration listed: nothing rules it out but the missing mark
    theirs = {"id": "cgt-theirs", "model": model, "status": "queued", "created_at": 1_000_003}
    vendor = SlowPostVendor(created=None, listed=[theirs])
    with pytest.raises(httpx.ReadTimeout):
        slow_adapter(vendor, model=model).submit(request(**params), api_key=API_KEY)
    assert len(vendor.posts) == 1
    assert vendor.lists == len(ADOPT_LIST_DELAYS_SECONDS)


@pytest.mark.parametrize(("model", "params"), LOOK_ALIKE_CASES)
def test_a_single_look_alike_with_another_mark_is_never_adopted(
    model: str, params: dict[str, object]
) -> None:
    vendor = SlowPostVendor(created=None)
    vendor.listed = [
        {"id": "cgt-theirs", "model": model, "status": "queued", "created_at": 1_000_003,
         "execution_expires_after": VENDOR_TASK_EXPIRY_SECONDS + ADOPT_MARK_RANGE + 1}
    ]  # fmt: skip
    with pytest.raises(httpx.ReadTimeout):
        slow_adapter(vendor, model=model).submit(request(**params), api_key=API_KEY)
    assert len(vendor.posts) == 1


@pytest.mark.parametrize(("model", "params"), LOOK_ALIKE_CASES)
def test_every_create_is_marked_and_adopts_only_its_own_task(
    model: str, params: dict[str, object]
) -> None:
    """1.x, a draft's final and a caller-set expiry carry the mark too, beside a
    look-alike without one: the task with this POST's mark is the one taken."""
    look_alike = {"id": "cgt-theirs", "model": model, "status": "queued",
                  "created_at": 1_000_002}  # fmt: skip
    vendor = SlowPostVendor(listed=[look_alike])
    task_id = slow_adapter(vendor, model=model).submit(request(**params), api_key=API_KEY)
    assert task_id == "cgt-adopted" and len(vendor.posts) == 1
    mark = json.loads(vendor.posts[0].content)["execution_expires_after"]
    low, high = EXPIRES_AFTER_RANGE_SECONDS
    assert low <= mark <= high
    asked = params.get("execution_expires_after", VENDOR_TASK_EXPIRY_SECONDS)
    assert 0 < abs(mark - asked) <= ADOPT_MARK_RANGE


def test_an_unmarked_body_is_never_matched() -> None:
    item = {"id": "cgt-x", "model": V25, "status": "queued", "created_at": 1_000_003}
    assert not _sent_by(item, {"model": V25}, 1_000_000.0, None)
