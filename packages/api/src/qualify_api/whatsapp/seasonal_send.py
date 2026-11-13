"""Send a seasonal sticker or short video from a WhatsApp chat (m-24976894).

Library: `whatsapp.seasonal` (m-24976891). UX: `docs/ux-stickers-videos.md` §3.
Assisted, never autonomous: the owner picks an APPROVED medium of an unarchived season
and presses «Enviar»; the send is queued through `ChatService.send_prepared`, the same
path as a typed reply — the acting-member check, the 24 h window (`WindowClosed`,
nothing written), the takeover and the request-key idempotency are the chat's own.

## What is queued

A `reply` outbox row whose body is a `sticker` (`{}`: no caption, ever) or a `video`
(optional caption ≤ 1024, refused — not cut — when longer), WITHOUT a media reference,
plus `attachment`:

    {"kind": "seasonal_media", "seasonal_media_id": "<uuid>", "attempt": 1,
     "object_key": "seasonal/{tenant}/{brand}/{season}/{id}-{attempt}.{webp|mp4}",
     "brand_id": "<uuid>", "media_kind": "sticker" | "video", "season_key": "…",
     "recipe": "…", "content_type": "image/webp" | "video/mp4", "filename": "…",
     "bytes": 12345, "media_id": null, "pipeline": "wa-seasonal-1",
     "library_pipeline": "seasonal-v1"}

`media_id` is Meta's id once uploaded (`outbox.record_media_id` writes it), so the
library's id travels as `seasonal_media_id`. No R2 copy is made: the library file lives
outside the purge (ADR 39 amendment) and is read in place, through the business-bound
`ObjectGate.open_seasonal_media`.

## At send time (`outbox.OutboxSender` + `SeasonalSendGuard`)

Before anything is uploaded or sent, the sender re-reads the library row (as `qualify_app`
under `tenant_session`, the outbox worker's door — no webhook-worker grant is involved):

- the key is under `seasonal/{tenant}/{brand}/`, the row is that business's, and the key
  and `attempt` are the row's CURRENT ones (a «Pedir otro» meanwhile) — else
  `attachment_refused`;
- the row is still `approved` and its season not archived — else `seasonal_withdrawn`.

Both are terminal (`failed`), shown in the chat as unsent. One upload per row: the
sender records Meta's media id before the send, so a retry never uploads again (there
is no cross-row media-id cache in the module; each send uploads once).

## The transcript

The outbound message's `media_kind` is the body type (`sticker` / `video`); its text is
«Sticker» for a sticker, the caption (or «Video») for a video — never an empty bubble.

## The file at send time

The sender reads at most one byte past the limit and checks the bytes themselves
(`check_file`) before the upload: a sticker is a RIFF/WEBP whose size — read from its
`VP8X`, `VP8 ` or `VP8L` header — is 512×512, ≤ 500 KB when animated and ≤ 100 KB
when static; a video is ≤ 16 MB and opens with its `ftyp` box. A file that fails is
`failed` with `sticker_too_large`, `not_sticker_size`, `not_a_sticker`,
`video_too_large` or `not_a_video` — never retried.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from qualify_shared.objects.keys import seasonal_brand_prefix

from qualify_api.whatsapp.chats import ChatService, PreparedSend, ThreadRef
from qualify_api.whatsapp.client import (
    MAX_MEDIA_CAPTION_CHARS,
    build_media_body,
    build_sticker_body,
)
from qualify_api.whatsapp.outbox import (
    ATTACHMENT_KIND_SEASONAL,
    ERROR_ATTACHMENT_REFUSED,
    ERROR_SEASONAL_WITHDRAWN,
)
from qualify_api.whatsapp.seasonal import (
    EXTENSIONS,
    KIND_STICKER,
    KIND_VIDEO,
    STATUS_APPROVED,
    STATUS_DELETED,
    ObjectKeyRefused,
    SeasonalMedia,
    SeasonalMediaService,
    SeasonalRepository,
    check_object_key,
)

logger = logging.getLogger("qualify_api.whatsapp.seasonal_send")

#: Provenance stamp of the outbox attachment this module writes.
SEASONAL_SEND_PIPELINE: Final = "wa-seasonal-1"
#: Meta's sticker limit (animated WebP 500 KB; a static one 100 KB) and video limit
#: (16 MB), reference/media «Supported media types», read 2026-11-08 — not yet measured.
MAX_STICKER_BYTES: Final = 500 * 1024  # animated
MAX_STATIC_STICKER_BYTES: Final = 100 * 1024
STICKER_SIDE: Final = 512
MAX_VIDEO_BYTES: Final = 16 * 1024 * 1024
#: Recipe E (the free stickers, `seasonal.STANDARD_BATCH`) always renders an ANIMATED
#: WebP; a sticker of any other recipe is held to the static limit.
ANIMATED_STICKER_RECIPE_PREFIX: Final = "e-"
#: m-25017372: the animated product sticker (its still twin is `k-quieto`, ≤ 100 KB).
ANIMATED_PRODUCT_STICKER_RECIPE: Final = "k-animado"
MAX_CAPTION_CHARS: Final = MAX_MEDIA_CAPTION_CHARS
#: The transcript's text of a sent sticker, and of a video without caption: never an
#: empty bubble.
STICKER_SENT_TEXT: Final = "Sticker"
VIDEO_SENT_TEXT: Final = "Video"
CONTENT_TYPES: Final[dict[str, str]] = {KIND_STICKER: "image/webp", KIND_VIDEO: "video/mp4"}

#: What the owner reads for each refusal (qualify-copy-es).
REFUSAL_TEXT: Final[dict[str, str]] = {
    "not_found": "Ese sticker o video ya no está en tu biblioteca.",
    "not_approved": "Ese sticker o video todavía no está aprobado.",
    "archived": "Esa temporada está archivada. Recupérala para enviar sus stickers y videos.",
    "no_brand": "Este número no tiene una marca con stickers y videos.",
    "no_file": "Ese sticker o video todavía se está preparando.",
    "too_large": "Este archivo es muy pesado para WhatsApp. Pide otro.",
    "not_sticker_size": "Este sticker no tiene el tamaño que pide WhatsApp. Pide otro.",
    "sticker_caption": "Los stickers se envían sin texto.",
    "caption_too_long": f"El texto del video puede tener hasta {MAX_CAPTION_CHARS} caracteres.",
}


class SeasonalSendRefused(ValueError):
    """The send cannot be built; nothing was written. `reason` is a key of
    `REFUSAL_TEXT`; `message` is its Spanish text."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.message = REFUSAL_TEXT.get(reason, "No pudimos preparar el envío.")


