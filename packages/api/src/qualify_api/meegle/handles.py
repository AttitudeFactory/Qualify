"""Offline normalization of explicitly selected Alta channels and account identifiers."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from qualify_api.meegle.instagram import normalize_instagram_handle

SUPPORTED_CHANNELS = frozenset({"instagram", "tiktok"})
_TIKTOK_HANDLE = re.compile(r"[a-z0-9._]{2,24}")


def normalize_channel(raw: str | None) -> str | None:
    value = (raw or "").strip().casefold()
    return value if value in SUPPORTED_CHANNELS else None


def normalize_handle(network: str, raw: str | None) -> str | None:
    """Never resolve short URLs or infer a channel from an identifier."""
    if network == "instagram":
        return normalize_instagram_handle(raw)
    if network != "tiktok":
        return None
    value = (raw or "").strip().lower()
    if "/" in value or "://" in value:
        try:
            parts = urlsplit(value if "://" in value else "https://" + value)
            if parts.scheme not in {"https", "http"} or parts.username or parts.password:
                return None
            if parts.hostname not in {"tiktok.com", "www.tiktok.com", "m.tiktok.com"}:
                return None
            segments = [part for part in parts.path.split("/") if part]
            if len(segments) != 1 or not segments[0].startswith("@"):
                return None
            value = segments[0]
        except ValueError:
            return None
    value = value.removeprefix("@")
    return value if _TIKTOK_HANDLE.fullmatch(value) and not value.endswith(".") else None
