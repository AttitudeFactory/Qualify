"""ED-09 (m-25026643; ADR 50 D-E2): when the owner comes back to the editor, its preview
plays the light 480p copy of the video they uploaded — only the editor's OWN video (the
one `resolve_clip_preview` mints); the Clip's other videos keep their original.

- `play_key_for` (called by `CreativeState.resolve_clip_preview` before it mints the
  `/r2media` path): the copy's key once it is made AND the original's size is known,
  else the original's. It also records, on the editor's state, the ORIGINAL's upright
  size for the copy (`_clip_copy_sizes`), and on `UploadPreviewState` whether the copy
  failed for good.
- `reported_size` (called by `_report_clip_source`; pure: `original_size`): while the
  copy plays, «Cortar» is judged with the original's size the server sent, never with
  the copy's 480p that the browser measures — else every video would be told it looks
  blurry.
- `play_key_for` also asks for the copy again (in the background, `upload_preview_provider`;
  one job per file) when it was never asked for or its last failure is worth a retry.
- A renewal of a path that died in the browser (`_clip_preview_renewed`) mints the
  ORIGINAL: a copy that does not play here never leaves the video broken for good.
- `upload_preview_notice`: a small muted line in the step's scrolling part, next to «Esta
  vista previa es gratis.», when the copy failed for good — never while the preview says
  it cannot show the video at all (`PREVIEW_UNAVAILABLE`). It never stops the piece: the
  preview plays the original, and the assembly always reads the original.

ED-11b (m-25029110): `read_strips` reads the frame strip of each of the Clip's uploaded
videos (made by the media-worker with the copy) and mints its `/r2media` path for the
session's business; `CreativeState.read_clip_frame_strips` keeps reading while one is on
its way and asks for a strip that is wanted (a copy made before strips existed). The strip
only DRAWS the timeline (`timeline_vm.strip_cells`): it never reaches the recipe.

Nothing here fails the editor: any error leaves the original playing, without a notice.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import reflex as rx
from qualify_api.creative.upload_previews import STATUS_NONE, previews_for

from . import upload_preview_provider
from .ui import tokens as T

logger = logging.getLogger(__name__)

#: Next to «Esta vista previa es gratis.» when the 480p copy could not be made
#: (ux-designer, option B chosen by Deivid).
NOTICE_TEXT = "Tu video puede tardar un poco en verse aquí. El video final no cambia."


@dataclass(frozen=True)
class PlayChoice:
    """What the editor's preview plays for one video."""

    play_key: str
    #: The ORIGINAL's upright size when `play_key` is the copy; 0 otherwise.
    width: int = 0
    height: int = 0
    #: The copy failed for good: the notice shows (the original plays).
    failed: bool = False
    #: The copy was never asked for, or its last failure is worth a retry: ask again.
    ask: bool = False


def choose_play(tenant_id: UUID, key: str) -> PlayChoice:
    """`key`'s copy when it is made and its original's size is known, else `key` itself
    (blocking: one query; none for a key that is not this tenant's uploaded video)."""
    try:
        preview = previews_for(tenant_id, [key]).get(key)
    except Exception as exc:  # noqa: BLE001 — the original still plays
        logger.warning("upload preview not read: %s", type(exc).__name__)
        return PlayChoice(key)
    if preview is None:
        return PlayChoice(key)
    if preview.ready and preview.source_width > 1 and preview.source_height > 1:
        return PlayChoice(preview.preview_key, preview.source_width, preview.source_height)
    retry = preview.status == "failed" and not preview.failed_for_good
    return PlayChoice(
        key, failed=preview.failed_for_good, ask=preview.status == STATUS_NONE or retry
    )


def original_size(
    sizes: Mapping[str, Sequence[int]], key: str, width: int, height: int
) -> tuple[int, int]:
    """The size «Cortar» judges `key` by: the original's (`sizes`, recorded while its copy
    plays) when known, else what the browser measured."""
    size = sizes.get(key) or ()
    if len(size) == 2 and int(size[0]) > 1 and int(size[1]) > 1:
        return int(size[0]), int(size[1])
    return width, height


def reported_size(state: Any, key: str, width: int, height: int) -> tuple[int, int]:
    """`original_size` over the editor's own record (`state._clip_copy_sizes`)."""
    return original_size(state._clip_copy_sizes, key, width, height)


