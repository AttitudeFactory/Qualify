"""The joined preview of a video by parts (ADR 44, VE-10a m-24921067).

When every part (child draft) of a parent has its 480p vista previa, the creative
worker joins them locally (`qualify_creative.video.join_clips`, VE-07) into ONE 480×854
preview of the whole video — cost 0, no vendor, no charge row (the vistas previas were
charged per part, D7). Nothing here publishes: the joined file carries a `draft` block
of its own (`finish: "join"`, `status: "join_preview"`), so `draft_pending` is true and
the Planificador refuses it, and `_waiting_drafts` never asks Seedance for a final of it
(VE-10b turns it into the 1080p join).

How it runs (no parent waits in `drafting`, risk N1): the parent's own `generation`
phase only writes its text and ends `generated`. Every time a part settles — its
preview made or failed, another version made, a version restored — `parts.
mark_parent_dirty` opens (or dirties) the parent's `join` run in the same transaction,
and the worker's `PipelinePreparation` runs `run_join` under that run's lease
(`PipelineStore.acquire`): two parts finishing together give one join.

Idempotent by its FINGERPRINT: the ordered `(part, version, file, trim)` list plus the
join's version. The same fingerprint as the parent's current join does nothing; a file
already in R2 under `join-<fingerprint>.mp4` (the bucket never lets a key be
overwritten, N10) is reused, never encoded twice. A part missing, failed, expired or
purged → nothing is joined (the parent shows «generating»).

Trim (design §4.2, «se recorta al unir»): a «Nueva» (`reference`) part was asked for
`generation_seconds` and keeps its first `seconds`; an «Igual al original» (`edit`) part
keeps its own cuts inside the window VE-09 cut, from `params.part.window.offset_s`
(SIGNED: positive = the window opened that many seconds before the part's first cut;
negative = it opened after the part's start and those seconds are not there).

`parent_video_status` is the parent's state FOR THE SCREEN (`generating`, `joining`,
`previewing`, design §3.2) — computed, never a state of `fsm.py`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from qualify_creative.compose import text_layer
from qualify_creative.video.join import JOIN_FPS, JOIN_VERSION, JoinClip, JoinError, join_clips
from qualify_shared.db.session import tenant_session, tenant_unit_of_work
from sqlalchemy import text

from qualify_api.creative.draft_mode import DRAFT_READY, draft_expired, draft_state
from qualify_api.creative.fsm import GENERATED
from qualify_api.creative.media import JPEG, MP4, MediaWrite, owned_by
from qualify_api.creative.pipeline import PipelineStore, current_preparation

logger = logging.getLogger(__name__)

#: The parent's run that joins its parts' previews (`creative_pipeline_runs.phase`).
JOIN_PHASE = "join"
#: Version of the joined preview's recipe — in its fingerprint and its provenance: a
#: new recipe joins again (another key), it never reuses an older recipe's file.
JOIN_PREVIEW_VERSION = "join-preview-v1"
#: The joined preview's size: the vistas previas are 480p 9:16 (Seedance 2.5 draft).
#: The measurement harness sets this constant to 1080×1920 for VE-10b's worst case.
JOIN_PREVIEW_SIZE = (480, 854)
#: `params.draft.finish` / `params.draft.status` of the joined preview.
FINISH_JOIN = "join"
JOIN_PREVIEW_STATUS = "join_preview"
#: Who made the file (`image_assets.provider` / `model_id`): our own local join.
JOIN_PROVIDER = "qualify"
#: A trimmed interval shorter than this is not a trim (float noise): kept whole.
_MIN_SPAN_S = 0.05

#: The parent's states for the screen (design §3.2) — computed, not `fsm.py` states.
PARENT_GENERATING = "generating"
PARENT_JOINING = "joining"
PARENT_PREVIEWING = "previewing"


class JoinNotKept(RuntimeError):
    """The joined file could not be put in R2 (after the store's own retries). Raised so
    the `join` run is NOT marked done: the next pass joins again; the parent keeps the
    join it had (failures keep the previous version)."""


@dataclass(frozen=True)
class PartPreview:
    """One part as the join reads it: the child draft and its ACTIVE version's video."""

    draft_id: UUID
    part_index: int | None
    status: str
    revision: int
    version_id: UUID | None
    object_key: str | None
    params: Mapping[str, Any] = field(default_factory=dict)
    purged: bool = False

    @property
    def join_source(self) -> str | None:
        """The file the join reads: the part's preview WITHOUT the logo when its shown
        preview carries one (`params.part.clean_key`, VE-10a), else the preview itself —
        so the joined video never shows the logo twice."""
        meta = self.params.get("part")
        clean = meta.get("clean_key") if isinstance(meta, Mapping) else None
        return clean if isinstance(clean, str) and clean else self.object_key


@dataclass(frozen=True)
class PartsToJoin:
    """A parent and its parts, as read in one go (`PartJoinStore.read`)."""

    parent_id: UUID
    revision: int
    planned: int  # how many parts the parent's plan has
    parts: tuple[PartPreview, ...]
    #: the fingerprint of the parent's current joined preview (None: none yet)
    joined_fingerprint: str | None = None
    #: the logo chosen for the video (the parent's brief), laid ONCE over the join
    logo_key: str | None = None


class PartJoinStore(Protocol):
    """What the join reads and writes in the database (`DbPartJoins` in production)."""

    def read(self, *, tenant_id: UUID, parent_id: UUID) -> PartsToJoin | None: ...

    def save(self, *, tenant_id: UUID, parent_id: UUID, write: MediaWrite) -> bool: ...


# ---------------------------------------------------------------------------
# pure rules


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def part_span(params: Mapping[str, Any] | None) -> tuple[float, float | None]:
    """The interval of a part's preview the join keeps, `(start_s, end_s)` in seconds
    from its first frame (`end_s=None`: to its end). Pure.

    `reference` / `extend`: asked for `generation_seconds`, keeps the first `seconds`.
    `edit`: the part's own cuts inside its window — `[offset, offset + seconds]` cut to
    `[0, generation_seconds]` (the signed `offset_s` of VE-09). A part without its
    provenance (or a window cut before the part existed, whose offset is unknown) is
    kept from its start, like a `reference` part. An explicit trim of the plan
    (`trim_start_s` / `trim_end_s`, VE-06) wins over both."""
    part = (params or {}).get("part")
    if not isinstance(part, Mapping):
        return 0.0, None
    seconds = _number(part.get("seconds"))
    generated = _number(part.get("generation_seconds"))
    if seconds is None or seconds <= 0:
        return 0.0, None
    whole = generated if generated is not None and generated > 0 else None
    trim_start, trim_end = _number(part.get("trim_start_s")), _number(part.get("trim_end_s"))
    if trim_start is not None and trim_end is not None and trim_end - trim_start >= _MIN_SPAN_S:
        if whole is not None:
            trim_end = min(trim_end, whole)
        if trim_end - trim_start >= _MIN_SPAN_S:
            return round(max(0.0, trim_start), 3), round(trim_end, 3)
    if part.get("mode") == "edit":
        window = part.get("window")
        offset = _number(window.get("offset_s")) if isinstance(window, Mapping) else None
        if offset is not None:
            start = max(0.0, offset)
            end = offset + seconds
            if whole is not None:
                end = min(end, whole)
            if end - start >= _MIN_SPAN_S:
                keep_end: float | None = round(end, 3)
                if whole is not None and end >= whole - 1e-6:
                    keep_end = None  # to its end: nothing to cut there
                return round(start, 3), keep_end
            logger.warning("edit part window leaves nothing to join: kept whole")
            return 0.0, None
    if whole is not None and seconds < whole - 1e-6:
        return 0.0, round(seconds, 3)
    return 0.0, None


def ready_parts(
    snapshot: PartsToJoin, tenant_id: UUID, now: float | None = None
) -> tuple[PartPreview, ...] | None:
    """The parts in plan order when EVERY one has a live vista previa to join, else
    None: one missing (not created yet, still drafting), failed, without its 480p
    preview, expired (7 days, `draft_expired`), purged, or with a file that is not this
    business's. Pure."""
    if snapshot.planned < 1 or len(snapshot.parts) != snapshot.planned:
        return None
    ordered = sorted(snapshot.parts, key=lambda p: p.part_index or 0)
    if [p.part_index for p in ordered] != list(range(1, snapshot.planned + 1)):
        return None
    moment = time.time() if now is None else now
    for part in ordered:
        if part.status != GENERATED or part.purged or part.version_id is None:
            return None
        if not part.object_key or not owned_by(tenant_id, part.object_key):
            return None
        source = part.join_source
        if not source or not owned_by(tenant_id, source):
            return None
        block = draft_state(part.params)
        if block is None or block.get("status") != DRAFT_READY:
            return None
        if draft_expired(block, moment):
            return None
    return tuple(ordered)


def join_fingerprint(
    parts: Sequence[PartPreview],
    spans: Sequence[tuple[float, float | None]],
    logo_key: str | None = None,
) -> str:
    """What makes a joined preview THIS one: the recipe, the size, the logo laid over it
    and, in order, each part's draft, active version, file (the one without the logo)
    and trim. Another version of any part (made or restored) or another logo is another
    fingerprint. Pure."""
    data: dict[str, Any] = {
        "version": JOIN_PREVIEW_VERSION,
        "recipe": JOIN_VERSION,
        "size": list(JOIN_PREVIEW_SIZE),
        "parts": [
            [str(p.draft_id), str(p.version_id), p.join_source, start, end]
            for p, (start, end) in zip(parts, spans, strict=True)
        ],
    }
    if logo_key:
        data["logo"] = logo_key  # absent without one: older fingerprints stay valid
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:20]


