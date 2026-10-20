"""HTTP client for the render service — CONTRACT.md §4, nothing more.

`httpx` is imported lazily (same rule as the vendor adapters): only a process that renders
needs it. Every method raises :class:`RenderServiceError` with the service's own `error`
code, so callers branch on `exc.code`, never on message text.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from qualify_creative.enums import FailureReason

DEFAULT_BASE_URL = "http://localhost:3200"
POLL_INTERVAL_SECONDS = 2.0
DEFAULT_TIMEOUT_SECONDS = 600.0


class JobStatus(StrEnum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)


#: CONTRACT §4.2 → the draft's typed reason. Kept explicit so a new service code fails
#: loudly in `to_failure_reason` instead of becoming `provider_error` by accident.
_FAILURE_MAP: dict[str, FailureReason] = {
    "timeout": FailureReason.TIMEOUT,
    "render_error": FailureReason.RENDER_ERROR,
    "invalid_parameters": FailureReason.INVALID_PARAMETERS,
    "dependency_failed": FailureReason.DEPENDENCY_FAILED,
    "internal_error": FailureReason.PROVIDER_ERROR,
    "cancelled": FailureReason.CANCELLED,
}


def to_failure_reason(code: str | None) -> FailureReason:
    if code is None:
        return FailureReason.PROVIDER_ERROR
    try:
        return _FAILURE_MAP[code]
    except KeyError:
        raise ValueError(f"render service reported unknown failure reason {code!r}") from None


class RenderServiceError(Exception):
    def __init__(self, code: str, status: int, message: str) -> None:
        super().__init__(f"render service {status} {code}: {message}")
        self.code = code
        self.status = status
        self.message = message


@dataclass(frozen=True)
class AssetRef:
    asset_id: str
    url: str
    mime_type: str
    bytes: int

    @property
    def ref(self) -> str:
        return f"asset://{self.asset_id}"


@dataclass(frozen=True)
class OutputState:
    port: str
    kind: str
    status: JobStatus
    progress: float = 0.0
    mime_type: str | None = None
    bytes: int | None = None
    width: int | None = None
    height: int | None = None
    duration_sec: float | None = None
    failure_reason: str | None = None
    error_message: str | None = None

    @property
    def done(self) -> bool:
        return self.status is JobStatus.COMPLETED


@dataclass(frozen=True)
class RenderJob:
    job_id: str
    template_id: str
    version: int
    status: JobStatus
    outputs: dict[str, OutputState]
    duration_sec: float | None = None
    warnings: tuple[str, ...] = ()
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> RenderJob:
        outputs: dict[str, OutputState] = {}
        for port, o in (data.get("outputs") or {}).items():
            outputs[port] = OutputState(
                port=port,
                kind=str(o.get("kind", "")),
                status=JobStatus(o.get("status", "pending")),
                progress=float(o.get("progress") or 0),
                mime_type=o.get("mimeType"),
                bytes=o.get("bytes"),
                width=o.get("width"),
                height=o.get("height"),
                duration_sec=o.get("durationSec"),
                failure_reason=o.get("failureReason"),
                error_message=o.get("errorMessage"),
            )
        return cls(
            job_id=str(data["jobId"]),
            template_id=str(data["templateId"]),
            version=int(data["version"]),
            status=JobStatus(data["status"]),
            outputs=outputs,
            duration_sec=data.get("durationSec"),
            warnings=tuple(data.get("warnings") or ()),
            created_at=data.get("createdAt"),
            started_at=data.get("startedAt"),
            finished_at=data.get("finishedAt"),
            raw=dict(data),
        )

    @property
    def completed_ports(self) -> list[str]:
        return [p for p, o in self.outputs.items() if o.done]

    @property
    def first_failure(self) -> OutputState | None:
        return next((o for o in self.outputs.values() if o.status is JobStatus.FAILED), None)


@dataclass(frozen=True)
class Estimate:
    outputs: dict[str, dict[str, Any]]
    total_eta_sec: float
    warnings: tuple[str, ...] = ()


class RemotionRenderClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout_seconds: float = 60.0,
        http_factory: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._http_factory = http_factory
        self._sleep = sleep
        self._clock = clock

    # -- plumbing ----------------------------------------------------------------------

    def _client(self) -> Any:
        if self._http_factory is not None:
            return self._http_factory(base_url=self._base, timeout=self._timeout)
        import httpx  # lazy: only a rendering process needs it

        return httpx.Client(base_url=self._base, timeout=self._timeout)

    @staticmethod
    def _raise_for(response: Any) -> None:
        if response.status_code < 400:
            return
        try:
            body = response.json()
        except Exception:  # not JSON: keep the status, synthesize a code
            body = {}
        code = str(body.get("error") or _code_for_status(response.status_code))
        message = str(body.get("message") or response.text or "")
        raise RenderServiceError(code, response.status_code, message)

    # -- CONTRACT §4 -------------------------------------------------------------------

    def health(self) -> Mapping[str, Any]:
        with self._client() as c:
            r = c.get("/health")
            self._raise_for(r)
            return r.json()

    def templates(self) -> list[Mapping[str, Any]]:
        with self._client() as c:
            r = c.get("/templates")
            self._raise_for(r)
            return list(r.json().get("templates", []))

    def upload_asset(self, data: bytes, *, filename: str, content_type: str) -> AssetRef:
        with self._client() as c:
            r = c.post("/assets", files={"file": (filename, data, content_type)})
            self._raise_for(r)
            body = r.json()
        return AssetRef(
            asset_id=str(body["assetId"]),
            url=str(body["url"]),
            mime_type=str(body.get("mimeType") or content_type),
            bytes=int(body.get("bytes") or len(data)),
        )

    def estimate(self, *, template_id: str, version: int, props: Mapping[str, Any]) -> Estimate:
        with self._client() as c:
            r = c.post(
                "/estimate", json={"templateId": template_id, "version": version, "props": props}
            )
            self._raise_for(r)
            body = r.json()
        return Estimate(
            outputs=dict(body.get("outputs") or {}),
            total_eta_sec=float(body.get("totalEtaSec") or 0),
            warnings=tuple(body.get("warnings") or ()),
        )

    def render(
        self,
        *,
        job_id: str,
        template_id: str,
        version: int,
        props: Mapping[str, Any],
        outputs: list[str] | None = None,
    ) -> RenderJob:
        payload: dict[str, Any] = {
            "jobId": job_id,
            "templateId": template_id,
            "version": version,
            "props": props,
        }
        if outputs:
            payload["outputs"] = outputs
        with self._client() as c:
            r = c.post("/render", json=payload)
            self._raise_for(r)
            return RenderJob.from_payload(r.json())

    def job(self, job_id: str) -> RenderJob:
        with self._client() as c:
            r = c.get(f"/jobs/{job_id}")
            self._raise_for(r)
            return RenderJob.from_payload(r.json())

    def download(self, job_id: str, port: str) -> tuple[bytes, str]:
        """(bytes, mime type) of a completed output."""
        with self._client() as c:
            r = c.get(f"/jobs/{job_id}/outputs/{port}")
            self._raise_for(r)
            return r.content, str(r.headers.get("content-type", "application/octet-stream"))

    def cancel(self, job_id: str) -> RenderJob:
        with self._client() as c:
            r = c.post(f"/jobs/{job_id}/cancel")
            self._raise_for(r)
            return RenderJob.from_payload(r.json())

    # -- convenience -------------------------------------------------------------------

    def wait(
        self,
        job_id: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        interval_seconds: float = POLL_INTERVAL_SECONDS,
        on_update: Callable[[RenderJob], None] | None = None,
    ) -> RenderJob:
        """Poll until terminal (CONTRACT: "at a modest interval"). On timeout, cancels
        the job and raises `RenderServiceError('timeout', 504, …)` so nothing keeps
        burning CPU for a draft nobody waits for any more."""
        deadline = self._clock() + timeout_seconds
        last: RenderJob | None = None
        while True:
            job = self.job(job_id)
            if on_update is not None and (last is None or job.raw != last.raw):
                on_update(job)
            last = job
            if job.status.terminal:
                return job
            if self._clock() >= deadline:
                try:
                    self.cancel(job_id)
                except RenderServiceError:
                    pass
                raise RenderServiceError(
                    "timeout", 504, f"render job {job_id} not finished after {timeout_seconds:.0f}s"
                )
            self._sleep(interval_seconds)


def _code_for_status(status: int) -> str:
    return {
        404: "not_found",
        409: "not_ready",
        422: "invalid_parameters",
        504: "timeout",
    }.get(status, "internal_error")
