"""Seedance starts from what was prepared (EF-11, m-25026585, ADR 50 §1.1 step 4).

A piece made by Seedance (`reference`: a Clip in `motion`, a part in `reference`) whose
recipe holds stretches of the owner's OWN video or photos (`segments`) no longer hands the
vendor anything as it was uploaded: its opening frame is the FIRST frame of the first
stretch, PREPARED — upright and cropped to 9:16 exactly as «Preparar» (EF-03) makes it —
sent as a `data:` URL (no public link to the owner's file is ever made for it). Which
frame is not chosen: always the stretch's first (choosing it is out of EF-11's scope).

D4 (founder, 2026-11-13): an own video never goes to `edit` (nor to `extend`): stretches
only make a `reference` piece; any other mode with stretches is refused before anything
is read or paid (`OwnVideoModeRefused`), on top of the recipe gate
(`recipe.unbuilt_recipe_problems`).

Memory and colour (m-25042483): a video stretch's file is asked for through
`LocalSources`, like the local assembly's — a source over 4K or over 8 bits is read as
its normalized copy, or the piece WAITS for the media-worker to make it
(`LocalSourceNormalizing`, a `CheckpointError`: nothing decoded, nothing paid). The copy's
key and the normalizer's version go into the manifest (`source`).

Tenant isolation: every stretch's key is checked with `owned_by` BEFORE any read; another
business's file is never opened, so no byte of it can reach the request.

Idempotent and sticky per revision: the first run keeps the frame
(`PREPARED_FRAME_NAME`) and a manifest (`PREPARED_FRAME_MANIFEST`: which stretch of which
file, the source as read, the step's versions, the sha256 of the kept frame and of the
bytes sent) under the draft's revision; a later run of the same revision whose stretch is
the same reads them back, so a retried request carries the very same bytes. The service
makes it BEFORE the copy is paid (`MediaProducer.prepare_reference_videos`); the clip
route reads it back. The manifest is the provenance the asset records
(`params["prepared_frame"]`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final, Protocol
from uuid import UUID

from qualify_creative.enums import FailureReason
from qualify_creative.schemas import ContentBrief, SourceSegment

logger = logging.getLogger(__name__)

#: The revision's files of the step (beside the clip, under the draft's revision).
PREPARED_FRAME_NAME: Final = "prepared-first-frame.jpg"
PREPARED_FRAME_MANIFEST: Final = "prepared-frame.json"
#: The manifest's own shape — bump on any change of what it records. 2: the source as
#: read (`LocalSources`) and the sha256 of the bytes sent.
PREPARED_FRAME_MANIFEST_VERSION: Final = 2
#: The modes a piece with stretches may be sent to Seedance in (D4: never `edit`, never
#: `extend`) — in the vocabulary of `MediaInputs.clip_reference_mode` and of `PartMode`.
STRETCH_MODES: Final = frozenset({"motion", "reference"})

#: What the owner reads (Spanish, `qualify-copy-es`; the screen calls them «Fotos y videos»).
PREPARED_FRAME_FAILED_TEXT: Final = (
    "No pudimos sacar el primer cuadro de tu video. Prueba con otro video o inténtalo de nuevo."
)
PREPARED_FRAME_MISSING_TEXT: Final = (
    "Ya no encontramos el video que elegiste. Cámbialo por otro y vuelve a crear el video."
)
PREPARED_FRAME_READ_FAILED_TEXT: Final = (
    "No pudimos abrir tu video en este momento. Inténtalo de nuevo en un rato."
)
OWN_VIDEO_MODE_TEXT: Final = (
    "Tu propio video no se puede rehacer igual al original. Elige «Nueva» o usa tu video tal cual."
)


#: Deivid, 2026-11-20: a `reference` PART that also carries references (its photos, videos
#: or audio) opens on its prepared frame only with this switch on — the frame then goes
#: as reference «Image 1» and the part prompt names it (part prompt version 6), a prompt
#: change not measured yet. Off (the default): such a part is made exactly as on main
#: (no frame, same prompt, same images, same version). A Clip, and a part without
#: references, always open on the prepared frame.
PREPARED_FRAME_REFS_SWITCH: Final = "QUALIFY_PARTS_PREPARED_FRAME_REFS"


def prepared_frame_with_references() -> bool:
    """Whether a `reference` part with references opens on its prepared frame
    (`QUALIFY_PARTS_PREPARED_FRAME_REFS`: `off`, the default, or `on`). An unknown value
    is logged and read as off: never an unmeasured prompt by a typo."""
    import os  # noqa: PLC0415

    value = os.environ.get(PREPARED_FRAME_REFS_SWITCH, "off").strip().lower()
    if value in ("", "off"):
        return False
    if value == "on":
        return True
    logger.error("%s must be off or on, not %r: read as off", PREPARED_FRAME_REFS_SWITCH, value)
    return False


def stretches_wait_for_switch(has_references: bool) -> bool:
    """Whether a `reference` PART's own stretches cannot be used yet: it carries
    references and the switch is off — then the piece is refused (`recipe_unavailable`,
    as before EF-11), never made ignoring the owner's video."""
    return has_references and not prepared_frame_with_references()


