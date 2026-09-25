"""HeyGen avatar-video adapter, exercised entirely offline over an httpx MockTransport."""

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

httpx = pytest.importorskip("httpx")

from qualify_creative.adapters import (  # noqa: E402
    HeyGenAPIError,
    HeyGenAvatarVideoAdapter,
    HeyGenError,
    HeyGenRenderFailed,
    HeyGenRenderTimeout,
)
from qualify_creative.adapters.heygen_video import estimate_seconds  # noqa: E402
from qualify_creative.enums import GenerationTask, PaidBy  # noqa: E402
from qualify_creative.pricing import JsonPricingTable  # noqa: E402
from qualify_creative.providers import GenerationRequest, RenderedPrompt, ResolvedKey  # noqa: E402
from qualify_creative.router import BudgetContext, CreativeRouter, HopAction  # noqa: E402

API_KEY = "hg-tenant-key"
SCRIPT = "Hola, somos Bianki. Este viernes llega el nuevo pan de masa madre."  # 12 words

COMPLETED = {
    "id": "v_1",
    "status": "completed",
    "video_url": "https://files.heygen.ai/video/v_1.mp4",
    "thumbnail_url": "https://files.heygen.ai/thumb/v_1.jpg",
    "subtitle_url": "https://files.heygen.ai/srt/v_1.srt",
    "captioned_video_url": None,
    "duration": 6.4,
    "failure_code": None,
    "failure_message": None,
}


def make_request(**params: object) -> GenerationRequest:
    base: dict[str, object] = {"avatar_id": "av_1", "voice_id": "vo_1", "script": SCRIPT}
    base.update(params)
    return GenerationRequest(
        task=GenerationTask.AVATAR_VIDEO,
        rendered_prompt=RenderedPrompt(stable_prefix="", volatile_suffix="", prefix_fingerprint=""),
        params=base,
    )


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
    """Scripted HeyGen: one create answer, then the poll answers in order (the last one
    repeats). Every request is kept so tests can assert on the wire."""

    def __init__(self, create: httpx.Response, polls: list[httpx.Response]) -> None:
        self._create = create
        self._polls = polls
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "POST":
            return self._create
        return self._polls.pop(0) if len(self._polls) > 1 else self._polls[0]


def ok(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"data": data})


def err(status: int, code: str, message: str = "boom", **headers: str) -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"code": code, "message": message}}, headers=headers
    )


CREATED = ok({"video_id": "v_1", "status": "waiting", "output_format": "mp4"})


def adapter_for(
    handler: Callable[[httpx.Request], httpx.Response], clock: FakeClock | None = None, **kw: Any
) -> HeyGenAvatarVideoAdapter:
    clock = clock or FakeClock()
    return HeyGenAvatarVideoAdapter(
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        **kw,
    )


def test_generate_submits_v3_body_and_polls_to_completion() -> None:
    rec = Recorder(
        CREATED, [ok({"status": "pending"}), ok({"status": "processing"}), ok(COMPLETED)]
    )
    clock = FakeClock()
    result = adapter_for(rec, clock).generate(
        make_request(idempotency_key="draft-42", locale="es-CO", burn_captions=True),
        api_key=API_KEY,
    )

    create = rec.requests[0]
    assert create.method == "POST" and create.url.path == "/v3/videos"
    assert create.headers["x-api-key"] == API_KEY
    assert create.headers["Idempotency-Key"] == "draft-42"
    body = json.loads(create.content)
    assert body == {
        "type": "avatar",
        "avatar_id": "av_1",
        "script": SCRIPT,
        "voice_id": "vo_1",
        "engine": {"type": "avatar_iv"},
        "resolution": "1080p",
        "aspect_ratio": "9:16",
        "voice_settings": {"speed": 1.0, "locale": "es-CO"},
        "caption": {"file_format": "srt", "style": "default"},
    }
    assert all(r.url.path == "/v3/videos/v_1" for r in rec.requests[1:])
    assert len(clock.sleeps) == 2

    assert result.provider == "heygen"
    assert result.model_id == "heygen_avatar_iv"
    assert result.media_url == COMPLETED["video_url"]
    assert result.media_expires_at_seconds is None  # undocumented by HeyGen, never invented
    assert result.usage.media_seconds == Decimal("6.4")
    assert result.usage.pieces == 1
    assert result.payload["subtitle_url"] == COMPLETED["subtitle_url"]