def io_failure(exc: BaseException) -> bool:
    """Whether a `JoinError` came from the machine (a full /tmp, a file cut short, a
    read or write that failed: an `OSError` anywhere in its causes) rather than from the
    parts themselves (no video stream, no frame, undecodable data, a bad interval). Only
    the latter is final; the former is retried by the next pass. Pure."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, OSError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def join_key(tenant_id: UUID, parent_id: UUID, fingerprint: str, suffix: str = "mp4") -> str:
    """`t/{tenant}/generated/{parent}/join-<fingerprint>.<suffix>`: one key per join (the
    bucket refuses overwrites), under the parent's folder (retention purges it)."""
    return f"t/{tenant_id}/generated/{parent_id}/join-{fingerprint}.{suffix}"


def parent_video_status(
    snapshot: PartsToJoin | None, tenant_id: UUID, now: float | None = None
) -> str:
    """The parent's state for the screen (design §3.2), computed: `generating` while a
    part is missing, being made, failed or expired; `joining` when every part is ready
    and the joined preview is not (yet) theirs; `previewing` when it is."""
    if snapshot is None:
        return PARENT_GENERATING
    parts = ready_parts(snapshot, tenant_id, now)
    if parts is None:
        return PARENT_GENERATING
    fingerprint = join_fingerprint(parts, [part_span(p.params) for p in parts], snapshot.logo_key)
    return PARENT_PREVIEWING if fingerprint == snapshot.joined_fingerprint else PARENT_JOINING