@dataclass(frozen=True)
class SeasonalPreview:
    """What the review step shows before «Enviar»."""

    media_id: UUID
    kind: str  # "sticker" | "video"
    season_key: str
    season_label: str
    bytes: int
    weight_label: str  # «85 KB», «2,3 MB»
    width: int | None
    height: int | None
    duration_ms: int | None
    object_key: str  # read it with `ObjectGate.open_seasonal_media(tenant, brand, key)`
    caption_allowed: bool
    max_caption_chars: int


def weight_label(size: int) -> str:
    """Spanish weight: «85 KB», «2,3 MB» (decimal comma)."""
    if size < 1024 * 1024:
        return f"{max(1, round(size / 1024))} KB"
    return f"{size / (1024 * 1024):.1f} MB".replace(".", ",")


def _sendable(media: SeasonalMedia | None, brand_id: UUID) -> SeasonalMedia:
    """The owner-side checks (the sender repeats the state ones at send time)."""
    if media is None or media.brand_id != brand_id:
        raise SeasonalSendRefused("not_found")
    if media.archived_at is not None:
        raise SeasonalSendRefused("archived")
    if media.status != STATUS_APPROVED:
        raise SeasonalSendRefused("not_approved")
    if not media.object_key or not media.bytes:
        raise SeasonalSendRefused("no_file")
    try:
        check_object_key(media, media.object_key)
    except ObjectKeyRefused as exc:
        raise SeasonalSendRefused("no_file") from exc
    if media.kind == KIND_STICKER:
        if media.width != STICKER_SIDE or media.height != STICKER_SIDE:
            raise SeasonalSendRefused("not_sticker_size")
        animated = (
            media.recipe.startswith(ANIMATED_STICKER_RECIPE_PREFIX)
            or media.recipe == ANIMATED_PRODUCT_STICKER_RECIPE
        )
        limit = MAX_STICKER_BYTES if animated else MAX_STATIC_STICKER_BYTES
    else:
        limit = MAX_VIDEO_BYTES
    if media.bytes > limit:
        raise SeasonalSendRefused("too_large")
    return media


