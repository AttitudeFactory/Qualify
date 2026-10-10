"""Design tokens for the Qualify CRM UI.

The single place a screen may take a colour, radius, gutter or duration from. Colours
resolve to Radix Themes scales (so light/dark is free and every step has a defined
contrast role); layout, shape and motion resolve to the ``--q-*`` CSS variables declared
in ``assets/qualify.css`` so a page reads the same value the stylesheet does.

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
"""Horizontal gutter inside a page panel (2rem desktop, 1rem below 900px)."""

GAP = "var(--q-gap)"
"""Air between the floating blocks — sidebar islands, main panel, page edge."""

SIDEBAR_W = "var(--q-sidebar-w)"
SIDEBAR_ZEN_W = "var(--q-sidebar-zen-w)"
CONTENT_MAX = "var(--q-content-max)"

PAD_HEADER = f"1.5rem {PAGE_X} 1rem {PAGE_X}"
"""Page header block: title row + subtitle."""

PAD_BODY = f"1.25rem {PAGE_X} 2rem {PAGE_X}"
"""Everything below the header shares this gutter and bottom breathing room. The top
1.25rem (QUA-146, 2026-10-09; it was 0) keeps the first block off the header's hairline
(`.q-page-header`'s bottom edge) — with 0 every page's first card touched that line."""

PAD_EMPTY = f"4rem {PAGE_X}"
"""Empty states sit lower and centred; the extra top space is deliberate."""

# ---------------------------------------------------------------------------------------
# Shape and elevation
# ---------------------------------------------------------------------------------------

RADIUS_ISLAND = "var(--q-radius-island)"
"""Floating surfaces: sidebar islands, the main page panel."""

RADIUS_CARD = "var(--q-radius-card)"
RADIUS_CONTROL = "var(--q-radius-control)"

ELEV_ISLAND = "var(--q-elev-island)"
"""Resting elevation of any surface that floats on the app ground."""

ELEV_LIFT = "var(--q-elev-lift)"
"""Hover elevation — only for surfaces that actually do something when clicked."""

ELEV_OVERLAY = "var(--q-elev-overlay)"
"""Dialogs, popovers, the zen fly-out: things that sit above the page."""

# ---------------------------------------------------------------------------------------
# Motion. Two curves only: `EASE` for opacity/colour, `SPRING` for size and shape.
# ---------------------------------------------------------------------------------------

EASE = "var(--q-ease)"
SPRING = "var(--q-spring)"
DUR_FAST = "var(--q-dur-fast)"
DUR = "var(--q-dur)"
DUR_SLOW = "var(--q-dur-slow)"

# ---------------------------------------------------------------------------------------
# Surfaces and text
# ---------------------------------------------------------------------------------------

GROUND = "var(--color-background)"
"""The app ground the islands float on — Radix's own page background."""

SURFACE_BG = "var(--color-panel-solid)"
"""An island's fill. Radix pairs it with GROUND in both themes, so it reads as
'above the page' in light *and* dark without a per-theme override."""

CARD_BG = rx.color("gray", 2)
"""A card's fill *inside* a page panel. One step off the panel so the card reads as a
block on it — in light the card is slightly grey on white, in dark slightly lighter
than the panel. Do not use SURFACE_BG here: it would match the panel exactly."""

SURFACE_BG_RAISED = rx.color("gray", 3)

BORDER = f"1px solid {rx.color('gray', 5)}"
BORDER_STRONG = f"1px solid {rx.color('gray', 7)}"

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
# Navigation zones. The sidebar groups modules by what the operator is doing, and the
# tint is a *surface*, never a state: it stays at the faint end of the scale so it can
# never be mistaken for a status colour (docs/design-system.md §4.2). Since the menu is
# liquid glass (assets/qualify.css, "Liquid glass menu") the tint is an alpha wash UNDER
# the glass material rather than an opaque fill — an opaque step would hide the ground
# the glass is meant to refract.
# ---------------------------------------------------------------------------------------

ZONE_SCALE: dict[str, str] = {
    "listen": "accent",  # inbound — what the market says
    "publish": "iris",  # outbound — what the business says
    "business": "gray",  # sales metrics, outside the two planes
}


def zone_tint(zone: str) -> rx.Var:
    """Island wash for a zone (alpha step 3 — a surface, not a signal)."""
    return rx.color(ZONE_SCALE.get(zone, "gray"), 3, alpha=True)


def zone_line(zone: str) -> rx.Var:
    """The zone's hairline colour (alpha step 6), drawn by the island's own border."""
    return rx.color(ZONE_SCALE.get(zone, "gray"), 6, alpha=True)


def zone_ink(zone: str) -> rx.Var:
    """The zone's eyebrow label — step 11 so it stays readable on its own tint."""
    return rx.color(ZONE_SCALE.get(zone, "gray"), 11)


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