def test_no_idempotency_header_when_not_given() -> None:
    rec = Recorder(CREATED, [ok(COMPLETED)])
    adapter_for(rec).generate(make_request(), api_key=API_KEY)
    assert "Idempotency-Key" not in rec.requests[0].headers


def test_empty_api_key_refused_before_any_request() -> None:
    rec = Recorder(CREATED, [ok(COMPLETED)])
    with pytest.raises(ValueError, match="api_key"):
        adapter_for(rec).generate(make_request(), api_key="")
    assert rec.requests == []


@pytest.mark.parametrize(
    "params",
    [
        {"avatar_id": ""},
        {"voice_id": None},
        {"script": "   "},
        {"script": "x" * 5001},
        {"engine": "avatar_v"},
        {"aspect_ratio": "2:1"},
        {"voice_speed": 2.0},
        {"voice_speed": True},
    ],
)
def test_bad_spec_fails_before_any_request(params: dict[str, object]) -> None:
    rec = Recorder(CREATED, [ok(COMPLETED)])
    with pytest.raises(ValueError):
        adapter_for(rec).generate(make_request(**params), api_key=API_KEY)
    assert rec.requests == []


def test_create_error_surfaces_heygen_code() -> None:
    rec = Recorder(err(400, "avatar_not_usable", "avatar lacks matting"), [ok(COMPLETED)])
    with pytest.raises(HeyGenAPIError) as excinfo:
        adapter_for(rec).generate(make_request(), api_key=API_KEY)
    assert excinfo.value.status_code == 400
    assert excinfo.value.code == "avatar_not_usable"


def test_failed_render_raises_with_video_id() -> None:
    failed = ok({"status": "failed", "failure_code": "script_rejected", "failure_message": "nope"})
    rec = Recorder(CREATED, [failed])
    with pytest.raises(HeyGenRenderFailed) as excinfo:
        adapter_for(rec).generate(make_request(), api_key=API_KEY)
    assert excinfo.value.video_id == "v_1"
    assert excinfo.value.failure_code == "script_rejected"


def test_timeout_keeps_video_id_for_recovery() -> None:
    rec = Recorder(CREATED, [ok({"status": "processing"})])
    clock = FakeClock()
    adapter = adapter_for(rec, clock, poll_interval_seconds=10, poll_timeout_seconds=35)
    with pytest.raises(HeyGenRenderTimeout) as excinfo:
        adapter.generate(make_request(), api_key=API_KEY)
    assert excinfo.value.video_id == "v_1"
    assert clock.now <= 35


def test_poll_tolerates_transient_errors_and_honours_retry_after() -> None:
    rec = Recorder(
        CREATED,
        [err(503, "unavailable"), err(429, "rate_limited", **{"Retry-After": "30"}), ok(COMPLETED)],
    )
    clock = FakeClock()
    result = adapter_for(rec, clock).generate(make_request(), api_key=API_KEY)
    assert result.media_url == COMPLETED["video_url"]
    assert clock.sleeps == [10.0, 30.0]


def test_poll_gives_up_after_consecutive_server_errors() -> None:
    rec = Recorder(CREATED, [err(502, "bad_gateway")])
    with pytest.raises(HeyGenAPIError) as excinfo:
        adapter_for(rec).generate(make_request(), api_key=API_KEY)
    assert excinfo.value.status_code == 502


