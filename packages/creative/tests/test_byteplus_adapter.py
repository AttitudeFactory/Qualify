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
    estimate_video_tokens,
    output_dimensions,
    seedance_family,
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
    video; the vendor never started the work, so sending it again cannot bill twice."""
    handler = _flaky(
        [
            httpx.RemoteProtocolError("Server disconnected without sending a response."),
            httpx.Response(503, json={"error": {"code": "ServiceUnavailable"}}),
        ],
        _IMAGE_OK,
    )
    clock = FakeClock()
    adapter = SeedreamImageAdapter(transport=httpx.MockTransport(handler), sleep=clock.sleep)
    result = adapter.generate(image_request(), api_key=API_KEY)
    assert result.payload["images"] == [b"\x00"]
    assert len(handler.calls) == 3 and clock.sleeps == [2.0, 4.0]


def test_a_post_gives_up_after_its_attempts() -> None:
    error = httpx.RemoteProtocolError("Server disconnected without sending a response.")
    handler = _flaky([error, error, error], _IMAGE_OK)
    adapter = SeedreamImageAdapter(transport=httpx.MockTransport(handler), sleep=lambda _: None)
    with pytest.raises(httpx.RemoteProtocolError):
        adapter.generate(image_request(), api_key=API_KEY)
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
    with pytest.raises((httpx.ReadTimeout, ArkAPIError)):
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
