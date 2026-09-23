"""View-models for the `/stories` screen's trending/reference panel (QUA-106 V1
redesign). Publishing itself has no Stories-specific VM anymore — `/stories` reuses
`publishing_vm.ConnectionOptionVM`/`PendingItemVM`/`PublishAttemptVM` directly, the
exact same types `/publish` uses, since it is the exact same publish flow underneath
(`media_product_type="STORIES"` is the only difference, chosen in `stories_state.py`).

Kept free of Reflex and network imports so a whitelist-style test can assert this
stays true as the module grows, same convention `publishing_vm.py`/`creative_vm.py`
already follow.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def _duration_label(duration_ms: int | None) -> str:
    if not duration_ms or duration_ms <= 0:
        return ""
    total_seconds = duration_ms // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


@dataclass(frozen=True)
class TrendAudioOptionVM:
    """One audio suggested as 'trending' — a REFERENCE for the human, never a value
    sent to Meta's publish call (QUA-106 decision). `display_label` is computed once
    in `build_trend_audio_vm`, never as a `@property` on a Reflex-serialized dataclass.

    `user_count`/`recommend_status` (QUA-107) are populated only for a TikTok song
    enriched via `/v1/tiktok/song` — Meta's own `ig_audio` suggestion carries neither,
    so that call site simply leaves both `None`. Shared type rather than a third VM:
    the shape (id/title/artist/duration/rank) already matched exactly.

    `preview_url` (QUA-107 follow-up) is a temporary vendor/Meta URL for the human to
    LISTEN to as reference — never downloaded, never persisted, never threaded into a
    publish call. `has_preview` is precomputed so the page never string-compares it."""

    audio_id: str
    title: str
    artist_or_creator: str
    duration_label: str
    rank: int
    display_label: str = ""
    user_count: int | None = None
    recommend_status: int | None = None
    has_user_count: bool = False
    has_recommend_status: bool = False
    preview_url: str = ""
    has_preview: bool = False


@dataclass(frozen=True)
class TrendingVideoVM:
    """One trending TikTok video or Instagram Reel (QUA-107) — a REFERENCE only,
    never downloaded, never persisted. `has_music`/`has_thumbnail` are precomputed so
    the page never has to test a string for emptiness."""

    source: str  # "tiktok" | "instagram"
    external_id: str
    caption: str
    author_label: str
    likes_label: str
    comments_label: str
    plays_label: str
    created_label: str
    permalink: str
    thumbnail_url: str
    music_id: str
    music_title: str
    rank: int
    has_music: bool = False
    has_thumbnail: bool = False


def build_trend_audio_vm(
    *,
    audio_id: str,
    title: str,
    artist_or_creator: str,
    duration_ms: int | None,
    rank: int,
    user_count: int | None = None,
    recommend_status: int | None = None,
    preview_url: str = "",
) -> TrendAudioOptionVM:
    duration_label = _duration_label(duration_ms)
    parts = [title]
    if artist_or_creator:
        parts.append(f"· {artist_or_creator}")
    if duration_label:
        parts.append(f"({duration_label})")
    return TrendAudioOptionVM(
        audio_id=audio_id,
        title=title,
        artist_or_creator=artist_or_creator,
        duration_label=duration_label,
        rank=rank,
        display_label=" ".join(parts),
        user_count=user_count,
        recommend_status=recommend_status,
        preview_url=preview_url,
        has_preview=bool(preview_url),
        has_user_count=user_count is not None,
        has_recommend_status=recommend_status is not None,
    )


def _count_label(value: int | None) -> str:
    """`12_400 -> "12.4K"`, `1_900_000 -> "1.9M"`, `850 -> "850"`, `None -> ""` — an
    omitted count must render as nothing, never as "0"."""
    if value is None:
        return ""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def _created_label(value: datetime | None) -> str:
    return value.strftime("%d %b %Y") if value is not None else ""


def build_trending_video_vm(
    *,
    source: str,
    external_id: str,
    caption: str,
    author_handle: str,
    author_display_name: str,
    likes: int | None,
    comments: int | None,
    plays: int | None,
    created_at: datetime | None,
    permalink: str,
    thumbnail_url: str,
    music_id: str,
    music_title: str,
    rank: int,
) -> TrendingVideoVM:
    author_label = f"@{author_handle}" if author_handle else author_display_name
    return TrendingVideoVM(
        source=source,
        external_id=external_id,
        caption=caption,
        author_label=author_label,
        likes_label=_count_label(likes),
        comments_label=_count_label(comments),
        plays_label=_count_label(plays),
        created_label=_created_label(created_at),
        permalink=permalink,
        thumbnail_url=thumbnail_url,
        music_id=music_id,
        music_title=music_title,
        rank=rank,
        has_music=bool(music_id),
        has_thumbnail=bool(thumbnail_url),
    )
