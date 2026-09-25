"""HeyGen avatar-video adapter — the UGC-avatar lane of the ``GenerationProvider`` seam.

HeyGen sits in no aggregator, so it gets a dedicated adapter with its own key and
billing (ADR 32 D5, backlog F5-MA-10). API facts pinned from developers.heygen.com
(2026-09), not from memory:

- **v3 only.** ``POST /v3/videos`` creates, ``GET /v3/videos/{id}`` reads. The v1/v2
  pair (``/v2/video/generate`` + ``/v1/video_status.get``) is legacy and is retired on
  2026-10-31 — building on it would be a migration scheduled for five weeks out.
- Auth is the ``x-api-key`` header. The client is built with the resolved key and no
  ambient fallback, the same rule as the copy adapter.
- Rendering is asynchronous: create returns ``{"data": {"video_id", "status"}}`` and the
  video walks ``pending`` / ``processing`` to ``completed`` or ``failed``. This adapter
  polls inside ``generate`` so it fits the synchronous Protocol and the
  ``InlineDispatcher`` thread unchanged; ``poll_timeout_seconds`` defaults below the
  dispatcher's 10-minute reaper so the adapter fails before the draft is reaped.
- ``Idempotency-Key`` (24 h window) makes a retried create return the same video instead
  of rendering — and billing — a second one. Callers should pass the draft id.
- Errors are ``{"error": {"code", "message", "param"}}``; 429 carries ``Retry-After``.
- Script cap 5,000 characters. Default engine is Avatar IV. Pay-as-you-go concurrency is
  10 renders.
- The docs do not state how long ``video_url`` stays valid, so
  ``media_expires_at_seconds`` is reported as ``None`` rather than invented: the caller
  must copy the file to our own storage as soon as the result lands.

Scope guard: this adapter renders with an avatar that ALREADY exists in the HeyGen
account (stock or pre-approved). It never creates or clones an avatar — cloning a real
person is blocked until the consent/licence gate of F5-MA-05 has its own ADR.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from qualify_creative.enums import GenerationTask
from qualify_creative.providers import (
    GenerationRequest,
    GenerationResult,
    PricingTable,
    Usage,
)

BASE_URL = "https://api.heygen.com"
MAX_SCRIPT_CHARS = 5000
MAX_AVATAR_PROMPT_CHARS = 1000  # CreatePromptAvatarRequest.prompt maxLength
MAX_ASSET_UPLOAD_BYTES = 32 * 1024 * 1024  # HeyGen's own cap on POST /v3/assets

ENGINES = frozenset({"avatar_iii", "avatar_iv"})
RESOLUTIONS = frozenset({"720p", "1080p", "4k"})
ASPECT_RATIOS = frozenset({"16:9", "9:16", "4:5", "5:4", "1:1"})

#: Reels is the placement this lane exists for, and 1080p is the resolution that is
#: priced; 4K is accepted by the vendor but deliberately unpriced in the table, so it
#: fails the pre-flight loudly instead of billing an unknown rate.
DEFAULT_ENGINE = "avatar_iv"
DEFAULT_RESOLUTION = "1080p"
DEFAULT_ASPECT_RATIO = "9:16"

#: Under the dispatcher's 10-minute reaper (``DEFAULT_REAP_AFTER_MINUTES``).
DEFAULT_POLL_TIMEOUT_SECONDS = 480.0
DEFAULT_POLL_INTERVAL_SECONDS = 10.0
#: A poll that hits a 5xx or a dropped connection is not a failed render; only this many
#: in a row is.
MAX_CONSECUTIVE_POLL_ERRORS = 3

#: Pre-flight duration model. Conversational Spanish runs at ~2.5 words/s; estimating
#: at 2.2 deliberately OVER-states the length so the budget check errs expensive, plus a
#: fixed second for the avatar's lead-in and tail.
ESTIMATE_WORDS_PER_SECOND = Decimal("2.2")
ESTIMATE_PADDING_SECONDS = Decimal(1)

_TERMINAL_OK = "completed"
_TERMINAL_FAILED = "failed"


class HeyGenError(Exception):
    """Base for everything this adapter raises, so the router's hop record names it."""


