"""Seed Speech (clone, status, synthesis) and OmniHuman (submit, poll, result) against
`httpx.MockTransport` — the request each sends and how each reads the answer, as the
official docs describe them (read 2026-10-16). No key, no network."""

from __future__ import annotations

import base64
import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from qualify_creative.adapters.byteplus_omnihuman import (
    OMNIHUMAN_20,
    OmniHumanError,
    OmniHumanTimeout,
    OmniHumanVideoAdapter,
)
from qualify_creative.adapters.byteplus_speech import (
    APP_KEY,
    CLONE_RESOURCE,
    PUBLIC_RESOURCE,
    PUBLIC_SPANISH_VOICES,
    SeedSpeechClient,
    SeedSpeechError,
    SeedSpeechNotConfigured,
    SeedSpeechVoiceoverAdapter,
    language_code,
    new_speaker_id,
    poll_voice,
)
from qualify_creative.enums import GenerationTask
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationRequest, RenderedPrompt

KEY = "speech-key"


def _request(task: GenerationTask, **params: Any) -> GenerationRequest:
    return GenerationRequest(task=task, rendered_prompt=RenderedPrompt("", "", ""), params=params)


def _transport(handler: Any, seen: list[httpx.Request]) -> httpx.MockTransport:
    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.MockTransport(wrapped)


# -- Seed Speech ---------------------------------------------------------------------


def test_clone_sends_the_sample_as_base64_with_our_own_id() -> None:
    seen: list[httpx.Request] = []
    transport = _transport(
        lambda r: httpx.Response(200, json={"code": 0, "status": 1, "speaker_id": "qlf-x"}), seen
    )
    status = SeedSpeechClient(transport=transport).clone_voice(
        api_key=KEY, speaker_id="qlf-abc12345", audio=b"RIFF....", language=16, text="Autorizo"
    )
    (request,) = seen
    assert request.url.host == "voice.ap-southeast-1.bytepluses.com"
    assert request.url.path == "/api/v3/tts/voice_clone"
    assert request.headers["X-Api-Key"] == KEY and request.headers["X-Api-Request-Id"]
    body = json.loads(request.content)
    assert body["speaker_id"] == "custom_speaker_id" and body["custom_speaker_id"] == "qlf-abc12345"
    assert base64.b64decode(body["audio"]["data"]) == b"RIFF...."
    assert body["language"] == 16 and body["text"] == "Autorizo"
    assert 4 <= len(body["extra_params"]["demo_text"]) <= 80
    assert status.status == 1 and not status.ready


def test_get_voice_reads_ready_failed_and_the_demo() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": 0, "status": 2, "speaker_id": "qlf-x", "demo_audio": "https://d/x.mp3"},
        )

    status = SeedSpeechClient(transport=_transport(handler, [])).get_voice(
        api_key=KEY, speaker_id="qlf-x"
    )
    assert status.ready and status.demo_audio_url == "https://d/x.mp3"


def test_poll_voice_waits_until_ready() -> None:
    answers = iter([1, 1, 4])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "status": next(answers)})

    slept: list[float] = []
    status = poll_voice(
        SeedSpeechClient(transport=_transport(handler, [])),
        api_key=KEY,
        speaker_id="qlf-x",
        sleep=slept.append,
        monotonic=lambda: 0.0,
    )
    assert status.ready and len(slept) == 2


def test_a_vendor_error_carries_its_code_and_never_the_key() -> None:
    transport = _transport(
        lambda r: httpx.Response(400, json={"code": 45001109, "message": "text mismatch"}), []
    )
    with pytest.raises(SeedSpeechError) as exc:
        SeedSpeechClient(transport=transport).clone_voice(
            api_key=KEY, speaker_id="qlf-x", audio=b"x", language=3
        )
    assert exc.value.code == 45001109 and KEY not in str(exc.value)


def test_no_key_is_not_configured() -> None:
    with pytest.raises(SeedSpeechNotConfigured):
        SeedSpeechClient().get_voice(api_key="", speaker_id="qlf-x")


