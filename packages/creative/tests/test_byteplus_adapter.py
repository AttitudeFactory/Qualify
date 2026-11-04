"""BytePlus ModelArk adapters (Seedance video, Seedream image), exercised entirely offline
over an httpx MockTransport. The wire shapes are the ones verified live on 2026-10-07."""

import base64
import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest

httpx = pytest.importorskip("httpx")

from qualify_creative.adapters import (  # noqa: E402
    ArkAPIError,
    ArkTaskFailed,
    ArkTaskTimeout,
    SeedanceVideoAdapter,
    SeedreamImageAdapter,
)
from qualify_creative.adapters.byteplus_ark import (  # noqa: E402
    MAX_PROMPT_CHARS,
    SEEDREAM_MAX_POST_ATTEMPTS,
    VIDEO_PROMPT_MAX_WORDS,
    SeedreamDisconnected,
    estimate_video_tokens,
    output_dimensions,
    seedance_family,
    seedream_size,
    video_cost_usd,
)
from qualify_creative.enums import GenerationTask  # noqa: E402
from qualify_creative.pricing import JsonPricingTable  # noqa: E402
from qualify_creative.providers import GenerationRequest, RenderedPrompt  # noqa: E402

API_KEY = "ark-key"
PRICING = JsonPricingTable("v3")
FRAME = "data:image/jpeg;base64,AAAA"
SCRIPT = 'Hola, somos Nibbles. Esta es la "smash" triple.'


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Recorder:
    """Scripted ModelArk: the create answer, then the poll answers in order (the last
    one repeats). Every request is kept."""

    def __init__(self, create: httpx.Response, polls: list[httpx.Response]) -> None:
        self._create = create
        self._polls = polls
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "POST":
            return self._create
        return self._polls.pop(0) if len(self._polls) > 1 else self._polls[0]


def task(status: str, **extra: Any) -> httpx.Response:
    return httpx.Response(200, json={"id": "cgt-1", "status": status, **extra})


SUCCEEDED = task(
    "succeeded",
    model="seedance-1-0-pro-250528",
    content={"video_url": "https://ark/v.mp4", "last_frame_url": "https://ark/last.jpg"},
    usage={"completion_tokens": 102960, "total_tokens": 102960},
    duration=5,
    ratio="9:16",
    resolution="720p",
    seed=7,
)


def video_request(**params: object) -> GenerationRequest:
    base: dict[str, object] = {"prompt": "The presenter talks to the camera."}
    base.update(params)
    return GenerationRequest(
        task=GenerationTask.SCENE_VIDEO,
        rendered_prompt=RenderedPrompt("", "", ""),
        params=base,
    )


def seedance(
    handler: Callable[[httpx.Request], httpx.Response], clock: FakeClock | None = None, **kw: Any
) -> SeedanceVideoAdapter:
    clock = clock or FakeClock()
    return SeedanceVideoAdapter(
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        **kw,
    )


# -- Seedance ------------------------------------------------------------------------


def test_seedance_creates_an_i2v_task_and_polls_it_to_the_video() -> None:
    rec = Recorder(
        httpx.Response(200, json={"id": "cgt-1"}), [task("queued"), task("running"), SUCCEEDED]
    )
    clock = FakeClock()
    result = seedance(rec, clock).generate(
        video_request(
            first_frame=FRAME, ratio="9:16", resolution="720p", duration_seconds=5, dialogue=SCRIPT
        ),
        api_key=API_KEY,
    )

    create = rec.requests[0]
    assert create.url.path == "/api/v3/contents/generations/tasks"
    assert create.headers["Authorization"] == f"Bearer {API_KEY}"
    body = json.loads(create.content)
    # m-24820842 Q2: 1.x gets no adopt mark (only 2.x documents and uses the expiry)
    assert "execution_expires_after" not in body
    assert body == {
        "model": "seedance-1-0-pro-250528",
        # 1.0 is silent: the script is NOT put in the prompt, and no audio flag is sent
        "content": [
            {"type": "text", "text": "The presenter talks to the camera."},
            {"type": "image_url", "image_url": {"url": FRAME}, "role": "first_frame"},
        ],
        "ratio": "9:16",
        "resolution": "720p",
        "duration": 5,
        "watermark": False,
        "return_last_frame": True,
    }
    assert all(r.url.path.endswith("/tasks/cgt-1") for r in rec.requests[1:])
    assert len(clock.sleeps) == 2

    assert result.provider == "seedance" and result.model_id == "seedance-1-0-pro-250528"
    assert result.media_url == "https://ark/v.mp4"
    assert result.media_expires_at_seconds == 24 * 3600
    assert result.usage.output_tokens == 102960 and result.usage.media_seconds == Decimal(5)
    assert result.payload["last_frame_url"] == "https://ark/last.jpg"
    assert result.payload["generate_audio"] is False