def test_poll_client_error_is_not_retried() -> None:
    rec = Recorder(CREATED, [err(401, "unauthorized")])
    with pytest.raises(HeyGenAPIError):
        adapter_for(rec).generate(make_request(), api_key=API_KEY)
    assert len(rec.requests) == 2  # create + one poll, no retry


def test_estimate_seconds_rounds_up_and_scales_with_speed() -> None:
    # 12 words / 2.2 wps = 5.45 + 1 padding = 6.45 -> 7
    assert estimate_seconds(SCRIPT) == Decimal(7)
    # Faster voice, shorter video.
    assert estimate_seconds(SCRIPT, Decimal("1.5")) == Decimal(5)


def test_estimate_cost_uses_per_second_rate_for_engine_and_resolution() -> None:
    pricing = JsonPricingTable("v2")
    adapter = adapter_for(Recorder(CREATED, [ok(COMPLETED)]))
    assert adapter.estimate_cost_usd(make_request(), pricing) == Decimal(7) * Decimal("0.0667")
    assert adapter.estimate_cost_usd(make_request(engine="avatar_iii"), pricing) == Decimal(
        7
    ) * Decimal("0.0433")


def test_unpriced_resolution_fails_preflight_loudly() -> None:
    adapter = adapter_for(Recorder(CREATED, [ok(COMPLETED)]))
    with pytest.raises(KeyError, match="per_second_4k"):
        adapter.estimate_cost_usd(make_request(resolution="4k"), JsonPricingTable("v2"))


class StaticKeys:
    def resolve(self, *, tenant_id: Any, brand_id: Any, provider: str) -> ResolvedKey:
        return ResolvedKey(api_key=API_KEY, paid_by=PaidBy.PLATFORM, fingerprint="fp")


def test_router_drives_the_adapter_end_to_end() -> None:
    rec = Recorder(CREATED, [ok(COMPLETED)])
    router = CreativeRouter({"heygen": adapter_for(rec)}, JsonPricingTable("v2"), StaticKeys())
    outcome = router.run(
        tenant_id=uuid4(),
        brand_id=uuid4(),
        chain=("heygen",),
        request=make_request(),
        budget=BudgetContext(remaining_usd=Decimal("5")),
    )
    assert outcome.succeeded
    assert [h.action for h in outcome.hops] == [HopAction.SUCCEEDED]


def test_router_budget_blocks_before_any_render() -> None:
    rec = Recorder(CREATED, [ok(COMPLETED)])
    router = CreativeRouter({"heygen": adapter_for(rec)}, JsonPricingTable("v2"), StaticKeys())
    outcome = router.run(
        tenant_id=uuid4(),
        brand_id=uuid4(),
        chain=("heygen",),
        request=make_request(),
        budget=BudgetContext(remaining_usd=Decimal("0.10")),
    )
    assert not outcome.succeeded
    assert outcome.hops[0].action == HopAction.BUDGET_BLOCKED
    assert rec.requests == []


# ---------------------------------------------------------------------------
# Discovery: list_avatar_looks / list_voices — browse HeyGen's public library so a
# caller with no avatar/voice of their own yet can still generate. Response shapes
# below are copied from a REAL call against the live API (2026-09-23, read-only, the
# key that made it never billed anything) — not guessed from docs, which disagreed
# with themselves about whether GET /v3/avatars returns a usable avatar_id (it does
# not: it returns avatar GROUPS; GET /v3/avatars/looks, called with no group_id, is
# what returns a flat page of directly-usable look ids across every public group).

REAL_LOOK = {
    "avatar_type": "photo_avatar",
    "default_voice_id": "6c5a16cb1ce6469a85b80798be89d95c",
    "gender": "male",
    "group_id": "ac9b5d2334c44d219e6ccf4dc07edcc1",
    "id": "ee25a2363ef941a1b5b0f7b1172e57d1",
    "name": "Dante Office 2",
    "preview_image_url": "https://resource2.heygen.ai/public-avatars/Dante/office118_p1_a1.jpg",
    "status": "completed",
    "supported_api_engines": ["avatar_v", "avatar_iv", "avatar_iii"],
    "tags": [],
}