# ---------------------------------------------------------------------------
# the store's files (R2 in production, a dict in tests)


def _fetch(store: Any, tenant_id: UUID, key: str, path: Path) -> None:
    """The part's file to disk — streamed from R2 when the store can (never the whole
    1080p file in the heap); the plain `read` otherwise."""
    copy = getattr(store, "copy_to_file", None)
    if callable(copy):
        copy(tenant_id, key, path)
        return
    path.write_bytes(store.read(key))


def _held(store: Any, tenant_id: UUID, key: str) -> bool:
    """Whether `key` already holds a file (a join of this same fingerprint kept by a run
    whose database write never landed). Unknown → False: the join is made again."""
    has = getattr(store, "has_object", None)
    try:
        if callable(has):
            return bool(has(tenant_id, key))
        store.read(key)
        return True
    except Exception:  # noqa: BLE001 — not there, or cannot tell
        return False


def _keep(store: Any, tenant_id: UUID, key: str, path: Path, content_type: str) -> bool:
    """Put the joined file in R2 (streamed, retried by the store); a key already held is
    a success — its name is its fingerprint. A store without R2 (tests, dev) writes."""
    keep_file = getattr(store, "keep_file", None)
    if callable(keep_file):
        return bool(keep_file(tenant_id, key, path, content_type))
    keep = getattr(store, "keep", None)
    if callable(keep):
        return bool(keep(tenant_id, key, path.read_bytes(), content_type))
    store.write(key, path.read_bytes())
    return True


