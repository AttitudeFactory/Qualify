"""Extract the embedded hydration JSON from a scraped post page's HTML.

These are the in-house parsing seam the ADR chose over a vendor's normalized
schema: they read the raw payload the platform itself renders, so coverage is
bounded only by what the page contains. Extractors return the same dict shapes
the parsers in `parsers/` consume, and are tested against saved HTML fixtures
with no network."""

from __future__ import annotations

import json
import re
from typing import Any

_TIKTOK_SCRIPT = re.compile(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(?P<json>.*?)</script>',
    re.DOTALL,
)
_IG_SHARED_DATA = re.compile(
    r"window\._sharedData\s*=\s*(?P<json>\{.*?\});</script>",
    re.DOTALL,
)


class HydrationExtractionError(ValueError):
    """Raised when the expected hydration payload is absent from the HTML —
    e.g. a login wall or a layout change. Signals a targeted fallback (vendor
    API for that format) rather than a silent empty parse."""


def extract_tiktok_hydration(html: str) -> dict[str, Any]:
    """Pull TikTok's `__UNIVERSAL_DATA_FOR_REHYDRATION__` JSON out of the page.
    Returns the object whose top-level key is `__DEFAULT_SCOPE__`."""
    match = _TIKTOK_SCRIPT.search(html)
    if match is None:
        raise HydrationExtractionError("TikTok hydration script not found in HTML")
    return json.loads(match.group("json"))


def extract_instagram_hydration(html: str) -> dict[str, Any]:
    """Pull Instagram's `window._sharedData` JSON out of the page and narrow it
    to the `{graphql: {shortcode_media: ...}}` shape the parser expects."""
    match = _IG_SHARED_DATA.search(html)
    if match is None:
        raise HydrationExtractionError("Instagram _sharedData not found in HTML")
    shared_data = json.loads(match.group("json"))
    try:
        media = shared_data["entry_data"]["PostPage"][0]["graphql"]["shortcode_media"]
    except (KeyError, IndexError) as exc:
        raise HydrationExtractionError(
            "Instagram shortcode_media missing from _sharedData"
        ) from exc
    return {"graphql": {"shortcode_media": media}}
