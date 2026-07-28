"""Detection of Meta's soft-404: a missing page served with HTTP 200.

**On this host, a 200 status is not evidence that a page exists.** Measured
2026-07-24, `https://developers.facebook.com/documentation/graph-api/overview`
returns `HTTP 200`, `text/html`, ~137KB -- of which **40 characters** are visible
text: "Page Not Found - Meta for Developers".

This is a correctness gate, not a nicety. Any `/docs/` -> `/documentation/`
prefix rewrite (see the warning in `urls.py`) maps the entire Graph API portion
of the harvest onto this response. Without this check the corpus silently fills
with not-found bodies, each one recorded in the manifest as a successful fetch,
and nothing downstream can tell the difference.
"""

from __future__ import annotations

import html
import re

# Both locales observed: the host geo-localizes and returns Spanish without an
# explicit `Accept-Language` header.
_NOT_FOUND_MARKERS: tuple[str, ...] = (
    "page not found",
    "no se pudo encontrar la página",
)

# The real graph-api overview yields ~10.7KB of visible text; the soft-404 yields
# 40 characters. Anything under this threshold is a shell, not a document.
MIN_VISIBLE_CHARS = 200

_SCRIPT_OR_STYLE_RE = re.compile(r"(?s)<(script|style)\b.*?</\1>")
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def visible_text(body: str) -> str:
    """Strip scripts, styles and tags, leaving collapsed human-readable text."""
    stripped = _SCRIPT_OR_STYLE_RE.sub(" ", body)
    stripped = _TAG_RE.sub(" ", stripped)
    return _WHITESPACE_RE.sub(" ", html.unescape(stripped)).strip()


def is_soft_404(body: str) -> bool:
    """True if `body` is a not-found page despite whatever status accompanied it.

    Requires *both* signals -- a not-found marker and an implausibly small amount
    of visible text. A real page that merely discusses 404 handling (the Graph API
    error-codes reference does) carries the phrase but has thousands of characters
    of prose, so it is not misclassified.
    """
    text = visible_text(body)
    if len(text) >= MIN_VISIBLE_CHARS:
        return False
    lowered = text.casefold()
    return any(marker in lowered for marker in _NOT_FOUND_MARKERS)
