"""How the referentes screens write a figure — shared by the referentes search
(`Qualify/creator_discovery.py`) and the reel cards (`qualify_api.referentes.reels`), so
neither imports the other just to format a number (m-24854844)."""

from __future__ import annotations


def compact_count(value: int | None) -> str:
    """«1.2M», «92K», «640», «—» for unknown. The unit is chosen from the ROUNDED figure:
    999 950 is «1M», never «1000K»."""
    if value is None:
        return "—"
    if value >= 999_950:
        return f"{value / 1_000_000:.1f}M".replace(".0M", "M")
    if value >= 1_000:
        return f"{value / 1_000:.1f}K".replace(".0K", "K")
    return str(value)


__all__ = ["compact_count"]