REAL_VOICE = {
    "gender": "male",
    "language": "Spanish",
    "name": "Lenny - Clear & Professional",
    "support_locale": False,
    "support_pause": True,
    "type": "public",
    "voice_id": "050c403a43e047c796f8a6257ed2533e",
}


def list_response(items: list[dict[str, Any]]) -> httpx.Response:
    return httpx.Response(200, json={"data": items, "has_more": False, "next_token": None})


def test_list_avatar_looks_returns_the_real_response_shape() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return list_response([REAL_LOOK])

    looks = adapter_for(handler).list_avatar_looks(api_key=API_KEY)
    assert looks == [REAL_LOOK]
    request = seen[0]
    assert request.url.path == "/v3/avatars/looks"
    assert dict(request.url.params) == {"ownership": "public", "limit": "20"}


def test_list_avatar_looks_ownership_and_limit_are_overridable() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return list_response([])

    adapter_for(handler).list_avatar_looks(api_key=API_KEY, ownership="private", limit=5)
    assert dict(seen[0].url.params) == {"ownership": "private", "limit": "5"}


def test_list_voices_returns_the_real_response_shape_and_filters_by_language() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return list_response([REAL_VOICE])

    voices = adapter_for(handler).list_voices(api_key=API_KEY, language="Spanish")
    assert voices == [REAL_VOICE]
    assert dict(seen[0].url.params) == {"type": "public", "limit": "20", "language": "Spanish"}


def test_list_voices_omits_language_param_when_not_given() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return list_response([])

    adapter_for(handler).list_voices(api_key=API_KEY)
    assert "language" not in dict(seen[0].url.params)


def test_list_endpoints_surface_api_errors_like_create_does() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return err(401, "unauthorized", "bad key")

    with pytest.raises(HeyGenAPIError) as excinfo:
        adapter_for(handler).list_avatar_looks(api_key=API_KEY)
    assert excinfo.value.status_code == 401


def test_list_endpoints_reject_a_non_list_data_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return ok({"not": "a list"})  # data as an OBJECT — wrong shape for a browse call

    with pytest.raises(HeyGenError):
        adapter_for(handler).list_voices(api_key=API_KEY)


def test_list_endpoints_refuse_empty_api_key_before_any_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return list_response([])

    with pytest.raises(ValueError, match="api_key"):
        adapter_for(handler).list_avatar_looks(api_key="")
    assert seen == []


# ---------------------------------------------------------------------------
# Subject/audio discriminated union — image mode (no avatar needed at all) and every
# audio-optional / alternate-audio-source combination (operator request 2026-09-24:
# "puedo generar sin avatar o sin voz?"). See the adapter class docstring for the
# full params contract this enforces.


def make_raw_request(**params: object) -> GenerationRequest:
    """No defaults at all — every subject/audio-combination test states exactly what
    it means to test, instead of overriding fields out of `make_request`'s avatar
    defaults."""
    return GenerationRequest(
        task=GenerationTask.AVATAR_VIDEO,
        rendered_prompt=RenderedPrompt(stable_prefix="", volatile_suffix="", prefix_fingerprint=""),
        params=params,
    )


def test_image_subject_with_script_produces_a_talking_photo_body() -> None:
    rec = Recorder(CREATED, [ok(COMPLETED)])
    req = make_raw_request(
        image_url="https://example.com/product.jpg", script=SCRIPT, voice_id="vo_1"
    )
    adapter_for(rec).generate(req, api_key=API_KEY)
    body = json.loads(rec.requests[0].content)
    assert body["type"] == "image"
    assert body["image"] == {"type": "url", "url": "https://example.com/product.jpg"}
    assert body["script"] == SCRIPT
    assert body["voice_id"] == "vo_1"
    assert "avatar_id" not in body
    assert "engine" not in body  # engine is an avatar-only concept


