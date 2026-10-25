"""A network's picture kept in the brand's own R2 prefix (m-24852537).

Instagram and TikTok serve pictures from signed CDN links that expire (measured with the
Scrape Creators CLI on 2026-10-25: an Instagram image URL lives ~4.4 days, a TikTok
profile picture ~47 h). Anything a brand will look at later — the profile picture the
Alta proposes as the logo today, a post's thumbnail tomorrow — has to be copied while
the link is still alive. This module is that copy, for bytes the caller ALREADY holds
(the prefill downloads the profile picture once for its palette): it never fetches,
so it never costs a credit, and the vendor's own `--download-media` is never used.

Where it goes, inside the brand's prefix (`brand_kit_store.brand_asset_prefix`):

    t/{tenant_id}/brand/{brand_id}/kept/{kind}/{sha256[:32]}{.ext}

`kind` names what the picture is (`KIND_PROFILE`; `KIND_POST` is reserved for post
thumbnails). The name is the content's own hash, so keeping the same picture twice
writes the same object instead of piling up copies, and a new picture never overwrites
the one a decided proposal still points at. Outside every `PURGEABLE_ROOTS` root: the
retention job never empties it.

Through the sanctioned door only (`qualify_shared.objects.ObjectGate`, which re-checks
the tenant prefix on every write). The write retries (`attempts`, house rule: R2 writes
retry); a picture that still cannot be kept raises `PictureNotKept`, which never
carries the source URL (it is a signed link) — the caller degrades, it never fails."""

from __future__ import annotations

import hashlib
import io
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final, Protocol
from uuid import UUID

from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.keys import require_tenant_prefix

from qualify_api.creative.brand_kit_store import brand_asset_prefix

logger = logging.getLogger(__name__)

#: The account's profile picture (the Alta's proposed logo).
KIND_PROFILE: Final = "profile"
#: A post's thumbnail — reserved; nothing keeps one yet.
KIND_POST: Final = "post"
KINDS: Final = frozenset({KIND_PROFILE, KIND_POST})
#: The folder inside the brand's prefix.
KEPT_FOLDER: Final = "kept"
#: A picture, not a video: anything larger is not what was asked for.
MAX_PICTURE_BYTES: Final = 8 * 1024 * 1024
DEFAULT_ATTEMPTS: Final = 3
_BACKOFF_SECONDS: Final = 0.5
_HASH_CHARS: Final = 32
_KEY_RE = re.compile(r"^t/[0-9a-f-]{36}/brand/[0-9a-f-]{36}/kept/[a-z]+/[0-9a-f]{32}\.[a-z]+$")

#: Magic bytes → (content type, extension). The CDNs answer JPEG or WebP; the rest are
#: what an `image/*` answer can plausibly be.
_SIGNATURES: Final[tuple[tuple[bytes, int, str, str], ...]] = (
    (b"\xff\xd8\xff", 0, "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", 0, "image/png", ".png"),
    (b"GIF87a", 0, "image/gif", ".gif"),
    (b"GIF89a", 0, "image/gif", ".gif"),
)


class PictureNotKept(Exception):
    """The picture could not be copied to R2 (not an image, too large, R2 not configured
    or not answering after the retries). Never carries a URL."""


@dataclass(frozen=True)
class KeptPicture:
    key: str
    content_type: str
    sha256: str
    size: int


def sniff_image(data: bytes) -> tuple[str, str] | None:
    """`(content type, extension)` from the bytes themselves, or None (not an image we
    keep). The CDN's header is not trusted: the bytes are what gets served back."""
    for magic, offset, kind, ext in _SIGNATURES:
        if data[offset : offset + len(magic)] == magic:
            return kind, ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    if data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"):
        return "image/avif", ".avif"
    return None


def kept_key(tenant_id: UUID, brand_id: UUID, kind: str, data: bytes, extension: str) -> str:
    """The deterministic key of `data` as a kept `kind` picture of this brand."""
    if kind not in KINDS:
        raise ValueError(f"unknown kept picture kind {kind!r}")
    digest = hashlib.sha256(data).hexdigest()[:_HASH_CHARS]
    prefix = brand_asset_prefix(tenant_id, brand_id)
    return require_tenant_prefix(tenant_id, f"{prefix}{KEPT_FOLDER}/{kind}/{digest}{extension}")


def is_kept_key(tenant_id: UUID, brand_id: UUID, key: object) -> bool:
    """A key this module would have written for THIS tenant's brand — the check a reader
    makes before trusting a key that came back from a stored document."""
    if not isinstance(key, str) or not _KEY_RE.match(key):
        return False
    return key.startswith(f"{brand_asset_prefix(tenant_id, brand_id)}{KEPT_FOLDER}/")


def owner_of(key: object) -> tuple[UUID, UUID] | None:
    """`(tenant id, brand id)` a kept key names, or None when it is not a kept key."""
    if not isinstance(key, str) or not _KEY_RE.match(key):
        return None
    parts = key.split("/")
    try:
        return UUID(parts[1]), UUID(parts[3])
    except ValueError:
        return None


class PictureKeeper(Protocol):
    def keep(self, tenant_id: UUID, brand_id: UUID, kind: str, data: bytes) -> KeptPicture:
        """Copy `data` to R2; raises `PictureNotKept`."""
        ...


def _default_gate() -> ObjectGate:
    """Built only when a picture is kept: a missing R2 configuration then fails that one
    picture, never the run around it."""
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    return ObjectGate(R2ObjectStore(R2Settings.from_env()))


@dataclass
class R2PictureKeeper:
    """The production keeper: one PUT through the gate, retried."""

    gate_factory: Callable[[], ObjectGate] = _default_gate
    attempts: int = DEFAULT_ATTEMPTS
    sleep: Callable[[float], None] = field(default=time.sleep)

    def keep(self, tenant_id: UUID, brand_id: UUID, kind: str, data: bytes) -> KeptPicture:
        if not data:
            raise PictureNotKept("empty picture")
        if len(data) > MAX_PICTURE_BYTES:
            raise PictureNotKept("picture is larger than the cap")
        sniffed = sniff_image(data)
        if sniffed is None:
            raise PictureNotKept("not an image format we keep")
        content_type, extension = sniffed
        key = kept_key(tenant_id, brand_id, kind, data, extension)
        try:
            gate = self.gate_factory()
        except Exception as exc:  # noqa: BLE001 - R2 not configured: this picture only
            raise PictureNotKept(f"object store unavailable: {type(exc).__name__}") from exc
        last: Exception | None = None
        for attempt in range(max(1, self.attempts)):
            try:
                gate.put_media(tenant_id, key, io.BytesIO(data), content_type)
                return KeptPicture(key, content_type, hashlib.sha256(data).hexdigest(), len(data))
            except Exception as exc:  # noqa: BLE001 - retried, then reported as not kept
                last = exc
                logger.info("kept picture: write %d failed: %s", attempt + 1, type(exc).__name__)
                if attempt + 1 < self.attempts:
                    self.sleep(_BACKOFF_SECONDS * (attempt + 1))
        raise PictureNotKept(f"object store write failed: {type(last).__name__}")


__all__ = [
    "DEFAULT_ATTEMPTS",
    "KIND_POST",
    "KIND_PROFILE",
    "KINDS",
    "MAX_PICTURE_BYTES",
    "KeptPicture",
    "PictureKeeper",
    "PictureNotKept",
    "R2PictureKeeper",
    "is_kept_key",
    "kept_key",
    "owner_of",
    "sniff_image",
]