def uses_prepared_frame(brief: ContentBrief) -> bool:
    """Whether `brief` (a Clip or a part with own stretches, not `local`) opens on its
    prepared frame. A part with references while the switch is off does not — and is
    refused (`refuse_waiting_stretches`). Pure but for the switch; nothing is read."""
    media = brief.media
    if not own_segments(brief) or media.clip_reference_mode == "local":
        return False
    if media.part is not None:
        return not stretches_wait_for_switch(media.clip_has_references)
    return True


#: What the owner reads when a part made from their own video also has photos, videos or
#: audio to follow while the switch is off (qualify-copy-es).
STRETCHES_WITH_REFERENCES_TEXT: Final = (
    "Por ahora esta parte no puede usar tu video y, a la vez, fotos, videos o audio de "
    "referencia. Quita las referencias y vuelve a crear la parte, o elige «Tu video, con "
    "efectos»."
)


def refuse_waiting_stretches(brief: ContentBrief) -> None:
    """`PreparedFrameFailed` (`recipe_unavailable` in the log) for a `reference` part with
    own stretches AND references while the switch is off: refused before any read or
    spend, as the recipe gate does, never made without the owner's video. Pure."""
    media = brief.media
    part = media.part
    if (
        part is not None
        and part.mode == "reference"
        and part.segments
        and stretches_wait_for_switch(media.clip_has_references)
    ):
        raise PreparedFrameFailed(
            FailureReason.PART_FAILED.value,
            STRETCHES_WITH_REFERENCES_TEXT,
            raw="recipe_unavailable: own stretches with references, "
            f"{PREPARED_FRAME_REFS_SWITCH} off",
        )


class PreparedFrameFailed(Exception):
    """The opening frame could not be made: `failure` (a `FailureReason` value) and
    `detail` (what the owner reads); `raw` only reaches the log."""

    def __init__(self, failure: str, detail: str, raw: str = "") -> None:
        super().__init__(detail)
        self.failure = failure
        self.detail = detail
        self.raw = raw


class OwnVideoModeRefused(PreparedFrameFailed):
    """D4: a piece with stretches of own video asked for `edit` or `extend`."""


class _Store(Protocol):
    def read(self, key: str) -> bytes: ...


class _Save(Protocol):
    def __call__(self, name: str, data: bytes, content_type: str) -> str: ...

    def key_for(self, name: str) -> str: ...


@dataclass(frozen=True)
class PreparedFrame:
    """The prepared opening frame (`jpeg`, 9:16, as kept), the bytes the request carries
    (`sent`: `to_reference_jpeg` of it) and its provenance (`manifest`)."""

    jpeg: bytes
    sent: bytes
    manifest: dict[str, Any]

    @property
    def key(self) -> str:
        return str(self.manifest["frame_key"])


