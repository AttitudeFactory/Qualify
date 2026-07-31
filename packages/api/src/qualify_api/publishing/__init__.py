"""Publishing to connected Instagram accounts (QUA-19, Fase 1 Parte 4-A).

Video only: reel, video story and carousel video, via the resumable byte upload to
`rupload.facebook.com` (ADR 28a). Image publishing needs a public HTTP surface and is
deferred to QUA-68 — nothing here should grow an `image_url` path.
"""

from qualify_api.publishing.client import (
    CONTAINER_POLL_CEILING_SECONDS,
    CONTAINER_POLL_INTERVAL_SECONDS,
    MEDIA_TYPE_REELS,
    MEDIA_TYPE_STORIES,
    MEDIA_TYPE_VIDEO,
    RESUMABLE_MEDIA_TYPES,
    UPLOAD_CHUNK_BYTES,
    ContainerStatus,
    HttpPublishClient,
    PublishClient,
    PublishError,
    ResumableContainer,
    UploadOutcome,
)

__all__ = [
    "CONTAINER_POLL_CEILING_SECONDS",
    "CONTAINER_POLL_INTERVAL_SECONDS",
    "MEDIA_TYPE_REELS",
    "MEDIA_TYPE_STORIES",
    "MEDIA_TYPE_VIDEO",
    "RESUMABLE_MEDIA_TYPES",
    "UPLOAD_CHUNK_BYTES",
    "ContainerStatus",
    "HttpPublishClient",
    "PublishClient",
    "PublishError",
    "ResumableContainer",
    "UploadOutcome",
]