def test_seedance_clamps_the_briefs_length_to_the_models_range() -> None:
    adapter = SeedanceVideoAdapter()
    assert adapter.spec({"prompt": "x", "duration_seconds": 30}).seconds == 12  # 1.0: 2–12 s
    assert adapter.spec({"prompt": "x", "duration_seconds": 1}).seconds == 2
    two = SeedanceVideoAdapter(model="dreamina-seedance-2-0-260128")
    assert two.spec({"prompt": "x", "duration_seconds": 30}).seconds == 15
    two_five = SeedanceVideoAdapter(model="dreamina-seedance-2-5-260628")
    assert two_five.spec({"prompt": "x", "duration_seconds": 30}).seconds == 30


def test_a_2x_seedance_speaks_the_script_in_quotes() -> None:
    adapter = SeedanceVideoAdapter(model="dreamina-seedance-2-5-260628")
    spec = adapter.spec({"prompt": "Escena.", "dialogue": SCRIPT, "duration_seconds": 15})
    body = spec.body()
    text = body["content"][0]["text"]  # type: ignore[index]
    # the line travels between double quotes; the script's own quotes are softened
    assert text.endswith("\"Hola, somos Nibbles. Esta es la 'smash' triple.\"")
    assert body["generate_audio"] is True
    assert "camera_fixed" not in body


def test_seedance_refuses_what_the_family_does_not_take() -> None:
    with pytest.raises(ValueError, match="unknown Seedance model"):
        SeedanceVideoAdapter(model="sora-2")
    fast = SeedanceVideoAdapter(model="dreamina-seedance-2-0-fast-260128")
    with pytest.raises(ValueError, match="renders"):
        fast.spec({"prompt": "x", "resolution": "1080p"})
    with pytest.raises(ValueError, match="ratio"):
        SeedanceVideoAdapter().spec({"prompt": "x", "ratio": "4:5"})
    with pytest.raises(ValueError, match="prompt"):
        SeedanceVideoAdapter().spec({"prompt": "  "})


def test_a_failed_task_raises_with_its_code_and_is_not_retried() -> None:
    failed = task("failed", error={"code": "OutputVideoSensitiveContentDetected", "message": "x"})
    rec = Recorder(httpx.Response(200, json={"id": "cgt-1"}), [failed])
    with pytest.raises(ArkTaskFailed, match="OutputVideoSensitiveContentDetected") as info:
        seedance(rec).generate(video_request(), api_key=API_KEY)
    assert info.value.task_id == "cgt-1" and info.value.status == "failed"


def test_the_poll_window_closes_with_the_task_id_kept() -> None:
    rec = Recorder(httpx.Response(200, json={"id": "cgt-1"}), [task("running")])
    adapter = seedance(rec, poll_interval_seconds=10, poll_timeout_seconds=25)
    with pytest.raises(ArkTaskTimeout) as info:
        adapter.generate(video_request(), api_key=API_KEY)
    assert info.value.task_id == "cgt-1"


def test_an_api_error_keeps_modelarks_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"error": {"code": "ModelNotOpen", "message": "not activated"}}
        )

    with pytest.raises(ArkAPIError) as info:
        seedance(handler).generate(video_request(), api_key=API_KEY)
    assert info.value.status_code == 404 and info.value.code == "ModelNotOpen"