def test_image_subject_with_no_audio_at_all_is_a_silent_render() -> None:
    """The exact "video de producto sencillo" case: an image, no avatar, no voice."""
    rec = Recorder(CREATED, [ok(COMPLETED)])
    req = make_raw_request(image_url="https://example.com/product.jpg")
    adapter_for(rec).generate(req, api_key=API_KEY)
    body = json.loads(rec.requests[0].content)
    assert body["type"] == "image"
    for absent in ("script", "voice_id", "audio_url", "audio_asset_id", "voice_settings"):
        assert absent not in body


def test_image_subject_via_asset_id_instead_of_url() -> None:
    rec = Recorder(CREATED, [ok(COMPLETED)])
    req = make_raw_request(image_asset_id="img_asset_1")
    adapter_for(rec).generate(req, api_key=API_KEY)
    body = json.loads(rec.requests[0].content)
    assert body["image"] == {"type": "asset_id", "asset_id": "img_asset_1"}


def test_avatar_subject_can_lip_sync_a_pre_recorded_audio_url() -> None:
    """Skips voice_id/script entirely — the avatar lip-syncs YOUR audio, not HeyGen's
    TTS reading a script."""
    rec = Recorder(CREATED, [ok(COMPLETED)])
    req = make_raw_request(avatar_id="av_1", audio_url="https://example.com/vo.mp3")
    adapter_for(rec).generate(req, api_key=API_KEY)
    body = json.loads(rec.requests[0].content)
    assert body["type"] == "avatar"
    assert body["avatar_id"] == "av_1"
    assert body["audio_url"] == "https://example.com/vo.mp3"
    assert "script" not in body
    assert "voice_id" not in body
    assert "voice_settings" not in body  # speed/locale don't apply to audio you supply


def test_avatar_subject_can_lip_sync_a_pre_uploaded_audio_asset() -> None:
    rec = Recorder(CREATED, [ok(COMPLETED)])
    req = make_raw_request(avatar_id="av_1", audio_asset_id="aud_asset_1")
    adapter_for(rec).generate(req, api_key=API_KEY)
    body = json.loads(rec.requests[0].content)
    assert body["audio_asset_id"] == "aud_asset_1"


@pytest.mark.parametrize(
    "params",
    [
        {},  # no subject at all
        {  # two subjects at once
            "avatar_id": "av_1",
            "image_url": "https://x/y.jpg",
            "script": SCRIPT,
            "voice_id": "vo_1",
        },
        {"image_url": "https://x/y.jpg", "image_asset_id": "img_1"},  # two image sources
        {"avatar_id": "av_1"},  # avatar with no audio source at all — nothing to say
        {"avatar_id": "av_1", "script": SCRIPT},  # script without voice_id
        {"avatar_id": "av_1", "voice_id": "vo_1"},  # voice_id without script
        {  # two audio sources at once
            "avatar_id": "av_1",
            "script": SCRIPT,
            "voice_id": "vo_1",
            "audio_url": "https://x/vo.mp3",
        },
    ],
)
def test_bad_subject_or_audio_combinations_fail_before_any_request(
    params: dict[str, object],
) -> None:
    rec = Recorder(CREATED, [ok(COMPLETED)])
    with pytest.raises(ValueError):
        adapter_for(rec).generate(make_raw_request(**params), api_key=API_KEY)
    assert rec.requests == []


def test_estimate_cost_for_image_subject_is_unpriced_by_design() -> None:
    """No published per-second rate for image-animation mode exists yet — model_id
    resolves to "heygen_image" and the pricing table correctly has nothing for it
    (KeyError, never a silently-wrong 0)."""
    adapter = adapter_for(Recorder(CREATED, [ok(COMPLETED)]))
    req = make_raw_request(image_url="https://x/y.jpg", duration_seconds_hint=5)
    with pytest.raises(KeyError, match="heygen_image"):
        adapter.estimate_cost_usd(req, JsonPricingTable("v2"))


