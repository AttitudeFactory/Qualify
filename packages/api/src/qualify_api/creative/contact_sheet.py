"""The contact sheet kept with a piece, and how a screen reads it (EF-18, m-25026598;
ADR 50 D8, D-E1).

Made by the creative worker right where the composed video is on its disk, inside the
heavy-video gate that step already holds (`heavy_video.assembling` / `joining`):

- a `local` Clip or part (`video_pipeline.local.produce_local`, stage `local`);
- a Clip made by Seedance with texts or layers, its composed preview
  (`MediaProducer._compose_clip` → `recompose.ClipComposer.compose`, stage `preview`);
- the joined preview of a video by parts, «Tu video completo»
  (`part_join.join_preview`, stage `join`).

`keep_contact_sheet` makes the frames (`qualify_creative.video.contact_sheet`), keeps each
JPEG and the one-row sheet beside the piece in R2 — inside the piece's folder
`t/{tenant}/generated/{draft}/…`, so retention deletes them with it (ADR 39) and no door
serves them once the piece is purged — and returns the block the asset records in
`params["contact_sheet"]`: the process' version and settings, the source video (its key,
sha256 and stage, its revision or join fingerprint) and, per frame, the second it was
taken at, its key and sha256. Cost 0: PyAV and Pillow; no AI looks at it (D8).

Best effort: a sheet that cannot be made or kept is logged and left out (None) — it
never fails, delays or charges the piece; the screen then shows the video alone.
Idempotent: the same video gives the same JPEG bytes, kept under the same names (a
revision's folder, or the join's fingerprint), so a retried step reuses the files and
records the same block; nothing is duplicated.

The screen reads it with `DbContactSheets.read(tenant_id=…, draft_id=…)` — the draft's
visible video and its sheet, only when the sheet was made from THAT file
(`contact_sheet_of`: a Seedance final replaces the preview it was made from, and the
preview's sheet is then not offered).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

#: The asset's params key that holds the sheet.
CONTACT_SHEET_PARAMS_KEY = "contact_sheet"
#: The file names inside the piece's folder (prefixed for a join: `join-<fp>-`).
FRAME_NAME = "contact-{number}.jpg"
SHEET_NAME = "contact-sheet.jpg"

#: What the owner reads above the sheet (the ticket's texts, `qualify-copy-es`).
CONTACT_SHEET_TITLE = "Revisa tu video antes de aprobarlo"
CONTACT_SHEET_HELP = (
    "Estos son cuadros de tu video con el texto y los efectos puestos. Fíjate que el "
    "texto se lea completo y no tape tu producto."
)

#: `keep(name, data)` → the key the JPEG was kept under, or None when it was not.
Keep = Callable[[str, bytes], str | None]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def keep_contact_sheet(
    video: Path | str,
    keep: Keep,
    *,
    source: Mapping[str, Any],
    prefix: str = "",
) -> dict[str, Any] | None:
    """The sheet of the composed video at `video`, kept through `keep`, as the block for
    `params["contact_sheet"]` — or None when it could not be made or kept (logged; the
    piece goes on without it). `source` says where the video comes from (`stage`, and
    `object_key`, `revision` or `fingerprint` when known); its sha256 is added here."""
    from qualify_creative.video.contact_sheet import make_contact_sheet  # noqa: PLC0415

    path = Path(video)
    try:
        sheet = make_contact_sheet(path)
        frames: list[dict[str, Any]] = []
        for frame in sheet.frames:
            key = keep(prefix + FRAME_NAME.format(number=frame.index + 1), frame.jpeg)
            if not key:
                logger.warning("contact sheet frame %s not kept: left out", frame.index + 1)
                return None
            frames.append(
                {
                    "key": key,
                    "role": frame.role,
                    "target_s": frame.target_s,
                    "time_s": frame.time_s,
                    "width": frame.width,
                    "height": frame.height,
                    "sha256": _sha256(frame.jpeg),
                }
            )
        strip_key = keep(prefix + SHEET_NAME, sheet.strip)
        if not strip_key:
            logger.warning("contact sheet not kept: left out")
            return None
        video_sha256 = _file_sha256(path)
    except Exception:  # noqa: BLE001 — a review aid never fails the piece
        logger.warning("contact sheet not made: left out", exc_info=True)
        return None
    return {
        **sheet.params(),
        "source": {**dict(source), "sha256": video_sha256},
        "frames": frames,
        "sheet": {
            "key": strip_key,
            "width": sheet.strip_size[0],
            "height": sheet.strip_size[1],
            "sha256": _sha256(sheet.strip),
        },
        "reviewed_by": "owner",  # D8: no AI review
        "cost_usd": "0",
    }


@dataclass(frozen=True)
class SheetFrameView:
    """One frame as the screen shows it: its picture and the second of the video."""

    key: str
    time_s: float
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class ContactSheetView:
    """What the screen shows before «Aprobar»: the frames (a grid, two columns at 375 px)
    or the one-row `sheet_key`, with `title` and `help` above them."""

    video_key: str
    frames: tuple[SheetFrameView, ...]
    sheet_key: str
    version: str
    title: str = CONTACT_SHEET_TITLE
    help: str = CONTACT_SHEET_HELP


def contact_sheet_of(
    object_key: str | None, params: Mapping[str, Any] | None
) -> ContactSheetView | None:
    """The sheet recorded in `params`, when it was made from the video at `object_key`
    (anything else — no sheet, another file, a malformed block — is None). Pure."""
    block = (params or {}).get(CONTACT_SHEET_PARAMS_KEY)
    if not object_key or not isinstance(block, Mapping):
        return None
    source = block.get("source")
    if not isinstance(source, Mapping) or source.get("object_key") != object_key:
        return None
    raw_frames = block.get("frames")
    sheet = block.get("sheet")
    if not isinstance(raw_frames, list) or not raw_frames or not isinstance(sheet, Mapping):
        return None
    frames: list[SheetFrameView] = []
    for entry in raw_frames:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("key"), str):
            return None
        try:
            time_s = float(entry.get("time_s") or 0.0)
        except (TypeError, ValueError):
            return None
        frames.append(
            SheetFrameView(
                key=entry["key"],
                time_s=time_s,
                width=entry.get("width") if isinstance(entry.get("width"), int) else None,
                height=entry.get("height") if isinstance(entry.get("height"), int) else None,
            )
        )
    if not isinstance(sheet.get("key"), str):
        return None
    return ContactSheetView(
        video_key=object_key,
        frames=tuple(frames),
        sheet_key=sheet["key"],
        version=str(block.get("version") or ""),
    )


def with_source_key(block: dict[str, Any] | None, object_key: str) -> dict[str, Any] | None:
    """`block` with the video's key recorded (a Seedance preview's key is known only once
    the composed file is kept, after its sheet)."""
    if block is None:
        return None
    return {**block, "source": {**dict(block.get("source") or {}), "object_key": object_key}}


class DbContactSheets:
    """The sheet of a draft's visible video, read through the tenant door (RLS)."""

    def read(self, *, tenant_id: UUID, draft_id: UUID) -> ContactSheetView | None:
        """The sheet of `draft_id`'s visible video — a Clip, or a video by parts' parent
        («Tu video completo»: its joined preview) — or None: no video, a purged piece,
        no sheet, or a sheet made from another file than the one shown."""
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.creative.models import ContentDraft, ImageAsset  # noqa: PLC0415
        from qualify_api.creative.versions import visible_version  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.execute(
                select(ImageAsset.object_key, ImageAsset.params)
                .join(ContentDraft, ContentDraft.id == ImageAsset.draft_id)
                .where(
                    ImageAsset.draft_id == draft_id,
                    ImageAsset.media_type == "video",
                    ContentDraft.media_purged_at.is_(None),
                    visible_version(ImageAsset),
                )
                .order_by(ImageAsset.position, ImageAsset.updated_at.desc())
                .limit(1)
            ).first()
        if row is None:
            return None
        return contact_sheet_of(row.object_key, row.params)


__all__ = [
    "CONTACT_SHEET_HELP",
    "CONTACT_SHEET_PARAMS_KEY",
    "CONTACT_SHEET_TITLE",
    "ContactSheetView",
    "DbContactSheets",
    "SheetFrameView",
    "contact_sheet_of",
    "keep_contact_sheet",
    "with_source_key",
]