def test_a_transient_poll_error_is_retried() -> None:
    rec = Recorder(
        httpx.Response(200, json={"id": "cgt-1"}),
        [httpx.Response(503, json={"error": {"code": "ServiceUnavailable"}}), SUCCEEDED],
    )
    result = seedance(rec).generate(video_request(), api_key=API_KEY)
    assert result.media_url == "https://ark/v.mp4"


def test_the_estimate_is_modelarks_own_token_formula_at_the_price_sheet() -> None:
    # 704 × 1248 × 24 fps × 5 s / 1024 = 102,960 tokens — the price page's own 720p row
    assert estimate_video_tokens("seedance-1-0-pro-250528", "720p", "9:16", 5) == 102960
    assert output_dimensions("seedance-1-0-pro-250528", "720p", "9:16") == (704, 1248)
    assert output_dimensions("dreamina-seedance-2-0-260128", "720p", "9:16") == (720, 1280)
    estimate = SeedanceVideoAdapter().estimate_cost_usd(
        video_request(ratio="9:16", resolution="720p", duration_seconds=5), PRICING
    )
    assert estimate == Decimal("0.257400")  # USD 2.5 / M tokens; the page says 0.26
    fast = video_cost_usd(PRICING, "seedance-1-0-pro-fast-251015", "720p", 102960)
    assert fast == Decimal("0.102960")  # the page says 0.10
    assert seedance_family("seedance-1-0-pro-fast-251015").audio is False


def test_an_unpriced_resolution_fails_the_estimate_loudly() -> None:
    adapter = SeedanceVideoAdapter(model="dreamina-seedance-2-0-260128")
    with pytest.raises(ValueError, match="renders"):
        adapter.estimate_cost_usd(video_request(resolution="4k"), PRICING)


# -- Seedream ------------------------------------------------------------------------


def image_request(**params: object) -> GenerationRequest:
    base: dict[str, object] = {"prompt": "An appetizing burger in a cozy restaurant."}
    base.update(params)
    return GenerationRequest(
        task=GenerationTask.PRODUCT_IMAGE,
        rendered_prompt=RenderedPrompt("", "", ""),
        params=base,
    )


def test_seedream_sends_the_references_and_returns_the_bytes() -> None:
    seen: list[httpx.Request] = []
    jpeg = b"\xff\xd8\xff-fake-jpeg"

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "model": "seedream-5-0-260128",
                "data": [{"b64_json": base64.b64encode(jpeg).decode(), "size": "1728x2160"}],
                "usage": {"generated_images": 1, "output_tokens": 14580},
            },
        )

    adapter = SeedreamImageAdapter(transport=httpx.MockTransport(handler))
    result = adapter.generate(
        image_request(images=[FRAME, "https://cdn/bg.jpg"], size="1728x2160"), api_key=API_KEY
    )

    (request,) = seen
    assert request.url.path == "/api/v3/images/generations"
    body = json.loads(request.content)
    assert body == {
        "model": "seedream-5-0-lite-260128",
        "prompt": "An appetizing burger in a cozy restaurant.",
        "size": "1728x2160",
        "response_format": "b64_json",
        "output_format": "jpeg",
        "watermark": False,
        "sequential_image_generation": "disabled",
        "image": [FRAME, "https://cdn/bg.jpg"],
    }
    assert result.payload["images"] == [jpeg]
    assert result.provider == "seedream" and result.usage.pieces == 1
    assert result.model_id == "seedream-5-0-lite-260128"
    assert result.model_revision == "seedream-5-0-260128"  # what the API echoes back


def test_one_reference_travels_as_a_string_and_none_is_text_to_image() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"b64_json": "AA=="}]})

    adapter = SeedreamImageAdapter(transport=httpx.MockTransport(handler))
    adapter.generate(image_request(images=[FRAME]), api_key=API_KEY)
    adapter.generate(image_request(), api_key=API_KEY)
    assert bodies[0]["image"] == FRAME and "image" not in bodies[1]