class HeyGenAPIError(HeyGenError):
    """A non-2xx answer from the API, with HeyGen's own error code kept for branching:
    ``avatar_not_usable`` is a configuration problem, ``unauthorized`` a credential one,
    and neither should be retried against the same account."""

    def __init__(
        self,
        status_code: int,
        code: str | None,
        message: str,
        param: str | None = None,
        retry_after: float = 0.0,
    ) -> None:
        detail = f"HTTP {status_code} {code or 'unknown_error'}: {message}"
        if param:
            detail += f" (param: {param})"
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.param = param
        self.retry_after = retry_after


class HeyGenRenderFailed(HeyGenError):
    """The render reached ``failed``. The video id is kept for the support ticket."""

    def __init__(self, video_id: str, failure_code: str | None, message: str | None) -> None:
        super().__init__(
            f"HeyGen render {video_id} failed: {failure_code or 'unknown'}: {message or ''}"
        )
        self.video_id = video_id
        self.failure_code = failure_code


class HeyGenRenderTimeout(HeyGenError):
    """The poll window closed before the render finished.

    The render is NOT cancelled by this — it keeps going and HeyGen bills it. The video
    id is carried so reconciliation can pick the finished file up with
    :meth:`HeyGenAvatarVideoAdapter.get_video` instead of paying for a second one.
    """

    def __init__(self, video_id: str, waited_seconds: float) -> None:
        super().__init__(
            f"HeyGen render {video_id} still running after {waited_seconds:.0f}s; "
            "it will keep rendering and billing — recover it by video id"
        )
        self.video_id = video_id


