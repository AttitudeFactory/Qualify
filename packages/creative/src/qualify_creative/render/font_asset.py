"""A Brand Kit's own font file as a render-service asset (shared by the sticker, m-24987158,
and the video text, ED-13 m-25029108).

The service stores an asset under the sha256 of its bytes (`server/assets.mjs`), so the
reference of a font is known before it is uploaded — `asset://<sha256>` — and a job id that
names it names exactly those bytes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


def font_type(data: bytes) -> str:
    """The MIME type of a font file by its first bytes (WOFF2, OpenType CFF, else TrueType)."""
    head = data[:4]
    if head == b"wOF2":
        return "font/woff2"
    if head == b"OTTO":
        return "font/otf"
    return "font/ttf"


@dataclass(frozen=True)
class TextFont:
    """A font file the owner uploaded to the Brand Kit, already checked to be one FreeType
    draws (`qualify_creative.compose.font_usable`): its storage key (provenance), the
    sha256 of its bytes and the bytes."""

    key: str | None
    sha256: str
    data: bytes = field(repr=False)

    @classmethod
    def of(cls, data: bytes, key: str | None = None) -> TextFont:
        return cls(key=key, sha256=hashlib.sha256(data).hexdigest(), data=bytes(data))

    @property
    def ref(self) -> str:
        """Its reference on the render service once uploaded (content-addressed)."""
        return f"asset://{self.sha256}"


__all__ = ["TextFont", "font_type"]