def own_segments(brief: ContentBrief) -> tuple[SourceSegment, ...]:
    """The stretches of own video or photos a Clip (or a part, a child Clip) is made from:
    the part's for a part, the Clip's own otherwise. Pure."""
    part = brief.media.part
    return part.segments if part is not None else brief.media.segments


def refuse_stretch_mode(mode: str, segments: Sequence[SourceSegment]) -> None:
    """D4: stretches of own video only make a `reference` piece — `OwnVideoModeRefused`
    for `edit` or `extend` (`local` never reaches Seedance). Pure; raises before any read."""
    if segments and mode not in STRETCH_MODES and mode != "local":
        raise OwnVideoModeRefused(
            FailureReason.ROUTE_BLOCKED_BY_POLICY.value,
            OWN_VIDEO_MODE_TEXT,
            raw=f"own stretches with mode {mode!r} (D4)",
        )


def _segment_record(segment: SourceSegment) -> dict[str, Any]:
    return {
        "key": segment.key,
        "start_s": segment.start_s,
        "end_s": segment.end_s,
        "rotate": int(segment.rotate),
        "kind": segment.kind,
    }


def _missing(exc: BaseException) -> bool:
    from qualify_api.creative.part_join import _missing as missing  # noqa: PLC0415

    return missing(exc)


def _sent_bytes(jpeg: bytes) -> bytes:
    """The bytes the request carries for the kept frame (deterministic)."""
    from qualify_creative.photo.normalize import to_reference_jpeg  # noqa: PLC0415

    return to_reference_jpeg(jpeg)


def _sticky(
    store: _Store, save: _Save, tenant_id: UUID, segment: SourceSegment
) -> PreparedFrame | None:
    """This revision's frame, when an earlier run made it from the same stretch with the
    same step; None on a first run (or a different stretch). Only a manifest that is not
    there means «first run»: an unreadable one (R2 down) is the queue's to retry, never a
    guess that could disagree with a request already captured."""
    from qualify_creative.video.opening_frame import OPENING_FRAME_VERSION  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectNotFound  # noqa: PLC0415

    from qualify_api.creative.media import owned_by  # noqa: PLC0415
    from qualify_api.creative.queue_dispatch import CheckpointError  # noqa: PLC0415

    try:
        raw = store.read(save.key_for(PREPARED_FRAME_MANIFEST))
    except (FileNotFoundError, KeyError, ObjectNotFound):
        return None
    except Exception as exc:  # noqa: BLE001 — unknown: never guessed as a first run
        raise CheckpointError(f"prepared frame manifest unreadable: {type(exc).__name__}") from exc
    try:
        manifest = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(manifest, dict):
        return None
    frame = manifest.get("frame")
    if (
        manifest.get("manifest_version") != PREPARED_FRAME_MANIFEST_VERSION
        or not isinstance(frame, dict)
        or frame.get("version") != OPENING_FRAME_VERSION
        or manifest.get("segment") != _segment_record(segment)
    ):
        return None
    frame_key = manifest.get("frame_key")
    if not isinstance(frame_key, str) or not owned_by(tenant_id, frame_key):
        return None
    try:
        jpeg = store.read(frame_key)
    except (FileNotFoundError, KeyError, ObjectNotFound):
        return None
    except Exception as exc:  # noqa: BLE001
        raise CheckpointError(f"prepared frame unreadable: {type(exc).__name__}") from exc
    if hashlib.sha256(jpeg).hexdigest() != manifest.get("sha256"):
        return None
    sent = _sent_bytes(jpeg)
    if hashlib.sha256(sent).hexdigest() != manifest.get("sent_sha256"):
        return None  # a different encoder since: made again, never sent unrecorded
    return PreparedFrame(jpeg=jpeg, sent=sent, manifest=manifest)