def _caption(media: SeasonalMedia, caption: str | None) -> str | None:
    text = (caption or "").strip()
    if media.kind == KIND_STICKER:
        if text:
            raise SeasonalSendRefused("sticker_caption")
        return None
    if len(text) > MAX_CAPTION_CHARS:
        raise SeasonalSendRefused("caption_too_long")
    return text or None


class SeasonalSendService:
    """The chat's seasonal picker, preview and send. `number_brand(tenant, connection)`
    is the number's business (`AttachmentReads.number_brand`)."""

    def __init__(
        self,
        chats: ChatService,
        library: SeasonalMediaService,
        repo: SeasonalRepository,
        number_brand: Callable[[UUID, UUID], UUID | None],
    ) -> None:
        self._chats = chats
        self._library = library
        self._repo = repo
        self._number_brand = number_brand

    def _brand(self, tenant_id: UUID, connection_id: UUID) -> UUID:
        brand = self._number_brand(tenant_id, connection_id)
        if brand is None:
            raise SeasonalSendRefused("no_brand")
        return brand

    def list_for_chat(self, tenant_id: UUID, connection_id: UUID) -> list[SeasonalMedia]:
        """Approved media of unarchived seasons, current season first, stickers first
        (`SeasonalMediaService.list_approved_for_chat`); `[]` for a number without a
        business."""
        brand = self._number_brand(tenant_id, connection_id)
        if brand is None:
            return []
        return self._library.list_approved_for_chat(tenant_id, brand)

    def preview(self, tenant_id: UUID, connection_id: UUID, media_id: UUID) -> SeasonalPreview:
        brand = self._brand(tenant_id, connection_id)
        media = _sendable(self._repo.get(tenant_id=tenant_id, media_id=media_id), brand)
        assert media.object_key is not None and media.bytes is not None
        return SeasonalPreview(
            media_id=media.id,
            kind=media.kind,
            season_key=media.season_key,
            season_label=media.season_label,
            bytes=media.bytes,
            weight_label=weight_label(media.bytes),
            width=media.width,
            height=media.height,
            duration_ms=media.duration_ms,
            object_key=media.object_key,
            caption_allowed=media.kind == KIND_VIDEO,
            max_caption_chars=MAX_CAPTION_CHARS if media.kind == KIND_VIDEO else 0,
        )

    def send(
        self,
        tenant_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        media_id: UUID,
        caption: str | None = None,
        *,
        request_key: str | None = None,
    ) -> UUID:
        """Queue the owner's send; returns the outbox id (the same one on a replayed
        `request_key`). Refusals: `SeasonalSendRefused`, `chats.WindowClosed`."""

        def prepare(thread: ThreadRef) -> PreparedSend:
            brand = self._brand(tenant_id, thread.connection_id)
            media = _sendable(self._repo.get(tenant_id=tenant_id, media_id=media_id), brand)
            text = _caption(media, caption)
            if media.kind == KIND_STICKER:
                body = build_sticker_body(thread.wa_id, None)
            else:
                body = build_media_body(
                    thread.wa_id,
                    "video",
                    media_id="pending-upload",
                    link=None,
                    caption=text,
                    filename=None,
                )
                del body["video"]["id"]  # the sender fills it after `upload_media`
            content_type = CONTENT_TYPES[media.kind]
            return PreparedSend(
                payload=body,
                attachment={
                    "kind": ATTACHMENT_KIND_SEASONAL,
                    "seasonal_media_id": str(media.id),
                    "attempt": media.attempt,
                    "object_key": media.object_key,
                    "brand_id": str(brand),
                    "media_kind": media.kind,
                    "season_key": media.season_key,
                    "recipe": media.recipe,
                    "content_type": content_type,
                    "filename": f"{media.kind}.{EXTENSIONS[media.kind]}",
                    "bytes": media.bytes,
                    "media_id": None,
                    "pipeline": SEASONAL_SEND_PIPELINE,
                    "library_pipeline": media.pipeline_version,
                },
                preview_text=(
                    STICKER_SENT_TEXT if media.kind == KIND_STICKER else text or VIDEO_SENT_TEXT
                ),
                request_key=request_key,
            )

        return self._chats.send_prepared(
            tenant_id, thread_id, user_id, prepare, request_key=request_key
        )


