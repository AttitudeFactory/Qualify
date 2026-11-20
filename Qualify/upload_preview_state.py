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

Nothing here fails the editor: any error leaves the original playing, without a notice.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
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
    "PlayChoice",
    "UploadPreviewState",
    "choose_play",
    "notice_condition",
    "original_size",
    "play_key_for",
    "reported_size",
    "upload_preview_notice",
]