def _fetch(store: Any, tenant_id: UUID, key: str, path: Path) -> None:
    """A file to disk through the tenant-checking door (`copy_to_file` when the store
    streams from R2), else read whole (a test's memory store). `owned_by` again here: the
    normalized copy's key is checked like the original's."""
    from qualify_api.creative.media import owned_by  # noqa: PLC0415

    if not owned_by(tenant_id, key):
        raise PreparedFrameFailed(
            FailureReason.ROUTE_BLOCKED_BY_POLICY.value,
            PREPARED_FRAME_FAILED_TEXT,
            raw="a file of another business",
        )
    copy = getattr(store, "copy_to_file", None)
    try:
        if callable(copy):
            copy(tenant_id, key, path)
        else:
            path.write_bytes(store.read(key))
    except Exception as exc:
        if _missing(exc):
            raise PreparedFrameFailed(
                FailureReason.INVALID_PARAMETERS.value,
                PREPARED_FRAME_MISSING_TEXT,
                raw=f"missing {key}",
            ) from exc
        # a read that failed on the way (R2 down, a cut connection): the queue's to retry,
        # like `_sticky`'s — never a failed piece for a passing problem
        from qualify_api.creative.queue_dispatch import CheckpointError  # noqa: PLC0415

        raise CheckpointError(
            f"own stretch unreadable for now: {type(exc).__name__}: {exc}"
        ) from exc


def _source_file(
    store: Any,
    tenant_id: UUID,
    segment: SourceSegment,
    path: Path,
    *,
    draft_id: UUID | None,
    brand_id: UUID | None,
    source_jobs: Any,
) -> dict[str, Any] | None:
    """The stretch's file at `path`: a photo as it is; a video through `LocalSources`
    (its normalized copy, or `LocalSourceNormalizing` before anything is decoded). Returns
    what the manifest records of the source (`LocalSources.provenance`)."""
    from qualify_creative.video._source import VideoSourceError  # noqa: PLC0415

    from qualify_api.creative.video_pipeline.local import LocalVideoFailed  # noqa: PLC0415
    from qualify_api.creative.video_pipeline.local_sources import LocalSources  # noqa: PLC0415

    if segment.kind != "video":
        _fetch(store, tenant_id, segment.key, path)
        return {"source_key": segment.key}
    try:
        sources = LocalSources.open(
            SimpleNamespace(segments=(segment,)),
            tenant_id=tenant_id,
            fetch_file=lambda key, target: _fetch(store, tenant_id, key, target),
            jobs=source_jobs,
            draft_id=draft_id,
            brand_id=brand_id,
        )
        sources.fetch(segment.key, path)
    except LocalVideoFailed as exc:  # a normalization that failed for good (or timed out)
        raise PreparedFrameFailed(exc.failure, PREPARED_FRAME_FAILED_TEXT, raw=exc.raw) from exc
    except VideoSourceError as exc:  # its header cannot be read: the owner's file
        raise PreparedFrameFailed(
            FailureReason.INVALID_PARAMETERS.value,
            PREPARED_FRAME_FAILED_TEXT,
            raw=f"{type(exc).__name__}: {exc}",
        ) from exc
    except Exception as exc:
        if not _unreadable(exc):
            raise
        raise PreparedFrameFailed(
            FailureReason.INVALID_PARAMETERS.value,
            PREPARED_FRAME_FAILED_TEXT,
            raw=f"{type(exc).__name__}: {exc}",
        ) from exc
    return sources.provenance(segment.key) or {"source_key": segment.key}