# ======================================================================================
# The sender's guard (outbox.SeasonalSendGuardLike)
# ======================================================================================


def send_time_refusal(
    tenant_id: UUID, attachment: dict[str, Any], media: SeasonalMedia | None
) -> str | None:
    """`None` when the queued medium may still go; else the outbox error code."""
    key = str(attachment.get("object_key") or "")
    try:
        brand = UUID(str(attachment.get("brand_id") or ""))
        attempt = int(attachment.get("attempt") or 0)
    except (ValueError, TypeError):
        return ERROR_ATTACHMENT_REFUSED
    if not key.startswith(seasonal_brand_prefix(tenant_id, brand)):
        return ERROR_ATTACHMENT_REFUSED
    if media is None or media.tenant_id != tenant_id or media.brand_id != brand:
        return ERROR_ATTACHMENT_REFUSED
    if media.status == STATUS_DELETED:
        return ERROR_SEASONAL_WITHDRAWN  # «Eliminar» meanwhile (m-25016851)
    if attempt != media.attempt or key != media.object_key:
        return ERROR_ATTACHMENT_REFUSED  # «Pedir otro» meanwhile: a stale file
    if media.status != STATUS_APPROVED or media.archived_at is not None:
        return ERROR_SEASONAL_WITHDRAWN
    return None


#: The outbox error codes of a file refused at send time (`SeasonalFileRefused`).
FILE_REFUSAL_NOT_A_STICKER: Final = "not_a_sticker"
FILE_REFUSAL_NOT_STICKER_SIZE: Final = "not_sticker_size"
FILE_REFUSAL_STICKER_TOO_LARGE: Final = "sticker_too_large"
FILE_REFUSAL_VIDEO_TOO_LARGE: Final = "video_too_large"
FILE_REFUSAL_NOT_A_VIDEO: Final = "not_a_video"
FILE_REFUSAL_CODES: Final = frozenset(
    {
        FILE_REFUSAL_NOT_A_STICKER,
        FILE_REFUSAL_NOT_STICKER_SIZE,
        FILE_REFUSAL_STICKER_TOO_LARGE,
        FILE_REFUSAL_VIDEO_TOO_LARGE,
        FILE_REFUSAL_NOT_A_VIDEO,
    }
)


