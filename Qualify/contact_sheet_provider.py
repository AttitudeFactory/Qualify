"""Backend access of the contact sheet before «Aprobar» (EF-18, m-25026598).

Plain, blocking Python — the state runs it with `asyncio.to_thread`. The sheet is read
through `DbContactSheets`, which opens `tenant_session` itself (RLS: another business's
draft reads as no sheet); each frame's `/r2media/<token>` is minted by
`r2_media.issue_view_path`, which again refuses a key outside the viewing business.

`READER` and `MINT` are module attributes so a test can swap them for doubles.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from qualify_api.creative.contact_sheet import DbContactSheets

from .contact_sheet_vm import sheet_frames
from .r2_media import issue_view_path

logger = logging.getLogger(__name__)

#: The sheet's reader (the tenant door inside).
READER = DbContactSheets()


def _mint(tenant_id: UUID, key: str) -> str:
    """A frame's `/r2media` path ("" when no token can be minted: that frame is left out,
    never the screen)."""
    try:
        return issue_view_path(tenant_id, key, "image", "image/jpeg")
    except Exception as exc:  # noqa: BLE001 — a frame is not worth failing the screen
        logger.warning("contact sheet frame token not issued: %s", type(exc).__name__)
        return ""


MINT = _mint


@dataclass(frozen=True)
class SheetRead:
    """One read: `made` says whether the worker already made the sheet (else waiting is
    worth it); `frames` are the drawable ones for the video on screen, as dicts."""

    made: bool
    frames: tuple[dict[str, str], ...] = ()


def read_sheet(tenant_id: UUID, draft_id: UUID, video_key: str) -> SheetRead:
    """The sheet of `draft_id`'s visible video, drawn for `video_key` (the file the screen
    shows). Raises what the reader raises: the state logs it and shows no sheet."""
    view = READER.read(tenant_id=tenant_id, draft_id=draft_id)
    if view is None:
        return SheetRead(made=False)
    frames = sheet_frames(tenant_id, view, video_key, lambda key: MINT(tenant_id, key))
    return SheetRead(made=True, frames=tuple(frame.as_dict() for frame in frames))


__all__ = ["MINT", "READER", "SheetRead", "read_sheet"]
