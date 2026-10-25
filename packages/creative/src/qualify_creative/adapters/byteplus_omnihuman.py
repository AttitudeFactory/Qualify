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
- **States** (`get_result` → `data.status`): `in_queue` → `generating` → `done`; a task
  ends `not_found` / `expired` (and, defensively, `canceled` / `failed`) without a video.
- **Slow** — the docs' own figure is ~11-13 min of render per 30 s of video at 1.5.

**Never lose a billed render (m-24852495 — the Seedance fix of m-24852154, applied here).**
`request.observer` hears the task id the moment `submit_task` answers 2xx, before the
first poll, so the caller keeps it by id. The render window (`poll_timeout_seconds`, 40
min) counts from the first `generating` answer; while the task is still `in_queue` the
adapter waits up to `queue_timeout_seconds` instead — OmniHuman runs one task at a time
per account, so a queue is normal and must not use the render window up. Past either
window (or when OmniHuman stops answering) it raises `OmniHumanTimeout` carrying the id,
and a later run passes `params[RESUME_TASK_PARAM]` to wait for THAT task: a task with an
id is never submitted again. A resume is priced at zero by the pre-flight — it orders
nothing; the render is recorded at its real price when it lands.

httpx is imported lazily (the `video` extra).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from qualify_creative.enums import GenerationTask
from qualify_creative.providers import (
    GenerationRequest,
    GenerationResult,
    PricingTable,
    Usage,
    VendorTaskObserver,
)

logger = logging.getLogger(__name__)

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
#: The render window, counted from the first `generating` answer (m-24852495).
DEFAULT_POLL_TIMEOUT_SECONDS = 40 * 60.0
#: How long this thread keeps waiting while the task is still `in_queue` (concurrency 1
#: per account: a second presenter waits for the first). Past it the adapter raises
#: `OmniHumanTimeout` and the caller resumes the task by id later.
DEFAULT_QUEUE_TIMEOUT_SECONDS = 60 * 60.0
#: `params[RESUME_TASK_PARAM]`: the id of a task this generation already submitted — the
#: adapter waits for it instead of submitting another (the same key as Seedance's).
RESUME_TASK_PARAM = "resume_task_id"
#: Consecutive polls that say nothing about the task (a dropped connection, a 5xx / 429)
#: before the wait stops — as a TIMEOUT, so the id is kept and the render recovered.
MAX_CONSECUTIVE_POLL_ERRORS = 3
QUEUED = "in_queue"
GENERATING = "generating"
DONE = "done"
_FAILED = frozenset({"not_found", "expired", "canceled", "cancelled", "failed"})


