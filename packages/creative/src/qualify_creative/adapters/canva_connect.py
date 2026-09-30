"""Canva Connect API client — send a generated piece to the operator's Canva to edit it
there, and bring the edited result back (§ request 2026-09-28).

**Written against the documentation, never run against the live API** (no Canva
integration credentials existed when it was written). Shapes follow canva.dev as read
on 2026-09-28; the parts most likely to need adjusting on the first real run are marked
``UNVERIFIED``.

The round trip:

1. **OAuth 2.0 + PKCE (S256), per user.** ``authorize_url`` → the user consents on
   canva.com → our redirect page gets ``code`` → ``exchange_code``. A refresh token is
   single-use: every ``refresh`` returns a NEW one that must replace the stored one.
2. **Upload** the file as an asset of the user (``POST /v1/asset-uploads``, raw bytes +
   ``Asset-Upload-Metadata``; async job): images ≤ 50 MB, videos ≤ 500 MB.
3. **Create a design** (``POST /v1/designs``) of the piece's exact size. Only an IMAGE
   asset can be placed in it by the API — a video stays in the user's Uploads and the
   user drags it in (Canva's own limit, not ours).
4. The user edits at ``edit_url`` (valid 30 days, only for that user) with our
   ``correlation_state`` appended; "Return" sends them to our return URL with a
   ``correlation_jwt`` (see ``decode_correlation_jwt``).
5. **Export** (``POST /v1/exports``, async job) as PNG/JPG or MP4; the download URLs last
   24 h, so the caller downloads at once.

Canva has no "design edited" webhook: the return navigation (and a manual "Traer de
Canva") is the signal.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

AUTHORIZE_URL = "https://www.canva.com/api/oauth/authorize"
API_BASE_URL = "https://api.canva.com/rest"
TOKEN_PATH = "/v1/oauth/token"

#: What the round trip needs: upload assets, create designs, read and export them.
SCOPES = (
    "asset:read",
    "asset:write",
    "design:meta:read",
    "design:content:read",
    "design:content:write",
)

MAX_IMAGE_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_VIDEO_UPLOAD_BYTES = 500 * 1024 * 1024
#: A custom design's side, in pixels (Canva's documented bounds).
MIN_DESIGN_SIDE = 40
MAX_DESIGN_SIDE = 8000
#: ``correlation_state`` must be URL-safe and at most 50 characters.
MAX_CORRELATION_STATE = 50

EXPORT_FORMATS = frozenset({"png", "jpg", "mp4"})
#: MP4 export quality names; a vertical piece (4:5, 9:16) takes a ``vertical_*`` one.
MP4_QUALITIES = frozenset(
    {
        "horizontal_480p",
        "horizontal_720p",
        "horizontal_1080p",
        "horizontal_4k",
        "vertical_480p",
        "vertical_720p",
        "vertical_1080p",
        "vertical_4k",
    }
)

DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_POLL_TIMEOUT_SECONDS = 180.0

_JOB_OK = "success"
_JOB_FAILED = "failed"


class CanvaError(Exception):
    """Anything that went wrong talking to Canva."""


class CanvaAPIError(CanvaError):
    """A non-2xx answer. ``code`` is Canva's own error code when the body carried one
    (e.g. ``license_required`` on a pro export of a design with premium elements)."""

    def __init__(self, status_code: int, code: str | None, message: str | None) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"Canva HTTP {status_code}: {code or '?'}: {message or ''}".strip())


class CanvaJobFailed(CanvaError):
    def __init__(self, job_id: str, code: str | None, message: str | None) -> None:
        self.job_id = job_id
        self.code = code
        self.message = message
        super().__init__(f"Canva job {job_id} failed: {code or '?'}: {message or ''}".strip())


class CanvaJobTimeout(CanvaError):
    def __init__(self, job_id: str, waited_seconds: float) -> None:
        self.job_id = job_id
        self.waited_seconds = waited_seconds
        super().__init__(f"Canva job {job_id} still running after {waited_seconds:.0f}s")


# ---------------------------------------------------------------------------------------
# OAuth helpers (pure)


@dataclass(frozen=True)
class PkcePair:
    verifier: str
    challenge: str


def new_pkce() -> PkcePair:
    """A fresh PKCE pair: a 64-character verifier (RFC 7636 allows 43–128) and its S256
    challenge."""
    verifier = secrets.token_urlsafe(48)  # 64 chars
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PkcePair(verifier=verifier, challenge=challenge)


def new_correlation_state() -> str:
    """The random key that ties Canva's return navigation back to one of our rows. It is
    also what makes an unverified ``correlation_jwt`` safe to act on: only someone who
    opened the edit URL knows it."""
    return secrets.token_urlsafe(24)  # 32 chars, URL-safe


def authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scopes: tuple[str, ...] = SCOPES,
) -> str:
    """Where to send the user to connect their Canva account."""
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def with_correlation_state(edit_url: str, correlation_state: str) -> str:
    """``edit_url`` with our ``correlation_state`` added to its query."""
    if not correlation_state or len(correlation_state) > MAX_CORRELATION_STATE:
        raise ValueError(f"correlation_state must be 1–{MAX_CORRELATION_STATE} characters")
    parts = urlsplit(edit_url)
    extra = urlencode({"correlation_state": correlation_state})
    query = f"{parts.query}&{extra}" if parts.query else extra
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def decode_correlation_jwt(token: str) -> dict[str, Any]:
    """The claims of the ``correlation_jwt`` Canva appends to our return URL
    (``design_id``, ``correlation_state``, ``aud``, ``exp``, …) — decoded, **NOT
    signature-verified**. The caller must treat them as a hint: look the
    ``correlation_state`` up in its own (tenant-scoped) rows and read the design with
    the user's own token before trusting anything. Verifying the signature needs
    Canva's keys endpoint, which was still marked preview on 2026-09-28."""
    parts = token.split(".")
    if len(parts) != 3:
        raise CanvaError("correlation_jwt is not a JWT")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise CanvaError("correlation_jwt payload is not JSON") from exc
    if not isinstance(claims, dict):
        raise CanvaError("correlation_jwt payload is not an object")
    return claims


