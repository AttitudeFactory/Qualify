"""The TikTok Content Posting API seam — INBOX (draft) upload only (m-24921091).

Same shape as `client.py`: a Protocol, an httpx implementation over an already-authenticated
client (this module never sees a token), and one `_parse_*` per endpoint marked `[V]`.

Flow (docs: Content Posting API, "Upload Content" / inbox):

1. `init_file_upload` / `init_pull_from_url` — `POST /v2/post/publish/inbox/video/init/`.
   Returns `publish_id` (+ `upload_url` for FILE_UPLOAD). Requires scope `video.upload`.
2. FILE_UPLOAD: `PUT <upload_url>` the bytes in chunks with `Content-Range`.
   Chunk rules: a file under 5 MB is one chunk; otherwise chunks of 5-64 MB where the LAST
   chunk may reach 128 MB (so `total_chunk_count = floor(size / chunk_size)`).
3. `fetch_status` — `POST /v2/post/publish/status/fetch/`: PROCESSING_UPLOAD |
   PROCESSING_DOWNLOAD | SEND_TO_USER_INBOX | PUBLISH_COMPLETE | FAILED.

There is NO direct-post (`/video/init/` with `post_info`) and no scheduling method here, on
purpose: `video.publish` is not requested and TikTok scheduled publishing is out of scope
(ADR 21(d)/23(c)). The creator finishes the draft in the TikTok app.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import IO, Any, Protocol

import httpx

from qualify_api.connections.resolver import AuthenticatedClient

MB = 1024 * 1024
MIN_CHUNK_BYTES = 5 * MB
MAX_CHUNK_BYTES = 64 * MB
# TikTok caps one video at 4 GB; Qualify's object gate caps media at 300 MB (far below).
MAX_VIDEO_BYTES = 4 * 1024 * MB


class TikTokPublishError(Exception):
    """A Content Posting call failed. `code` is TikTok's error code (`spam_risk_too_many_
    pending_share`, `access_token_invalid`, …). Never carries a token or a response body."""

    def __init__(self, message: str, *, code: str | None = None, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status

    @property
    def is_auth_failure(self) -> bool:
        return self.http_status == 401 or self.code in {
            "access_token_invalid",
            "scope_not_authorized",
            "scope_permission_missed",
        }


class RemoteStatus(StrEnum):
    PROCESSING_UPLOAD = "PROCESSING_UPLOAD"
    PROCESSING_DOWNLOAD = "PROCESSING_DOWNLOAD"
    SEND_TO_USER_INBOX = "SEND_TO_USER_INBOX"
    PUBLISH_COMPLETE = "PUBLISH_COMPLETE"
    FAILED = "FAILED"


@dataclass(frozen=True)
class InitResult:
    publish_id: str
    upload_url: str | None  # None for PULL_FROM_URL


@dataclass(frozen=True)
class RemoteState:
    status: RemoteStatus
    fail_reason: str | None = None


@dataclass(frozen=True)
class ChunkPlan:
    chunk_size: int
    total_chunk_count: int


def plan_chunks(video_size: int) -> ChunkPlan:
    """One chunk up to 64 MB; above that, 64 MB chunks with the remainder folded into the last
    (`floor(size / chunk)` chunks, the last one < 128 MB for any file this system holds)."""
    if video_size <= 0 or video_size > MAX_VIDEO_BYTES:
        raise TikTokPublishError("video size out of range", code="invalid_video_size")
    if video_size <= MAX_CHUNK_BYTES:
        return ChunkPlan(chunk_size=video_size, total_chunk_count=1)
    return ChunkPlan(chunk_size=MAX_CHUNK_BYTES, total_chunk_count=video_size // MAX_CHUNK_BYTES)


class TikTokPostClient(Protocol):
    async def init_file_upload(self, *, video_size: int) -> InitResult: ...

    async def init_pull_from_url(self, *, video_url: str) -> InitResult: ...

    async def upload_file(
        self, *, upload_url: str, fileobj: IO[bytes], video_size: int
    ) -> None: ...

    async def fetch_status(self, *, publish_id: str) -> RemoteState: ...


def _error_code(payload: dict[str, Any]) -> str | None:
    err = payload.get("error")
    if isinstance(err, dict):
        code = err.get("code")
        if isinstance(code, str) and code and code != "ok":
            return code
    return None


def _parse_init_response(payload: dict[str, Any]) -> InitResult:
    """[V] {"data":{"publish_id":"v_inbox_file~v2.…","upload_url":"https://…"},
    "error":{"code":"ok","message":"","log_id":"…"}}."""
    code = _error_code(payload)
    if code is not None:
        raise TikTokPublishError(f"init refused: {code}", code=code)
    data = payload.get("data")
    publish_id = data.get("publish_id") if isinstance(data, dict) else None
    if not isinstance(publish_id, str) or not publish_id:
        raise TikTokPublishError("init response carried no publish_id")
    upload_url = data.get("upload_url")
    return InitResult(
        publish_id=publish_id,
        upload_url=upload_url if isinstance(upload_url, str) and upload_url else None,
    )


def _parse_status_response(payload: dict[str, Any]) -> RemoteState:
    """[V] {"data":{"status":"SEND_TO_USER_INBOX","fail_reason":"…"},"error":{"code":"ok"}}."""
    code = _error_code(payload)
    if code is not None:
        raise TikTokPublishError(f"status refused: {code}", code=code)
    data = payload.get("data")
    raw = data.get("status") if isinstance(data, dict) else None
    try:
        status = RemoteStatus(str(raw))
    except ValueError:
        raise TikTokPublishError("status response carried an unknown status") from None
    reason = data.get("fail_reason") if isinstance(data, dict) else None
    return RemoteState(status=status, fail_reason=str(reason) if reason else None)


class HttpTikTokPostClient:
    """Takes an authenticated client for the API host; the upload PUT goes to TikTok's
    pre-signed `upload_url`, which needs no (and gets no) credential header."""

    def __init__(
        self,
        *,
        client: AuthenticatedClient,
        api_base_url: str = "https://open.tiktokapis.com",
        upload_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = client
        self._base = api_base_url.rstrip("/")
        self._upload_transport = upload_transport

    async def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post(
            f"{self._base}{path}",
            json=body,
            headers={"Content-Type": "application/json; charset=UTF-8"},
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if response.status_code != 200 and _error_code(payload) is None:
            # Status only: never the body.
            raise TikTokPublishError(
                f"POST {path} failed with HTTP {response.status_code}",
                http_status=response.status_code,
            )
        if response.status_code != 200:
            raise TikTokPublishError(
                f"POST {path} refused: {_error_code(payload)}",
                code=_error_code(payload),
                http_status=response.status_code,
            )
        return payload

    async def init_file_upload(self, *, video_size: int) -> InitResult:
        plan = plan_chunks(video_size)
        return _parse_init_response(
            await self._post_json(
                "/v2/post/publish/inbox/video/init/",
                {
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": video_size,
                        "chunk_size": plan.chunk_size,
                        "total_chunk_count": plan.total_chunk_count,
                    }
                },
            )
        )

    async def init_pull_from_url(self, *, video_url: str) -> InitResult:
        return _parse_init_response(
            await self._post_json(
                "/v2/post/publish/inbox/video/init/",
                {"source_info": {"source": "PULL_FROM_URL", "video_url": video_url}},
            )
        )

    async def upload_file(self, *, upload_url: str, fileobj: IO[bytes], video_size: int) -> None:
        plan = plan_chunks(video_size)
        async with httpx.AsyncClient(transport=self._upload_transport, timeout=300.0) as http:
            sent = 0
            for index in range(plan.total_chunk_count):
                last = index == plan.total_chunk_count - 1
                length = video_size - sent if last else plan.chunk_size
                data = fileobj.read(length)
                if len(data) != length:
                    raise TikTokPublishError("source video ended before its declared size")
                response = await http.put(
                    upload_url,
                    content=data,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(length),
                        "Content-Range": f"bytes {sent}-{sent + length - 1}/{video_size}",
                    },
                )
                # 201 = last chunk stored, 206 = partial accepted.
                if response.status_code not in (200, 201, 206):
                    raise TikTokPublishError(
                        f"chunk upload failed with HTTP {response.status_code}",
                        http_status=response.status_code,
                    )
                sent += length

    async def fetch_status(self, *, publish_id: str) -> RemoteState:
        return _parse_status_response(
            await self._post_json("/v2/post/publish/status/fetch/", {"publish_id": publish_id})
        )
