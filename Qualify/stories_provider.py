"""The seam between the `/stories` trending panel and the real Meta trend-audio
backend (QUA-106 V1 redesign). Same posture `publishing_provider.py` documents for
its own reads/writes: a direct in-process projection over the published seam, no
HTTP hop.

Publishing a Story is NOT here — `stories_state.py` calls `publishing_provider.
start_publish`/`poll_publish` directly (`media_product_type="STORIES"`), the exact
same seam `/publish` uses. This module only ever projects Meta's trending-audio
reference list.
"""

from __future__ import annotations

from uuid import UUID

from qualify_api.stories import suggest_trend_audio as _suggest_trend_audio
from qualify_api.stories.trend_audio_client import TrendAudioOption

from .stories_vm import TrendAudioOptionVM, build_trend_audio_vm

__all__ = ["suggest_trend_audio"]


def _trend_to_vm(option: TrendAudioOption) -> TrendAudioOptionVM:
    return build_trend_audio_vm(
        audio_id=option.audio_id,
        title=option.title,
        artist_or_creator=option.artist_or_creator,
        duration_ms=option.duration_ms,
        rank=option.rank,
        preview_url=option.preview_url,
    )


async def suggest_trend_audio(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    audio_type: str = "music",
    search_query: str = "",
) -> list[TrendAudioOptionVM]:
    """Never raises — a failed lookup is an empty list (see
    `qualify_api.stories.suggest_trend_audio_using`'s own degrade-don't-block
    posture). `search_query` empty means Meta's own trending list; non-empty
    searches Meta's catalog by keyword (`content-publishing/audio-api.md`)."""
    options = await _suggest_trend_audio(
        tenant_id=tenant_id,
        connection_id=connection_id,
        audio_type=audio_type,
        search_query=search_query or None,
    )
    return [_trend_to_vm(o) for o in options]