class OmniHumanError(Exception):
    """An OmniHuman call failed; `code` is the vendor's (50215 invalid input, 50400
    access denied, 50510 content pre-filter…). Never carries the key."""

    def __init__(self, message: str, *, code: int | None = None, task_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.task_id = task_id


class OmniHumanTimeout(OmniHumanError):
    """This thread stopped waiting before the render finished — still `in_queue` past
    `queue_timeout_seconds`, `generating` past the render window, or OmniHuman not
    answering. It keeps running — and is billed if it succeeds — so the task id travels
    for a recovery (`RESUME_TASK_PARAM`)."""


class OmniHumanTaskFailed(OmniHumanError):
    """OmniHuman ended the task without a video (`not_found`, `expired`, `canceled`, or
    an error code on the task's own result): nothing was rendered, nothing is billed."""

    def __init__(
        self, message: str, *, task_id: str, status: str = "", code: int | None = None
    ) -> None:
        super().__init__(message, code=code, task_id=task_id)
        self.status = status


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
    track's length: what the render is billed on), ``seed`` (optional);
    ``resume_task_id`` (m-24852495) instead of submitting: wait for that task.

    ``request.observer`` hears the new task's id as soon as OmniHuman accepts it, and
    every poll answer (`VendorTaskObserver`)."""

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
        queue_timeout_seconds: float = DEFAULT_QUEUE_TIMEOUT_SECONDS,
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
        self._queue_timeout = queue_timeout_seconds
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
        resume_id = _resume_id(params)
        if not resume_id and seconds and float(seconds) > self.max_audio_seconds:
            raise ValueError(f"OmniHuman takes at most {self.max_audio_seconds:.0f} s of audio")
        submit, result = self._paths()
        observer = request.observer
        with self._client(api_key) as client:
            if resume_id:
                # m-24852495: a task this generation already submitted (and is billed for
                # when it ends) — waited for, never submitted again
                task_id = resume_id
            else:
                data = self._data(client.post(submit, json=self._submit_body(params)))
                task_id = str(data.get("task_id") or "")
                if not task_id:
                    raise OmniHumanError("OmniHuman returned no task id")
                _tell(observer, "created", task_id)
            video_url = self._wait(client, result, task_id, observer)
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

    def get_task(self, task_id: str, *, api_key: str) -> Mapping[str, Any]:
        """One task's current `data` (`status`, `resp_data`…) — a read for the recovery
        pass (m-24852495): nothing is submitted or billed. Raises `OmniHumanError` when
        OmniHuman answers an error code."""
        _, result = self._paths()
        with self._client(api_key) as client:
            return self._data(
                client.post(result, json={"req_key": self.req_key, "task_id": task_id}), task_id
            )

    def _wait(
        self,
        client: Any,
        path: str,
        task_id: str,
        observer: VendorTaskObserver | None = None,
    ) -> str:
        """Poll until the task ends. Two windows (m-24852495): while it is `in_queue` (or
        the answer says nothing) up to `queue_timeout_seconds` since the wait began; once
        it answers `generating`, the render window counts from THAT answer."""
        import httpx  # lazy, already loaded by _client

        started = self._monotonic()
        generating_since: float | None = None
        status = ""
        errors = 0
        while True:
            data: Mapping[str, Any] | None = None
            try:
                response = client.post(path, json={"req_key": self.req_key, "task_id": task_id})
            except httpx.TransportError:
                response = None
            if response is None or response.status_code >= 500 or response.status_code == 429:
                # OmniHuman said nothing about the task: ask again; past a few in a row,
                # stop waiting WITHOUT failing it — the render may well go on
                errors += 1
                if errors >= MAX_CONSECUTIVE_POLL_ERRORS:
                    raise OmniHumanTimeout(
                        f"OmniHuman task {task_id} unreachable after {errors} polls",
                        task_id=task_id,
                    )
            else:
                errors = 0
                try:
                    data = self._data(response, task_id)
                except OmniHumanError as exc:
                    # an error code on the task's own result: OmniHuman refused it
                    raise OmniHumanTaskFailed(str(exc), task_id=task_id, code=exc.code) from exc

            if data is not None:
                status = str(data.get("status") or "")
                _tell(observer, "polled", task_id, status)
                if status == GENERATING and generating_since is None:
                    generating_since = self._monotonic()
                if status == DONE:
                    url = _video_url(data.get("resp_data"))
                    if not url:
                        raise OmniHumanTaskFailed(
                            f"OmniHuman task {task_id} finished without a video_url",
                            task_id=task_id,
                            status=status,
                        )
                    return url
                if status in _FAILED:
                    raise OmniHumanTaskFailed(
                        f"OmniHuman task {task_id} {status}", task_id=task_id, status=status
                    )

            now = self._monotonic()
            if generating_since is not None:
                if now - generating_since + self._poll_interval > self._poll_timeout:
                    raise OmniHumanTimeout(
                        f"OmniHuman task {task_id} still generating after "
                        f"{now - generating_since:.0f}s",
                        task_id=task_id,
                    )
            elif now - started + self._poll_interval > self._queue_timeout:
                raise OmniHumanTimeout(
                    f"OmniHuman task {task_id} still {status or QUEUED} after {now - started:.0f}s",
                    task_id=task_id,
                )
            self._sleep(self._poll_interval)

    def estimate_cost_usd(
        self, request: GenerationRequest, pricing: PricingTable, *, api_key: str | None = None
    ) -> Decimal:
        """The render's price at the voice track's length (the cap when unknown). Zero
        for a resume (m-24852495): it orders nothing — the render already ordered is
        recorded at its real price when it lands, and a budget block here would lose a
        video BytePlus bills anyway."""
        if _resume_id(request.params):
            return Decimal(0)
        seconds = Decimal(str(request.params.get("audio_seconds") or self.max_audio_seconds))
        return omnihuman_cost_usd(pricing, self.req_key, self._resolution(request.params), seconds)

    def _resolution(self, params: Mapping[str, object]) -> int:
        """2.0 renders native 720p; 1.5 takes 720 or 1080."""
        if self.req_key == OMNIHUMAN_20:
            return 720
        return 1080 if int(params.get("resolution") or 720) >= 1080 else 720


def _resume_id(params: Mapping[str, object]) -> str:
    resume = params.get(RESUME_TASK_PARAM)
    return resume.strip() if isinstance(resume, str) else ""


def _video_url(raw: Any) -> str | None:
    """`resp_data` is a JSON string holding `video_url` (a dict is taken as is)."""
    parsed: Any = raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return None
    url = parsed.get("video_url") if isinstance(parsed, dict) else None
    return str(url) if url else None


def _tell(observer: VendorTaskObserver | None, event: str, *args: str) -> None:
    """Tell the observer, never letting it break the task (a sign of life and a
    bookmark — the wait goes on without them)."""
    if observer is None:
        return
    try:
        getattr(observer, event)(*args)
    except Exception:  # noqa: BLE001
        logger.warning("vendor task observer failed on %s", event, exc_info=True)
