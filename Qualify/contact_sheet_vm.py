"""The contact sheet before «Aprobar» — its words and frames (EF-18, m-25026598; ADR 50 D8).

Pure: no Reflex, no database. `contact_sheet_provider` reads the sheet
(`qualify_api.creative.contact_sheet.DbContactSheets`) and mints each frame's `/r2media`
path; this module decides which frames may be shown and what each one says.

- Only keys of the viewing business (`t/{tenant}/…`) ever become a frame: a key of
  another business, or one with `..`, is dropped before any path is minted.
- A frame shows the second it was taken at as «0:03»; a screen reader hears «Cuadro de
  tu video en el segundo 3» (`alt`) and «Ver más grande el cuadro del segundo 3» (the
  button) — «del minuto 1:05» past the minute.
- The sheet is informative (D8): nothing here can hold «Aprobar».
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from uuid import UUID

from qualify_api.creative.contact_sheet import (
    CONTACT_SHEET_HELP,
    CONTACT_SHEET_TITLE,
    ContactSheetView,
)

#: What the owner reads above the frames (the ticket's texts, kept by the server module
#: so the screen and the backend never drift).
TITLE = CONTACT_SHEET_TITLE
HELP = CONTACT_SHEET_HELP
#: The enlarged frame's dialog: its one way out.
CLOSE_LABEL = "Cerrar"
#: The enlarged frame's dialog: what to look at (its accessible description).
ZOOM_HELP = "Fíjate que el texto se lea completo y no tape tu producto."
#: Under the server's help, on the screen (ux-designer, 2026-11-25): the frames open.
TAP_HINT = "Toca un cuadro para verlo más grande."
#: What to do when a frame looks wrong — the REAL way on each screen, shown only while
#: that way is offered. On the Clip's page «Editar texto» edits the publication's copy,
#: not the words on the video: the way is «Pedir otra versión» (its button «Regenerar»).
FIX_CLIP = "Si algo se ve mal, pide otra versión antes de aprobar."
#: «Tu video completo»: «Cambiar esta» on a part opens its panel, «Crear otra versión».
FIX_PARTS = (
    "Si algo se ve mal, toca «Cambiar esta» en la parte que quieras y crea otra "
    "versión antes de aprobar."
)

#: `(key) -> "/r2media/<token>"` or "" (no token could be minted).
Mint = Callable[[str], str]


@dataclass(frozen=True)
class SheetFrame:
    """One frame as the grid draws it."""

    url: str
    time: str  # «0:03», visible under the frame
    alt: str  # «Cuadro de tu video en el segundo 3»
    zoom: str = ""  # «Ver más grande el cuadro del segundo 3» (the button's name)

    def as_dict(self) -> dict[str, str]:
        return {"url": self.url, "time": self.time, "alt": self.alt, "zoom": self.zoom}


#: Below this the sheet's seconds are too close to tell apart: tenths are shown.
TENTHS_BELOW_SECONDS = 10.0


def _seconds(value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return number if math.isfinite(number) and number > 0 else 0.0


def time_label(seconds: float, tenths: bool = False) -> str:
    """«0:03», «1:05» — minutes and whole seconds (never negative). With `tenths`, rounded
    to the tenth with a decimal comma: «0:00,5», «0:01,2», «1:05,5»."""
    if not tenths:
        whole = int(math.floor(_seconds(seconds)))
        return f"{whole // 60}:{whole % 60:02d}"
    count = round(_seconds(seconds) * 10)  # in tenths, so 59.96 carries to «1:00,0»
    whole, tenth = divmod(count, 10)
    return f"{whole // 60}:{whole % 60:02d},{tenth}"


def spoken_time(seconds: float, tenths: bool = False) -> str:
    """The second as a screen reader says it: «segundo 3», «segundo 0,5»; past the
    minute, «minuto 1:05», «minuto 1:05,5» (the caller puts the article)."""
    label = time_label(seconds, tenths)
    minutes, rest = label.split(":", 1)
    if minutes != "0":
        return f"minuto {label}"
    whole, _, tenth = rest.partition(",")
    return f"segundo {int(whole)}" + (f",{tenth}" if tenth else "")


def frame_alt(seconds: float, tenths: bool = False) -> str:
    """«Cuadro de tu video en el segundo 3» — the picture's `alt` and its dialog title."""
    return f"Cuadro de tu video en el {spoken_time(seconds, tenths)}"


def zoom_label(seconds: float, tenths: bool = False) -> str:
    """«Ver más grande el cuadro del segundo 3» / «… del minuto 1:05» (the button)."""
    return f"Ver más grande el cuadro del {spoken_time(seconds, tenths)}"


def needs_tenths(times: Iterable[float]) -> bool:
    """Tenths when the video lasts under `TENTHS_BELOW_SECONDS` (its last frame is its
    end) or when two frames fall on the same whole second — never two equal labels."""
    seconds = [_seconds(t) for t in times]
    if not seconds:
        return False
    if max(seconds) < TENTHS_BELOW_SECONDS:
        return True
    return len({int(math.floor(t)) for t in seconds}) < len(seconds)


def business_key(tenant_id: UUID, key: str) -> bool:
    """Whether `key` is an object of THIS business (`t/{tenant}/…`), never another's."""
    return bool(key) and ".." not in key and key.startswith(f"t/{tenant_id}/")


def sheet_frames(
    tenant_id: UUID, view: ContactSheetView | None, video_key: str, mint: Mint
) -> list[SheetFrame]:
    """The frames to draw for the video on screen (`video_key`), in the sheet's order —
    none when there is no sheet, when it was made from another file than the one shown,
    or when not one frame could get a path. A frame of another business is dropped."""
    if view is None or not video_key or view.video_key != video_key:
        return []
    tenths = needs_tenths(frame.time_s for frame in view.frames)
    return list(_frames(tenant_id, view.frames, mint, tenths))


def _frames(tenant_id: UUID, frames: Iterable, mint: Mint, tenths: bool) -> Iterable[SheetFrame]:
    for frame in frames:
        if not business_key(tenant_id, frame.key):
            continue
        url = mint(frame.key)
        if not url:
            continue
        yield SheetFrame(
            url=url,
            time=time_label(frame.time_s, tenths),
            alt=frame_alt(frame.time_s, tenths),
            zoom=zoom_label(frame.time_s, tenths),
        )


__all__ = [
    "CLOSE_LABEL",
    "FIX_CLIP",
    "FIX_PARTS",
    "HELP",
    "TAP_HINT",
    "TITLE",
    "ZOOM_HELP",
    "SheetFrame",
    "business_key",
    "frame_alt",
    "needs_tenths",
    "sheet_frames",
    "spoken_time",
    "time_label",
    "zoom_label",
]