# ---------------------------------------------------------------------------
# the join


def _missing(exc: BaseException) -> bool:
    """A file that is not there (R2's `ObjectNotFound`, a local file or a test store's
    key that does not exist) — final — as opposed to a read that failed on the way."""
    from qualify_shared.objects.gate import ObjectNotFound  # noqa: PLC0415

    return isinstance(exc, ObjectNotFound | FileNotFoundError | KeyError)


def _read_logo(store: Any, tenant_id: UUID, key: str | None) -> bytes | None:
    """The video's logo, if it is this business's. A key that is missing from the store
    or another business's is joined without a logo («sin logo», final, like a Clip's); a
    read that FAILS (R2 down, a cut connection) is raised, so the run is retried rather
    than saving a joined preview without its logo that nothing would redo."""
    if not key:
        return None
    if not owned_by(tenant_id, key):
        logger.error("a joined preview's logo is not this business's file: not laid")
        return None
    try:
        return store.read(key)
    except Exception as exc:
        if _missing(exc):
            logger.warning("joined preview's logo %s is gone: joined without it", key)
            return None
        raise


def _oldest_created_at(parts: Sequence[PartPreview]) -> float | None:
    """The oldest part's vista previa date (Unix seconds): the whole video's deadline
    starts there (design §3.2, «el plazo del padre es el de su parte más vieja»)."""
    dates = [
        value
        for value in (_number((draft_state(p.params) or {}).get("created_at")) for p in parts)
        if value is not None
    ]
    return min(dates) if dates else None


