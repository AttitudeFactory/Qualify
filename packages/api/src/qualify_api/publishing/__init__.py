"""Publishing to connected Instagram accounts (QUA-19, Fase 1 Parte 4-A).

Reel, video story and carousel video via the resumable byte upload to
`rupload.facebook.com` (ADR 28a); single-image publish via `image_url` + the public
`/public/media/{token}` route (QUA-68); image support inside a carousel (2-10 images, or
a mix of image and video) is QUA-103's next slice, not yet built.

`stage_and_start_publish` / `advance_publish` are the **published seam for the Reflex
CRM** — direct async Python calls over ids, no HTTP hop. Same role as
`connections.start_connect` / `connections.revoke_connection`. See `composition.py`.
"""

from qualify_api.publishing.client import (
    CONTAINER_POLL_CEILING_SECONDS,
    CONTAINER_POLL_INTERVAL_SECONDS,
    IMAGE_CONTENT_TYPE,
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_REELS,
    MEDIA_TYPE_STORIES,
    MEDIA_TYPE_VIDEO,
    RESUMABLE_MEDIA_TYPES,
    ContainerStatus,
    HttpPublishClient,
    PublishClient,
    PublishError,
    ResumableContainer,
    UploadOutcome,
)
from qualify_api.publishing.composition import (
    PendingUpload,
    advance_publish,
    get_child_statuses,
    stage_and_start_many_publish,
    stage_and_start_publish,
)
from qualify_api.publishing.service import ChildStatus

__all__ = [
    "CONTAINER_POLL_CEILING_SECONDS",
    "CONTAINER_POLL_INTERVAL_SECONDS",
    "IMAGE_CONTENT_TYPE",
    "MEDIA_TYPE_IMAGE",
    "MEDIA_TYPE_REELS",
    "MEDIA_TYPE_STORIES",
    "MEDIA_TYPE_VIDEO",
    "RESUMABLE_MEDIA_TYPES",
    "ChildStatus",
    "ContainerStatus",
    "HttpPublishClient",
    "PendingUpload",
    "PublishClient",
    "PublishError",
    "ResumableContainer",
    "UploadOutcome",
    "advance_publish",
    "get_child_statuses",
    "stage_and_start_many_publish",
    "stage_and_start_publish",
]