def test_synthesis_reads_the_base64_stream_until_the_closing_code() -> None:
    seen: list[httpx.Request] = []
    lines = [
        json.dumps({"code": 0, "message": "", "data": base64.b64encode(b"ID3-").decode()}),
        json.dumps({"code": 0, "message": "", "data": base64.b64encode(b"audio").decode()}),
        json.dumps({"code": 20000000, "message": "ok", "data": None}),
    ]
    transport = _transport(lambda r: httpx.Response(200, text="\n".join(lines)), seen)
    audio = SeedSpeechClient(transport=transport).synthesize(
        api_key=KEY, text="  Hola,   mundo ", speaker="qlf-x", resource_id=CLONE_RESOURCE
    )
    assert audio == b"ID3-audio"
    (request,) = seen
    assert request.url.path == "/api/v3/tts/unidirectional"
    assert request.headers["X-Api-Resource-Id"] == CLONE_RESOURCE
    assert request.headers["X-Api-App-Key"] == APP_KEY
    body = json.loads(request.content)["req_params"]
    assert body["text"] == "Hola, mundo" and body["speaker"] == "qlf-x"
    assert body["audio_params"]["format"] == "mp3" and body["audio_params"]["bit_rate"]
    assert json.loads(body["additions"])["explicit_language"] == "es"


def test_synthesis_fails_on_an_error_line() -> None:
    lines = [json.dumps({"code": 45000000, "message": "speaker permission denied"})]
    transport = _transport(lambda r: httpx.Response(200, text="\n".join(lines)), [])
    with pytest.raises(SeedSpeechError) as exc:
        SeedSpeechClient(transport=transport).synthesize(
            api_key=KEY, text="Hola", speaker="otro", resource_id=CLONE_RESOURCE
        )
    assert exc.value.code == 45000000


def test_the_voiceover_provider_prices_by_character() -> None:
    lines = [
        json.dumps({"code": 0, "data": base64.b64encode(b"mp3").decode()}),
        json.dumps({"code": 20000000}),
    ]
    client = SeedSpeechClient(
        transport=_transport(lambda r: httpx.Response(200, text="\n".join(lines)), [])
    )
    adapter = SeedSpeechVoiceoverAdapter(client)
    request = _request(
        GenerationTask.VOICEOVER,
        text="a" * 1000,
        speaker=PUBLIC_SPANISH_VOICES[0]["id"],
        resource_id=PUBLIC_RESOURCE,
    )
    result = adapter.generate(request, api_key=KEY)
    assert result.payload == b"mp3" and result.provider == "seed_speech"
    assert result.usage.input_tokens == 1000
    assert adapter.estimate_cost_usd(request, JsonPricingTable("v5")) == Decimal("0.030000")


def test_language_codes_and_opaque_ids() -> None:
    assert language_code("es-MX") == 16 and language_code("es-CO") == 3
    assert language_code("en-US") == 1
    sid = new_speaker_id()
    assert sid.startswith("qlf-") and len(sid) == 28  # never `xx_…`, never the tenant
    assert {v["gender"] for v in PUBLIC_SPANISH_VOICES} == {"female", "male"}


# -- OmniHuman -----------------------------------------------------------------------


