"""Design tokens for the Qualify CRM UI.

The single place a screen may take a colour, radius or gutter from. Colours resolve
to Radix Themes scales (so light/dark is free and every step has a defined contrast
role); layout values resolve to the ``--q-*`` CSS variables declared in
``assets/qualify.css`` so a page reads the same value the stylesheet does.

Naming rule: tokens are named by **role**, never by value or by hue. A screen asks for
``TONE_ERROR``, not for ``"tomato"``, so that the mapping can move once and everywhere.

Reference: docs/design-system.md §3.
"""

from __future__ import annotations

from typing import Literal

import reflex as rx

# ---------------------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------------------

PAGE_X = "var(--q-page-x)"
"""Horizontal gutter of every business page (2rem desktop, 1rem below 900px)."""

SIDEBAR_W = "var(--q-sidebar-w)"
CONTENT_MAX = "var(--q-content-max)"

PAD_HEADER = f"1.5rem {PAGE_X} 1rem {PAGE_X}"
"""Page header block: title row + subtitle."""

PAD_BODY = f"0 {PAGE_X} 2rem {PAGE_X}"
"""Everything below the header shares this gutter and bottom breathing room."""

PAD_EMPTY = f"4rem {PAGE_X}"
"""Empty states sit lower and centred; the extra top space is deliberate."""

# ---------------------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------------------

RADIUS_CARD = "var(--q-radius-card)"
RADIUS_CONTROL = "var(--q-radius-control)"

# ---------------------------------------------------------------------------------------
# Surfaces and text
# ---------------------------------------------------------------------------------------

BORDER = f"1px solid {rx.color('gray', 5)}"
BORDER_STRONG = f"1px solid {rx.color('gray', 7)}"
SURFACE_BG = rx.color("gray", 2)
SURFACE_BG_RAISED = rx.color("gray", 3)

TEXT_MUTED = rx.color("gray", 10)
"""Secondary copy: subtitles, helper text, table meta. Contrast-safe on gray 1-3."""

TEXT_FAINT = rx.color("gray", 8)
"""Placeholders and decorative icons only — NOT for text that must be read."""

TEXT_STRONG = rx.color("gray", 12)

# ---------------------------------------------------------------------------------------
# Tones (semantic colour roles) → Radix scale names
# ---------------------------------------------------------------------------------------

Tone = Literal["accent", "ok", "warn", "error", "info", "neutral"]

TONE_SCALE: dict[str, str] = {
    "accent": "accent",  # the brand action colour (teal via rxconfig)
    "ok": "grass",  # healthy, positive, delivered
    "warn": "amber",  # needs attention, degraded, demo/beta
    "error": "tomato",  # failed, revoked, negative
    "info": "blue",  # informational, in progress
    "neutral": "gray",  # unknown, pending, neutral sentiment
}


def tone_scale(tone: str) -> str:
    """Radix scale name for a tone (valid for ``rx.color``). Unknown tones fall back to
    neutral on purpose: an unmapped state must never render as accent or as an alarm."""
    return TONE_SCALE.get(tone, "gray")


def tone_scheme(tone: str) -> dict[str, str]:
    """``color_scheme`` kwargs for a Radix component. Radix components take no
    ``"accent"`` literal — omitting the prop *is* accent — so this returns ``{}`` for
    the accent tone and ``{"color_scheme": <scale>}`` otherwise. Spread it:
    ``**T.tone_scheme(tone)``."""
    scale = tone_scale(tone)
    return {} if scale == "accent" else {"color_scheme": scale}


def tone_color(tone: str, step: int = 9) -> rx.Var:
    """A Radix step of a tone's scale (``9`` = solid, ``11`` = text, ``2/3`` = surface)."""
    return rx.color(tone_scale(tone), step)


# ---------------------------------------------------------------------------------------
# Platform identity → Radix scale names (always used with the ``outline`` badge variant,
# so identity never looks like a status — see docs/design-system.md §5.3)
# ---------------------------------------------------------------------------------------

PLATFORM_SCALE: dict[str, str] = {
    "instagram": "pink",
    "tiktok": "purple",
    "facebook": "blue",
    "whatsapp": "green",
}

PLATFORM_LABEL: dict[str, str] = {
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "facebook": "Facebook",
    "whatsapp": "WhatsApp",
}


def platform_scale(platform: str) -> str:
    return PLATFORM_SCALE.get(platform, "gray")


# ---------------------------------------------------------------------------------------
# Icon sizes (lucide, in px) — three sizes, no in-betweens
# ---------------------------------------------------------------------------------------

ICON_SM = 14  # inside size-1 buttons/badges
ICON_MD = 18  # nav items, size-2 buttons, inline with body text
ICON_LG = 40  # empty-state illustrations