def test_estimate_cost_without_a_script_requires_a_duration_hint() -> None:
    adapter = adapter_for(Recorder(CREATED, [ok(COMPLETED)]))
    req = make_raw_request(avatar_id="av_1", audio_url="https://x/vo.mp3")
    with pytest.raises(ValueError, match="duration_seconds_hint"):
        adapter.estimate_cost_usd(req, JsonPricingTable("v2"))


def test_estimate_cost_uses_the_duration_hint_when_there_is_no_script() -> None:
    adapter = adapter_for(Recorder(CREATED, [ok(COMPLETED)]))
    req = make_raw_request(avatar_id="av_1", audio_url="https://x/vo.mp3", duration_seconds_hint=12)
    cost = adapter.estimate_cost_usd(req, JsonPricingTable("v2"))
    assert cost == Decimal(12) * Decimal("0.0667")


# ---------------------------------------------------------------------------
# upload_asset — lets a locally-uploaded file (a dev server's localhost is not a URL
# HeyGen can fetch) become an image_asset_id/audio_asset_id. Response shape below is
# copied from a REAL upload against the live API (2026-09-24, a throwaway 1x1 PNG —
# read the adapter method's docstring for how it was verified).

REAL_UPLOAD_RESPONSE = {
    "asset_id": "e8ff0afd7954424c818f76714ab7669f",
    "mime_type": "image/png",
    "size_bytes": 68,
    "url": "https://resource2.heygen.ai/image/e8ff0afd7954424c818f76714ab7669f/original.png",
}


def test_upload_asset_sends_multipart_and_returns_the_real_response_shape() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok(REAL_UPLOAD_RESPONSE)

    result = adapter_for(handler).upload_asset(
        api_key=API_KEY, file_bytes=b"\x89PNG...", filename="pixel.png", content_type="image/png"
    )
    assert result == REAL_UPLOAD_RESPONSE
    request = seen[0]
    assert request.method == "POST" and request.url.path == "/v3/assets"
    assert request.headers["x-api-key"] == API_KEY
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert b'filename="pixel.png"' in request.content
    assert b"\x89PNG..." in request.content


def test_upload_asset_passes_idempotency_key_when_given() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok(REAL_UPLOAD_RESPONSE)

    adapter_for(handler).upload_asset(
        api_key=API_KEY,
        file_bytes=b"data",
        filename="a.png",
        content_type="image/png",
        idempotency_key="draft-99",
    )
    assert seen[0].headers["Idempotency-Key"] == "draft-99"


def test_upload_asset_refuses_a_file_over_32mb_before_any_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok(REAL_UPLOAD_RESPONSE)

    oversized = b"x" * (32 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="32 MB"):
        adapter_for(handler).upload_asset(
            api_key=API_KEY, file_bytes=oversized, filename="big.png", content_type="image/png"
        )
    assert seen == []


def test_upload_asset_surfaces_api_errors_like_create_does() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return err(400, "invalid_file", "unsupported type")

    with pytest.raises(HeyGenAPIError) as excinfo:
        adapter_for(handler).upload_asset(
            api_key=API_KEY, file_bytes=b"x", filename="a.exe", content_type="application/exe"
        )
    assert excinfo.value.status_code == 400
    assert excinfo.value.code == "invalid_file"


def test_upload_asset_refuses_empty_api_key_before_any_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok(REAL_UPLOAD_RESPONSE)

    with pytest.raises(ValueError, match="api_key"):
        adapter_for(handler).upload_asset(
            api_key="", file_bytes=b"x", filename="a.png", content_type="image/png"
        )
    assert seen == []