class UploadPreviewState(rx.State):
    """The editor's video whose 480p copy failed for good ("" = none)."""

    failed_key: str = ""


async def play_key_for(state: Any, tenant_id: UUID, key: str) -> str:
    """What `resolve_clip_preview` mints for the editor's own video `key`. Records the
    original's size for the copy on `state._clip_copy_sizes` and the notice on
    `UploadPreviewState`, and asks for a copy never asked for or worth a retry; never
    raises. A renewal of a path that died in the browser plays the original."""
    if getattr(state, "_clip_preview_renewed", "") == key:
        choice = PlayChoice(key)
    else:
        choice = await asyncio.to_thread(choose_play, tenant_id, key)
    if choice.ask:  # in the background, one job per file: never waited for
        upload_preview_provider.ask_for_preview(tenant_id, str(state._brand_id or ""), key)
    sizes = {k: v for k, v in dict(state._clip_copy_sizes).items() if k != key}
    if choice.play_key != key:
        sizes[key] = [choice.width, choice.height]
    state._clip_copy_sizes = sizes
    if getattr(state, "_clip_preview_renewed", "") == key:
        return choice.play_key  # the notice stays as it was
    try:
        notice = await state.get_state(UploadPreviewState)
        notice.failed_key = key if choice.failed else ""
    except Exception as exc:  # noqa: BLE001 — a notice is never worth failing the preview
        logger.warning("upload preview notice not set: %s", type(exc).__name__)
    return choice.play_key


# -- ED-11b (m-25029110): the frame strip of each uploaded video on the timeline ----------

#: How long the timeline waits before reading again a strip still on its way: growing
#: (6 s, 12 s, 30 s, then every minute) — the media-worker may take minutes (live test
#: 2026-11-26: more than 4) — until `STRIP_GIVE_UP_SECONDS` of waiting, while the editor
#: is on screen. A reader that gave up is armed again when the owner touches the timeline.
STRIP_DELAYS: tuple[float, ...] = (6.0, 12.0, 30.0)
STRIP_MAX_DELAY = 60.0
STRIP_GIVE_UP_SECONDS = 30 * 60.0
#: A reader that has not been heard of for this long is gone (a restart): a new one starts.
STRIP_READER_ALIVE_SECONDS = STRIP_MAX_DELAY + 60.0


def strip_delay(attempt: int) -> float:
    """The wait before read number `attempt` (1 = the second read)."""
    if attempt < 1:
        return 0.0
    return STRIP_DELAYS[attempt - 1] if attempt <= len(STRIP_DELAYS) else STRIP_MAX_DELAY


def strip_waits() -> list[float]:
    """Every wait of one reader, in order, until it gives up (their sum ≤ the give-up)."""
    waits: list[float] = []
    attempt = 1
    while sum(waits) + strip_delay(attempt) <= STRIP_GIVE_UP_SECONDS:
        waits.append(strip_delay(attempt))
        attempt += 1
    return waits


#: What a strip still on its way looks like (its copy's or its own job).
_ON_ITS_WAY = frozenset({"queued", "running"})


@dataclass(frozen=True)
class StripRead:
    """One read of the strips of the Clip's uploaded videos.

    `strips`: per video key, the strip as the timeline draws it — its `/r2media` path
    (``url``) and its layout (`FrameStrip`'s numbers); only the strips made and minted.
    `ask`: the videos whose strip is wanted (`UploadPreview.strip_wanted`: a v1 copy, or a
    failure worth a retry) — the screen asks for them, in the background. `waiting`: some
    strip is still on its way, so reading again later is worth it."""

    strips: dict[str, dict[str, Any]]
    ask: tuple[str, ...] = ()
    waiting: bool = False


def _mint_strip(tenant_id: UUID, key: str) -> str:
    """The strip's `/r2media` path ("" when no token can be minted: no strip, the
    picture of before stays)."""
    from qualify_creative.video.upload_preview import STRIP_CONTENT_TYPE  # noqa: PLC0415

    from .r2_media import issue_view_path  # noqa: PLC0415

    try:
        return issue_view_path(tenant_id, key, "image", STRIP_CONTENT_TYPE)
    except Exception as exc:  # noqa: BLE001 — a strip is not worth failing the timeline
        logger.warning("frame strip token not issued: %s", type(exc).__name__)
        return ""