class HeyGenAvatarVideoAdapter:
    """``GenerationProvider`` for avatar AND image-animation videos over HeyGen API v3.

    ``request.params`` carries the video spec (the rendered prompt does not apply: the
    script is already-approved copy, not an instruction to a model). It is a
    discriminated union on the SUBJECT, same as HeyGen's own ``POST /v3/videos``:

    - **Subject — exactly one of:**
      ``avatar_id`` (a library avatar/look) | ``image_url`` | ``image_asset_id``
      (animate a still image instead — no avatar needed at all).
    - **Audio — at most one of:**
      ``script`` + ``voice_id`` together (HeyGen TTS reads the script, ≤5,000 chars) |
      ``audio_url`` (lip-sync to audio you already recorded) | ``audio_asset_id``.
      With an ``avatar_id`` subject, HeyGen requires one of these three — a talking
      avatar with nothing to say makes no sense. With an image subject, audio is
      OPTIONAL: omit it all for a silent animated shot (e.g. a plain product video),
      verified live against HeyGen's own schema (2026-09-23) — image mode is the only
      one of the two that supports "no audio at all".
    - ``engine`` ``avatar_iv`` | ``avatar_iii`` (avatar subject only — ignored, and not
      sent, for an image subject); ``resolution``; ``aspect_ratio``
    - ``voice_speed`` (0.5–1.5), ``locale`` (e.g. ``es-CO``) — apply only to the
      ``script`` audio path; HeyGen has no speed/locale control over audio you supply.
    - **Background — at most one of:** ``background_color`` (``#RRGGBB``) |
      ``background_image_url`` | ``background_image_asset_id``. Works for BOTH
      subjects (avatar or image) — verified live against HeyGen's schema
      (2026-09-24): a talking avatar in front of a product photo, or an animated
      product image with a second image behind it, is the same field either way.
    - ``burn_captions`` (SRT is always produced)
    - ``idempotency_key`` — pass the draft id; ``title``
    """

    name = "heygen"
    supports = frozenset({GenerationTask.AVATAR_VIDEO})

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        transport: Any = None,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        poll_timeout_seconds: float = DEFAULT_POLL_TIMEOUT_SECONDS,
        request_timeout_seconds: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base_url = base_url
        self._transport = transport
        self._poll_interval = poll_interval_seconds
        self._poll_timeout = poll_timeout_seconds
        self._request_timeout = request_timeout_seconds
        self._sleep = sleep
        self._monotonic = monotonic

    def _client(self, api_key: str) -> Any:
        """Build the HTTP client for ``api_key``. ``httpx`` is imported lazily so that
        importing ``qualify_creative`` never drags a network client (install via the
        ``video`` extra). Tests inject an ``httpx.MockTransport`` through ``transport``;
        the key header is set here either way, so the tests see the real auth path."""
        if not api_key:
            raise ValueError("HeyGen adapter requires an explicit, non-empty api_key")
        import httpx  # lazy: optional dependency

        return httpx.Client(
            base_url=self._base_url,
            headers={"x-api-key": api_key, "accept": "application/json"},
            timeout=self._request_timeout,
            transport=self._transport,
        )

    # -- GenerationProvider -------------------------------------------------------------

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        spec = _VideoSpec.from_params(request.params)
        with self._client(api_key) as client:
            video_id = self._create(client, spec)
            data = self._wait(client, video_id)

        duration = Decimal(str(data.get("duration") or 0))
        payload: dict[str, object] = {
            "video_id": video_id,
            "video_url": data.get("video_url"),
            "thumbnail_url": data.get("thumbnail_url"),
            "subtitle_url": data.get("subtitle_url"),
            "captioned_video_url": data.get("captioned_video_url"),
            "duration_seconds": str(duration),
            "aspect_ratio": spec.aspect_ratio,
            "resolution": spec.resolution,
            "subject_kind": spec.subject_kind,
        }
        return GenerationResult(
            payload=payload,
            model_id=spec.model_id,
            provider=self.name,
            usage=Usage(pieces=1, media_seconds=duration),
            model_revision=spec.engine if spec.subject_kind == "avatar" else None,
            media_url=data.get("video_url"),
            media_expires_at_seconds=None,
        )

    def estimate_cost_usd(
        self,
        request: GenerationRequest,
        pricing: PricingTable,
        *,
        api_key: str | None = None,  # unused: per-second pricing needs no vendor counter
    ) -> Decimal:
        """Pre-flight estimate for the router's (P) check: estimated seconds × the
        per-second rate for this engine/subject and resolution. The duration model
        over-states on purpose (see ``ESTIMATE_WORDS_PER_SECOND``); an unpriced
        engine/resolution raises ``KeyError`` from the table rather than estimating
        zero.

        With a ``script`` audio source, seconds come from the word count. Otherwise
        (pre-recorded audio, or a silent image) HeyGen reports no duration before
        rendering, so the caller MUST supply a positive ``duration_seconds_hint`` param
        — refusing to guess is the same "loud over silent zero" rule as an unpriced
        model."""
        spec = _VideoSpec.from_params(request.params)
        rate = pricing.unit_price(model_id=spec.model_id, unit=f"per_second_{spec.resolution}")
        if spec.audio_kind == "script":
            seconds = estimate_seconds(spec.script or "", spec.voice_speed)
        else:
            hint = request.params.get("duration_seconds_hint")
            if not isinstance(hint, int | float) or isinstance(hint, bool) or hint <= 0:
                raise ValueError(
                    "cost estimate needs a script to count words from, or an explicit "
                    "positive 'duration_seconds_hint' param when audio is pre-recorded "
                    "or the render is silent — HeyGen reports no duration before "
                    "rendering"
                )
            seconds = Decimal(math.ceil(hint))
        return seconds * rate

    # -- recovery -----------------------------------------------------------------------

    def get_video(self, video_id: str, *, api_key: str) -> Mapping[str, Any]:
        """Read one video's current state — the recovery path after a
        ``HeyGenRenderTimeout`` or a process restart."""
        with self._client(api_key) as client:
            return self._get(client, video_id)

    # -- discovery ------------------------------------------------------------------------
    #
    # Both endpoints below are the ONLY thing this module is allowed to use for avatar
    # discovery — never ``avatar-from-photo``/``avatar-from-video`` (real-person cloning,
    # blocked until F5-MA-05's consent/licence gate has an ADR). ``ownership="public"``
    # is HeyGen's own preset library: licensed stock actors, not a clone of anyone, so no
    # consent question applies — same guarantee HeyGen documents for its prompt-based
    # synthetic avatar generator (``POST /v3/avatars {type: "prompt"}``, not implemented
    # here: it is a second async render on top of the video one and out of scope for a
    # "browse what already exists" seam). Verified live against the real API (2026-09-23),
    # not just docs: ``GET /v3/avatars`` returns avatar *groups* (a character, e.g.
    # "Dante") whose ``id`` is NOT usable as ``avatar_id`` in ``generate`` — you need one
    # of the group's *looks*. ``GET /v3/avatars/looks`` turned out to need no ``group_id``
    # at all: called bare, it returns a flat page of looks spanning every public group,
    # and each look's ``id`` IS directly usable as ``avatar_id``. That is the only call
    # ``list_avatar_looks`` makes — the group-listing/group-detail endpoints are
    # deliberately unused, since they would only add a step for no benefit here.

    def list_avatar_looks(
        self, *, api_key: str, ownership: str = "public", limit: int = 20
    ) -> list[Mapping[str, Any]]:
        """Ready-to-use avatar looks; each item's ``"id"`` is what ``generate``'s
        ``params["avatar_id"]`` wants. ``ownership="private"`` lists the account's own
        (consented) avatars instead of HeyGen's public library."""
        with self._client(api_key) as client:
            return _list_or_raise(
                client.get("/v3/avatars/looks", params={"ownership": ownership, "limit": limit})
            )

    def list_voices(
        self,
        *,
        api_key: str,
        voice_type: str = "public",
        language: str | None = None,
        limit: int = 20,
    ) -> list[Mapping[str, Any]]:
        """Voices; each item's ``"voice_id"`` is what ``generate``'s
        ``params["voice_id"]`` wants. ``language`` filters by HeyGen's language name
        (e.g. ``"Spanish"``) when given."""
        params: dict[str, Any] = {"type": voice_type, "limit": limit}
        if language:
            params["language"] = language
        with self._client(api_key) as client:
            return _list_or_raise(client.get("/v3/voices", params=params))

    # -- upload ---------------------------------------------------------------------------

    def upload_asset(
        self,
        *,
        api_key: str,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        idempotency_key: str | None = None,
    ) -> Mapping[str, Any]:
        """Upload a local file (image/video/audio/PDF, ≤``MAX_ASSET_UPLOAD_BYTES``) to
        HeyGen's own storage and get back an ``asset_id`` usable as
        ``params["image_asset_id"]``/``audio_asset_id`` in ``generate`` — this is what
        makes a locally-uploaded product photo or avatar-source image usable at all: a
        dev server on ``localhost`` is not a URL HeyGen's renderer can fetch, so the
        bytes have to go to HeyGen directly instead of being passed as ``image_url``.
        Verified live against the real endpoint (2026-09-24, a throwaway 1×1 PNG): the
        response is ``{"data": {"asset_id", "url", "mime_type", "size_bytes"}}``,
        exactly as documented."""
        if len(file_bytes) > MAX_ASSET_UPLOAD_BYTES:
            raise ValueError(
                f"file is {len(file_bytes)} bytes; HeyGen's asset upload caps it at "
                f"{MAX_ASSET_UPLOAD_BYTES} bytes (32 MB)"
            )
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        with self._client(api_key) as client:
            response = client.post(
                "/v3/assets",
                files={"file": (filename, file_bytes, content_type)},
                headers=headers,
            )
            return _data_or_raise(response)

    # -- prompt avatars ------------------------------------------------------------------
    #
    # An AI-generated character (`ContentKind.ANIMATED_AVATAR_VIDEO`, source "ai"):
    # `POST /v3/avatars {type: "prompt"}` generates a SYNTHETIC avatar from a text
    # description — nobody's likeness, so no consent question (HeyGen's own docs, and the
    # scope guard above still holds: photo/footage cloning stays out). Asynchronous like a
    # render: the response carries the new look (`avatar_item`) in `processing`, and
    # `GET /v3/avatars/looks/{id}` is polled until `completed`; that look id is then the
    # `avatar_id` of an ordinary avatar video. Shapes pinned from the v3 OpenAPI spec
    # (`CreatePromptAvatarRequest`, `CreateAvatarResponse`, `AvatarLookItem`), 2026-09-25.

    def create_prompt_avatar(
        self,
        *,
        api_key: str,
        name: str,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        idempotency_key: str | None = None,
    ) -> str:
        """Start generating a synthetic avatar; returns the new look's id (not yet
        usable — see `wait_for_look`)."""
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("a prompt avatar needs a description")
        if len(prompt) > MAX_AVATAR_PROMPT_CHARS:
            raise ValueError(
                f"prompt is {len(prompt)} characters; HeyGen caps it at {MAX_AVATAR_PROMPT_CHARS}"
            )
        if aspect_ratio not in ASPECT_RATIOS:
            raise ValueError(f"aspect_ratio must be one of {sorted(ASPECT_RATIOS)}")
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        body = {"type": "prompt", "name": name[:80] or "avatar", "prompt": prompt}
        body["aspect_ratio"] = aspect_ratio
        with self._client(api_key) as client:
            data = _data_or_raise(client.post("/v3/avatars", json=body, headers=headers))
        item = data.get("avatar_item")
        look_id = item.get("id") if isinstance(item, dict) else None
        if not look_id:
            raise HeyGenError(f"prompt avatar response carried no look id: {data!r}")
        return str(look_id)

    def wait_for_look(self, look_id: str, *, api_key: str) -> Mapping[str, Any]:
        """Poll a look until it is `completed` (returned) or `failed` (raises), within
        the same timeout as a render."""
        started = self._monotonic()
        with self._client(api_key) as client:
            while True:
                data = _data_or_raise(client.get(f"/v3/avatars/looks/{look_id}"))
                status = data.get("status")
                if status == _TERMINAL_OK:
                    return data
                if status == _TERMINAL_FAILED:
                    error = data.get("error") if isinstance(data.get("error"), dict) else {}
                    raise HeyGenRenderFailed(look_id, error.get("code"), error.get("message"))
                waited = self._monotonic() - started
                if waited + self._poll_interval > self._poll_timeout:
                    raise HeyGenRenderTimeout(look_id, waited)
                self._sleep(self._poll_interval)

    # -- internals ----------------------------------------------------------------------

    def _create(self, client: Any, spec: _VideoSpec) -> str:
        headers = {}
        if spec.idempotency_key:
            headers["Idempotency-Key"] = spec.idempotency_key
        response = client.post("/v3/videos", json=spec.body(), headers=headers)
        data = _data_or_raise(response)
        video_id = data.get("video_id")
        if not video_id:
            raise HeyGenError(f"create response carried no video_id: {data!r}")
        return str(video_id)

    def _get(self, client: Any, video_id: str) -> Mapping[str, Any]:
        return _data_or_raise(client.get(f"/v3/videos/{video_id}"))

    def _wait(self, client: Any, video_id: str) -> Mapping[str, Any]:
        import httpx  # lazy, already loaded by _client

        started = self._monotonic()
        consecutive_errors = 0
        while True:
            delay = self._poll_interval
            try:
                data = self._get(client, video_id)
                consecutive_errors = 0
            except HeyGenAPIError as exc:
                if exc.status_code == 429:
                    delay = max(delay, exc.retry_after)
                elif exc.status_code < 500:
                    raise
                else:
                    consecutive_errors += 1
                    if consecutive_errors >= MAX_CONSECUTIVE_POLL_ERRORS:
                        raise
                data = None
            except httpx.TransportError:
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_POLL_ERRORS:
                    raise
                data = None

            if data is not None:
                status = data.get("status")
                if status == _TERMINAL_OK:
                    if not data.get("video_url"):
                        raise HeyGenError(f"render {video_id} completed without a video_url")
                    return data
                if status == _TERMINAL_FAILED:
                    raise HeyGenRenderFailed(
                        video_id, data.get("failure_code"), data.get("failure_message")
                    )

            waited = self._monotonic() - started
            if waited + delay > self._poll_timeout:
                raise HeyGenRenderTimeout(video_id, waited)
            self._sleep(delay)