def test_seedream_without_an_image_or_with_an_error_raises() -> None:
    def moderated(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"code": "OutputImageSensitiveContentDetected", "message": "x"}},
        )

    with pytest.raises(ArkAPIError, match="OutputImageSensitiveContentDetected"):
        SeedreamImageAdapter(transport=httpx.MockTransport(moderated)).generate(
            image_request(), api_key=API_KEY
        )


def _flaky(failures: list[Exception | httpx.Response], ok: httpx.Response) -> Any:
    """A handler that fails with `failures` in order, then answers `ok`."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if failures:
            failure = failures.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return failure
        return ok

    handler.calls = calls  # type: ignore[attr-defined]
    return handler


_IMAGE_OK = httpx.Response(200, json={"data": [{"b64_json": "AA=="}]})


def test_a_dropped_connection_on_seedream_is_sent_again() -> None:
    """§ 2026-10-08: «Server disconnected without sending a response» failed a whole avatar
    video; a drop within seconds means the vendor never started, so ONE more try."""
    handler = _flaky(
        [httpx.RemoteProtocolError("Server disconnected without sending a response.")],
        _IMAGE_OK,
    )
    clock = FakeClock()
    adapter = SeedreamImageAdapter(transport=httpx.MockTransport(handler), sleep=clock.sleep)
    result = adapter.generate(image_request(), api_key=API_KEY)
    assert result.payload["images"] == [b"\x00"]
    assert len(handler.calls) == 2 and clock.sleeps == [2.0]


def test_seedream_tries_a_fast_drop_only_twice() -> None:
    error = httpx.RemoteProtocolError("Server disconnected without sending a response.")
    handler = _flaky([error, error, error], _IMAGE_OK)
    adapter = SeedreamImageAdapter(transport=httpx.MockTransport(handler), sleep=lambda _: None)
    with pytest.raises(SeedreamDisconnected, match="RemoteProtocolError"):
        adapter.generate(image_request(), api_key=API_KEY)
    assert len(handler.calls) == SEEDREAM_MAX_POST_ATTEMPTS == 2


def test_a_seedream_drop_after_a_long_wait_is_never_sent_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """m-24820842 (2026-11-03, drafts b9c3ec5e / 3dbfe77c): each of 3 attempts was cut at
    ~63 s — the image was being generated (and possibly billed). One attempt, then a
    message; never two more minutes of the same cut."""
    now = [0.0]

    def handler(request: httpx.Request) -> httpx.Response:
        now[0] += 63.0  # the gateway cut
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.")

    adapter = SeedreamImageAdapter(transport=httpx.MockTransport(handler), sleep=lambda _: None)
    adapter._clock = lambda: now[0]
    caplog.set_level("INFO", logger="qualify_creative.adapters.byteplus_ark")
    with pytest.raises(SeedreamDisconnected):
        adapter.generate(image_request(), api_key=API_KEY)
    assert now[0] == 63.0  # one attempt only
    assert "attempt 1: RemoteProtocolError in 63.0 s" in caplog.text


def test_every_post_attempt_is_logged_with_its_outcome(caplog: pytest.LogCaptureFixture) -> None:
    handler = _flaky([httpx.Response(503, json={"error": {"code": "x"}})], _IMAGE_OK)
    adapter = SeedreamImageAdapter(transport=httpx.MockTransport(handler), sleep=lambda _: None)
    caplog.set_level("INFO", logger="qualify_creative.adapters.byteplus_ark")
    adapter.generate(image_request(), api_key=API_KEY)
    assert "attempt 1: HTTP 503" in caplog.text and "attempt 2: ok" in caplog.text


def test_a_seedance_task_post_keeps_its_three_attempts() -> None:
    error = httpx.RemoteProtocolError("Server disconnected without sending a response.")
    handler = _flaky([error, error, error], httpx.Response(200, json={"id": "cgt-1"}))
    adapter = SeedanceVideoAdapter(transport=httpx.MockTransport(handler), sleep=lambda _: None)
    with adapter._client(API_KEY) as client, pytest.raises(httpx.RemoteProtocolError):
        adapter._post(client, "/contents/generations/tasks", {})
    assert len(handler.calls) == 3


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout("the model may be working on it"),
        httpx.Response(400, json={"error": {"code": "InvalidParameter", "message": "x"}}),
    ],
)
def test_a_post_the_vendor_may_have_started_is_never_sent_twice(
    failure: Exception | httpx.Response,
) -> None:
    handler = _flaky([failure], _IMAGE_OK)
    adapter = SeedreamImageAdapter(transport=httpx.MockTransport(handler), sleep=lambda _: None)
    with pytest.raises((SeedreamDisconnected, ArkAPIError)):
        adapter.generate(image_request(), api_key=API_KEY)
    assert len(handler.calls) == 1


def test_a_dropped_connection_creating_a_seedance_task_is_sent_again() -> None:
    handler = _flaky([httpx.ConnectError("refused")], httpx.Response(200, json={"id": "cgt-1"}))

    def routed(request: httpx.Request) -> httpx.Response:
        return handler(request) if request.method == "POST" else SUCCEEDED

    result = seedance(routed).generate(video_request(), api_key=API_KEY)
    assert result.media_url == "https://ark/v.mp4" and len(handler.calls) == 2


@pytest.mark.parametrize(
    ("model_id", "family"),
    [
        ("seedance-1-0-pro-250528", "seedance-1-0-pro"),
        ("seedance-1-0-pro", "seedance-1-0-pro"),
        ("dreamina-seedance-2-0-260128", "dreamina-seedance-2-0"),
        ("dreamina-seedance-2-0", "dreamina-seedance-2-0"),
        ("dreamina-seedance-2-5", "dreamina-seedance-2-5"),
        ("dreamina-seedance-2-5-260628", "dreamina-seedance-2-5"),
    ],
)
def test_a_family_resolves_with_or_without_its_date(model_id: str, family: str) -> None:
    """PR #100 review: a 2.x id ends in its version digit, which is not a date."""
    from qualify_creative.adapters.byteplus_ark import SEEDANCE_FAMILIES

    assert seedance_family(model_id) is SEEDANCE_FAMILIES[family]


