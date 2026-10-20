"""BytePlus OmniHuman — a presenter photo and a voice track become a talking video, lips
in sync (§ request 2026-10-16: the avatar videos move from HeyGen to ByteDance).

OmniHuman is NOT in ModelArk: it is BytePlus Vision AI, another console and another key,
and its activation asks for a verified business. Read from the official docs on
2026-10-16 (`docs.byteplus.com/en/docs/byteplus-vision/…`: `omnihuman-video_generation`,
`omnihuman-2-0-video-generation`, `api-key-usage-instructions`):

- **Auth** — `Authorization: Bearer <API key>` on `https://openapi.cv.bytepluses.com`
  (the API-key route; the AK/SK-signed `cv.byteplusapi.com` route is not used).
- **1.5** (`req_key=realman_avatar_picture_omni15_cv`, the default) — `POST
  /api/common/v3/submit_task` with `image_url` + `audio_url` (both public URLs), optional
  `prompt` (es-MX accepted), `seed`, `output_resolution` 720|1080, `pe_fast_mode`; then
  `POST /api/common/v3/get_result` with `task_id` until `data.status == "done"`. Audio
  under 60 s; image JPG/PNG < 5 MB. USD 0.12/s, concurrency 1.
- **2.0** (`realman_avatar_picture_omni20_cv`) — the sync-to-async pair `submit_task_v2`
  / `get_result_v2`, `image_urls` (a list), audio 4-300 s, `enable_watermark`. USD 0.07/s.
- **Answers** — `code` 10000 is success (anything else: ignore `data`); the result's
  `data.resp_data` is a JSON STRING holding `video_url`, valid ONE hour — the producer
  copies the file to R2 at once.
- **Slow** — the docs' own figure is ~11-13 min of render per 30 s of video at 1.5, so
  the poll window is long and the task id is kept on a timeout for a later recovery.

httpx is imported lazily (the `video` extra).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from qualify_creative.enums import GenerationTask
from qualify_creative.providers import GenerationRequest, GenerationResult, PricingTable, Usage

BASE_URL = "https://openapi.cv.bytepluses.com"
API_KEY_ENV = "QUALIFY_BYTEPLUS_CV_API_KEY"
REQ_KEY_ENV = "QUALIFY_OMNIHUMAN_REQ_KEY"
OMNIHUMAN_15 = "realman_avatar_picture_omni15_cv"
OMNIHUMAN_20 = "realman_avatar_picture_omni20_cv"
DEFAULT_REQ_KEY = OMNIHUMAN_15
#: The pricing table's model ids, per `req_key`.
MODEL_IDS = {OMNIHUMAN_15: "omnihuman-1-5", OMNIHUMAN_20: "omnihuman-2-0"}
#: What each version takes as audio (seconds): 1.5 under 60, 2.0 from 4 to 300.
MAX_AUDIO_SECONDS = {OMNIHUMAN_15: 59.0, OMNIHUMAN_20: 300.0}
SUCCESS = 10_000
#: The video URL's life (resp_data.video_url: «valid for 1 hour»).
MEDIA_URL_TTL_SECONDS = 3600
DEFAULT_POLL_INTERVAL_SECONDS = 10.0
#: ~12 min per 30 s of video at 1.5 (official RTF 23-27), so 60 s of audio is ~25 min.
DEFAULT_POLL_TIMEOUT_SECONDS = 40 * 60.0
_FAILED = frozenset({"not_found", "expired", "canceled"})


class OmniHumanError(Exception):
    """An OmniHuman call failed; `code` is the vendor's (50215 invalid input, 50400
    access denied, 50510 content pre-filter…). Never carries the key."""

    def __init__(self, message: str, *, code: int | None = None, task_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.task_id = task_id


class OmniHumanTimeout(OmniHumanError):
    """The window closed before the render finished. It keeps running — and is billed if
    it succeeds — so the task id travels for a recovery."""


def omnihuman_cost_usd(
    pricing: PricingTable, req_key: str, resolution: int, seconds: Decimal
) -> Decimal:
    model_id = MODEL_IDS.get(req_key, req_key)
    price = pricing.unit_price(model_id=model_id, unit=f"per_second_{resolution}p")
    return (price * seconds).quantize(Decimal("0.0001"))


class OmniHumanVideoAdapter:
    """``GenerationProvider`` for a talking presenter (`GenerationTask.AVATAR_VIDEO`).

    ``request.params``: ``image_url`` and ``audio_url`` (public ``https`` URLs — the
    producer serves them through a public-media token), ``prompt`` (gestures, camera,
    emotion; optional), ``resolution`` (720 | 1080), ``audio_seconds`` (the voice
    track's length: what the render is billed on), ``seed`` (optional)."""

    name = "omnihuman"
    supports = frozenset({GenerationTask.AVATAR_VIDEO})

    def __init__(
        self,
        *,
        req_key: str = DEFAULT_REQ_KEY,
        base_url: str = BASE_URL,
        transport: Any = None,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        poll_timeout_seconds: float = DEFAULT_POLL_TIMEOUT_SECONDS,
        request_timeout_seconds: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if req_key not in MODEL_IDS:
            raise ValueError(f"unknown OmniHuman req_key {req_key!r}")
        self.req_key = req_key
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._poll_interval = poll_interval_seconds
        self._poll_timeout = poll_timeout_seconds
        self._timeout = request_timeout_seconds
        self._sleep = sleep
        self._monotonic = monotonic

    @property
    def model_id(self) -> str:
        return MODEL_IDS[self.req_key]

    @property
    def max_audio_seconds(self) -> float:
        return MAX_AUDIO_SECONDS[self.req_key]

    def _client(self, api_key: str) -> Any:
        if not api_key:
            raise ValueError("OmniHuman adapter requires an explicit, non-empty api_key")
        import httpx  # lazy: optional dependency

        return httpx.Client(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=self._timeout,
            transport=self._transport,
        )

    @staticmethod
    def _data(response: Any, task_id: str | None = None) -> Mapping[str, Any]:
        try:
            body = response.json()
        except ValueError:
            body = {}
        body = body if isinstance(body, dict) else {}
        code = body.get("code")
        if response.status_code >= 400 or code != SUCCESS:
            raise OmniHumanError(
                f"OmniHuman answered HTTP {response.status_code} code {code}: "
                f"{str(body.get('message') or '')[:200]}",
                code=code if isinstance(code, int) else None,
                task_id=task_id,
            )
        data = body.get("data")
        return data if isinstance(data, dict) else {}

    def _paths(self) -> tuple[str, str]:
        if self.req_key == OMNIHUMAN_20:
            return "/api/common/v3/submit_task_v2", "/api/common/v3/get_result_v2"
        return "/api/common/v3/submit_task", "/api/common/v3/get_result"

    def _submit_body(self, params: Mapping[str, object]) -> dict[str, object]:
        image, audio = str(params.get("image_url") or ""), str(params.get("audio_url") or "")
        if not image.startswith("https://") or not audio.startswith("https://"):
            raise ValueError("OmniHuman needs a public https image_url and audio_url")
        body: dict[str, object] = {"req_key": self.req_key, "audio_url": audio}
        prompt = str(params.get("prompt") or "").strip()
        if prompt:
            body["prompt"] = prompt[:1000]
        if self.req_key == OMNIHUMAN_20:
            body["image_urls"] = [image]
            body["enable_watermark"] = bool(params.get("watermark", False))
        else:
            body["image_url"] = image
            body["output_resolution"] = self._resolution(params)
            if params.get("seed") is not None:
                body["seed"] = int(params["seed"])  # type: ignore[arg-type]
        return body

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        params = request.params
        seconds = Decimal(str(params.get("audio_seconds") or 0))
        if seconds and float(seconds) > self.max_audio_seconds:
            raise ValueError(f"OmniHuman takes at most {self.max_audio_seconds:.0f} s of audio")
        submit, result = self._paths()
        with self._client(api_key) as client:
            data = self._data(client.post(submit, json=self._submit_body(params)))
            task_id = str(data.get("task_id") or "")
            if not task_id:
                raise OmniHumanError("OmniHuman returned no task id")
            video_url = self._wait(client, result, task_id)
        resolution = self._resolution(params)
        return GenerationResult(
            payload={
                "task_id": task_id,
                "video_url": video_url,
                "req_key": self.req_key,
                "resolution": resolution,
                "duration_seconds": str(seconds),
            },
            model_id=self.model_id,
            provider=self.name,
            usage=Usage(pieces=1, media_seconds=seconds),
            model_revision=self.req_key,
            media_url=video_url,
            media_expires_at_seconds=MEDIA_URL_TTL_SECONDS,
        )

    def _wait(self, client: Any, path: str, task_id: str) -> str:
        import httpx  # lazy, already loaded by _client

        started = self._monotonic()
        errors = 0
        while True:
            try:
                data = self._data(
                    client.post(path, json={"req_key": self.req_key, "task_id": task_id}), task_id
                )
                errors = 0
            except httpx.TransportError:
                errors += 1
                if errors >= 3:
                    raise
                data = {}
            status = str(data.get("status") or "")
            if status == "done":
                raw = data.get("resp_data")
                parsed: Any = raw
                if isinstance(raw, str):
                    try:
                        parsed = json.loads(raw)
                    except ValueError:
                        parsed = {}
                url = parsed.get("video_url") if isinstance(parsed, dict) else None
                if not url:
                    raise OmniHumanError("OmniHuman finished without a video_url", task_id=task_id)
                return str(url)
            if status in _FAILED:
                raise OmniHumanError(f"OmniHuman task {task_id} {status}", task_id=task_id)
            waited = self._monotonic() - started
            if waited + self._poll_interval > self._poll_timeout:
                raise OmniHumanTimeout(
                    f"OmniHuman task {task_id} still rendering after {waited:.0f}s", task_id=task_id
                )
            self._sleep(self._poll_interval)

    def estimate_cost_usd(
        self, request: GenerationRequest, pricing: PricingTable, *, api_key: str | None = None
    ) -> Decimal:
        seconds = Decimal(str(request.params.get("audio_seconds") or self.max_audio_seconds))
        return omnihuman_cost_usd(pricing, self.req_key, self._resolution(request.params), seconds)

    def _resolution(self, params: Mapping[str, object]) -> int:
        """2.0 renders native 720p; 1.5 takes 720 or 1080."""
        if self.req_key == OMNIHUMAN_20:
            return 720
        return 1080 if int(params.get("resolution") or 720) >= 1080 else 720
