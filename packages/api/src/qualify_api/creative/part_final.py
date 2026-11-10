"""The final of a video by parts (ADR 44, VE-10b m-24921068): approved once, each part's
1080p kept as it came, and ONE local join at 1080×1920 that is the whole video's final.

1. **Approval** (`ContentService.approve_parts`): the owner approves the joined preview
   they saw — refused when it is not the join of the parts' ACTIVE versions any more
   (`approval_problem`: `stale`). Every part's seconds (D29) are charged in ONE
   transaction, all or nothing (`charge_videos_many`); parent and parts are approved
   through the state machine and one final per part is ordered in the night lane
   (ADR 41). The parent's join row goes `join_final_pending`.
2. **A part's final** (`MediaProducer._final_video` with `brief.media.part`): the paid
   raw 1080p is kept (`raw_final`) and the part's block goes `part_final`
   (`part_final_media`) — no H.264 fit, no logo: Seedance 2.5 delivers 10-bit H.265 and
   the final join is its only re-encode. The part keeps showing its vista previa (the
   row's file does not change), so the preview's fingerprint does not change either.
   Settling it opens the parent's `join_final` run (`parts.open_parent_join_final`).
3. **The final join** (`join_final`, the worker's `join_final` phase, like VE-10a's
   join: background, one at a time, lease kept, fenced save): once EVERY part is
   `part_final`, their raw files are joined at `JOIN_FINAL_SIZE` with the business logo
   laid ONCE over the whole video (VE-07's `overlay`, the same `text_layer` as a Clip;
   never per part, never sent to the vendor) and the parent's join row becomes
   `final_ready` with `final_sha256` / `final_object_key` / `final_revision`: the
   owner's second look (`final_review.confirm_final`) works unchanged.

Cost: the join is ours (0 USD, no charge row). A part's final that fails gives its
seconds back (D9, `_refund_final_part`, unchanged). A final join that fails charges
nothing more and the retry starts from what is saved: the raw finals stay in R2, so
nothing is paid to the vendor again — an IO failure is retried by the next pass, a
part file that cannot be decoded marks the join row `failed` («Reintentar» opens the
run again, `ContentService.retry_final`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from qualify_creative.compose import text_layer
from qualify_creative.video.join import (
    JOIN_FPS,
    JOIN_SAMPLE_RATE,
    JOIN_SEGMENT_VERSION,
    JOIN_VERSION,
    JoinClip,
    JoinError,
    JoinSegment,
    concat_segments,
    segment_crf,
    segment_lookahead,
)
from qualify_creative.video.join_child import JoinChildLost, segment_in_child
from qualify_shared.db.session import tenant_unit_of_work
from sqlalchemy import text

from qualify_api.creative.draft_mode import DRAFT_FAILED, draft_expired, draft_state
from qualify_api.creative.fsm import APPROVED, FAILED
from qualify_api.creative.media import JPEG, MP4, MediaWrite, owned_by
from qualify_api.creative.part_join import (
    FINISH_JOIN,
    JOIN_PREVIEW_STATUS,
    JOIN_PROVIDER,
    PART_FINAL,
    JoinNotKept,
    PartPreview,
    PartsToJoin,
    _duration,
    _fetch,
    _held,
    _keep,
    _missing,
    _read_logo,
    io_failure,
    join_fingerprint,
    join_key,
    part_span,
    ready_parts,
)
from qualify_api.creative.pipeline import CheckpointError, PipelineStore, current_preparation

logger = logging.getLogger(__name__)

#: The parent's run that joins its parts' raw finals (`creative_pipeline_runs.phase`).
JOIN_FINAL_PHASE = "join_final"
#: Version of the final join's recipe — in its fingerprint and its provenance.
JOIN_FINAL_VERSION = "join-final-v1"
#: The final's size: 1080p 9:16 (Seedance 2.5's final; an `edit` part is cover-cropped).
JOIN_FINAL_SIZE = (1080, 1920)
#: The parent's join row between the approval and its final join.
JOIN_FINAL_PENDING = "join_final_pending"
#: `final_review.FINAL_READY` (not imported: `final_review` reads versions and members).
FINAL_READY = "final_ready"
#: What the owner reads when a final join failed for good (no seconds were used by it).
JOIN_FINAL_FAILED_TEXT = (
    "No pudimos preparar el video final. Toca Reintentar: no usa más segundos de tu video del mes."
)
#: A part final whose paid 1080p could not be kept: nothing to join it from.
PART_FINAL_NOT_KEPT_TEXT = "No pudimos guardar el video final de esta parte. Toca Reintentar."
#: A part whose vista previa expired (7 days) when the whole video is approved.
PART_EXPIRED_TEXT = (
    "Una parte venció: las vistas previas duran 7 días. Pide otra versión de esa parte."
)
#: How many times a final join's child may die (killed, OOM, timed out) before the join
#: row fails — the owner's «Reintentar» starts the count again.
CHILD_LOSSES_MAX = 3

# what `approval_problem` answers
NOT_READY = "not_ready"
PART_FAILED = "part_failed"
EXPIRED = "expired"
STALE = "stale"


class ApproveWholeVideo(Exception):
    """A video by parts is approved whole (`approve_parts`): neither its parent through
    the plain `approve` nor one of its parts on its own. Nothing written."""

    def __init__(self) -> None:
        super().__init__("Las partes se aprueban juntas: aprueba tu video completo.")


class PartsNotReady(Exception):
    """A part is missing, still being made or failed, or the joined preview is not
    there yet: nothing to approve. Nothing written."""

    def __init__(self) -> None:
        super().__init__(
            "Tu video completo todavía no está listo. Espera a que terminen todas sus partes."
        )


class PartFailed(PartsNotReady):
    """A part's generation failed: approving waits for another version of it."""

    def __init__(self) -> None:
        Exception.__init__(
            self,
            "Una parte de tu video no salió. Pide otra versión de esa parte para poder aprobarlo.",
        )