def prepared_first_frame(
    *,
    tenant_id: UUID,
    segments: Sequence[SourceSegment],
    store: Any,
    save: _Save,
    draft_id: UUID | None = None,
    brand_id: UUID | None = None,
    source_jobs: Any = None,
) -> PreparedFrame | None:
    """The opening frame of a piece made from `segments` (see the module): None without
    stretches. Raises `PreparedFrameFailed` before anything is paid (a file of another
    business — nothing read —, a file gone, one that cannot be read or prepared, a
    normalization that failed) and `LocalSourceNormalizing` while the media-worker makes a
    lighter copy. Kept (frame + manifest) under the draft's revision through `save`."""
    from PIL import UnidentifiedImageError  # noqa: PLC0415
    from qualify_creative.video._source import VideoSourceError  # noqa: PLC0415
    from qualify_creative.video.opening_frame import prepared_opening_frame  # noqa: PLC0415

    from qualify_api.creative.media import owned_by  # noqa: PLC0415

    if not segments:
        return None
    segment = segments[0]
    # every stretch is checked, not only the first: a recipe naming another business's
    # file is refused as a whole, before any read
    for stretch in segments:
        if not owned_by(tenant_id, stretch.key):
            raise PreparedFrameFailed(
                FailureReason.ROUTE_BLOCKED_BY_POLICY.value,
                PREPARED_FRAME_FAILED_TEXT,
                raw="a stretch of another business",
            )
    kept = _sticky(store, save, tenant_id, segment)
    if kept is not None:
        return kept
    with tempfile.TemporaryDirectory(prefix="qualify-opening-") as folder:
        path = Path(folder) / "source"
        source = _source_file(
            store,
            tenant_id,
            segment,
            path,
            draft_id=draft_id,
            brand_id=brand_id,
            source_jobs=source_jobs,
        )
        source_sha256 = _file_sha256(path)
        try:
            frame = prepared_opening_frame(
                path,
                key=segment.key,
                start_s=segment.start_s,
                end_s=segment.end_s,
                rotate=int(segment.rotate),
                kind=segment.kind,
            )
        except (VideoSourceError, UnidentifiedImageError, ValueError) as exc:
            raise PreparedFrameFailed(
                FailureReason.INVALID_PARAMETERS.value,
                PREPARED_FRAME_FAILED_TEXT,
                raw=f"{type(exc).__name__}: {exc}",
            ) from exc
        except Exception as exc:
            # a decoder or picture error of the file's own (PyAV's, Pillow's) is the
            # owner's file; anything else (the disk, a bug) goes up as it is
            if not _unreadable(exc):
                raise
            raise PreparedFrameFailed(
                FailureReason.INVALID_PARAMETERS.value,
                PREPARED_FRAME_FAILED_TEXT,
                raw=f"{type(exc).__name__}: {exc}",
            ) from exc
    sent = _sent_bytes(frame.jpeg)
    frame_key = save(PREPARED_FRAME_NAME, frame.jpeg, "image/jpeg")
    manifest: dict[str, Any] = {
        "manifest_version": PREPARED_FRAME_MANIFEST_VERSION,
        "segment_index": 0,
        "segment": _segment_record(segment),
        "source": source,
        "source_sha256": source_sha256,
        "frame": frame.params,
        "frame_key": frame_key,
        "sha256": hashlib.sha256(frame.jpeg).hexdigest(),
        "sent_sha256": hashlib.sha256(sent).hexdigest(),
        "sent_as": "data_url",
    }
    manifest_key = save.key_for(PREPARED_FRAME_MANIFEST)
    written = save(
        PREPARED_FRAME_MANIFEST,
        json.dumps(manifest, sort_keys=True).encode("utf-8"),
        "application/json",
    )
    if written != manifest_key:
        # another run of this revision recorded its frame first: that one is what the
        # request carries (same stretch, same step: the same picture)
        winner = _sticky(store, save, tenant_id, segment)
        if winner is not None:
            return winner
    return PreparedFrame(jpeg=frame.jpeg, sent=sent, manifest=manifest)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _unreadable(exc: BaseException) -> bool:
    from qualify_api.creative.video_pipeline.local import _unreadable as unreadable  # noqa: PLC0415

    return unreadable(exc)


__all__ = [
    "OWN_VIDEO_MODE_TEXT",
    "OwnVideoModeRefused",
    "PREPARED_FRAME_MANIFEST",
    "PREPARED_FRAME_NAME",
    "PreparedFrame",
    "PreparedFrameFailed",
    "STRETCH_MODES",
    "own_segments",
    "prepared_frame_with_references",
    "uses_prepared_frame",
    "refuse_waiting_stretches",
    "stretches_wait_for_switch",
    "prepared_first_frame",
    "refuse_stretch_mode",
]
