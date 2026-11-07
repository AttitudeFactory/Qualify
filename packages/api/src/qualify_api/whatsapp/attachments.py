"""«Foto o menú» from a WhatsApp chat (m-24945888): send a product with its price, a piece
from the generator, the interactive menu list or a photo from the phone — never a link.

Spec: `docs/ux-whatsapp-enviar-imagen.md` (PR 1: products, pieces, menu, phone photo).
Assisted, never autonomous: every send here is the owner's «Enviar», queued through
`ChatService.send_prepared` — the same path as a typed reply, so the 24 h window
(`WindowClosed`, nothing written), the takeover (the menu automation pauses) and the
acting-member check are the chat's own, not re-implemented.

## Where the bytes go, and where the upload happens

1. **At «Enviar» (this module, request path):** the image is read from where it lives —
   a catalog photo in R2 (`t/{tenant}/uploads/catalog/…` since CM-9; an older one on the
   local upload store, or in R2 through the key map once copied), a
   piece in R2 (`t/{tenant}/generated/{draft}/…`) or the local store (pre-2026-10-06),
   or the phone photo's bytes (≤ 15 MB in) — checked (JPEG/PNG for WhatsApp, ≤ 5 MB,
   ≤ 40 MP declared; a WebP or any image over 5 MB is downscaled and re-encoded as
   JPEG before a single full-size pixel is decoded) and **copied to R2** under
   `t/{tenant}/whatsapp/outbound/{connection}/{uuid}.{ext}`. The outbox row carries an
   image body WITHOUT a media reference and `attachment.object_key` (migration 0123).
   The copy exists because the whatsapp-worker container does not mount the upload
   store, and because a piece purged by ADR 39 must not strand a queued send.
2. **At send time (`outbox.OutboxSender`):** the worker reads the copy, `upload_media`s
   it, records the media id on the row (`record_media_id`) and THEN sends. A retried
   row already has the id: one upload per row, however many tries.

Bytes never sit in Postgres. `whatsapp/outbound/` is outside `PURGEABLE_ROOTS`
(`qualify_shared.objects.gate`): the copies are kept with the conversation; a retention
rule for them is the follow-up m-24945889 (see «Not covered yet»).

## Provenance (0123 `whatsapp_outbox.attachment`)

`kind` (`product` / `piece` / `menu` / `photo`), the source id (`product_id` /
`draft_id` / `menu_version_id` + `product_ids`), `source_key` (the stored file it came
from), `object_key` / `content_type` / `filename` / `bytes` / `sha256` of the copy,
`media_id` once uploaded, and `pipeline` (`ATTACHMENT_PIPELINE`). The outbound `messages`
row is joined to it by `wamid`. A piece sent «sin aprobar» records `status_at_send`;
sending it does NOT approve it for the networks (spec §6, question 1 — open).

## Retention (ADR 39, founder decision 2026-11-04)

A piece sent over WhatsApp counts as a use: `creative.retention.read_facts` reads the
last `sent` outbox row whose `attachment->>'draft_id'` is the piece — derived, never a
flag.

## «Tu menú» resumes the automation (founder decision 2026-11-04)

A product, a piece, a photo or a typed reply is a takeover: the menu automation of the
thread pauses, as before. «Tu menú» is the opposite — an invitation to order through the
menu — so `send_menu_list` hands the thread BACK to the automation when it is queued
(`ChatService.send_prepared` with `PreparedSend.resume_at`, through the same
`whatsapp_thread_state` door the pause uses): pause cleared, `menu_version_id` = the
published version, `node_id` = that menu's own `products` step, `attempts = 0`,
`context.products_page = 0` (the order in progress is kept). The list is rendered by the
engine from that very node (`products_list`), so its row ids (`prod:…`, `more:…`) are the
ones the engine expects: the customer's pick goes into the order (`next_after_pick`) and
«Ver más» pages on its own, exactly as after «Ver menú y pedir». A catalog in categories
mode (m-24955838) sends the categories list instead; the cursor also resets
`products_category` (to null: jsonb `||` cannot drop a key, and the engine reads null as
"on the categories list") and `products_categories_page`, so the customer's category pick
(`cat:…`) is answered from the first page, whatever the thread was looking at before.

Hence a number with no published menu, a paused menu, or a menu without a `products`
step is refused (`AttachmentRefused("no_menu")`): with nobody to answer the pick, the
list would be a dead end. An empty catalog is `empty_menu`.

## Not covered yet

The R2 copies under `whatsapp/outbound/` have no retention rule yet (follow-up
m-24945889).
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

from qualify_shared.objects.keys import is_object_store_key, tenant_prefix

from qualify_api.whatsapp.chats import ChatService, MenuCursor, PreparedSend, ThreadRef
from qualify_api.whatsapp.client import (
    MAX_MEDIA_CAPTION_CHARS,
    MAX_TEXT_BODY_CHARS,
    build_media_body,
    build_text_body,
)
from qualify_api.whatsapp.menus.engine import (
    PRODUCT_ROW_PREFIX,
    CatalogItem,
    is_categories_mode,
    products_list,
)
from qualify_api.whatsapp.menus.schema import ProductsNode

logger = logging.getLogger("qualify_api.whatsapp.attachments")

#: Provenance stamp of what this module writes into `attachment`.
ATTACHMENT_PIPELINE: Final = "wa-attach-1"

KIND_PRODUCT: Final = "product"
KIND_PIECE: Final = "piece"
KIND_MENU: Final = "menu"
KIND_PHOTO: Final = "photo"

#: Cloud API image limit (messages/image-messages + reference/media «Supported media
#: types»: image/jpeg, image/png, 5 MB). From Meta's docs, not yet measured live.
MAX_IMAGE_BYTES: Final = 5 * 1024 * 1024
WHATSAPP_IMAGE_TYPES: Final = frozenset({"image/jpeg", "image/png"})
#: What the owner may pick from the phone; a WebP is re-encoded as JPEG (WhatsApp takes
#: WebP only as a sticker).
PHONE_PHOTO_TYPES: Final = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_CAPTION_CHARS: Final = MAX_MEDIA_CAPTION_CHARS
OUTBOUND_DIR: Final = "whatsapp/outbound"
_EXTENSIONS: Final = {"image/jpeg": "jpg", "image/png": "png"}
#: What a phone photo may weigh on the way IN (Android photos are often 6-12 MB); it is
#: downscaled and re-encoded to a JPEG within `MAX_IMAGE_BYTES` (UX review, m-24945888).
MAX_INPUT_BYTES: Final = 15 * 1024 * 1024
#: Decompression-bomb cap, checked on the header BEFORE any pixel is decoded: Pillow's
#: own guard only warns at ~89 MP, and a ≤ 5 MB file can declare far more.
MAX_IMAGE_PIXELS: Final = 40_000_000
#: Re-encode attempts, largest first: (longest side, JPEG quality).
_REENCODE_STEPS: Final = ((2048, 85), (1600, 80), (1280, 72))

PIECES_LIMIT: Final = 60

# Draft status (creative/fsm.py) → the picker's word. STAGED was approved first.
PIECE_STATUS_APPROVED: Final = "approved"
PIECE_STATUS_PUBLISHED: Final = "published"
PIECE_STATUS_UNAPPROVED: Final = "unapproved"
PIECE_STATUSES: Final[dict[str, str]] = {
    "approved": PIECE_STATUS_APPROVED,
    "staged": PIECE_STATUS_APPROVED,
    "published": PIECE_STATUS_PUBLISHED,
    "generated": PIECE_STATUS_UNAPPROVED,
}


# ======================================================================================
# Errors
# ======================================================================================


#: What the owner reads for each refusal (qualify-copy-es): `AttachmentRefused.message`.
REFUSAL_TEXT: Final[dict[str, str]] = {
    "too_large": "La foto es demasiado grande. Elige una de menos de 15 MB.",
    "unsupported_type": "Esa foto no se puede enviar. Usa una foto JPG o PNG.",
    "empty": "La foto está vacía. Elige otra.",
    "unreadable": "No pudimos abrir la foto. Elige otra o vuelve a intentarlo.",
    "no_brand": "Este número no tiene una marca con productos.",
    "empty_menu": "Tu menú está vacío: agrega productos para poder enviarlo.",
    "no_menu": (
        "Todavía no tienes una respuesta automática con tus productos activa. "
        "Créala en Respuesta automática para poder enviar tu menú."
    ),
}


class AttachmentRefused(ValueError):
    """The send cannot be built; nothing was written. `reason` is a key of
    `REFUSAL_TEXT`; `message` is its Spanish text for the owner."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.message = REFUSAL_TEXT.get(reason, "No pudimos preparar el envío.")