def _provenance(
    parts: Sequence[PartPreview], spans: Sequence[tuple[float, float | None]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for part, (start, end) in zip(parts, spans, strict=True):
        meta = part.params.get("part") if isinstance(part.params.get("part"), Mapping) else {}
        window = meta.get("window") if isinstance(meta.get("window"), Mapping) else {}
        block = draft_state(part.params) or {}
        out.append(
            {
                "draft_id": str(part.draft_id),
                "part_index": part.part_index,
                "version_id": str(part.version_id),
                "revision": part.revision,
                "object_key": part.object_key,
                "joined_key": part.join_source,
                "raw_key": block.get("raw_key") or meta.get("raw_key"),
                "mode": meta.get("mode"),
                "seconds": meta.get("seconds"),
                "generation_seconds": meta.get("generation_seconds"),
                "offset_s": window.get("offset_s"),
                "start_s": start,
                "end_s": end,
                "model_id": block.get("model"),
            }
        )
    return out


def _duration(parts: Sequence[PartPreview], spans: Sequence[tuple[float, float | None]]) -> float:
    total = 0.0
    for part, (start, end) in zip(parts, spans, strict=True):
        meta = part.params.get("part") if isinstance(part.params.get("part"), Mapping) else {}
        whole = _number(meta.get("generation_seconds")) or _number(
            (draft_state(part.params) or {}).get("duration_seconds")
        )
        stop = end if end is not None else whole
        if stop is not None:
            total += max(0.0, stop - start)
    return round(total, 3)


def join_preview(
    store: Any,
    joins: PartJoinStore,
    tenant_id: UUID,
    parent_id: UUID,
    *,
    now: float | None = None,
    joiner: Callable[..., Any] | None = None,
) -> MediaWrite | None:
    """The joined preview of `parent_id` to save, or None when there is nothing to do:
    a part not ready, or the parent's current join already IS these parts. The file is
    in R2 when this returns (`JoinNotKept` otherwise). A part that cannot be decoded
    (`JoinError` from the parts themselves) is logged and nothing is joined: joining
    again would fail the same way, so the run is not retried until a part changes. An
    IO failure (`OSError`, also wrapped in a `JoinError`: full /tmp, a stream cut short)
    is raised, so the run is retried."""
    snapshot = joins.read(tenant_id=tenant_id, parent_id=parent_id)
    if snapshot is None:
        return None
    parts = ready_parts(snapshot, tenant_id, now)
    if parts is None:
        logger.info("parent %s: not every part has its preview yet; nothing joined", parent_id)
        return None
    spans = [part_span(p.params) for p in parts]
    logo = _read_logo(store, tenant_id, snapshot.logo_key)
    logo_key = snapshot.logo_key if logo is not None else None
    fingerprint = join_fingerprint(parts, spans, logo_key)
    if fingerprint == snapshot.joined_fingerprint:
        return None
    logo_record: dict[str, Any] | str = (
        {"key": logo_key, "sha256": hashlib.sha256(logo).hexdigest()[:16]}
        if logo is not None
        else "sin logo"
    )
    key = join_key(tenant_id, parent_id, fingerprint)
    poster_key: str | None = join_key(tenant_id, parent_id, fingerprint, "jpg")
    frames: int | None = None
    if _held(store, tenant_id, key):
        # kept by a run whose database write never landed, or a version restored back to
        # one already joined: the same parts, the same file — not encoded again
        logger.info("parent %s: join %s already kept; reused", parent_id, fingerprint)
        if not _held(store, tenant_id, poster_key):
            poster_key = None
    else:
        with tempfile.TemporaryDirectory(prefix="qualify-join-") as folder:
            root = Path(folder)
            clips = []
            for index, (part, (start, end)) in enumerate(zip(parts, spans, strict=True)):
                path = root / f"part-{index}.mp4"
                try:
                    _fetch(store, tenant_id, str(part.join_source), path)
                except Exception as exc:
                    if not _missing(exc):
                        raise  # an IO or transport failure: the next pass retries
                    # the part's file is gone for good: like a part not ready, final —
                    # the run is done until a part changes (no retry every pass)
                    logger.error(
                        "parent %s: part %s file %s is missing; nothing joined",
                        parent_id,
                        part.part_index,
                        part.join_source,
                    )
                    return None
                clips.append(JoinClip(path, start_s=start, end_s=end))
            # the logo ONCE over the whole joined video (VE-07's overlay), placed as on
            # any Clip: `text_layer` with the logo alone (Deivid, 2026-11-06)
            overlay = text_layer(size=JOIN_PREVIEW_SIZE, logo=logo) if logo is not None else None
            try:
                joined = (joiner or join_clips)(
                    clips, out=root / "join.mp4", size=JOIN_PREVIEW_SIZE, overlay=overlay
                )
            except JoinError as exc:
                if io_failure(exc):
                    # the disk or the stream failed, not the parts: the run is not marked
                    # done, the next pass joins again (or reuses a kept file)
                    logger.warning(
                        "parent %s: join interrupted by an IO error (%s): %s",
                        parent_id,
                        fingerprint,
                        exc,
                    )
                    raise
                logger.error(
                    "parent %s: parts could not be joined (%s): %s", parent_id, fingerprint, exc
                )
                return None
            frames = joined.frames
            if not _keep(store, tenant_id, key, joined.path, MP4):
                raise JoinNotKept(key)
            if joined.poster:
                poster = root / "join.jpg"
                poster.write_bytes(joined.poster)
                try:
                    if not _keep(store, tenant_id, poster_key, poster, JPEG):
                        poster_key = None
                except Exception:  # noqa: BLE001 — the video is kept; the picture is a nicety
                    logger.warning("parent %s: join poster not kept", parent_id, exc_info=True)
                    poster_key = None
            else:
                poster_key = None
    width, height = JOIN_PREVIEW_SIZE
    duration = _duration(parts, spans)
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
        ai_generated=True,  # made of AI clips: the parent keeps the AI disclosure
        params={
            "thumbnail_key": poster_key,
            "duration_seconds": duration,
            "resolution": f"{height}p",
            # rule 6 — what was joined, how, by which recipe, at what cost
            "join": {
                "version": JOIN_PREVIEW_VERSION,
                "recipe": JOIN_VERSION,
                "size": [width, height],
                "fps": JOIN_FPS,
                "frames": frames,
                "parts": _provenance(parts, spans),
                "logo": logo_record,
                "cost_usd": "0",
            },
            # its own lifecycle: never publishable (draft_pending), never a final of
            # Seedance (`_waiting_drafts` asks only `draft` / `failed`)
            "draft": {
                "finish": FINISH_JOIN,
                "status": JOIN_PREVIEW_STATUS,
                "parts": [[str(p.draft_id), str(p.version_id)] for p in parts],
                "fingerprint": fingerprint,
                "logo": logo_record,
                "created_at": _oldest_created_at(parts),
                "parent_revision": snapshot.revision,
                "duration_seconds": duration,
                "cost_usd": "0",
            },
        },
    )


def run_join(media: Any, tenant_id: UUID, parent_id: UUID) -> bool:
    """The parent's `join` phase (the worker's `PipelinePreparation`): join and save.
    True when a new joined preview was saved."""
    join = getattr(media, "join_preview", None)
    save = getattr(media, "save_join_preview", None)
    if not callable(join) or not callable(save):
        logger.error("parent %s: this producer cannot join parts", parent_id)
        return False
    write = join(tenant_id, parent_id)
    if write is None:
        return False
    return bool(save(tenant_id, parent_id, write))


# ---------------------------------------------------------------------------
# Postgres


class DbPartJoins:
    """`PartJoinStore` over Postgres, always as the owning tenant (`tenant_session`, RLS):
    another business's parent reads as missing."""

    def read(self, *, tenant_id: UUID, parent_id: UUID) -> PartsToJoin | None:
        with tenant_session(tenant_id) as session:
            parent = (
                session.execute(
                    text("""
                SELECT p.revision, p.active_version_id, p.parent_draft_id, b.kind,
                       b.media->>'brand_logo_key' AS logo_key,
                       COALESCE(jsonb_array_length(
                           CASE WHEN jsonb_typeof(b.media->'parts') = 'array'
                                THEN b.media->'parts' END), 0) AS planned
                FROM content_drafts p JOIN content_briefs b ON b.id = p.brief_id
                WHERE p.id = :p
            """),
                    {"p": parent_id},
                )
                .mappings()
                .first()
            )
            if parent is None or parent["parent_draft_id"] is not None:
                return None
            if parent["kind"] != "shot_video":
                return None
            rows = (
                session.execute(
                    text("""
                SELECT c.id, c.part_index, c.status, c.revision, c.active_version_id,
                       c.media_purged_at IS NOT NULL AS purged, a.object_key, a.params
                FROM content_drafts c
                LEFT JOIN LATERAL (
                    SELECT object_key, params FROM image_assets a
                    WHERE a.draft_id = c.id AND a.version_id = c.active_version_id
                      AND a.media_type = 'video'
                    ORDER BY a.position, a.created_at LIMIT 1
                ) a ON true
                WHERE c.parent_draft_id = :p
                ORDER BY c.part_index
            """),
                    {"p": parent_id},
                )
                .mappings()
                .all()
            )
            joined = session.execute(
                text("""
                SELECT a.params->'draft'->>'fingerprint' FROM image_assets a
                WHERE a.draft_id = :p AND a.params->'draft'->>'finish' = :finish
                  AND a.version_id IS NOT DISTINCT FROM :v
                ORDER BY a.updated_at DESC LIMIT 1
            """),
                {"p": parent_id, "finish": FINISH_JOIN, "v": parent["active_version_id"]},
            ).scalar()
        return PartsToJoin(
            parent_id=parent_id,
            revision=int(parent["revision"]),
            planned=int(parent["planned"]),
            parts=tuple(
                PartPreview(
                    draft_id=row["id"],
                    part_index=row["part_index"],
                    status=row["status"],
                    revision=int(row["revision"]),
                    version_id=row["active_version_id"],
                    object_key=row["object_key"],
                    params=dict(row["params"] or {}),
                    purged=bool(row["purged"]),
                )
                for row in rows
            ),
            joined_fingerprint=joined,
            logo_key=parent["logo_key"] or None,
        )

    def parent_logo_key(self, *, tenant_id: UUID, part_id: UUID) -> str | None:
        """The logo chosen for a part's video by parts (its parent's brief), or None."""
        with tenant_session(tenant_id) as session:
            return session.execute(
                text("""
                SELECT b.media->>'brand_logo_key' FROM content_drafts c
                JOIN content_drafts p ON p.tenant_id = c.tenant_id AND p.id = c.parent_draft_id
                JOIN content_briefs b ON b.id = p.brief_id
                WHERE c.id = :c
            """),
                {"c": part_id},
            ).scalar()

    def save(self, *, tenant_id: UUID, parent_id: UUID, write: MediaWrite) -> bool:
        """Put the joined preview on the parent's ACTIVE version (one row at position 0:
        a later join replaces the row's file, the files stay in R2) and make it the
        parent's picture, in ONE transaction fenced by the run's lease. False (nothing
        written) when the parent moved on (another revision) or already shows this join."""
        block = dict(write.params.get("draft") or {})
        fingerprint = block.get("fingerprint")
        with tenant_unit_of_work(tenant_id) as session:
            run = current_preparation()
            if run is not None:
                PipelineStore().fence(session, run)  # a lost lease never writes
            parent = (
                session.execute(
                    text("""
                SELECT revision, active_version_id FROM content_drafts
                WHERE id = :p AND parent_draft_id IS NULL FOR UPDATE
            """),
                    {"p": parent_id},
                )
                .mappings()
                .first()
            )
            if parent is None or parent["revision"] != block.get("parent_revision"):
                logger.info("parent %s moved on before its join was saved", parent_id)
                return False
            version = parent["active_version_id"]
            current = (
                session.execute(
                    text("""
                SELECT id, params->'draft'->>'fingerprint' AS fingerprint FROM image_assets
                WHERE draft_id = :p AND params->'draft'->>'finish' = :finish
                  AND version_id IS NOT DISTINCT FROM :v
                ORDER BY updated_at DESC LIMIT 1 FOR UPDATE
            """),
                    {"p": parent_id, "finish": FINISH_JOIN, "v": version},
                )
                .mappings()
                .first()
            )
            if current is not None and current["fingerprint"] == fingerprint:
                return False
            values = {
                "t": tenant_id,
                "p": parent_id,
                "v": version,
                "url": write.media_url,
                "key": write.object_key,
                "ct": write.content_type,
                "w": write.width,
                "h": write.height,
                "ratio": write.aspect_ratio,
                "model": write.model_id,
                "provider": write.provider,
                "params": json.dumps(write.params),
                "pos": write.position,
            }
            if current is None:
                session.execute(
                    text("""
                    INSERT INTO image_assets (tenant_id, draft_id, version_id, media_url,
                        object_key, content_type, width, height, aspect_ratio, model_id,
                        provider, params, media_type, position)
                    VALUES (:t, :p, :v, :url, :key, :ct, :w, :h, :ratio, :model, :provider,
                        CAST(:params AS jsonb), 'video', :pos)
                """),
                    values,
                )
            else:
                session.execute(
                    text("""
                    UPDATE image_assets SET media_url = :url, object_key = :key,
                        content_type = :ct, width = :w, height = :h, aspect_ratio = :ratio,
                        model_id = :model, provider = :provider,
                        params = CAST(:params AS jsonb), updated_at = now()
                    WHERE id = :id
                """),
                    {**values, "id": current["id"]},
                )
            session.execute(
                text("""
                UPDATE content_drafts SET preview_key = :preview,
                    requires_ai_disclosure = true
                WHERE id = :p
            """),
                {"p": parent_id, "preview": write.params.get("thumbnail_key") or write.media_url},
            )
        logger.info("parent %s: joined preview %s saved", parent_id, fingerprint)
        return True


__all__ = [
    "FINISH_JOIN",
    "JOIN_PHASE",
    "JOIN_PREVIEW_SIZE",
    "JOIN_PREVIEW_STATUS",
    "JOIN_PREVIEW_VERSION",
    "PARENT_GENERATING",
    "PARENT_JOINING",
    "PARENT_PREVIEWING",
    "DbPartJoins",
    "JoinNotKept",
    "PartJoinStore",
    "PartPreview",
    "PartsToJoin",
    "join_fingerprint",
    "io_failure",
    "join_key",
    "join_preview",
    "parent_video_status",
    "part_span",
    "ready_parts",
    "run_join",
]