def read_strips(
    tenant_id: UUID, keys: Sequence[str], asked: Collection[str] = frozenset()
) -> StripRead:
    """The strips of `keys` (blocking: ONE query, then a token per strip made). A key
    that is not this tenant's uploaded video is left out (`previews_for`); the strip's
    own key comes from the service, and `issue_view_path` checks it again against the
    session's business. Never raises: a failed read is no strip, nothing waiting.

    `asked`: the videos this reader already asked for. A video to ask for (never asked,
    a v1 copy, a failure worth a retry) is asked ONCE and waited for; asked already and
    still there, the request failed quietly: nothing to wait for. A strip made whose path
    could not be minted is waited for (read again)."""
    try:
        previews = previews_for(tenant_id, list(keys))
    except Exception as exc:  # noqa: BLE001 — the timeline keeps its pictures
        logger.warning("frame strips not read: %s", type(exc).__name__)
        return StripRead({})
    strips: dict[str, dict[str, Any]] = {}
    ask: list[str] = []
    waiting = False
    for key, preview in previews.items():
        strip = preview.strip
        if strip is not None:
            url = _mint_strip(tenant_id, strip.key)
            if url:
                strips[key] = {
                    "url": url,
                    "frames": strip.frames,
                    "columns": strip.columns,
                    "rows": strip.rows,
                    "tile_width": strip.tile_width,
                    "tile_height": strip.tile_height,
                    "interval_s": strip.interval_s,
                    "offset_s": strip.offset_s,
                }
            else:
                waiting = True  # made, but no path now: read again (a new token)
            continue
        retry = preview.status == "failed" and not preview.failed_for_good
        if preview.strip_wanted or preview.status == STATUS_NONE or retry:
            # a v1 copy, a failure worth a retry — or a video whose copy was never asked
            # for: only the upload (`ask_for_previews`) and the editor's OWN video
            # (`play_key_for`) ask, so another video of the Clip whose request was lost
            # would never get one. `request_preview` is free and never repeats work.
            if key not in asked:
                ask.append(key)
                waiting = True
        elif preview.status in _ON_ITS_WAY or preview.strip_status in _ON_ITS_WAY:
            waiting = True
    return StripRead(strips, tuple(ask), waiting)


def strip_video_keys(videos: Sequence[Mapping[str, Any]]) -> list[str]:
    """The Clip's videos that may have a strip: the owner's own (a reel's reference video
    is not on the timeline), videos by their name, once each."""
    keys = [str(v.get("key") or "") for v in videos if v.get("source") != "reel"]
    return [k for k in dict.fromkeys(keys) if upload_preview_provider.is_video_key(k)]


def notice_condition(
    failed_key: Any, video_key: Any, playable: Any, broken: Any, broken_key: Any
) -> Any:
    """Whether the notice shows — on plain values (tests) and on the states' Vars (the
    component), the same expression: the editor's own video's copy failed for good, the
    preview plays it, and the browser did not report it broken (then the preview says
    `PREVIEW_UNAVAILABLE`, and a second line would only repeat it)."""
    said_broken = broken & (broken_key == video_key)
    return (
        (failed_key != "") & (failed_key == video_key) & playable & (said_broken == False)  # noqa: E712 — a Var comparison, not a Python bool
    )


def upload_preview_notice() -> rx.Component:
    """The small muted line for the editor's own video when its copy failed for good."""
    from .creative_state import CreativeState as S  # noqa: PLC0415 — it imports this module

    shown = notice_condition(
        UploadPreviewState.failed_key,
        S.clip_edit_video_key,
        S.clip_edit_video_playable,
        S.clip_source_broken,
        S.clip_source_key,
    )
    return rx.cond(shown, rx.text(NOTICE_TEXT, size="1", color=T.TEXT_MUTED))


__all__ = [
    "NOTICE_TEXT",
    "STRIP_DELAYS",
    "STRIP_GIVE_UP_SECONDS",
    "STRIP_MAX_DELAY",
    "STRIP_READER_ALIVE_SECONDS",
    "PlayChoice",
    "StripRead",
    "UploadPreviewState",
    "choose_play",
    "notice_condition",
    "original_size",
    "play_key_for",
    "read_strips",
    "reported_size",
    "strip_delay",
    "strip_waits",
    "strip_video_keys",
    "upload_preview_notice",
]