class ProductNotFound(LookupError):
    """No product with this id for this tenant (another tenant's reads as missing), or
    one of another business than the number's."""


class PieceNotFound(LookupError):
    """No sendable piece with this id: another tenant's, another business's, purged,
    rejected, still drafting, or failed."""


# ======================================================================================
# Pure helpers
# ======================================================================================

_HASHTAG = re.compile(r"(?<![\w&])#[\w\-áéíóúüñÁÉÍÓÚÜÑ]+")
_SPACES = re.compile(r"[ \t]{2,}")
_SENTENCE_END = re.compile(r"[.!?…](?=\s|$)|\n")


def strip_hashtags(text: str) -> str:
    """`#tags` out of a piece's text (spec §1.8: in a chat they only clutter); lines
    left empty are dropped, doubled spaces collapsed."""
    lines = []
    for line in text.splitlines():
        cleaned = _SPACES.sub(" ", _HASHTAG.sub("", line)).strip()
        if cleaned or not line.strip():  # a line that was only hashtags goes away
            lines.append(cleaned)
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def fit_caption(text: str, limit: int = MAX_CAPTION_CHARS) -> tuple[str, bool]:
    """`(text, shortened)`: the text whole when it fits, else cut at the last complete
    sentence that fits in `limit` (a word boundary when no sentence ends in time)."""
    text = text.strip()
    if len(text) <= limit:
        return text, False
    window = text[: limit + 1]
    ends = [m.end() for m in _SENTENCE_END.finditer(window) if m.end() <= limit]
    if ends and ends[-1] >= limit // 3:
        return text[: ends[-1]].strip(), True
    cut = window[:limit].rsplit(None, 1)[0] if " " in window[:limit] else window[:limit]
    return cut.strip(), True