class StaleJoinedPreview(Exception):
    """The joined preview the owner saw is not the join of the parts as they are now
    (one was made again or restored since). Nothing charged nor approved."""

    def __init__(self) -> None:
        super().__init__("Tu video cambió mientras lo veías. Míralo de nuevo antes de aprobarlo.")


class PartFinalStore(Protocol):
    """What the final join reads and writes (`part_join.DbPartJoins` in production)."""

    def read(self, *, tenant_id: UUID, parent_id: UUID) -> PartsToJoin | None: ...

    def save_final(self, *, tenant_id: UUID, parent_id: UUID, write: MediaWrite) -> bool: ...

    def fail_final(self, *, tenant_id: UUID, parent_id: UUID, error: str) -> bool: ...


# ---------------------------------------------------------------------------
# pure rules


def block_logo_key(block: Mapping[str, Any] | None) -> str | None:
    """The logo a joined preview was made with (`{key, sha256}`), or None («sin logo»)."""
    logo = (block or {}).get("logo")
    if isinstance(logo, Mapping) and isinstance(logo.get("key"), str) and logo["key"]:
        return str(logo["key"])
    return None


def preview_fingerprint(parts: Sequence[PartPreview], block: Mapping[str, Any] | None) -> str:
    """The joined-preview fingerprint `parts` (their active versions) would have with the
    logo the shown preview carries — equal to the shown one iff the owner saw THESE
    versions joined. Pure."""
    return join_fingerprint(parts, [part_span(p.params) for p in parts], block_logo_key(block))


def approval_problem(
    snapshot: PartsToJoin | None, tenant_id: UUID, now: float | None = None
) -> str | None:
    """Why the whole video cannot be approved now, or None: `not_ready` (a part
    missing, being made or failed; no joined preview yet), `expired` (a part's vista
    previa can no longer make its final), `stale` (the joined preview on screen is not
    the join of the parts' active versions: one was made again or restored since). Pure."""
    if snapshot is None:
        return NOT_READY
    if any(p.status == FAILED for p in snapshot.parts):
        return PART_FAILED
    if any(
        draft_expired(draft_state(p.params) or {}, now)
        for p in snapshot.parts
        if draft_state(p.params) is not None
    ):
        return EXPIRED
    parts = ready_parts(snapshot, tenant_id, now)
    block = snapshot.joined_block
    if parts is None or block is None or block.get("status") != JOIN_PREVIEW_STATUS:
        return NOT_READY
    if block.get("parent_revision") != snapshot.revision:
        return STALE
    if preview_fingerprint(parts, block) != snapshot.joined_fingerprint:
        return STALE
    return None