def test_image_subject_generate_accepts_the_asset_id_from_upload_asset() -> None:
    """End-to-end within the test suite: the id `upload_asset` returns is exactly what
    `image_asset_id` in `generate`'s params expects."""
    upload_rec: list[httpx.Request] = []

    def upload_handler(request: httpx.Request) -> httpx.Response:
        upload_rec.append(request)
        return ok(REAL_UPLOAD_RESPONSE)

    adapter = adapter_for(upload_handler)
    uploaded = adapter.upload_asset(
        api_key=API_KEY, file_bytes=b"data", filename="product.jpg", content_type="image/jpeg"
    )

    rec = Recorder(CREATED, [ok(COMPLETED)])
    adapter_for(rec).generate(
        make_raw_request(image_asset_id=uploaded["asset_id"]), api_key=API_KEY
    )
    body = json.loads(rec.requests[0].content)
    assert body["image"] == {"type": "asset_id", "asset_id": REAL_UPLOAD_RESPONSE["asset_id"]}


# ---------------------------------------------------------------------------
# Background — at most one of background_color / background_image_url /
# background_image_asset_id, available for BOTH subjects (operator request
# 2026-09-24: "en el selector del avatar, subir el producto; en imagen, subir las
# dos"). Verified live against HeyGen's schema (2026-09-24) that `background` works
# identically whether the subject is an avatar or an image.


def test_avatar_subject_with_background_image_url() -> None:
    """The exact request: an avatar talking in front of a product photo."""
    rec = Recorder(CREATED, [ok(COMPLETED)])
    req = make_raw_request(
        avatar_id="av_1",
        script=SCRIPT,
        voice_id="vo_1",
        background_image_url="https://example.com/product.jpg",
    )
    adapter_for(rec).generate(req, api_key=API_KEY)
    body = json.loads(rec.requests[0].content)
    assert body["background"] == {"type": "image", "url": "https://example.com/product.jpg"}


def test_avatar_subject_with_background_image_asset_id() -> None:
    rec = Recorder(CREATED, [ok(COMPLETED)])
    req = make_raw_request(
        avatar_id="av_1",
        script=SCRIPT,
        voice_id="vo_1",
        background_image_asset_id="bg_asset_1",
    )
    adapter_for(rec).generate(req, api_key=API_KEY)
    body = json.loads(rec.requests[0].content)
    assert body["background"] == {"type": "image", "asset_id": "bg_asset_1"}


def test_image_subject_with_both_the_subject_and_a_background_image() -> None:
    """The other half of the request: image mode with TWO images — the animated
    subject and a second image behind it."""
    rec = Recorder(CREATED, [ok(COMPLETED)])
    req = make_raw_request(
        image_asset_id="subject_asset_1",
        background_image_asset_id="bg_asset_1",
    )
    adapter_for(rec).generate(req, api_key=API_KEY)
    body = json.loads(rec.requests[0].content)
    assert body["image"] == {"type": "asset_id", "asset_id": "subject_asset_1"}
    assert body["background"] == {"type": "image", "asset_id": "bg_asset_1"}


def test_background_color_still_works_unchanged() -> None:
    rec = Recorder(CREATED, [ok(COMPLETED)])
    req = make_raw_request(
        avatar_id="av_1", script=SCRIPT, voice_id="vo_1", background_color="#ff0000"
    )
    adapter_for(rec).generate(req, api_key=API_KEY)
    body = json.loads(rec.requests[0].content)
    assert body["background"] == {"type": "color", "value": "#ff0000"}


def test_no_background_omits_the_field_entirely() -> None:
    rec = Recorder(CREATED, [ok(COMPLETED)])
    adapter_for(rec).generate(make_request(), api_key=API_KEY)
    body = json.loads(rec.requests[0].content)
    assert "background" not in body


def test_more_than_one_background_source_fails_before_any_request() -> None:
    rec = Recorder(CREATED, [ok(COMPLETED)])
    req = make_raw_request(
        avatar_id="av_1",
        script=SCRIPT,
        voice_id="vo_1",
        background_color="#ff0000",
        background_image_url="https://example.com/bg.jpg",
    )
    with pytest.raises(ValueError, match="one background source"):
        adapter_for(rec).generate(req, api_key=API_KEY)
    assert rec.requests == []