def test_an_unknown_family_is_never_guessed() -> None:
    with pytest.raises(ValueError, match="unknown Seedance model"):
        seedance_family("dreamina-seedance-9-9")


def test_the_prompt_ceiling_counts_the_dialogue_line() -> None:
    """PR #100 review: the ceiling is on what is sent — prompt plus the spoken line. Since
    m-24820842 (2026-11-02) a 2.x prompt is bounded by the documented 1,000 words."""
    adapter = SeedanceVideoAdapter(model="dreamina-seedance-2-0")
    room = "palabra " * (VIDEO_PROMPT_MAX_WORDS - 4)
    adapter.spec({"prompt": room})  # alone it fits
    with pytest.raises(ValueError, match="recommended maximum is 1000"):
        adapter.spec({"prompt": room, "dialogue": "Una frase que ya no cabe."})


@pytest.mark.parametrize("model", ["dreamina-seedance-2-0", "dreamina-seedance-2-5"])
def test_a_2x_prompt_has_no_character_cap(model: str) -> None:
    """m-24820842: the docs state no hard length limit; only 1.x keeps the 3,000 cap."""
    long = "x" * (MAX_PROMPT_CHARS * 2)
    spec = SeedanceVideoAdapter(model=model).spec({"prompt": long})
    assert long in str(spec.body())
    with pytest.raises(ValueError, match="the cap is"):
        SeedanceVideoAdapter(model="seedance-1-0-pro").spec({"prompt": long})


def test_get_task_quotes_the_id_into_one_path_segment() -> None:
    """PR #100 review: a pasted id with `/` or `..` must not move the keyed call."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "x", "status": "running"})

    adapter = SeedanceVideoAdapter(transport=httpx.MockTransport(handler))
    adapter.get_task("cgt-1/../../models", api_key=API_KEY)
    assert seen[0].url.raw_path.decode().endswith("/tasks/cgt-1%2F..%2F..%2Fmodels")


@pytest.mark.parametrize("status", [502, 504])
def test_a_gateway_error_is_not_sent_twice(status: int) -> None:
    """PR #100 review: a 502/504 may come after the vendor started — no second bill."""
    handler = _flaky([httpx.Response(status, json={"error": {"code": "Gateway"}})], _IMAGE_OK)
    adapter = SeedreamImageAdapter(transport=httpx.MockTransport(handler), sleep=lambda _: None)
    with pytest.raises(ArkAPIError):
        adapter.generate(image_request(), api_key=API_KEY)
    assert len(handler.calls) == 1