class SeasonalFileRefused(ValueError):
    """The file read at send time is not what WhatsApp takes: the row fails with
    `outbox_error_code` (terminal, shown unsent), never retried."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.outbox_error_code = code


def webp_canvas(content: bytes) -> tuple[bool, int, int] | None:
    """(animated, width, height) from the first chunk of a WebP — a cheap read of its
    first 30 bytes: `VP8X` (extended: canvas + animation flag), `VP8 ` (simple lossy:
    the key frame's size) or `VP8L` (simple lossless: the bit-packed size). A simple
    WebP is never animated. None when the header cannot be read."""
    if len(content) < 30:
        return None
    chunk = content[12:16]
    if chunk == b"VP8X":
        animated = bool(content[20] & 0x02)
        width = 1 + int.from_bytes(content[24:27], "little")
        height = 1 + int.from_bytes(content[27:30], "little")
        return animated, width, height
    if chunk == b"VP8 ":
        if content[23:26] != b"\x9d\x01\x2a":  # the key frame's start code
            return None
        width = int.from_bytes(content[26:28], "little") & 0x3FFF
        height = int.from_bytes(content[28:30], "little") & 0x3FFF
        return False, width, height
    if chunk == b"VP8L":
        if content[20] != 0x2F:  # the lossless signature
            return None
        bits = int.from_bytes(content[21:25], "little")
        return False, (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def check_file(kind: str, content: bytes) -> None:
    """Meta's limits on the bytes actually read, before the upload."""
    if kind == KIND_STICKER:
        if content[:4] != b"RIFF" or content[8:12] != b"WEBP":
            raise SeasonalFileRefused(FILE_REFUSAL_NOT_A_STICKER)
        canvas = webp_canvas(content)
        if canvas is None:
            raise SeasonalFileRefused(FILE_REFUSAL_NOT_A_STICKER)
        animated = canvas[0]
        if canvas[1:] != (STICKER_SIDE, STICKER_SIDE):
            raise SeasonalFileRefused(FILE_REFUSAL_NOT_STICKER_SIZE)
        limit = MAX_STICKER_BYTES if animated else MAX_STATIC_STICKER_BYTES
        if len(content) > limit:
            raise SeasonalFileRefused(FILE_REFUSAL_STICKER_TOO_LARGE)
        return
    if len(content) > MAX_VIDEO_BYTES:
        raise SeasonalFileRefused(FILE_REFUSAL_VIDEO_TOO_LARGE)
    if content[4:8] != b"ftyp":  # every MP4 opens with its `ftyp` box
        raise SeasonalFileRefused(FILE_REFUSAL_NOT_A_VIDEO)


class SeasonalSendGuard:
    """Re-checks a queued seasonal send against the library row, and reads its file
    bounded to the business (`ObjectGate.open_seasonal_media` in production)."""

    def __init__(
        self,
        get_media: Callable[[UUID, UUID], SeasonalMedia | None],
        open_file: Callable[[UUID, UUID, str, int], bytes],
    ) -> None:
        self._get = get_media
        self._open = open_file

    def refusal(self, tenant_id: UUID, attachment: dict[str, Any]) -> str | None:
        try:
            media_id = UUID(str(attachment.get("seasonal_media_id") or ""))
        except ValueError:
            return ERROR_ATTACHMENT_REFUSED
        return send_time_refusal(tenant_id, attachment, self._get(tenant_id, media_id))

    def read(self, tenant_id: UUID, attachment: dict[str, Any]) -> bytes:
        """The file, at most one byte past its kind's limit, checked (`check_file`):
        `SeasonalFileRefused` when WhatsApp would not take it."""
        brand = UUID(str(attachment["brand_id"]))
        kind = str(attachment.get("media_kind") or "")
        limit = (MAX_STICKER_BYTES if kind == KIND_STICKER else MAX_VIDEO_BYTES) + 1
        content = self._open(tenant_id, brand, str(attachment["object_key"]), limit)
        check_file(kind, content)
        return content


def production_seasonal_send_guard() -> SeasonalSendGuard:
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    from qualify_api.whatsapp.seasonal import PostgresSeasonalRepository  # noqa: PLC0415

    repo = PostgresSeasonalRepository()
    gate: list[ObjectGate] = []

    def open_file(tenant_id: UUID, brand_id: UUID, key: str, limit: int) -> bytes:
        if not gate:
            gate.append(ObjectGate(R2ObjectStore(R2Settings.from_env())))
        stream = gate[0].open_seasonal_media(tenant_id, brand_id, key)
        try:
            return stream.read(limit)
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()

    return SeasonalSendGuard(
        lambda tenant_id, media_id: repo.get(tenant_id=tenant_id, media_id=media_id),
        open_file,
    )


def production_seasonal_send_service(chats: ChatService) -> SeasonalSendService:
    from qualify_api.whatsapp.attachments import PostgresAttachmentReads  # noqa: PLC0415
    from qualify_api.whatsapp.seasonal import (  # noqa: PLC0415
        PostgresSeasonalRepository,
        production_seasonal_service,
    )

    reads = PostgresAttachmentReads()
    return SeasonalSendService(
        chats,
        production_seasonal_service(),
        PostgresSeasonalRepository(),
        reads.number_brand,
    )


__all__: Sequence[str] = [
    "FILE_REFUSAL_CODES",
    "FILE_REFUSAL_NOT_A_STICKER",
    "FILE_REFUSAL_NOT_A_VIDEO",
    "FILE_REFUSAL_NOT_STICKER_SIZE",
    "FILE_REFUSAL_STICKER_TOO_LARGE",
    "FILE_REFUSAL_VIDEO_TOO_LARGE",
    "MAX_CAPTION_CHARS",
    "MAX_STICKER_BYTES",
    "REFUSAL_TEXT",
    "SEASONAL_SEND_PIPELINE",
    "STICKER_SENT_TEXT",
    "SeasonalPreview",
    "SeasonalFileRefused",
    "SeasonalSendGuard",
    "VIDEO_SENT_TEXT",
    "check_file",
    "webp_canvas",
    "SeasonalSendRefused",
    "SeasonalSendService",
    "production_seasonal_send_guard",
    "production_seasonal_send_service",
    "send_time_refusal",
    "weight_label",
]