def _omni_handler(statuses: list[str], seen: list[httpx.Request]) -> Any:
    answers = iter(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith(("submit_task", "submit_task_v2")):
            return httpx.Response(200, json={"code": 10000, "data": {"task_id": "7392"}})
        status = next(answers)
        data: dict[str, Any] = {"status": status}
        if status == "done":
            data["resp_data"] = json.dumps({"video_url": "https://cdn/v.mp4", "progress": 100})
        return httpx.Response(200, json={"code": 10000, "data": data})

    return handler


def test_omnihuman_15_submits_the_photo_and_voice_and_polls_until_done() -> None:
    seen: list[httpx.Request] = []
    slept: list[float] = []
    adapter = OmniHumanVideoAdapter(
        transport=httpx.MockTransport(_omni_handler(["in_queue", "generating", "done"], seen)),
        sleep=slept.append,
        monotonic=lambda: 0.0,
    )
    result = adapter.generate(
        _request(
            GenerationTask.AVATAR_VIDEO,
            image_url="https://q/img.jpg",
            audio_url="https://q/voice.mp3",
            prompt="Habla a la cámara con entusiasmo",
            resolution=720,
            audio_seconds=28.5,
        ),
        api_key="cv-key",
    )
    submit, *polls = seen
    assert submit.url.host == "openapi.cv.bytepluses.com"
    assert submit.url.path == "/api/common/v3/submit_task"
    assert submit.headers["Authorization"] == "Bearer cv-key"
    body = json.loads(submit.content)
    assert body == {
        "req_key": "realman_avatar_picture_omni15_cv",
        "audio_url": "https://q/voice.mp3",
        "prompt": "Habla a la cámara con entusiasmo",
        "image_url": "https://q/img.jpg",
        "output_resolution": 720,
    }
    assert {p.url.path for p in polls} == {"/api/common/v3/get_result"}
    assert json.loads(polls[0].content) == {
        "req_key": "realman_avatar_picture_omni15_cv",
        "task_id": "7392",
    }
    assert result.media_url == "https://cdn/v.mp4" and result.provider == "omnihuman"
    assert result.usage.media_seconds == Decimal("28.5") and len(slept) == 2
    cost = adapter.estimate_cost_usd(
        _request(GenerationTask.AVATAR_VIDEO, audio_seconds=30, resolution=720),
        JsonPricingTable("v5"),
    )
    assert cost == Decimal("3.6000")  # 30 s × USD 0.12


def test_omnihuman_20_uses_the_sync_to_async_pair_and_a_list_of_images() -> None:
    seen: list[httpx.Request] = []
    adapter = OmniHumanVideoAdapter(
        req_key=OMNIHUMAN_20,
        transport=httpx.MockTransport(_omni_handler(["done"], seen)),
        sleep=lambda s: None,
        monotonic=lambda: 0.0,
    )
    adapter.generate(
        _request(
            GenerationTask.AVATAR_VIDEO,
            image_url="https://q/i.jpg",
            audio_url="https://q/a.mp3",
            audio_seconds=90,
        ),
        api_key="k",
    )
    assert seen[0].url.path == "/api/common/v3/submit_task_v2"
    assert json.loads(seen[0].content)["image_urls"] == ["https://q/i.jpg"]
    assert seen[1].url.path == "/api/common/v3/get_result_v2"


def test_omnihuman_refuses_private_urls_and_too_much_audio_before_the_network() -> None:
    adapter = OmniHumanVideoAdapter(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(ValueError):
        adapter.generate(
            _request(GenerationTask.AVATAR_VIDEO, image_url="/local.jpg", audio_url="https://a"),
            api_key="k",
        )
    with pytest.raises(ValueError):
        adapter.generate(
            _request(
                GenerationTask.AVATAR_VIDEO,
                image_url="https://i",
                audio_url="https://a",
                audio_seconds=75,  # 1.5 takes under 60 s
            ),
            api_key="k",
        )


def test_omnihuman_error_codes_and_timeout() -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 50510, "message": "content pre-filter"})

    with pytest.raises(OmniHumanError) as exc:
        OmniHumanVideoAdapter(transport=httpx.MockTransport(refused)).generate(
            _request(GenerationTask.AVATAR_VIDEO, image_url="https://i", audio_url="https://a"),
            api_key="k",
        )
    assert exc.value.code == 50510

    clock = iter(range(0, 10_000, 600))
    adapter = OmniHumanVideoAdapter(
        transport=httpx.MockTransport(_omni_handler(["generating"] * 50, [])),
        poll_timeout_seconds=1200,
        sleep=lambda s: None,
        monotonic=lambda: float(next(clock)),
    )
    with pytest.raises(OmniHumanTimeout) as timeout:
        adapter.generate(
            _request(GenerationTask.AVATAR_VIDEO, image_url="https://i", audio_url="https://a"),
            api_key="k",
        )
    assert timeout.value.task_id == "7392"