def final_parts(snapshot: PartsToJoin, tenant_id: UUID) -> tuple[PartPreview, ...] | None:
    """The parts in plan order when EVERY one is approved with its raw 1080p kept
    (`part_final`) under this business's folder, else None. Pure."""
    kept = snapshot.kept_indexes  # m-24985192: a removed part is not joined
    if not kept or len(snapshot.parts) != len(kept):
        return None
    ordered = sorted(snapshot.parts, key=lambda p: p.part_index or 0)
    if tuple(p.part_index for p in ordered) != kept:
        return None
    for part in ordered:
        if part.status != APPROVED or part.purged or part.version_id is None:
            return None
        block = draft_state(part.params) or {}
        if block.get("status") != PART_FINAL or raw_key(part) is None:
            return None
    return tuple(ordered) if all(owned_by(tenant_id, str(raw_key(p))) for p in ordered) else None


def raw_key(part: PartPreview) -> str | None:
    """The part's paid raw 1080p in the store (`raw_final.key`), or None."""
    raw = (draft_state(part.params) or {}).get("raw_final")
    key = raw.get("key") if isinstance(raw, Mapping) else None
    return key if isinstance(key, str) and key else None


def join_final_fingerprint(
    parts: Sequence[PartPreview],
    spans: Sequence[tuple[float, float | None]],
    logo_key: str | None,
) -> str:
    """What makes a final join THIS one: its recipe, size, logo and, in order, each
    part's draft, active version, raw 1080p and trim. Pure."""
    data: dict[str, Any] = {
        "version": JOIN_FINAL_VERSION,
        "recipe": JOIN_VERSION,
        "size": list(JOIN_FINAL_SIZE),
        "parts": [
            [str(p.draft_id), str(p.version_id), raw_key(p), start, end]
            for p, (start, end) in zip(parts, spans, strict=True)
        ],
        "logo": logo_key,
    }
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:20]