@dataclass(frozen=True)
class _VideoSpec:
    """``request.params`` validated once, before any network call — a bad spec must
    fail the pre-flight, not cost a render. ``subject_kind``/``audio_kind`` are the
    resolved discriminators (see the adapter's class docstring for the params
    contract); every other subject/audio field is ``None`` unless it is the one the
    kind selected."""

    subject_kind: str  # "avatar" | "image"
    avatar_id: str | None
    image_url: str | None
    image_asset_id: str | None

    audio_kind: str | None  # "script" | "audio_url" | "audio_asset_id" | None (silent)
    script: str | None
    voice_id: str | None
    audio_url: str | None
    audio_asset_id: str | None

    engine: str
    resolution: str
    aspect_ratio: str
    voice_speed: Decimal
    locale: str | None

    background_kind: str | None  # "color" | "image" | None (no background override)
    background_color: str | None
    background_image_url: str | None
    background_image_asset_id: str | None

    burn_captions: bool
    idempotency_key: str | None
    title: str | None

    @classmethod
    def from_params(cls, params: Mapping[str, object]) -> _VideoSpec:
        avatar_id = _optional_str(params, "avatar_id")
        image_url = _optional_str(params, "image_url")
        image_asset_id = _optional_str(params, "image_asset_id")
        subjects = {
            "avatar_id": avatar_id,
            "image_url": image_url,
            "image_asset_id": image_asset_id,
        }
        given_subjects = [name for name, value in subjects.items() if value]
        if len(given_subjects) != 1:
            raise ValueError(
                "exactly one of avatar_id, image_url, image_asset_id is required "
                f"(a still image needs no avatar); got {given_subjects or 'none'}"
            )
        subject_kind = "avatar" if avatar_id else "image"

        script = _optional_str(params, "script")
        if script is not None:
            script = script.strip()
            if len(script) > MAX_SCRIPT_CHARS:
                raise ValueError(
                    f"script is {len(script)} characters; HeyGen caps it at {MAX_SCRIPT_CHARS}"
                )
        voice_id = _optional_str(params, "voice_id")
        if bool(script) != bool(voice_id):
            raise ValueError("script and voice_id must be given together, or neither")
        audio_url = _optional_str(params, "audio_url")
        audio_asset_id = _optional_str(params, "audio_asset_id")
        audio_sources = {
            "script+voice_id": script,
            "audio_url": audio_url,
            "audio_asset_id": audio_asset_id,
        }
        given_audio = [name for name, value in audio_sources.items() if value]
        if len(given_audio) > 1:
            raise ValueError(f"give at most one audio source; got {given_audio}")
        if subject_kind == "avatar" and not given_audio:
            raise ValueError(
                "avatar_id requires an audio source (script+voice_id, audio_url, or "
                "audio_asset_id) — a talking avatar needs something to say"
            )
        audio_kind = (
            "script"
            if script
            else "audio_url"
            if audio_url
            else "audio_asset_id"
            if audio_asset_id
            else None
        )

        speed = params.get("voice_speed", 1)
        if isinstance(speed, bool) or not isinstance(speed, int | float):
            raise ValueError(f"voice_speed must be a number in [0.5, 1.5], got {speed!r}")
        if not 0.5 <= speed <= 1.5:
            raise ValueError(f"voice_speed must be a number in [0.5, 1.5], got {speed!r}")

        background_color = _optional_str(params, "background_color")
        background_image_url = _optional_str(params, "background_image_url")
        background_image_asset_id = _optional_str(params, "background_image_asset_id")
        backgrounds = {
            "background_color": background_color,
            "background_image_url": background_image_url,
            "background_image_asset_id": background_image_asset_id,
        }
        given_backgrounds = [name for name, value in backgrounds.items() if value]
        if len(given_backgrounds) > 1:
            raise ValueError(f"give at most one background source; got {given_backgrounds}")
        background_kind = (
            "color"
            if background_color
            else "image"
            if (background_image_url or background_image_asset_id)
            else None
        )

        return cls(
            subject_kind=subject_kind,
            avatar_id=avatar_id,
            image_url=image_url,
            image_asset_id=image_asset_id,
            audio_kind=audio_kind,
            script=script,
            voice_id=voice_id,
            audio_url=audio_url,
            audio_asset_id=audio_asset_id,
            engine=_choice(params, "engine", ENGINES, DEFAULT_ENGINE),
            resolution=_choice(params, "resolution", RESOLUTIONS, DEFAULT_RESOLUTION),
            aspect_ratio=_choice(params, "aspect_ratio", ASPECT_RATIOS, DEFAULT_ASPECT_RATIO),
            voice_speed=Decimal(str(speed)),
            locale=_optional_str(params, "locale"),
            background_kind=background_kind,
            background_color=background_color,
            background_image_url=background_image_url,
            background_image_asset_id=background_image_asset_id,
            burn_captions=bool(params.get("burn_captions", False)),
            idempotency_key=_optional_str(params, "idempotency_key"),
            title=_optional_str(params, "title"),
        )

    @property
    def model_id(self) -> str:
        # Image mode runs on Avatar IV and is priced as its photo-avatar rate
        # (pricing_data v2 `heygen_image`, read from HeyGen's pricing page 2026-09-25).
        return f"heygen_{self.engine}" if self.subject_kind == "avatar" else "heygen_image"

    def body(self) -> dict[str, object]:
        body: dict[str, object] = {"type": self.subject_kind}
        if self.subject_kind == "avatar":
            body["avatar_id"] = self.avatar_id
            body["engine"] = {"type": self.engine}
        else:
            body["image"] = (
                {"type": "url", "url": self.image_url}
                if self.image_url
                else {"type": "asset_id", "asset_id": self.image_asset_id}
            )

        if self.audio_kind == "script":
            voice_settings: dict[str, object] = {"speed": float(self.voice_speed)}
            if self.locale:
                voice_settings["locale"] = self.locale
            body["script"] = self.script
            body["voice_id"] = self.voice_id
            body["voice_settings"] = voice_settings
        elif self.audio_kind == "audio_url":
            body["audio_url"] = self.audio_url
        elif self.audio_kind == "audio_asset_id":
            body["audio_asset_id"] = self.audio_asset_id
        # audio_kind is None: no audio field at all — a silent animated image.

        body["resolution"] = self.resolution
        body["aspect_ratio"] = self.aspect_ratio
        if self.background_kind == "color":
            body["background"] = {"type": "color", "value": self.background_color}
        elif self.background_kind == "image":
            body["background"] = (
                {"type": "image", "url": self.background_image_url}
                if self.background_image_url
                else {"type": "image", "asset_id": self.background_image_asset_id}
            )
        if self.burn_captions:
            body["caption"] = {"file_format": "srt", "style": "default"}
        if self.title:
            body["title"] = self.title
        return body