def test_seedream_is_priced_per_piece_and_caps_the_references() -> None:
    adapter = SeedreamImageAdapter()
    assert adapter.estimate_cost_usd(image_request(), PRICING) == Decimal("0.035")
    with pytest.raises(ValueError, match="at most 14"):
        adapter.estimate_cost_usd(image_request(images=[FRAME] * 15), PRICING)
    with pytest.raises(ValueError, match="explicit"):
        adapter.generate(image_request(), api_key="")


def test_v3_pricing_carries_the_byteplus_rates() -> None:
    assert PRICING.unit_price(model_id="seedream-5-0-lite-260128", unit="per_piece") == Decimal(
        "0.035"
    )
    assert PRICING.unit_price(
        model_id="dreamina-seedance-2-5-260628", unit="per_mtok_video_1080p"
    ) == Decimal("11.7")
    # everything v2 had is still there
    assert PRICING.unit_price(model_id="heygen_avatar_iv", unit="per_second_1080p") == Decimal(
        "0.0667"
    )


@pytest.mark.parametrize(
    ("size", "model", "sent"),
    [
        ("1280x1600", "seedream-5-0-pro-260128", "1280x1600"),
        ("1280x1280", "seedream-4-0-250828", "1280x1280"),
        ("1080x1920", "seedream-5-0-flash-260128", "1080x1920"),
        # 5.0 lite / 4.5 take at least 2560x1440 px: the smallest valid size, same shape
        ("1280x1600", "seedream-5-0-lite-260128", "1728x2160"),
        ("1280x1280", "seedream-5-0-lite-260128", "1920x1920"),
        ("1080x1920", "seedream-4-5-251128", "1440x2560"),
        ("1248x1664", "seedream-5-0-lite-260128", "1680x2240"),
        ("1280x1600", "seedream-9-9", "1728x2160"),  # unknown model: the higher minimum
        ("2K", "seedream-5-0-lite-260128", "2K"),
    ],
)
def test_seedream_size_is_fitted_to_the_models_minimum(size: str, model: str, sent: str) -> None:
    assert seedream_size(size, model) == sent
    if "x" in sent:
        width, height = (int(v) for v in sent.split("x"))
        asked_w, asked_h = (int(v) for v in size.split("x"))
        assert width * asked_h == height * asked_w  # same proportions
        assert width % 16 == 0 or sent == size


def test_seedream_sends_the_fitted_size() -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return _IMAGE_OK

    adapter = SeedreamImageAdapter(
        model="seedream-5-0-lite-260128", transport=httpx.MockTransport(handler)
    )
    adapter.generate(image_request(size="1280x1600"), api_key=API_KEY)
    assert sent[0]["size"] == "1728x2160"


@pytest.mark.parametrize(
    "model", ["dola-seedream-5-0-pro-260628", "dola-seedream-5-0-flash-260915"]
)
def test_a_vendor_prefixed_seedream_id_keeps_its_own_minimum(model: str) -> None:
    """Review 2026-11-03: `dola-seedream-5-0-pro-260628` (the repo's own pro id) fell to the
    3.69 MP default and was sent at 1728x2160 while quoted at 1K."""
    assert seedream_size("1280x1600", model) == "1280x1600"
    assert seedream_size("640x640", model) == "960x960"  # pro/flash minimum: 921,600


def test_odd_proportions_stay_near_the_minimum_and_under_the_maximum() -> None:
    sent = seedream_size("1000x1001", "seedream-5-0-lite-260128")
    width, height = (int(v) for v in sent.split("x"))
    assert width % 16 == 0 and height % 16 == 0
    assert 3_686_400 <= width * height <= 4_000_000  # not 16000x16016
    assert abs(width / height - 1000 / 1001) < 0.01
