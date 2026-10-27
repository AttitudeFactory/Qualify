"""Allowlisted return links for review and piece-retention emails."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID


def review_destination(raw: str) -> str:
    """Only internal review/piece routes; no arbitrary redirects or actions."""
    try:
        url = urlsplit(raw)
        values = parse_qs(url.query)
        if url.scheme or url.netloc or url.fragment:
            return ""
        if url.path.startswith("/drafts/"):
            # An email opens a single piece after login. UUID parsing rejects other
            # paths/actions; query parameters are never forwarded to the detail page.
            piece_id = UUID(url.path.removeprefix("/drafts/").removesuffix("/"))
            return f"/drafts/{piece_id}"
        if url.path not in {"/planner", "/planner/"}:
            return ""
        if values.get("revisar") != ["videos"]:
            return ""
        query = {"revisar": "videos"}
        for key in ("pieza", "evento"):
            value = values.get(key, [])
            if value:
                if len(value) != 1:
                    return ""
                query[key] = str(UUID(value[0]))
        if values.get("fallos") == ["1"]:
            query["fallos"] = "1"
        return "/planner?" + urlencode(query)
    except (ValueError, TypeError):
        return ""


def review_href(piece_id: str = "") -> str:
    return "/planner?" + urlencode(
        {"revisar": "videos", **({"pieza": piece_id} if piece_id else {})}
    )