def part_final_media(
    asset: Any, block: Mapping[str, Any], raw: Mapping[str, Any], revision: int
) -> MediaWrite:
    """A part's final, in place of its draft row: the SAME file as before (the vista
    previa the owner saw and the joined preview was made from) and the block `part_final`
    with the paid raw 1080p (`raw_final`, `part_final_key`) — nothing re-encoded, no
    `final_sha256`: a part is never published nor reviewed on its own. Pure."""
    params = dict(asset.params or {})
    params["draft"] = {
        **dict(block),
        "raw_final": dict(raw),
        "status": PART_FINAL,
        "part_final_key": raw.get("key"),
        "final_revision": revision,
        "final_task_id": raw.get("task_id"),
        "final_cost_usd": raw.get("cost_usd"),
        "final_resolution": raw.get("resolution"),
        "error": None,
        "claim": None,
    }
    key = str(asset.object_key)
    return MediaWrite(
        position=asset.position,
        media_type="video",
        media_url=str(asset.media_url or key),
        object_key=key,
        width=asset.width,
        height=asset.height,
        aspect_ratio=asset.aspect_ratio,
        model_id=str(raw.get("model_id") or block.get("model") or ""),
        provider=str(raw.get("provider") or "seedance"),
        content_type=MP4,
        ai_generated=True,
        params=params,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stored_sha256(store: Any, tenant_id: UUID, key: str) -> str:
    digest = getattr(store, "sha256", None)
    if callable(digest):
        return str(digest(tenant_id, key))
    return hashlib.sha256(store.read(key)).hexdigest()


def _provenance(
    parts: Sequence[PartPreview], spans: Sequence[tuple[float, float | None]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for part, (start, end) in zip(parts, spans, strict=True):
        meta = part.params.get("part") if isinstance(part.params.get("part"), Mapping) else {}
        block = draft_state(part.params) or {}
        raw = block.get("raw_final") if isinstance(block.get("raw_final"), Mapping) else {}
        out.append(
            {
                "draft_id": str(part.draft_id),
                "part_index": part.part_index,
                "version_id": str(part.version_id),
                "revision": part.revision,
                "preview_key": part.object_key,
                "clean_key": part.join_source,
                "raw_final_key": raw.get("key"),
                "raw_task_id": raw.get("task_id"),
                "raw_model_id": raw.get("model_id") or block.get("model"),
                "raw_resolution": raw.get("resolution"),
                "mode": meta.get("mode"),
                "seconds": meta.get("seconds"),
                "start_s": start,
                "end_s": end,
            }
        )
    return out


# ---------------------------------------------------------------------------
# the final join, in segments (VE-10b, option (c) of 2026-11-06)


class PartsGone(Exception):
    """A part's raw final is no longer in the store: final, like undecodable parts."""


def segment_fingerprint(
    part: PartPreview,
    span: tuple[float, float | None],
    logo_key: str | None,
    *,
    fade_in: bool,
    fade_out: bool,
) -> str:
    """What makes one part's encoded segment THIS one: the segment recipe, size and
    rate, the part's draft, active version, raw 1080p and trim, the logo laid on it and
    which of its edges fade (a part's place among the others). The same fingerprint is
    the same file: a pass that lost its lease resumes from the segments already kept.
    Pure."""
    data = {
        "version": JOIN_SEGMENT_VERSION,
        # the encoder's lookahead in force (`QUALIFY_JOIN_SEGMENT_LOOKAHEAD`): another
        # one is another recipe, never mixed with segments already kept
        "lookahead": segment_lookahead(),
        "crf": segment_crf(),  # `QUALIFY_JOIN_SEGMENT_CRF`: likewise another recipe
        "recipe": JOIN_VERSION,
        "size": list(JOIN_FINAL_SIZE),
        "fps": JOIN_FPS,
        "part": [str(part.draft_id), str(part.version_id), raw_key(part), span[0], span[1]],
        "logo": logo_key,
        "fade": [fade_in, fade_out],
    }
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:20]


def _child_lost(joins: Any, tenant_id: UUID, parent_id: UUID) -> bool:
    """Count one more lost child on the parent's join row; True once it reached
    `CHILD_LOSSES_MAX` (then the row fails). A store that cannot count never stops."""
    count = getattr(joins, "child_lost", None)
    if not callable(count):
        return False
    return int(count(tenant_id=tenant_id, parent_id=parent_id)) >= CHILD_LOSSES_MAX


def _drop_cache(path: Path) -> None:
    """Tell the kernel this file's pages may go (the worker's cgroup counts page cache):
    `posix_fadvise(DONTNEED)` after an fsync, where the platform has it."""
    advise = getattr(os, "posix_fadvise", None)
    if advise is None or not path.exists():
        return
    try:
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
            advise(handle.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
    except OSError:  # a hint, never a reason to fail
        pass


def _keep_lease() -> None:
    """Between two parts: renew the run's lease now (the heartbeat thread renews it too)
    and stop at once if it is gone — the segments made so far are in R2 and the next
    pass resumes from them instead of encoding on for a save that would be refused."""
    run = current_preparation()
    if run is None:
        return
    store = PipelineStore()
    if not store.renew(run):
        logger.warning(
            "creative.pipeline.lease_lost draft_id=%s between parts: %s",
            run.draft_id,
            store.lease_state(run),
        )
        raise CheckpointError("preparation lease lost between the parts of a final join")


def _fetch_raw(store: Any, tenant_id: UUID, part: PartPreview, path: Path) -> None:
    try:
        _fetch(store, tenant_id, str(raw_key(part)), path)
    except Exception as exc:
        if not _missing(exc):
            raise  # transport / IO: the next pass retries
        raise PartsGone(f"part {part.part_index}: its raw final {raw_key(part)} is gone") from exc


def _whole_join(
    store: Any,
    tenant_id: UUID,
    parts: Sequence[PartPreview],
    spans: Sequence[tuple[float, float | None]],
    overlay: bytes | None,
    root: Path,
    joiner: Callable[..., Any],
) -> Any:
    clips = []
    for index, (part, (start, end)) in enumerate(zip(parts, spans, strict=True)):
        path = root / f"part-{index}.mp4"
        _fetch_raw(store, tenant_id, part, path)
        clips.append(JoinClip(path, start_s=start, end_s=end))
    return joiner(clips, out=root / "final.mp4", size=JOIN_FINAL_SIZE, overlay=overlay)


def _segment_join(
    store: Any,
    tenant_id: UUID,
    parent_id: UUID,
    parts: Sequence[PartPreview],
    spans: Sequence[tuple[float, float | None]],
    logo_key: str | None,
    overlay: bytes | None,
    root: Path,
    *,
    segmenter: Callable[..., Any] | None,
    concat: Callable[..., Any] | None,
) -> Any:
    """Each part encoded on its own in a short-lived child (`segment_in_child`: its
    decoder, encoder and malloc memory go back to the OS before the next part), kept in
    R2 under its fingerprint at once (`join-segment-<fp>.mp4` + `.pcm`), its raw file
    deleted; a segment already kept is fetched instead of encoded (a pass that lost its
    lease resumes there). Then the segments are laid end to end by stream copy
    (`concat_segments`, no frame decoded) with the sound encoded once."""
    segments: list[JoinSegment] = []
    last = len(parts) - 1
    for index, (part, span) in enumerate(zip(parts, spans, strict=True)):
        fade_in, fade_out = index > 0, index < last
        fingerprint = segment_fingerprint(part, span, logo_key, fade_in=fade_in, fade_out=fade_out)
        video_key = join_key(tenant_id, parent_id, f"segment-{fingerprint}")
        pcm_key = join_key(tenant_id, parent_id, f"segment-{fingerprint}", "pcm")
        poster_key = join_key(tenant_id, parent_id, f"segment-{fingerprint}", "jpg")
        video, pcm = root / f"segment-{index}.mp4", root / f"segment-{index}.pcm"
        if _held(store, tenant_id, video_key) and _held(store, tenant_id, pcm_key):
            _fetch(store, tenant_id, video_key, video)
            _fetch(store, tenant_id, pcm_key, pcm)
            picture = None
            if index == 0 and _held(store, tenant_id, poster_key):
                picture = store.read(poster_key)
            samples = pcm.stat().st_size // 8  # float32 stereo
            # its frames are its samples at the common rate (`encode_segment` cuts the
            # sound to exactly `frames × 48000 / fps`): no need to read the video
            frames = round(Fraction(samples) * JOIN_FPS / JOIN_SAMPLE_RATE)
            segment = JoinSegment(video, pcm, frames, samples, picture)
            logger.info("parent %s: segment %s already kept; reused", parent_id, index + 1)
        else:
            raw = root / f"raw-{index}.mp4"
            _fetch_raw(store, tenant_id, part, raw)
            try:
                segment = (segmenter or segment_in_child)(
                    JoinClip(raw, start_s=span[0], end_s=span[1]),
                    out=video,
                    pcm_out=pcm,
                    size=JOIN_FINAL_SIZE,
                    overlay=overlay,
                    fade_in=fade_in,
                    fade_out=fade_out,
                    poster=index == 0,
                )
            finally:
                raw.unlink(missing_ok=True)  # its segment exists (or the join stops here)
            if not _keep(store, tenant_id, video_key, video, MP4):
                raise JoinNotKept(video_key)
            if not _keep(store, tenant_id, pcm_key, pcm, "application/octet-stream"):
                raise JoinNotKept(pcm_key)
            if segment.poster:
                picture_path = root / "segment-poster.jpg"
                picture_path.write_bytes(segment.poster)
                try:
                    _keep(store, tenant_id, poster_key, picture_path, JPEG)
                except Exception:  # noqa: BLE001 — a nicety
                    logger.warning("parent %s: segment poster not kept", parent_id)
                picture_path.unlink(missing_ok=True)
        _drop_cache(video)
        _drop_cache(pcm)
        segments.append(segment)
        _keep_lease()
    return (concat or concat_segments)(segments, out=root / "final.mp4")


# ---------------------------------------------------------------------------
# the final join


def join_final(
    store: Any,
    joins: PartFinalStore,
    tenant_id: UUID,
    parent_id: UUID,
    *,
    joiner: Callable[..., Any] | None = None,
    segmenter: Callable[..., Any] | None = None,
    concat: Callable[..., Any] | None = None,
) -> MediaWrite | None:
    """The 1080p final of `parent_id` to save, or None when there is nothing to do: the
    parent not approved, a part's final still on its way, or the final already made.
    The file is in R2 when this returns (`JoinNotKept` otherwise). A raw final that
    cannot be decoded or is gone marks the join row failed (`fail_final`) and returns
    None — nothing is charged and no vendor call is made again; an IO failure is raised,
    so the run is retried from the same kept files."""
    snapshot = joins.read(tenant_id=tenant_id, parent_id=parent_id)
    if snapshot is None or snapshot.status != APPROVED:
        return None
    block = dict(snapshot.joined_block or {})
    if block.get("status") not in (JOIN_FINAL_PENDING, DRAFT_FAILED):
        return None  # not approved through approve_parts, or the final is made already
    parts = final_parts(snapshot, tenant_id)
    if parts is None:
        logger.info("parent %s: not every part's final is kept yet; nothing joined", parent_id)
        return None
    spans = [part_span(p.params) for p in parts]
    if preview_fingerprint(parts, block) != block.get("approved_fingerprint"):
        # the parts are not the versions the owner approved: never a final of them
        logger.error("parent %s: its parts are not the approved ones; no final", parent_id)
        return None
    logo_key = block_logo_key(block)
    logo = _read_logo(store, tenant_id, logo_key)
    logo_key = logo_key if logo is not None else None
    fingerprint = join_final_fingerprint(parts, spans, logo_key)
    logo_record: dict[str, Any] | str = (
        {"key": logo_key, "sha256": hashlib.sha256(logo).hexdigest()[:16]}
        if logo is not None
        else "sin logo"
    )
    key = join_key(tenant_id, parent_id, f"final-{fingerprint}")
    poster_key: str | None = join_key(tenant_id, parent_id, f"final-{fingerprint}", "jpg")
    frames: int | None = None
    if _held(store, tenant_id, key):
        logger.info("parent %s: final join %s already kept; reused", parent_id, fingerprint)
        digest = _stored_sha256(store, tenant_id, key)
        if not _held(store, tenant_id, poster_key):
            poster_key = None
    else:
        with tempfile.TemporaryDirectory(prefix="qualify-join-final-") as folder:
            root = Path(folder)
            # the business logo over the whole final, as on any Clip (Deivid, 2026-11-06):
            # the same layer at the same place on every part, so it reads as ONE logo;
            # laid on the clean raw parts, never sent to the vendor
            overlay = text_layer(size=JOIN_FINAL_SIZE, logo=logo) if logo is not None else None
            try:
                if joiner is not None:
                    # a whole-video joiner (tests): every part in one call
                    joined = _whole_join(store, tenant_id, parts, spans, overlay, root, joiner)
                else:
                    # production: one short-lived child per part, then a stream copy
                    joined = _segment_join(
                        store,
                        tenant_id,
                        parent_id,
                        parts,
                        spans,
                        logo_key,
                        overlay,
                        root,
                        segmenter=segmenter,
                        concat=concat,
                    )
            except PartsGone as gone:
                logger.error("parent %s: %s", parent_id, gone)
                joins.fail_final(
                    tenant_id=tenant_id, parent_id=parent_id, error=JOIN_FINAL_FAILED_TEXT
                )
                return None
            except JoinError as exc:
                if isinstance(exc, JoinChildLost) and _child_lost(joins, tenant_id, parent_id):
                    # the same part killed its child CHILD_LOSSES_MAX times: not a loop
                    logger.error("parent %s: the join's child keeps dying: %s", parent_id, exc)
                    joins.fail_final(
                        tenant_id=tenant_id, parent_id=parent_id, error=JOIN_FINAL_FAILED_TEXT
                    )
                    return None
                if io_failure(exc):
                    logger.warning(
                        "parent %s: final join interrupted by an IO error: %s", parent_id, exc
                    )
                    raise
                logger.error("parent %s: raw finals could not be joined: %s", parent_id, exc)
                joins.fail_final(
                    tenant_id=tenant_id, parent_id=parent_id, error=JOIN_FINAL_FAILED_TEXT
                )
                return None
            frames = joined.frames
            digest = _file_sha256(joined.path)
            if not _keep(store, tenant_id, key, joined.path, MP4):
                raise JoinNotKept(key)
            if joined.poster:
                poster = root / "final.jpg"
                poster.write_bytes(joined.poster)
                try:
                    if not _keep(store, tenant_id, poster_key, poster, JPEG):
                        poster_key = None
                except Exception:  # noqa: BLE001 — the video is kept; the picture is a nicety
                    logger.warning("parent %s: final poster not kept", parent_id, exc_info=True)
                    poster_key = None
            else:
                poster_key = None
    width, height = JOIN_FINAL_SIZE
    duration = _duration(parts, spans)
    provenance = {
        "version": JOIN_FINAL_VERSION,
        "recipe": JOIN_VERSION,
        "size": [width, height],
        "fps": JOIN_FPS,
        "frames": frames,
        "parts": _provenance(parts, spans),
        "logo": logo_record,
        "approved_fingerprint": block.get("approved_fingerprint"),
        "cost_usd": "0",
    }
    return MediaWrite(
        position=0,
        media_type="video",
        media_url=key,
        object_key=key,
        width=width,
        height=height,
        aspect_ratio="9:16",
        model_id=JOIN_VERSION,
        provider=JOIN_PROVIDER,
        content_type=MP4,
        ai_generated=True,
        params={
            "thumbnail_key": poster_key,
            "duration_seconds": duration,
            "resolution": f"{width}p",
            "join_final": provenance,
            "draft": {
                **block,
                "finish": FINISH_JOIN,
                "status": FINAL_READY,
                "final_fingerprint": fingerprint,
                "final_sha256": digest,
                "final_object_key": key,
                "final_revision": snapshot.revision,
                "preview_object_key": snapshot.joined_object_key,
                "logo": block.get("logo"),
                "final_logo": logo_record,
                "duration_seconds": duration,
                "error": None,
                "confirmed_by": None,
                "confirmed_at": None,
                "confirmed_sha256": None,
                "confirmed_object_key": None,
                "confirmed_revision": None,
            },
        },
    )


def run_join_final(media: Any, tenant_id: UUID, parent_id: UUID) -> bool:
    """The parent's `join_final` phase (the worker's `PipelinePreparation`): join and
    save. True when the final was saved."""
    join = getattr(media, "join_final", None)
    save = getattr(media, "save_join_final", None)
    if not callable(join) or not callable(save):
        logger.error("parent %s: this producer cannot make a final join", parent_id)
        return False
    write = join(tenant_id, parent_id)
    if write is None:
        return False
    return bool(save(tenant_id, parent_id, write))


# ---------------------------------------------------------------------------
# Postgres


def save_final(*, tenant_id: UUID, parent_id: UUID, write: MediaWrite) -> bool:
    """Put the final join in place of the parent's join row (its active version) and
    make its poster the parent's picture — ONE transaction fenced by the run's lease.
    False (nothing written) when the parent is no longer approved at that revision,
    its row was replaced by another join, or the final is already there."""
    block = dict(write.params.get("draft") or {})
    with tenant_unit_of_work(tenant_id) as session:
        run = current_preparation()
        if run is not None:
            PipelineStore().fence(session, run)  # a lost lease never writes
        parent = (
            session.execute(
                text("""
            SELECT revision, active_version_id, status FROM content_drafts
            WHERE id = :p AND parent_draft_id IS NULL FOR UPDATE
        """),
                {"p": parent_id},
            )
            .mappings()
            .first()
        )
        if (
            parent is None
            or parent["status"] != APPROVED
            or parent["revision"] != block.get("final_revision")
        ):
            logger.info("parent %s moved on before its final join was saved", parent_id)
            return False
        current = (
            session.execute(
                text("""
            SELECT id, params->'draft' AS block FROM image_assets
            WHERE draft_id = :p AND params->'draft'->>'finish' = :finish
              AND version_id IS NOT DISTINCT FROM :v
            ORDER BY updated_at DESC LIMIT 1 FOR UPDATE
        """),
                {"p": parent_id, "finish": FINISH_JOIN, "v": parent["active_version_id"]},
            )
            .mappings()
            .first()
        )
        held = dict(current["block"] or {}) if current is not None else {}
        if (
            current is None
            or held.get("status") not in (JOIN_FINAL_PENDING, DRAFT_FAILED)
            or held.get("fingerprint") != block.get("fingerprint")
            or held.get("approved_fingerprint") != block.get("approved_fingerprint")
        ):
            return False
        session.execute(
            text("""
            UPDATE image_assets SET media_url = :url, object_key = :key, content_type = :ct,
                width = :w, height = :h, aspect_ratio = :ratio, model_id = :model,
                provider = :provider, params = CAST(:params AS jsonb), updated_at = now()
            WHERE id = :id
        """),
            {
                "id": current["id"],
                "url": write.media_url,
                "key": write.object_key,
                "ct": write.content_type,
                "w": write.width,
                "h": write.height,
                "ratio": write.aspect_ratio,
                "model": write.model_id,
                "provider": write.provider,
                "params": json.dumps(write.params),
            },
        )
        session.execute(
            text("UPDATE content_drafts SET preview_key = :preview WHERE id = :p"),
            {"p": parent_id, "preview": write.params.get("thumbnail_key") or write.media_url},
        )
    logger.info("parent %s: final join %s saved", parent_id, block.get("final_fingerprint"))
    return True


def child_lost(*, tenant_id: UUID, parent_id: UUID) -> int:
    """One more lost child of the parent's pending final join (`child_losses` on its join
    row), fenced by the lease; the new count (0 when there is no pending row)."""
    with tenant_unit_of_work(tenant_id) as session:
        run = current_preparation()
        if run is not None:
            PipelineStore().fence(session, run)
        count = session.execute(
            text("""
            UPDATE image_assets a SET params = jsonb_set(a.params, '{draft,child_losses}',
                    to_jsonb(COALESCE((a.params->'draft'->>'child_losses')::int, 0) + 1)),
                updated_at = now()
            FROM content_drafts p
            WHERE a.draft_id = p.id AND p.id = :p AND p.status = :approved
              AND a.version_id IS NOT DISTINCT FROM p.active_version_id
              AND a.params->'draft'->>'finish' = :finish
              AND a.params->'draft'->>'status' = :pending
            RETURNING (a.params->'draft'->>'child_losses')::int
        """),
            {
                "p": parent_id,
                "approved": APPROVED,
                "finish": FINISH_JOIN,
                "pending": JOIN_FINAL_PENDING,
            },
        ).scalar()
    return int(count or 0)


def fail_final(*, tenant_id: UUID, parent_id: UUID, error: str) -> bool:
    """Mark the parent's pending final join `failed` with why (fenced by the lease):
    «Reintentar» opens the run again (`ContentService.retry_final`). The raw finals and
    their charges are untouched: a retry pays nothing to the vendor."""
    with tenant_unit_of_work(tenant_id) as session:
        run = current_preparation()
        if run is not None:
            PipelineStore().fence(session, run)
        changed = session.execute(
            text("""
            UPDATE image_assets a SET params = jsonb_set(
                    jsonb_set(a.params, '{draft,status}', to_jsonb(CAST(:failed AS text))),
                    '{draft,error}', to_jsonb(CAST(:error AS text))),
                updated_at = now()
            FROM content_drafts p
            WHERE a.draft_id = p.id AND p.id = :p AND p.status = :approved
              AND a.version_id IS NOT DISTINCT FROM p.active_version_id
              AND a.params->'draft'->>'finish' = :finish
              AND a.params->'draft'->>'status' = :pending
            RETURNING a.id
        """),
            {
                "p": parent_id,
                "failed": DRAFT_FAILED,
                "error": error,
                "approved": APPROVED,
                "finish": FINISH_JOIN,
                "pending": JOIN_FINAL_PENDING,
            },
        ).scalar()
    return changed is not None


__all__ = [
    "CHILD_LOSSES_MAX",
    "PART_EXPIRED_TEXT",
    "PART_FAILED",
    "PartFailed",
    "child_lost",
    "ApproveWholeVideo",
    "PartsNotReady",
    "StaleJoinedPreview",
    "EXPIRED",
    "FINAL_READY",
    "JOIN_FINAL_FAILED_TEXT",
    "JOIN_FINAL_PENDING",
    "JOIN_FINAL_PHASE",
    "JOIN_FINAL_SIZE",
    "JOIN_FINAL_VERSION",
    "NOT_READY",
    "PART_FINAL_NOT_KEPT_TEXT",
    "STALE",
    "PartFinalStore",
    "approval_problem",
    "block_logo_key",
    "fail_final",
    "final_parts",
    "join_final",
    "join_final_fingerprint",
    "part_final_media",
    "preview_fingerprint",
    "raw_key",
    "run_join_final",
    "save_final",
]
