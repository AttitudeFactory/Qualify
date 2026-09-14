"""The Meta publishing seam (QUA-19 / ADR 28a).

Same shape as `connections/meta_oauth.py`, for the same reason: a `Protocol` the service
depends on, a real HTTP implementation, and one `_parse_*` function per endpoint marked
`[V]`. Nobody in this repo has run this flow against Meta yet, so every response shape is a
reading of the corpus rather than an observation. Confining each reading to one function
means that when reality lands, it lands in a known place and the service above does not move.

## The flow, and why the order is not arbitrary

1. `create_container` — `POST /<IG_USER_ID>/media?upload_type=resumable` returns BOTH an id
   and a `uri`. The container therefore exists **before** a single byte is uploaded, which is
   what makes the write-ahead record meaningful: there is a `creation_id` to reconcile
   against from the earliest possible moment.
2. `upload_bytes` — `POST` to that `uri` on `rupload.facebook.com`, headers `offset` and
   `file_size`, binary body streamed from R2.
3. `container_status` — `GET /<ID>?fields=status_code`, polled by the service.
4. `publish_container` — `POST /<IG_USER_ID>/media_publish?creation_id=<ID>`.

## Carousels (QUA-99) — one extra container, no extra upload

`create_carousel_container` wraps up to 10 already-created children (each made via step 1
above with `is_carousel_item=True`) into one more container whose `creation_id` is what
step 4 ultimately publishes. Confirmed against Meta real, 2026-09-10 (two `VIDEO` children,
both `is_carousel_item=true`, both reached `FINISHED` independently, then grouped): the
carousel container's response carries `{"id": ...}` **only** — never a `uri`
(`content-publishing.md:126-132`), because nothing is ever uploaded TO a carousel
container; it is built entirely from children that are already uploaded. That is why this
is a distinct method with its own return type rather than a `create_container` overload —
`ResumableContainer`/`_parse_container_response` require a `uri` unconditionally, and a
carousel response never has one. `media_publish` (step 4) does not know or care whether the
`creation_id` it receives names a single video or a carousel — this seam adds no new
publish path, only a new *shape* of `creation_id` for the existing one to accept.

## Two hosts, two clients, and no token anywhere here

Meta requires a different `Authorization` scheme per host, and the corpus contradicts itself
about which (R12) — `resumable-uploads.md` uses `Bearer` for the container on
`graph.facebook.com` (:41) but `OAuth` for `media_publish` on that same host (:137), while
`content-publishing.md` uses `Bearer` throughout (:84, :212, :272). The one invariant is that
`rupload` is never shown with `Bearer`. So the scheme is DATA, living on `MetaOAuthSettings`,
never a literal here.

This class therefore takes **two already-authenticated clients** rather than a token and a
transport. Composition builds them from `CredentialResolver.client_for(..., scheme=...)`,
which means this module never sees a credential at all — the same seam C-03 established for
workers, honoured rather than worked around. An earlier draft built its own transport; the
architect rejected it as a second door past the credential gate, and rightly: a second place
that handles a plaintext token is a second place one can reach a traceback.

## Token discipline

There is no token in this file. Error messages carry status codes, never bodies — a failed
publish response routinely echoes request parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import IO, Any, Protocol

import httpx

from qualify_api.connections.resolver import AuthenticatedClient

# Meta's own recommended cadence, pinned rather than invented: "We recommend querying a
# container's status once per minute, for no more than 5 minutes"
# (`content-publishing.md:324`). A tighter loop is not more correct — it burns the 200
# calls/hour development-mode budget against a container that is not going to be ready sooner.
CONTAINER_POLL_INTERVAL_SECONDS = 60
CONTAINER_POLL_CEILING_SECONDS = 300

# `resumable-uploads.md:32`: media_type is REELS, STORIES, or VIDEO (the last for carousel
# items). Image has NO resumable variant — QUA-68 gives it its own container method
# (`create_image_container`) instead of a fourth entry here, because the REQUEST SHAPE is
# genuinely different (`image_url`, no `upload_type`), not just a new label on the same call.
MEDIA_TYPE_REELS = "REELS"
MEDIA_TYPE_STORIES = "STORIES"
MEDIA_TYPE_VIDEO = "VIDEO"
RESUMABLE_MEDIA_TYPES = frozenset({MEDIA_TYPE_REELS, MEDIA_TYPE_STORIES, MEDIA_TYPE_VIDEO})

# QUA-68 — the single-image `media_product_type` this module's callers (staging, the
# service) use to route to `create_image_container` instead of the resumable path above.
# Deliberately NOT added to `RESUMABLE_MEDIA_TYPES`: that set's whole purpose is "media
# types `create_container` accepts", and image never goes through `create_container`.
MEDIA_TYPE_IMAGE = "IMAGE"

# `ig-user/media.md:55` — feed/story images are capped at 8 MB, a full order of magnitude
# under the 300 MB video ceiling (`ObjectGate.MAX_MEDIA_BYTES`). Lives here, not in
# `gate.py`, because it is a Meta-imposed limit on what THIS client can publish, not a
# property of the object store — the same reasoning that keeps the 300 MB video ceiling in
# `gate.py` (where it belongs, being the store's own absolute ceiling) separate from this
# tighter, format-specific one.
IMAGE_MAX_BYTES = 8 * 1024 * 1024


class PublishError(Exception):
    """A publishing call failed. Never carries the token or the response body.

    `platform_code`/`platform_subcode` are Meta's NUMERIC error identifiers when the
    failed response carried them — codes, not messages, so nothing credential-bearing can
    ride along. They are what lets the service map a specific refusal (e.g. a Page
    Publishing Authorization gate) to a distinguishable outcome instead of a generic
    `failed` that costs hours chasing a bug that does not exist.

    `http_status` (QUA-90) is the raw HTTP status of the failed response — captured
    alongside the platform code, not instead of it, because Meta's auth rejection
    (`error.code=190`) is not guaranteed to always ride a 401: the ticket's detection
    condition is HTTP 401 **or** code 190, and only having the numeric code on this
    exception cannot express the "or".
    """

    def __init__(
        self,
        message: str,
        *,
        platform_code: int | None = None,
        platform_subcode: int | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.platform_code = platform_code
        self.platform_subcode = platform_subcode
        self.http_status = http_status


class ContainerStatus(StrEnum):
    """The five values `GET /<IG_CONTAINER_ID>?fields=status_code` can return
    (`content-publishing.md:318-322`). Modelled as five states, not a ready/not-ready
    boolean: `ERROR` and `EXPIRED` are terminal failures that must never be retried into,
    and `PUBLISHED` is how reconciliation discovers that a publish we were unsure about
    actually succeeded."""

    EXPIRED = "EXPIRED"
    ERROR = "ERROR"
    FINISHED = "FINISHED"
    IN_PROGRESS = "IN_PROGRESS"
    PUBLISHED = "PUBLISHED"

    @property
    def is_terminal(self) -> bool:
        return self in {ContainerStatus.EXPIRED, ContainerStatus.ERROR, ContainerStatus.PUBLISHED}


@dataclass(frozen=True)
class ResumableContainer:
    """The container plus the upload URI Meta hands back.

    The `uri` is used VERBATIM rather than reconstructed from a template. The corpus shows it
    carrying an API version (`rupload.facebook.com/ig-api-upload/<API_VERSION>/<ID>`), and a
    client that rebuilds the URL is a client that pins a version Meta chose for it.
    """

    container_id: str
    upload_uri: str


@dataclass(frozen=True)
class UploadOutcome:
    """The result of the byte upload.

    `retriable` is Meta's OWN judgement, from `debug_info.retriable`
    (`content-publishing.md:187-194`). It is the reason ADR 22(e)'s ban on blind retries is
    implementable at all: a generic timeout cannot distinguish "the network blinked" from
    "this media will never be accepted", and retrying the second forever is how a queue
    fills with poison.

    `None` means Meta expressed no opinion — which is NOT the same as `False`, and the
    service must treat the absence as unknown rather than as a refusal (R10).
    """

    success: bool
    retriable: bool | None = None
    error_type: str | None = None


class PublishClient(Protocol):
    async def create_container(
        self,
        *,
        ig_user_id: str,
        media_type: str,
        caption: str | None = None,
        thumb_offset: int | None = None,
        is_carousel_item: bool = False,
    ) -> ResumableContainer: ...

    async def create_carousel_container(
        self,
        *,
        ig_user_id: str,
        children: list[str],
        caption: str | None = None,
    ) -> str: ...

    async def create_image_container(
        self,
        *,
        ig_user_id: str,
        image_url: str,
        caption: str | None = None,
    ) -> str: ...

    async def upload_bytes(
        self, *, upload_uri: str, fileobj: IO[bytes], file_size: int
    ) -> UploadOutcome: ...

    async def container_status(self, *, container_id: str) -> ContainerStatus: ...

    async def publish_container(self, *, ig_user_id: str, creation_id: str) -> str: ...


# --- [V] response parsing. One function per endpoint; the only place reality lands. ---


def _error_codes(response: httpx.Response) -> tuple[int | None, int | None]:
    """Meta's numeric `error.code`/`error.error_subcode` from a failed response, or Nones.

    Integers only, extracted defensively: everything else in an error body (message,
    fbtrace_id, nested JSON) stays where it is. A number cannot leak a credential."""
    try:
        error = dict(response.json()).get("error")
    except ValueError:
        return None, None
    if not isinstance(error, dict):
        return None, None
    code = error.get("code")
    subcode = error.get("error_subcode")
    return (
        code if isinstance(code, int) else None,
        subcode if isinstance(subcode, int) else None,
    )


def _parse_container_response(payload: dict[str, Any]) -> ResumableContainer:
    """[V] `resumable-uploads.md:58-65`: {"id": ..., "uri": ...}.

    Both are required. A response with an id but no uri would leave the caller with a
    container it cannot upload to, and guessing the uri is exactly the version-pinning
    mistake described on `ResumableContainer`.
    """
    container_id = payload.get("id")
    upload_uri = payload.get("uri")
    if not isinstance(container_id, str) or not container_id:
        raise PublishError("container response carried no id")
    if not isinstance(upload_uri, str) or not upload_uri:
        raise PublishError("container response carried no upload uri")
    return ResumableContainer(container_id=container_id, upload_uri=upload_uri)


def _parse_carousel_response(payload: dict[str, Any]) -> str:
    """[V] confirmed against Meta real 2026-09-10: `{"id": "<IG_CAROUSEL_CONTAINER_ID>"}`
    only (`content-publishing.md:126-132`). Deliberately NOT `_parse_container_response`:
    that function requires a `uri` unconditionally, and a carousel container never has
    one — there is nothing to upload to it, it is built entirely from children that are
    already uploaded.
    """
    container_id = payload.get("id")
    if not isinstance(container_id, str) or not container_id:
        raise PublishError("carousel container response carried no id")
    return container_id


def _parse_image_container_response(payload: dict[str, Any]) -> str:
    """[V] `ig-user/media.md:131-144` (Image Containers): `{"id": "..."}` only — same shape
    as `_parse_carousel_response`, and for the identical reason: nothing is ever uploaded TO
    this container (no `upload_type=resumable`, no `uri` in the response), because Meta
    fetches `image_url` itself. Kept as its OWN function rather than reused, matching this
    module's own convention of one `_parse_*` per endpoint — an image container and a
    carousel container happening to share a response shape today is not a guarantee they
    always will.
    """
    container_id = payload.get("id")
    if not isinstance(container_id, str) or not container_id:
        raise PublishError("image container response carried no id")
    return container_id


def _parse_upload_response(payload: dict[str, Any]) -> UploadOutcome:
    """[V] `resumable-uploads.md:108-124`. Success: {"success": true, "message": ...}.
    Failure: {"debug_info": {"retriable": bool, "type": str, "message": str}}.

    `debug_info.message` is deliberately NOT surfaced: the corpus sample shows it embedding a
    nested JSON error string, and error text from an auth-bearing call is exactly what should
    not reach a log.
    """
    debug_info = payload.get("debug_info")
    if isinstance(debug_info, dict):
        retriable = debug_info.get("retriable")
        error_type = debug_info.get("type")
        return UploadOutcome(
            success=False,
            retriable=retriable if isinstance(retriable, bool) else None,
            error_type=str(error_type) if isinstance(error_type, str) else None,
        )
    if payload.get("success") is True:
        return UploadOutcome(success=True)
    # Neither shape matched. Reported as a failure with retriable=None (unknown) rather than
    # as retriable=False: an unrecognised response is not evidence that retrying is wrong.
    return UploadOutcome(success=False, retriable=None, error_type="unrecognised_response")


def _parse_status_response(payload: dict[str, Any]) -> ContainerStatus:
    """[V] `ig-container` reading: {"status_code": "...", "id": "..."}."""
    raw = payload.get("status_code")
    if not isinstance(raw, str):
        raise PublishError("status response carried no status_code")
    try:
        return ContainerStatus(raw)
    except ValueError as exc:
        # An unknown status is NOT coerced to a known one. Meta adding a sixth value must
        # surface as a loud failure, not be silently read as IN_PROGRESS (which would make
        # the poller wait out its ceiling) or as ERROR (which would abandon a live publish).
        raise PublishError(f"unknown container status_code: {raw!r}") from exc


def _parse_publish_response(payload: dict[str, Any]) -> str:
    """[V] `media_publish` returns the published media id: {"id": "..."}.

    Its ABSENCE is the documented ambiguous case that reconciliation exists for
    (`content-publishing.md:316`: "If ... the media_publish endpoint does not return the
    published media ID, you can get the container's publishing status"). Raising here is
    correct — the service catches it and reconciles by `creation_id` instead of retrying.
    """
    media_id = payload.get("id")
    if not isinstance(media_id, str) or not media_id:
        raise PublishError("publish response carried no media id")
    return media_id


# Timeouts, measured rather than defaulted (live smoke, 2026-08-07): httpx's 5 s defaults
# fail BOTH heavy calls — a 9 MB upload dies on write, and `media_publish` takes longer
# than 5 s to answer (and, measured the same day, may have SUCCEEDED by the time the
# timeout fires — the exact ambiguity A6-min exists for).
UPLOAD_TIMEOUT = httpx.Timeout(600.0, connect=30.0)
GRAPH_WRITE_TIMEOUT = httpx.Timeout(60.0, connect=30.0)


class HttpPublishClient:
    """Real client over two already-authenticated clients — one per host.

    Takes `AuthenticatedClient`s rather than a token: the credential is injected by
    `CredentialResolver.client_for(..., scheme=...)` upstream, so nothing here can reach a
    plaintext token. Two clients because the two hosts need different `Authorization`
    schemes (R12), and which scheme that is comes from `MetaOAuthSettings`, not from here.
    """

    def __init__(
        self,
        *,
        graph_client: AuthenticatedClient,
        rupload_client: AuthenticatedClient,
        graph_url: str,
    ) -> None:
        self._graph = graph_client
        self._rupload = rupload_client
        self._graph_url = graph_url.rstrip("/")

    async def _post_graph(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        response = await self._graph.post(
            f"{self._graph_url}{path}", params=params, timeout=GRAPH_WRITE_TIMEOUT
        )
        if response.status_code != 200:
            # Status and NUMERIC platform codes only. A failed publish body routinely
            # echoes the request parameters, so the message/body never travels.
            code, subcode = _error_codes(response)
            raise PublishError(
                f"POST {path} failed with HTTP {response.status_code}",
                platform_code=code,
                platform_subcode=subcode,
                http_status=response.status_code,
            )
        return dict(response.json())

    async def create_container(
        self,
        *,
        ig_user_id: str,
        media_type: str,
        caption: str | None = None,
        thumb_offset: int | None = None,
        is_carousel_item: bool = False,
    ) -> ResumableContainer:
        if media_type not in RESUMABLE_MEDIA_TYPES:
            # Guarding here rather than at the platform: image has no resumable variant at
            # all, so an IMAGE media_type is a scope error (QUA-68), not a bad request.
            raise PublishError(
                f"media_type {media_type!r} has no resumable upload path; "
                f"expected one of {sorted(RESUMABLE_MEDIA_TYPES)}"
            )
        params = {"upload_type": "resumable", "media_type": media_type}
        if caption is not None:
            params["caption"] = caption
        if thumb_offset is not None:
            # `thumb_offset` picks a frame of the video itself. `cover_url` is deliberately
            # unreachable from this client: it stays a URL parameter even in the resumable
            # variant (`resumable-uploads.md:53`) and would reintroduce the public hosting
            # this whole scope exists to avoid (ADR 28).
            params["thumb_offset"] = str(thumb_offset)
        if is_carousel_item:
            params["is_carousel_item"] = "true"
        return _parse_container_response(await self._post_graph(f"/{ig_user_id}/media", params))

    async def create_carousel_container(
        self,
        *,
        ig_user_id: str,
        children: list[str],
        caption: str | None = None,
    ) -> str:
        """`POST /<IG_ID>/media?media_type=CAROUSEL&children=<id1,id2,...>`.

        No `upload_type`/`is_carousel_item` here — those belong to the CHILD containers
        (already created via `create_container(..., is_carousel_item=True)`), never to
        the carousel container itself. Cardinality (Meta allows 2-10) is NOT enforced
        here — same division of labour as `media_type` in `create_container`: this
        method rejects only what makes the REQUEST structurally impossible to send (an
        empty `children` list), and leaves count policy to the caller, which does not
        exist yet (QUA-99 backend orchestration, a later PR).
        """
        if not children:
            raise PublishError("a carousel container needs at least one child container id")
        params = {"media_type": "CAROUSEL", "children": ",".join(children)}
        if caption is not None:
            params["caption"] = caption
        return _parse_carousel_response(await self._post_graph(f"/{ig_user_id}/media", params))

    async def create_image_container(
        self,
        *,
        ig_user_id: str,
        image_url: str,
        caption: str | None = None,
    ) -> str:
        """`POST /<IG_USER_ID>/media?image_url=<URL>` — QUA-68's whole reason to exist as a
        SEPARATE method rather than an overload of `create_container`: no `upload_type`, no
        `media_type`, no `thumb_offset`, no `is_carousel_item` (that parameter is deferred to
        QUA-103, the carousel-of-images ticket — this method covers a single, standalone
        image post only). Meta fetches `image_url` itself; nothing is ever uploaded to this
        container, which is also why there is no matching `upload_bytes` call anywhere in
        this image's publish path.
        """
        params = {"image_url": image_url}
        if caption is not None:
            params["caption"] = caption
        return _parse_image_container_response(
            await self._post_graph(f"/{ig_user_id}/media", params)
        )

    async def upload_bytes(
        self, *, upload_uri: str, fileobj: IO[bytes], file_size: int
    ) -> UploadOutcome:
        """Send the body to `rupload` SIZED, not chunked. Measured 2026-08-07: a chunked
        body (Transfer-Encoding, no Content-Length) is refused with a non-retriable
        `ParameterValidationError`; the identical sized body succeeds. So the earlier
        streaming adapter is gone — its memory argument lost to a measured rejection, and
        the buffer is bounded by the gate's `MAX_MEDIA_BYTES` ceiling. A stream that
        preserves Content-Length is Sprint 4 work if concurrency ever demands it.

        `offset` is 0 because this client does not resume a partial upload — a fresh
        attempt starts a fresh container, which the write-ahead record makes safe."""
        response = await self._rupload.post(
            upload_uri,
            # Per-request headers MERGE with the client's default `Authorization` in httpx;
            # they do not replace it. Asserted by a test, because if that ever changed the
            # upload would go out unauthenticated and the failure would look like a Meta
            # problem.
            headers={"offset": "0", "file_size": str(file_size)},
            content=fileobj.read(),
            timeout=UPLOAD_TIMEOUT,
        )
        try:
            payload = dict(response.json())
        except ValueError:
            # A non-JSON body on a transport error says nothing about whether a retry would
            # help, so the outcome is unknown rather than assumed non-retriable.
            return UploadOutcome(
                success=False, retriable=None, error_type=f"http_{response.status_code}"
            )
        return _parse_upload_response(payload)

    async def container_status(self, *, container_id: str) -> ContainerStatus:
        response = await self._graph.get(
            f"{self._graph_url}/{container_id}", params={"fields": "status_code"}
        )
        if response.status_code != 200:
            # QUA-90: bring this in line with `_post_graph` — a poll can 401/190 exactly
            # as the initial calls can, and `advance()` needs the code to notice.
            code, subcode = _error_codes(response)
            raise PublishError(
                f"status check failed with HTTP {response.status_code}",
                platform_code=code,
                platform_subcode=subcode,
                http_status=response.status_code,
            )
        return _parse_status_response(dict(response.json()))

    async def publish_container(self, *, ig_user_id: str, creation_id: str) -> str:
        return _parse_publish_response(
            await self._post_graph(f"/{ig_user_id}/media_publish", {"creation_id": creation_id})
        )