def mp4_quality_for(width: int, height: int) -> str:
    """The 1080p MP4 export quality for a piece of this shape."""
    return "vertical_1080p" if height >= width else "horizontal_1080p"


# ---------------------------------------------------------------------------------------
# The client


@dataclass(frozen=True)
class CanvaTokens:
    access_token: str
    refresh_token: str
    expires_at: datetime
    scope: str


@dataclass(frozen=True)
class CanvaDesign:
    id: str
    edit_url: str
    view_url: str
    #: Unix seconds; how the caller tells whether the user changed anything.
    updated_at: int | None


class CanvaConnectClient:
    """Stateless per call: tokens are passed in, never held. Tests inject an
    ``httpx.MockTransport`` through ``transport`` and fake ``sleep``/``monotonic``."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        base_url: str = API_BASE_URL,
        transport: Any = None,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        poll_timeout_seconds: float = DEFAULT_POLL_TIMEOUT_SECONDS,
        request_timeout_seconds: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError("Canva client requires a client_id and a client_secret")
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url
        self._transport = transport
        self._poll_interval = poll_interval_seconds
        self._poll_timeout = poll_timeout_seconds
        self._request_timeout = request_timeout_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._now = now

    def _http(self, access_token: str | None = None) -> Any:
        import httpx  # lazy, same as the HeyGen adapter

        headers = {"accept": "application/json"}
        if access_token is not None:
            if not access_token:
                raise ValueError("Canva call requires a non-empty access token")
            headers["Authorization"] = f"Bearer {access_token}"
        return httpx.Client(
            base_url=self._base_url,
            headers=headers,
            timeout=self._request_timeout,
            transport=self._transport,
        )

    # -- OAuth ----------------------------------------------------------------------------

    def exchange_code(self, *, code: str, code_verifier: str, redirect_uri: str) -> CanvaTokens:
        return self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
            }
        )

    def refresh(self, *, refresh_token: str) -> CanvaTokens:
        """A new access token AND a new refresh token — the old refresh token is spent."""
        return self._token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})

    def _token_request(self, form: dict[str, str]) -> CanvaTokens:
        basic = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode()).decode()
        with self._http() as http:
            response = http.post(
                TOKEN_PATH,
                data=form,
                headers={"Authorization": f"Basic {basic}"},
            )
        body = _body_or_raise(response)
        access = body.get("access_token")
        refresh = body.get("refresh_token")
        if not access or not refresh:
            raise CanvaError("token response carried no access_token/refresh_token")
        expires_in = int(body.get("expires_in") or 0)
        return CanvaTokens(
            access_token=str(access),
            refresh_token=str(refresh),
            expires_at=self._now() + timedelta(seconds=expires_in),
            scope=str(body.get("scope") or ""),
        )

    # -- assets ---------------------------------------------------------------------------

    def upload_asset(self, *, access_token: str, data: bytes, name: str, is_video: bool) -> str:
        """Upload ``data`` to the user's Canva uploads and wait for it; returns the
        ``asset_id``."""
        limit = MAX_VIDEO_UPLOAD_BYTES if is_video else MAX_IMAGE_UPLOAD_BYTES
        if len(data) > limit:
            raise ValueError(f"file is {len(data)} bytes; Canva takes at most {limit}")
        metadata = {"name_base64": base64.b64encode(name[:255].encode()).decode()}
        with self._http(access_token) as http:
            response = http.post(
                "/v1/asset-uploads",
                content=data,
                headers={
                    "Content-Type": "application/octet-stream",
                    "Asset-Upload-Metadata": json.dumps(metadata),
                },
            )
            job = _job(_body_or_raise(response))
            done = self._wait(http, "/v1/asset-uploads/{id}", job)
        asset = done.get("asset")
        asset_id = asset.get("id") if isinstance(asset, dict) else None
        if not asset_id:
            raise CanvaError(f"asset upload {job.get('id')} finished without an asset id")
        return str(asset_id)

    # -- designs --------------------------------------------------------------------------

    def create_design(
        self,
        *,
        access_token: str,
        width: int,
        height: int,
        title: str,
        asset_id: str | None = None,
    ) -> CanvaDesign:
        """A custom-size design; with ``asset_id`` (an IMAGE asset only) the image is
        placed in it."""
        for side in (width, height):
            if not MIN_DESIGN_SIDE <= side <= MAX_DESIGN_SIDE:
                raise ValueError(
                    f"a design side must be {MIN_DESIGN_SIDE}–{MAX_DESIGN_SIDE} px, got {side}"
                )
        body: dict[str, Any] = {
            "design_type": {"type": "custom", "width": width, "height": height},
            "title": title[:255] or "Qualify",
        }
        if asset_id:
            body["asset_id"] = asset_id
        with self._http(access_token) as http:
            data = _body_or_raise(http.post("/v1/designs", json=body))
        return _design(data)

    def get_design(self, *, access_token: str, design_id: str) -> CanvaDesign:
        with self._http(access_token) as http:
            data = _body_or_raise(http.get(f"/v1/designs/{design_id}"))
        return _design(data)

    # -- exports --------------------------------------------------------------------------

    def export_design(
        self,
        *,
        access_token: str,
        design_id: str,
        file_type: str,
        mp4_quality: str = "vertical_1080p",
    ) -> list[str]:
        """Export and wait; returns the download URLs (one per page — a single-page
        design gives one). They expire after 24 h: download at once."""
        if file_type not in EXPORT_FORMATS:
            raise ValueError(f"file_type must be one of {sorted(EXPORT_FORMATS)}")
        export_format: dict[str, Any] = {"type": file_type}
        if file_type == "mp4":
            if mp4_quality not in MP4_QUALITIES:
                raise ValueError(f"mp4_quality must be one of {sorted(MP4_QUALITIES)}")
            export_format["quality"] = mp4_quality
        with self._http(access_token) as http:
            response = http.post(
                "/v1/exports", json={"design_id": design_id, "format": export_format}
            )
            job = _job(_body_or_raise(response))
            done = self._wait(http, "/v1/exports/{id}", job)
        urls = done.get("urls")
        if not isinstance(urls, list) or not urls:
            raise CanvaError(f"export {job.get('id')} finished without download urls")
        return [str(url) for url in urls]

    def download(self, url: str) -> bytes:
        """Fetch an export URL (pre-signed: no Canva auth header)."""
        import httpx

        with httpx.Client(timeout=self._request_timeout, transport=self._transport) as http:
            response = http.get(url, follow_redirects=True)
        if response.status_code >= 400:
            raise CanvaAPIError(response.status_code, None, "export download failed")
        return response.content

    # -- internals ------------------------------------------------------------------------

    def _wait(self, http: Any, path: str, job: Mapping[str, Any]) -> Mapping[str, Any]:
        """Poll a job until ``success`` (returned) or ``failed`` (raises)."""
        job_id = str(job.get("id") or "")
        if not job_id:
            raise CanvaError(f"job carried no id: {job!r}")
        started = self._monotonic()
        while True:
            status = job.get("status")
            if status == _JOB_OK:
                return job
            if status == _JOB_FAILED:
                error = job.get("error") if isinstance(job.get("error"), dict) else {}
                raise CanvaJobFailed(job_id, error.get("code"), error.get("message"))
            waited = self._monotonic() - started
            if waited + self._poll_interval > self._poll_timeout:
                raise CanvaJobTimeout(job_id, waited)
            self._sleep(self._poll_interval)
            job = _job(_body_or_raise(http.get(path.format(id=job_id))))


def _body_or_raise(response: Any) -> Mapping[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = None
    if response.status_code >= 400:
        code = message = None
        if isinstance(body, dict):
            code = body.get("code") or body.get("error")
            message = body.get("message") or body.get("error_description")
        raise CanvaAPIError(response.status_code, code, message)
    if not isinstance(body, dict):
        raise CanvaError(f"Canva answered {response.status_code} without a JSON object")
    return body


def _job(body: Mapping[str, Any]) -> Mapping[str, Any]:
    job = body.get("job")
    if not isinstance(job, dict):
        raise CanvaError(f"response carried no job: {body!r}")
    return job


def _design(body: Mapping[str, Any]) -> CanvaDesign:
    design = body.get("design")
    if not isinstance(design, dict) or not design.get("id"):
        raise CanvaError(f"response carried no design: {body!r}")
    urls = design.get("urls") if isinstance(design.get("urls"), dict) else {}
    updated = design.get("updated_at")
    return CanvaDesign(
        id=str(design["id"]),
        edit_url=str(urls.get("edit_url") or ""),
        view_url=str(urls.get("view_url") or ""),
        updated_at=int(updated) if isinstance(updated, int | float) else None,
    )