def estimate_seconds(script: str, voice_speed: Decimal = Decimal(1)) -> Decimal:
    """Whole seconds a script is expected to run, rounded UP."""
    words = len(script.split())
    raw = Decimal(words) / (ESTIMATE_WORDS_PER_SECOND * voice_speed) + ESTIMATE_PADDING_SECONDS
    return Decimal(math.ceil(raw))


def _body_or_raise(response: Any) -> Mapping[str, Any]:
    """Shared prefix of ``_data_or_raise``/``_list_or_raise``: parse the envelope and
    raise ``HeyGenAPIError`` on a non-2xx status. Returns the raw body (with ``data``
    still inside, whatever shape it is) so the two callers can each check the shape
    their endpoint actually promises — an object for create/get, an array for the
    browse endpoints."""
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400:
        error = body.get("error") if isinstance(body, dict) else None
        error = error if isinstance(error, dict) else {}
        retry_after = response.headers.get("Retry-After", "")
        raise HeyGenAPIError(
            response.status_code,
            error.get("code"),
            error.get("message") or response.text[:200],
            error.get("param"),
            retry_after=float(retry_after) if retry_after.isdigit() else 0.0,
        )
    return body if isinstance(body, dict) else {}


def _data_or_raise(response: Any) -> Mapping[str, Any]:
    """The create/get-video shape: ``data`` is a single object."""
    body = _body_or_raise(response)
    data = body.get("data")
    if not isinstance(data, dict):
        raise HeyGenError(f"response carried no data object: {body!r}")
    return data


def _list_or_raise(response: Any) -> list[Mapping[str, Any]]:
    """The browse/list shape (``/v3/avatars/looks``, ``/v3/voices``): ``data`` is an
    array."""
    body = _body_or_raise(response)
    data = body.get("data")
    if not isinstance(data, list):
        raise HeyGenError(f"response carried no data list: {body!r}")
    return data


def _optional_str(params: Mapping[str, object], key: str) -> str | None:
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"param {key!r} must be a string, got {type(value).__name__}")
    return value or None


def _choice(params: Mapping[str, object], key: str, allowed: frozenset[str], default: str) -> str:
    value = params.get(key, default)
    if value not in allowed:
        raise ValueError(f"param {key!r} must be one of {sorted(allowed)}, got {value!r}")
    return str(value)
