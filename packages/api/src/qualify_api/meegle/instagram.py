"""The «Cuenta de Instagram» of an Alta, normalized to a bare username (m-24852194, PB-1).

The founder types the account however it comes to hand: `@usuario`, `usuario`, or a pasted
profile link (`https://www.instagram.com/usuario/`, `instagram.com/usuario?igsh=…`). Whatever
reads it later (the Brand Kit prefill of PB-4) wants one thing: the lowercase username, or
`None` when the text is empty or is not an Instagram account. Pure and offline.

Instagram usernames: letters, digits, `.` and `_`, at most 30 characters, no leading or
trailing `.`, no `..`. Case-insensitive, so they are stored lowercase.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_USERNAME = re.compile(r"[a-z0-9._]{1,30}")
_HOSTS = frozenset({"instagram.com", "www.instagram.com", "m.instagram.com", "instagr.am"})
# First path segments of instagram.com that are not a profile (a post, a reel, a page).
_NOT_PROFILES = frozenset(
    {
        "p",
        "reel",
        "reels",
        "tv",
        "stories",
        "explore",
        "accounts",
        "direct",
        "about",
        "legal",
        "developer",
        "web",
    }
)


def _from_url(text: str) -> str | None:
    """The first path segment of an Instagram link, or `None` for any other link."""
    parts = urlsplit(text if "://" in text else f"https://{text}")
    if (parts.hostname or "").lower() not in _HOSTS:
        return None
    segment = next((s for s in parts.path.split("/") if s), "")
    if segment.lower() in _NOT_PROFILES:
        return None
    return segment


def _looks_like_url(text: str) -> bool:
    lowered = text.lower()
    return "://" in lowered or "/" in lowered or lowered.split("?")[0] in _HOSTS


def normalize_instagram_handle(raw: str | None) -> str | None:
    """`@Usuario`, `usuario` or a profile link → `usuario`; empty or invalid → `None`."""
    text = (raw or "").strip()
    if not text:
        return None
    if _looks_like_url(text):
        candidate = _from_url(text)
        if candidate is None:
            return None
    else:
        candidate = text
    candidate = candidate.removeprefix("@").strip().lower()
    if not _USERNAME.fullmatch(candidate):
        return None
    if candidate.startswith(".") or candidate.endswith(".") or ".." in candidate:
        return None
    return candidate