def sniff_image_type(content: bytes) -> str | None:
    """The image type the bytes ARE (Meta refuses a declared type that does not match
    them: error 131053), or `None` when they are none of the three we take."""
    if content[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _check_pixels(content: bytes) -> None:
    """Refuse (`too_large`) an image whose header declares more than `MAX_IMAGE_PIXELS`:
    `Image.open` reads only the header, nothing is decoded yet."""
    from PIL import Image  # noqa: PLC0415 — Pillow is the catalog's dependency already

    try:
        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
    except Image.DecompressionBombError as exc:
        raise AttachmentRefused("too_large") from exc
    except Exception as exc:  # noqa: BLE001 — not an image Pillow can read
        raise AttachmentRefused("unreadable") from exc
    if width * height > MAX_IMAGE_PIXELS:
        raise AttachmentRefused("too_large")


def _reencode_jpeg(content: bytes, side: int, quality: int) -> bytes:
    """Downscale BEFORE converting: `draft` lets the JPEG decoder skip to a reduced scale
    and `thumbnail` resizes in place, so `convert` never sees the full-size bitmap."""
    from PIL import Image  # noqa: PLC0415

    with Image.open(io.BytesIO(content)) as image:
        image.draft("RGB", (side, side))
        image.thumbnail((side, side))
        rgb = image.convert("RGB")
        out = io.BytesIO()
        rgb.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def fit_image(content: bytes) -> tuple[bytes, str]:
    """`(bytes, content_type)` WhatsApp accepts: JPEG or PNG within 5 MB. A WebP, or an
    image over 5 MB (a phone photo up to `MAX_INPUT_BYTES`, a catalog photo, a piece), is
    downscaled and re-encoded as JPEG; refused (`too_large`) only when its header
    declares more than `MAX_IMAGE_PIXELS` or it still does not fit."""
    if not content:
        raise AttachmentRefused("empty")
    kind = sniff_image_type(content)
    if kind is None:
        raise AttachmentRefused("unsupported_type")
    _check_pixels(content)
    if kind in WHATSAPP_IMAGE_TYPES and len(content) <= MAX_IMAGE_BYTES:
        return content, kind
    for side, quality in _REENCODE_STEPS:
        try:
            converted = _reencode_jpeg(content, side, quality)
        except Exception as exc:  # noqa: BLE001 — a corrupt file is the owner's to replace
            logger.warning("whatsapp.attachments.reencode_failed error=%s", type(exc).__name__)
            raise AttachmentRefused("unreadable") from exc
        if len(converted) <= MAX_IMAGE_BYTES:
            return converted, "image/jpeg"
    raise AttachmentRefused("too_large")


def _safe_filename(filename: str, content_type: str) -> str:
    stem = re.sub(r"[^\w.\-]+", "_", (filename or "").rsplit("/", 1)[-1]).strip("._")[:80]
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    return f"{stem or 'foto'}.{_EXTENSIONS[content_type]}"


def outbound_key(tenant_id: UUID, connection_id: UUID, copy_id: UUID, content_type: str) -> str:
    """Where the R2 copy of a sent image lives (module docstring)."""
    return (
        f"{tenant_prefix(tenant_id)}{OUTBOUND_DIR}/{connection_id}/{copy_id}."
        f"{_EXTENSIONS[content_type]}"
    )


def product_price_label(amount: Decimal | None, currency: str | None) -> str:
    from qualify_api.catalog.read import price_label  # noqa: PLC0415

    return price_label(amount, currency or "")


def product_text(name: str, price: str, description: str, caption: str) -> str:
    """The text a product without a photo goes as: the owner's caption when it already
    names the product (the screen pre-writes «{nombre} — {precio}. …»), else
    «{nombre} — {precio}» with the caption (or the description) under it."""
    caption = caption.strip()
    if caption and name.casefold() in caption.casefold():
        body = caption
    else:
        head = f"{name} — {price}" if price else name
        tail = caption or description.strip()
        body = f"{head}\n{tail}" if tail else head
    return fit_caption(body, MAX_TEXT_BODY_CHARS)[0]


# ======================================================================================
# Rows (what the reads return) and picks (what the picker shows)
# ======================================================================================


@dataclass(frozen=True)
class ProductRow:
    """An active `brand_products` row with its main photo. Satisfies
    `whatsapp.catalog.CatalogRow`, so the menu is built from the same rows."""

    id: UUID
    brand_id: UUID
    name: str
    description: str
    price_amount: Decimal | None
    price_currency: str
    category: str
    position: int
    photo_key: str | None = None
    is_active: bool = True


@dataclass(frozen=True)
class PieceRow:
    """A photo piece the picker may offer: its first image (by position), how many images
    it has, and its text (hook + caption + call to action, as written)."""

    id: UUID
    brand_id: UUID
    status: str  # creative/fsm.py
    title: str
    text: str
    image_key: str
    image_count: int
    created_at: datetime
    approved_at: datetime | None = None


@dataclass(frozen=True)
class ProductPick:
    id: str
    name: str
    price_label: str
    description: str
    #: A 15-minute public-media URL for an R2 photo; "" for a local upload-store photo
    #: (the page resolves `thumb_key` with `rx.get_upload_url`, like the catalog screen)
    #: and for a product without one.
    thumb_url: str
    has_photo: bool
    thumb_key: str = ""


@dataclass(frozen=True)
class PiecePick:
    id: str
    status: str  # PIECE_STATUS_*
    #: The piece's text without `#`, cut at a sentence end to fit 1024 characters.
    caption_suggestion: str
    thumb_url: str
    created_at: datetime
    title: str = ""
    thumb_key: str = ""
    caption_shortened: bool = False
    image_count: int = 1
    approved_at: datetime | None = None


@dataclass(frozen=True)
class MenuRef:
    """The products step of a number's live menu: its node id, the node, the version."""

    node_id: str
    node: ProductsNode
    menu_version_id: UUID


@dataclass(frozen=True)
class PaymentPick:
    """«¿Cuál forma de pago?» (spec `ux-paso-de-pago.md` §5): a `choice_card` row."""

    id: str
    name: str
    currency: str
    currency_label: str  # «En bolívares», «Al recibir», "" without a currency
    pay_on_delivery: bool
    has_qr: bool
    thumb_url: str
    updated_at: datetime


@dataclass(frozen=True)
class MenuPreview:
    """«Así le llega tu menú»: the list's text and button, how many products the
    business sells, and whether they overflow one WhatsApp list («Ver más»)."""

    body: str
    button_label: str
    header: str | None
    footer: str | None
    product_count: int
    rows_shown: int
    overflows: bool
    menu_version_id: str | None


# ======================================================================================
# Seams
# ======================================================================================


class AttachmentReads(Protocol):
    """Tenant-scoped reads (the Postgres implementation runs each in `tenant_session`)."""

    def products(self, tenant_id: UUID, brand_id: UUID) -> list[ProductRow]: ...

    def category_order(self, tenant_id: UUID, brand_id: UUID) -> tuple[str, ...]:
        """The owner's order of the brand's categories (`brand_product_categories`,
        m-24955643) — the picker and «Tu menú» sort with it, like the WhatsApp list."""
        ...

    def product(self, tenant_id: UUID, product_id: UUID) -> ProductRow | None: ...

    def pieces(self, tenant_id: UUID, brand_id: UUID) -> list[PieceRow]: ...

    def piece(self, tenant_id: UUID, draft_id: UUID) -> PieceRow | None: ...

    def number_brand(self, tenant_id: UUID, connection_id: UUID) -> UUID | None:
        """The business a WhatsApp number belongs to (`whatsapp_phone_numbers.brand_id`)."""
        ...

    def menu_node(self, tenant_id: UUID, connection_id: UUID) -> MenuRef | None:
        """The `products` step of the number's published, unpaused menu; `None` when
        there is no such menu or it has no `products` step."""
        ...


class BlobStore(Protocol):
    """Reads a stored image (R2 `t/…` or the local upload store, tenant re-checked) and
    writes the outbound copy to R2 (`ObjectGate.put_media`)."""

    def read(self, tenant_id: UUID, key: str) -> bytes: ...

    def put(self, tenant_id: UUID, key: str, content: bytes, content_type: str) -> None: ...


class ThumbLinker(Protocol):
    """`publishing.composition.TokenPublicMediaLinker`'s shape (15-minute token)."""

    def link(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str: ...


# ======================================================================================
# Service
# ======================================================================================


def _content_type_of_key(key: str) -> str:
    return "image/png" if key.lower().endswith(".png") else "image/jpeg"


class ChatAttachmentService:
    """The four sends and the picker's reads. Every method takes the caller's
    `tenant_id`; the thread's number is the gateway's to check (`ChatsGateway._owned`)."""

    def __init__(
        self,
        chats: ChatService,
        reads: AttachmentReads,
        blobs: BlobStore,
        linker: ThumbLinker | None = None,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        payment_methods: Callable[[UUID, UUID], Sequence[Any]] | None = None,
        payment_store: Any = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._chats = chats
        self._reads = reads
        self._blobs = blobs
        self._linker = linker
        self._new_id = id_factory
        # m-24955648: «Formas de pago» — the one reader of active methods and the
        # thread's payment record (`payment_status`); production defaults are lazy.
        self._payment_methods = payment_methods
        self._payment_store = payment_store
        self._clock = clock

    # --- the picker --------------------------------------------------------------------

    def _thumb(self, tenant_id: UUID, key: str | None) -> str:
        if not key or not key.startswith(tenant_prefix(tenant_id)) or self._linker is None:
            return ""
        try:
            return self._linker.link(
                tenant_id=tenant_id, object_key=key, content_type=_content_type_of_key(key)
            )
        except Exception as exc:  # noqa: BLE001 — a thumbnail is not worth the picker
            logger.warning("whatsapp.attachments.thumb_failed error=%s", type(exc).__name__)
            return ""

    def list_products_for_chat(self, tenant_id: UUID, brand_id: UUID) -> list[ProductPick]:
        """The business's active products in menu order; the ones without a photo last
        (spec §1.6: shown, marked «Sin foto», sent as text)."""
        from qualify_api.whatsapp.catalog import to_catalog_items  # noqa: PLC0415

        rows = {str(r.id): r for r in self._reads.products(tenant_id, brand_id)}
        order = self._reads.category_order(tenant_id, brand_id)
        ordered = [rows[item.product_id] for item in to_catalog_items(rows.values(), order)]
        picks = [
            ProductPick(
                id=str(row.id),
                name=row.name.strip(),
                price_label=product_price_label(row.price_amount, row.price_currency),
                description=row.description.strip(),
                thumb_url=self._thumb(tenant_id, row.photo_key),
                has_photo=bool(row.photo_key),
                thumb_key=row.photo_key or "",
            )
            for row in ordered
        ]
        return [p for p in picks if p.has_photo] + [p for p in picks if not p.has_photo]

    def list_pieces_for_chat(self, tenant_id: UUID, brand_id: UUID) -> list[PiecePick]:
        """Photo pieces only (PR 1): approved and published first, then «sin aprobar»,
        each group newest first."""
        picks: list[PiecePick] = []
        for row in self._reads.pieces(tenant_id, brand_id):
            status = PIECE_STATUSES.get(row.status)
            if status is None:
                continue
            caption, shortened = fit_caption(strip_hashtags(row.text))
            picks.append(
                PiecePick(
                    id=str(row.id),
                    status=status,
                    caption_suggestion=caption,
                    thumb_url=self._thumb(tenant_id, row.image_key),
                    created_at=row.created_at,
                    title=row.title,
                    thumb_key=row.image_key,
                    caption_shortened=shortened,
                    image_count=row.image_count,
                    approved_at=row.approved_at,
                )
            )
        picks.sort(key=lambda p: p.created_at, reverse=True)
        return [p for p in picks if p.status != PIECE_STATUS_UNAPPROVED] + [
            p for p in picks if p.status == PIECE_STATUS_UNAPPROVED
        ]

    def _menu(
        self, tenant_id: UUID, connection_id: UUID
    ) -> tuple[MenuRef, tuple[CatalogItem, ...]]:
        from qualify_api.whatsapp.catalog import to_catalog_items  # noqa: PLC0415

        ref = self._reads.menu_node(tenant_id, connection_id)
        if ref is None:
            raise AttachmentRefused("no_menu")
        brand_id = self._reads.number_brand(tenant_id, connection_id)
        if brand_id is None:
            return ref, ()
        rows = self._reads.products(tenant_id, brand_id)
        return ref, to_catalog_items(rows, self._reads.category_order(tenant_id, brand_id))

    def menu_preview(self, tenant_id: UUID, connection_id: UUID) -> MenuPreview:
        """Raises `AttachmentRefused("no_menu")` when «Tu menú» cannot be sent."""
        ref, catalog = self._menu(tenant_id, connection_id)
        node, version_id = ref.node, ref.menu_version_id
        by_category = bool(catalog) and is_categories_mode(node, catalog)
        shown = products_list(node, catalog).rows if catalog else ()
        product_rows = [r for r in shown if r.id.startswith(PRODUCT_ROW_PREFIX)]
        return MenuPreview(
            # Categories first (m-24955838): the customer picks a category, so there is
            # no «Ver más» over the whole catalog to warn about.
            body=node.categories_body if by_category else node.body,
            button_label=node.button_label,
            header=node.header,
            footer=node.footer,
            product_count=len(catalog),
            rows_shown=len(product_rows),
            overflows=not by_category and len(product_rows) < len(catalog),
            menu_version_id=str(version_id),
        )

    # --- sends -------------------------------------------------------------------------

    def _image_send(
        self,
        tenant_id: UUID,
        thread: ThreadRef,
        content: bytes,
        *,
        filename: str,
        caption: str,
        provenance: dict[str, Any],
        request_key: str | None,
    ) -> PreparedSend:
        data, content_type = fit_image(content)
        text, _ = fit_caption(caption)
        body = build_media_body(
            thread.wa_id,
            "image",
            media_id="pending-upload",
            link=None,
            caption=text or None,
            filename=None,
        )
        del body["image"]["id"]  # the sender fills it after `upload_media` (outbox.py)
        key = outbound_key(tenant_id, thread.connection_id, self._new_id(), content_type)
        self._blobs.put(tenant_id, key, data, content_type)
        attachment = {
            **provenance,
            "object_key": key,
            "content_type": content_type,
            "filename": _safe_filename(filename, content_type),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "media_id": None,
            "pipeline": ATTACHMENT_PIPELINE,
        }
        return PreparedSend(
            payload=body,
            attachment=attachment,
            preview_text=text or None,
            request_key=request_key,
        )

    def _read(self, tenant_id: UUID, key: str) -> bytes:
        try:
            return self._blobs.read(tenant_id, key)
        except AttachmentRefused:
            raise
        except Exception as exc:  # noqa: BLE001 — missing file / store down: no send
            logger.warning("whatsapp.attachments.read_failed error=%s", type(exc).__name__)
            raise AttachmentRefused("unreadable") from exc

    def send_product(
        self,
        tenant_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        product_id: UUID,
        caption: str,
        *,
        request_key: str | None = None,
    ) -> UUID:
        """The product's main photo with the owner's caption; a product without a photo
        goes as a text (name, price, caption). Returns the outbox id."""
        product = self._reads.product(tenant_id, product_id)
        if product is None:
            raise ProductNotFound(str(product_id))

        def prepare(thread: ThreadRef) -> PreparedSend:
            brand = self._reads.number_brand(tenant_id, thread.connection_id)
            if brand is None:  # ADR 43: never offer another business's products
                raise AttachmentRefused("no_brand")
            if brand != product.brand_id:
                raise ProductNotFound(str(product_id))
            provenance: dict[str, Any] = {
                "kind": KIND_PRODUCT,
                "product_id": str(product.id),
                "source_key": product.photo_key,
            }
            if not product.photo_key:
                text = product_text(
                    product.name.strip(),
                    product_price_label(product.price_amount, product.price_currency),
                    product.description,
                    caption,
                )
                return PreparedSend(
                    payload=build_text_body(thread.wa_id, text, False),
                    attachment={**provenance, "fallback": "text", "pipeline": ATTACHMENT_PIPELINE},
                    request_key=request_key,
                )
            return self._image_send(
                tenant_id,
                thread,
                self._read(tenant_id, product.photo_key),
                filename=product.name,
                caption=caption,
                provenance=provenance,
                request_key=request_key,
            )

        return self._chats.send_prepared(
            tenant_id, thread_id, user_id, prepare, request_key=request_key
        )

    def send_piece(
        self,
        tenant_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        draft_id: UUID,
        caption: str,
        *,
        request_key: str | None = None,
    ) -> UUID:
        """A photo piece's first image with the owner's caption. A piece «sin aprobar» is
        sent as it is and stays unapproved for the networks (`status_at_send`)."""
        piece = self._reads.piece(tenant_id, draft_id)
        if piece is None or piece.status not in PIECE_STATUSES:
            raise PieceNotFound(str(draft_id))

        def prepare(thread: ThreadRef) -> PreparedSend:
            brand = self._reads.number_brand(tenant_id, thread.connection_id)
            if brand is None:  # ADR 43: never offer another business's pieces
                raise AttachmentRefused("no_brand")
            if brand != piece.brand_id:
                raise PieceNotFound(str(draft_id))
            return self._image_send(
                tenant_id,
                thread,
                self._read(tenant_id, piece.image_key),
                filename=piece.title or "pieza",
                caption=caption,
                provenance={
                    "kind": KIND_PIECE,
                    "draft_id": str(piece.id),
                    "source_key": piece.image_key,
                    "status_at_send": piece.status,
                },
                request_key=request_key,
            )

        return self._chats.send_prepared(
            tenant_id, thread_id, user_id, prepare, request_key=request_key
        )

    def send_menu_list(
        self,
        tenant_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        *,
        request_key: str | None = None,
    ) -> UUID:
        """The interactive product list «Ver menú y pedir» sends (first page), built by
        the menu engine from the number's live menu and catalog. Resumes the thread's
        automation at that products step (module docstring)."""
        from qualify_api.whatsapp.handler import outbox_payload  # noqa: PLC0415
        from qualify_api.whatsapp.menus.engine import (  # noqa: PLC0415
            CTX_CATEGORIES_PAGE,
            CTX_PRODUCTS_CATEGORY,
            CTX_PRODUCTS_PAGE,
        )

        def prepare(thread: ThreadRef) -> PreparedSend:
            ref, catalog = self._menu(tenant_id, thread.connection_id)
            if not catalog:
                raise AttachmentRefused("empty_menu")
            send = products_list(ref.node, catalog)
            payload = outbox_payload(send, to=thread.wa_id)
            assert payload is not None  # a SendList always has a body
            return PreparedSend(
                payload=payload,
                attachment={
                    "kind": KIND_MENU,
                    "menu_version_id": str(ref.menu_version_id),
                    "node_id": ref.node_id,
                    "product_ids": [
                        r.id.removeprefix("prod:") for r in send.rows if r.id.startswith("prod:")
                    ],
                    "pipeline": ATTACHMENT_PIPELINE,
                },
                request_key=request_key,
                resume_at=MenuCursor(
                    menu_version_id=ref.menu_version_id,
                    node_id=ref.node_id,
                    context_patch={
                        CTX_PRODUCTS_PAGE: 0,
                        CTX_PRODUCTS_CATEGORY: None,
                        CTX_CATEGORIES_PAGE: 0,
                    },
                ),
            )

        return self._chats.send_prepared(
            tenant_id, thread_id, user_id, prepare, request_key=request_key
        )

    # --- «Formas de pago» (m-24955648, spec `ux-paso-de-pago.md` §5) --------------------

    def _active_methods(self, tenant_id: UUID, brand_id: UUID) -> Sequence[Any]:
        if self._payment_methods is None:
            from qualify_api.whatsapp.payments import active_payment_methods  # noqa: PLC0415

            self._payment_methods = active_payment_methods
        return tuple(self._payment_methods(tenant_id, brand_id))

    def _payments_store(self) -> Any:
        if self._payment_store is None:
            from qualify_api.whatsapp.payment_status import (  # noqa: PLC0415
                PostgresPaymentStatusStore,
            )

            self._payment_store = PostgresPaymentStatusStore()
        return self._payment_store

    def list_payment_methods_for_chat(self, tenant_id: UUID, brand_id: UUID) -> list[PaymentPick]:
        """The business's active methods (the same list as the menu), by position."""
        from qualify_api.whatsapp.menus.engine import currency_words  # noqa: PLC0415

        return [
            PaymentPick(
                id=str(m.id),
                name=m.name,
                currency=m.currency,
                currency_label=(
                    "Al recibir"
                    if m.pay_on_delivery
                    else (f"En {currency_words(m.currency)}" if m.currency else "")
                ),
                pay_on_delivery=m.pay_on_delivery,
                has_qr=bool(m.qr_media_key),
                thumb_url=self._thumb(tenant_id, m.qr_media_key),
                updated_at=m.updated_at,
            )
            for m in self._active_methods(tenant_id, brand_id)
        ]

    def payment_card_preview(
        self, tenant_id: UUID, connection_id: UUID, thread_id: UUID, method_id: UUID
    ) -> str:
        """«Revisa y envía»: the caption the customer will get (with the chat's order
        total when it has one)."""
        method = self._payment_method(tenant_id, connection_id, method_id)
        return self._payment_caption(tenant_id, thread_id, method)[0]

    def _payment_method(self, tenant_id: UUID, connection_id: UUID, method_id: UUID) -> Any:
        from qualify_api.whatsapp.payments import PaymentMethodNotFound  # noqa: PLC0415

        brand = self._reads.number_brand(tenant_id, connection_id)
        if brand is None:
            raise AttachmentRefused("no_brand")
        method = next(
            (m for m in self._active_methods(tenant_id, brand) if m.id == method_id), None
        )
        if method is None:
            raise PaymentMethodNotFound(str(method_id))
        return method

    def _payment_caption(self, tenant_id: UUID, thread_id: UUID, method: Any) -> tuple[str, Any]:
        from qualify_api.whatsapp.menus.engine import payment_card_caption  # noqa: PLC0415
        from qualify_api.whatsapp.orders import read_order  # noqa: PLC0415
        from qualify_api.whatsapp.payments import as_option  # noqa: PLC0415

        order = read_order(self._payments_store().context(tenant_id, thread_id))
        caption = payment_card_caption(
            as_option(method),
            total=order.total if order is not None else None,
            order_currency=order.currency if order is not None else None,
        )
        return caption, order

    def send_payment_method(
        self,
        tenant_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        method_id: UUID,
        *,
        request_key: str | None = None,
    ) -> UUID:
        """The same card the menu sends (the QR with its caption, or the caption alone),
        from a person: pauses the automation like every person's send. In a chat with an
        order it marks the payment «Esperando el pago» (or «Paga al recibir»)."""
        from qualify_api.whatsapp.payment_status import payment_record  # noqa: PLC0415

        chosen: dict[str, Any] = {}

        def prepare(thread: ThreadRef) -> PreparedSend:
            method = self._payment_method(tenant_id, thread.connection_id, method_id)
            caption, order = self._payment_caption(tenant_id, thread_id, method)
            chosen.update(method=method, order=order)
            provenance: dict[str, Any] = {
                "kind": "payment_method",
                "method_id": str(method.id),
                "brand_id": str(method.brand_id),
                "source_key": method.qr_media_key,
            }
            if not method.qr_media_key:
                return PreparedSend(
                    payload=build_text_body(thread.wa_id, caption, False),
                    attachment={**provenance, "fallback": "text", "pipeline": ATTACHMENT_PIPELINE},
                    preview_text=caption,
                    request_key=request_key,
                )
            return self._image_send(
                tenant_id,
                thread,
                self._read(tenant_id, method.qr_media_key),
                filename=f"qr-{method.name}",
                caption=caption,
                provenance=provenance,
                request_key=request_key,
            )

        outbox_id = self._chats.send_prepared(
            tenant_id, thread_id, user_id, prepare, request_key=request_key
        )
        method, order = chosen.get("method"), chosen.get("order")
        if method is not None and order is not None:
            now = self._clock() if self._clock is not None else datetime.now(UTC)
            self._payments_store().set_record(
                tenant_id=tenant_id,
                thread_id=thread_id,
                record=payment_record(
                    {
                        "choice": "method",
                        "method_id": str(method.id),
                        "name": method.name,
                        "currency": method.currency,
                        "pay_on_delivery": method.pay_on_delivery,
                    },
                    order_message_id=order.source_message_id,
                    at=now,
                    source="chat",
                ),
            )
        return outbox_id

    def send_photo(
        self,
        tenant_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        content: bytes,
        content_type: str,
        filename: str,
        caption: str,
        *,
        request_key: str | None = None,
    ) -> UUID:
        """A photo from the owner's phone: JPEG, PNG or WebP, ≤ 15 MB in, re-encoded to
        a JPEG ≤ 5 MB when needed — refused before anything is written otherwise."""
        declared = (content_type or "").split(";", 1)[0].strip().lower()
        if declared not in PHONE_PHOTO_TYPES:
            raise AttachmentRefused("unsupported_type")
        if not content:
            raise AttachmentRefused("empty")
        if len(content) > MAX_INPUT_BYTES:
            raise AttachmentRefused("too_large")
        if sniff_image_type(content) is None:
            raise AttachmentRefused("unsupported_type")

        def prepare(thread: ThreadRef) -> PreparedSend:
            return self._image_send(
                tenant_id,
                thread,
                content,
                filename=filename,
                caption=caption,
                provenance={"kind": KIND_PHOTO, "source_key": None},
                request_key=request_key,
            )

        return self._chats.send_prepared(
            tenant_id, thread_id, user_id, prepare, request_key=request_key
        )


# ======================================================================================
# In-memory doubles (tests)
# ======================================================================================


class MemoryAttachmentReads:
    def __init__(self) -> None:
        self.product_rows: dict[UUID, tuple[UUID, ProductRow]] = {}
        self.piece_rows: dict[UUID, tuple[UUID, PieceRow]] = {}
        self.brands: dict[tuple[UUID, UUID], UUID] = {}
        self.menus: dict[tuple[UUID, UUID], MenuRef] = {}
        self.category_orders: dict[tuple[UUID, UUID], tuple[str, ...]] = {}

    def products(self, tenant_id: UUID, brand_id: UUID) -> list[ProductRow]:
        return [
            r for t, r in self.product_rows.values() if t == tenant_id and r.brand_id == brand_id
        ]

    def category_order(self, tenant_id: UUID, brand_id: UUID) -> tuple[str, ...]:
        return self.category_orders.get((tenant_id, brand_id), ())

    def product(self, tenant_id: UUID, product_id: UUID) -> ProductRow | None:
        found = self.product_rows.get(product_id)
        return found[1] if found and found[0] == tenant_id else None

    def pieces(self, tenant_id: UUID, brand_id: UUID) -> list[PieceRow]:
        return [r for t, r in self.piece_rows.values() if t == tenant_id and r.brand_id == brand_id]

    def piece(self, tenant_id: UUID, draft_id: UUID) -> PieceRow | None:
        found = self.piece_rows.get(draft_id)
        return found[1] if found and found[0] == tenant_id else None

    def number_brand(self, tenant_id: UUID, connection_id: UUID) -> UUID | None:
        return self.brands.get((tenant_id, connection_id))

    def menu_node(self, tenant_id: UUID, connection_id: UUID) -> MenuRef | None:
        return self.menus.get((tenant_id, connection_id))


class MemoryBlobStore:
    """`objects[(tenant_id, key)] = bytes`; a read of another tenant's key is missing."""

    def __init__(self) -> None:
        self.objects: dict[tuple[UUID, str], bytes] = {}
        self.content_types: dict[tuple[UUID, str], str] = {}

    def read(self, tenant_id: UUID, key: str) -> bytes:
        return self.objects[(tenant_id, key)]

    def put(self, tenant_id: UUID, key: str, content: bytes, content_type: str) -> None:
        if not key.startswith(tenant_prefix(tenant_id)):
            raise PermissionError("key outside the tenant prefix")
        self.objects[(tenant_id, key)] = content
        self.content_types[(tenant_id, key)] = content_type


# ======================================================================================
# Production
# ======================================================================================


def _visible_text(copy: dict[str, Any] | None) -> str:
    """hook + caption + call to action of a copy variant, hashtags left out (they are
    stripped from a chat caption anyway)."""
    if not isinstance(copy, dict):
        return ""
    blocks = [copy.get("hook"), copy.get("caption"), copy.get("cta")]
    return "\n\n".join(b.strip() for b in blocks if isinstance(b, str) and b.strip())


class PostgresAttachmentReads:
    """`tenant_session(tenant_id)` per call (`qualify_app`): RLS bounds every read, so
    another tenant's product or piece reads as missing."""

    def _product_rows(self, session: Any, where: Sequence[Any]) -> list[ProductRow]:
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.catalog.models import (  # noqa: PLC0415
            MEDIA_TYPE_IMAGE,
            BrandProduct,
            ProductMedia,
        )

        products = session.scalars(
            select(BrandProduct)
            .where(BrandProduct.is_active.is_(True), *where)
            .order_by(BrandProduct.position, BrandProduct.name, BrandProduct.id)
        ).all()
        if not products:
            return []
        photos: dict[UUID, str] = {}
        for media in session.scalars(
            select(ProductMedia)
            .where(
                ProductMedia.product_id.in_([p.id for p in products]),
                ProductMedia.media_type == MEDIA_TYPE_IMAGE,
            )
            .order_by(ProductMedia.is_primary.desc(), ProductMedia.position, ProductMedia.id)
        ).all():
            photos.setdefault(media.product_id, media.object_key)
        return [
            ProductRow(
                id=p.id,
                brand_id=p.brand_id,
                name=p.name,
                description=p.description or "",
                price_amount=p.price_amount,
                price_currency=p.price_currency or "",
                category=p.category or "",
                position=p.position or 0,
                photo_key=photos.get(p.id),
            )
            for p in products
        ]

    def products(self, tenant_id: UUID, brand_id: UUID) -> list[ProductRow]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        from qualify_api.catalog.models import BrandProduct  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            return self._product_rows(session, [BrandProduct.brand_id == brand_id])

    def category_order(self, tenant_id: UUID, brand_id: UUID) -> tuple[str, ...]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.catalog.models import BrandProductCategory  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            return tuple(
                session.scalars(
                    select(BrandProductCategory.name)
                    .where(BrandProductCategory.brand_id == brand_id)
                    .order_by(BrandProductCategory.position, BrandProductCategory.name_key)
                )
            )

    def product(self, tenant_id: UUID, product_id: UUID) -> ProductRow | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        from qualify_api.catalog.models import BrandProduct  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            rows = self._product_rows(session, [BrandProduct.id == product_id])
        return rows[0] if rows else None

    def _piece_rows(self, session: Any, where: Sequence[Any], limit: int) -> list[PieceRow]:
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.creative import models as creative  # noqa: PLC0415
        from qualify_api.creative.versions import visible_version  # noqa: PLC0415

        drafts = session.scalars(
            select(creative.ContentDraft)
            .where(
                creative.ContentDraft.status.in_(tuple(PIECE_STATUSES)),
                creative.ContentDraft.media_purged_at.is_(None),
                creative.ContentDraft.parent_draft_id.is_(None),  # VE-08: never a part alone
                *where,
            )
            .order_by(creative.ContentDraft.created_at.desc())
            .limit(limit)
        ).all()
        rows: list[PieceRow] = []
        for draft in drafts:
            images = session.scalars(
                select(creative.ImageAsset)
                .where(
                    creative.ImageAsset.draft_id == draft.id,
                    visible_version(creative.ImageAsset),
                )
                .order_by(creative.ImageAsset.position, creative.ImageAsset.created_at)
            ).all()
            keyed = [i for i in images if i.object_key]
            # Photo pieces only (PR 1): a piece whose first medium is a video is left out.
            if not keyed or any(i.media_type != "image" for i in keyed):
                continue
            variant = None
            if draft.selected_variant_id is not None:
                variant = session.get(creative.CopyVariant, draft.selected_variant_id)
            if variant is None or variant.draft_id != draft.id:
                variant = session.scalars(
                    select(creative.CopyVariant)
                    .where(
                        creative.CopyVariant.draft_id == draft.id,
                        visible_version(creative.CopyVariant),
                    )
                    .order_by(creative.CopyVariant.ordinal)
                ).first()
            brief = session.get(creative.ContentBrief, draft.brief_id)
            text = _visible_text(variant.edited_copy or variant.copy) if variant else ""
            rows.append(
                PieceRow(
                    id=draft.id,
                    brand_id=draft.brand_id,
                    status=draft.status,
                    title=(draft.title or (brief.topic if brief else "") or "").strip(),
                    text=text,
                    image_key=str(keyed[0].object_key),
                    image_count=len(keyed),
                    created_at=draft.created_at,
                    approved_at=draft.approved_at,
                )
            )
        return rows

    def pieces(self, tenant_id: UUID, brand_id: UUID) -> list[PieceRow]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        from qualify_api.creative.models import ContentDraft  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            return self._piece_rows(session, [ContentDraft.brand_id == brand_id], PIECES_LIMIT)

    def piece(self, tenant_id: UUID, draft_id: UUID) -> PieceRow | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        from qualify_api.creative.models import ContentDraft  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            rows = self._piece_rows(session, [ContentDraft.id == draft_id], 1)
        return rows[0] if rows else None

    def number_brand(self, tenant_id: UUID, connection_id: UUID) -> UUID | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.whatsapp.models import WhatsAppPhoneNumber  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            return session.scalar(
                select(WhatsAppPhoneNumber.brand_id).where(
                    WhatsAppPhoneNumber.connection_id == connection_id
                )
            )

    def menu_node(self, tenant_id: UUID, connection_id: UUID) -> MenuRef | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.whatsapp.menus.schema import MenuDefinition  # noqa: PLC0415
        from qualify_api.whatsapp.models import (  # noqa: PLC0415
            WhatsAppMenu,
            WhatsAppMenuVersion,
            WhatsAppPhoneNumber,
        )

        with tenant_session(tenant_id) as session:
            row = session.execute(
                select(WhatsAppMenuVersion.id, WhatsAppMenuVersion.definition)
                .join(WhatsAppMenu, WhatsAppMenu.published_version_id == WhatsAppMenuVersion.id)
                .join(
                    WhatsAppPhoneNumber, WhatsAppPhoneNumber.id == WhatsAppMenu.phone_number_row_id
                )
                .where(
                    WhatsAppPhoneNumber.connection_id == connection_id,
                    # A paused menu answers nobody (the handler's own rule).
                    WhatsAppMenu.is_paused.is_(False),
                )
            ).first()
        if row is None:
            return None
        definition = MenuDefinition.model_validate(row.definition)
        found = next(
            ((nid, n) for nid, n in definition.nodes.items() if isinstance(n, ProductsNode)),
            None,
        )
        if found is None:
            return None
        return MenuRef(node_id=found[0], node=found[1], menu_version_id=row.id)


class ProductionBlobStore:
    """R2 through `ObjectGate` (tenant prefix re-checked on every call) for `t/…` keys —
    since CM-9 a catalog photo too; the app's local upload store (`media_root()`) for an
    old catalog photo or pre-R2 piece still on the volume, and R2 through the key map once
    it was copied (`owner_uploads.read_owner_media`), only for a key of THIS tenant."""

    def __init__(self) -> None:
        self._gate: Any = None

    def _object_gate(self) -> Any:
        if self._gate is None:
            from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
            from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
            from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

            self._gate = ObjectGate(R2ObjectStore(R2Settings.from_env()))
        return self._gate

    def read(self, tenant_id: UUID, key: str) -> bytes:
        if is_object_store_key(key):  # `t/…` or the Galería's `gallery/…` (m-24971181)
            stream = self._object_gate().open_object(tenant_id, key)
            try:
                return stream.read()
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
        from qualify_api.creative.composition import media_root  # noqa: PLC0415
        from qualify_api.creative.owner_uploads import read_owner_media  # noqa: PLC0415

        # CM-9 (m-24957283): an old local key whose file the one-time copy moved to R2
        # is read there through the key map; still on the volume, from the volume.
        return read_owner_media(tenant_id, key, root=media_root(), gate=self._object_gate)

    def put(self, tenant_id: UUID, key: str, content: bytes, content_type: str) -> None:
        self._object_gate().put_media(tenant_id, key, io.BytesIO(content), content_type)


class R2AttachmentSource:
    """The sender's `outbox.AttachmentSource`: the R2 copy, through `ObjectGate`."""

    def __init__(self) -> None:
        self._store = ProductionBlobStore()

    def read(self, tenant_id: UUID, object_key: str) -> bytes:
        if not object_key.startswith(tenant_prefix(tenant_id)):
            raise PermissionError("attachment key outside the tenant prefix")
        return self._store.read(tenant_id, object_key)


def production_thumb_linker() -> ThumbLinker | None:
    """The 15-minute public-media token linker, or `None` when Redis / the public base
    URL are not configured (the picker then shows placeholders, never fails)."""
    try:
        from qualify_api.config import PublicMediaSettings  # noqa: PLC0415
        from qualify_api.publishing.composition import (  # noqa: PLC0415
            TokenPublicMediaLinker,
            production_media_token_store,
        )

        store = production_media_token_store()
        return TokenPublicMediaLinker(store, PublicMediaSettings.from_env())
    except Exception as exc:  # noqa: BLE001 — thumbnails are optional
        logger.warning("whatsapp.attachments.linker_unavailable error=%s", type(exc).__name__)
        return None


def production_attachment_service(chats: ChatService) -> ChatAttachmentService:
    return ChatAttachmentService(
        chats, PostgresAttachmentReads(), ProductionBlobStore(), production_thumb_linker()
    )


__all__ = [
    "ATTACHMENT_PIPELINE",
    "REFUSAL_TEXT",
    "MAX_CAPTION_CHARS",
    "MAX_IMAGE_BYTES",
    "MAX_IMAGE_PIXELS",
    "MAX_INPUT_BYTES",
    "PHONE_PHOTO_TYPES",
    "AttachmentReads",
    "AttachmentRefused",
    "BlobStore",
    "ChatAttachmentService",
    "MemoryAttachmentReads",
    "MemoryBlobStore",
    "MenuPreview",
    "PaymentPick",
    "MenuRef",
    "PieceNotFound",
    "PiecePick",
    "PieceRow",
    "PostgresAttachmentReads",
    "ProductNotFound",
    "ProductPick",
    "ProductRow",
    "ProductionBlobStore",
    "R2AttachmentSource",
    "ThumbLinker",
    "fit_caption",
    "fit_image",
    "outbound_key",
    "product_text",
    "production_attachment_service",
    "sniff_image_type",
    "strip_hashtags",
]
