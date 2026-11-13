"""Review one part of a video by parts on its result screen (UI-8, m-24921083).

- «Me gusta así» (`set_part_liked`): the owner says the part's vista previa is fine.
  Stored as `liked_at` (Unix seconds) in the `draft` block of the part's ACTIVE video
  asset (`image_assets.params`, decided with the founder 2026-11-12: no migration).
  Each version has its own asset, so a new version starts without the mark and going
  back to an earlier one shows that version's own. The mark is optional and only
  remembers what was reviewed: it charges nothing, approves nothing and never touches
  the parent — approving the whole video stays the only charge. It is not in the join's
  fingerprint (`part_join.join_fingerprint`) nor in `ready_parts` /
  `approval_problem`, which read the block's `status` only. The row then reads
  `PartState.READY` «Lista» (`part_progress.derive_state`).
- «Versión 2 de 2 · Ver la anterior» (`part_versions`): the part's versions that came
  out (`piece_versions.status = 'active'`), each with the description and photos of
  ITS OWN brief (`piece_versions.brief_id`, VE-08) and its own video.
- «Usar esta versión» (`use_part_version`): `ContentService.restore_version`, which for
  a part already runs the parent's fence (`parts.part_changing("part_restored")`) and
  tells the parent to join again. Nothing is generated: it costs 0.
- `part_edit_fields`: what «Cambiar y crear otra versión» starts from (the active
  version's mode, description and photos) — the change itself is
  `PartsService.regenerate_part`.

Photos are the EFFECTIVE ones of each version: the child brief's `clip_image_keys`
(the parent's, already resolved when the part was made, or the owner's own — UI-4's
`clip_image_keys = None` inherits at `_child_brief`), only those with the product role.

Every read and write goes through `tenant_session` (RLS): another business's video
reads as missing (`UnknownDraft`).
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative.draft_mode import draft_expired
from qualify_api.creative.fsm import GENERATED, REJECTED
from qualify_api.creative.part_progress import liked_mark, part_source, poster_key
from qualify_api.creative.service import UnknownDraft
from qualify_api.creative.versions import PURGED_FILES_TEXT

if TYPE_CHECKING:
    from qualify_api.creative.service import ContentService

#: The child statuses whose vista previa the owner reviews («Para revisar»).
REVIEWABLE = frozenset({GENERATED, REJECTED})

#: Why a part cannot take «Me gusta así» (or a version cannot be used), with the text
#: the owner reads (`qualify-copy-es`).
NOT_REVIEWABLE_TEXTS: dict[str, str] = {
    "not_reviewable": "Esta parte no tiene una vista previa para revisar ahora.",
    "no_video": "Esta parte todavía no tiene una vista previa para revisar.",
    # the panel's real button is «Crear otra versión» (UX review of UI-8)
    "expired": "Esta vista previa venció. Crea otra versión.",
    "unknown_version": "Esa versión de la parte ya no está disponible.",
    # `versions.restore`'s own refusals, already written for the owner
    "purged": PURGED_FILES_TEXT,
    "scheduled": "Cancela la programación antes de cambiar la versión.",
    "busy": "Espera a que termine la generación antes de usar otra versión.",
}
#: `versions.restore` refuses with a `ValueError` whose text is the owner's: each one
#: maps to its reason here (anything else stays an unexpected error).
_RESTORE_REFUSALS: dict[str, str] = {
    "Esta versión no está disponible.": "unknown_version",
    "La publicación ya no está disponible.": "unknown_version",
    PURGED_FILES_TEXT: "purged",
    NOT_REVIEWABLE_TEXTS["scheduled"]: "scheduled",
    NOT_REVIEWABLE_TEXTS["busy"]: "busy",
}


class PartNotReviewable(ValueError):
    """The part (or the version asked for) cannot be reviewed now. `reason` is a key of
    `NOT_REVIEWABLE_TEXTS`; the message is the owner's text. Nothing written."""

    def __init__(self, reason: str) -> None:
        super().__init__(NOT_REVIEWABLE_TEXTS[reason])
        self.reason = reason


@dataclass(frozen=True)
class PartVersion:
    """One version of a part that came out, as «Versión n de m» shows it."""

    version_id: UUID
    ordinal: int  # 1..total among the part's versions that came out, by revision
    total: int
    current: bool  # the part's active version
    description: str  # the description of ITS brief
    photo_keys: tuple[str, ...]  # its effective product photos
    mode: str
    video_key: str | None  # R2 keys: the screen signs them
    poster_key: str | None
    seconds: float | None
    liked: bool
    expired: bool  # no file to watch any more: never offered to use


@dataclass(frozen=True)
class PartEditFields:
    """What «Cambiar y crear otra versión» starts from: the active version's fields and
    where the part comes from in the original reel («Original»)."""

    mode: str
    description: str
    photo_keys: tuple[str, ...]
    analysis_id: UUID | None
    shot_indexes: tuple[int, ...]
    #: EVERY photo of the active brief, in its order, whatever its role (place, style…):
    #: «Crear otra versión» with the owner's product photos must keep the others —
    #: `PartChanges.photo_keys` replaces the whole list (`parts.part_brief_with` keeps
    #: each key's role when the key was there before)
    all_photo_keys: tuple[str, ...] = ()
    #: the business's brand (what the month's balance is read for, with no lock)
    brand_id: UUID | None = None


# ---------------------------------------------------------------------------
# pure helpers


def image_keys(media: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Every photo of a part's brief `media` (`clip_image_keys`), in order, each once,
    whatever its role. Pure."""
    keys = (media or {}).get("clip_image_keys")
    if not isinstance(keys, list | tuple):
        return ()
    return tuple(dict.fromkeys(key for key in keys if isinstance(key, str)))


def product_photos(media: Mapping[str, Any] | None) -> tuple[str, ...]:
    """The effective product photos of a part's brief `media`: its `clip_image_keys`
    whose role is the product (no roles, or roles that do not match in number = every
    one the product, as `parts.parent_images`). Pure."""
    keys = (media or {}).get("clip_image_keys")
    if not isinstance(keys, list | tuple):
        return ()
    roles = (media or {}).get("clip_image_roles")
    if not isinstance(roles, list | tuple) or len(roles) != len(keys):
        roles = ("product",) * len(keys)
    return tuple(
        dict.fromkeys(
            key
            for key, role in zip(keys, roles, strict=True)
            if isinstance(key, str) and role == "product"
        )
    )


def _part(media: Mapping[str, Any] | None) -> Mapping[str, Any]:
    part = (media or {}).get("part")
    return part if isinstance(part, Mapping) else {}


def _seconds(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if 0 < seconds < 3600 else None


def version_expired(
    *, object_key: str | None, block: Mapping[str, Any] | None, purged: bool, now: float
) -> bool:
    """A version with nothing to watch: no video, files purged, or its vista previa past
    its 7 days (`draft_expired`). Pure."""
    if purged or not object_key:
        return True
    return isinstance(block, Mapping) and draft_expired(block, now)


def versions_from_rows(rows: list[Mapping[str, Any]], now: float) -> tuple[PartVersion, ...]:
    """The `PartVersion`s of a part from its version rows, in revision order. Pure."""
    total = len(rows)
    out: list[PartVersion] = []
    for ordinal, row in enumerate(rows, start=1):
        media = row["media"] if isinstance(row["media"], Mapping) else {}
        part = _part(media)
        block = row["block"] if isinstance(row["block"], Mapping) else None
        current = bool(row["current"])
        out.append(
            PartVersion(
                version_id=row["id"],
                ordinal=ordinal,
                total=total,
                current=current,
                description=str(part.get("description") or ""),
                photo_keys=product_photos(media),
                mode=str(part.get("mode") or "reference"),
                video_key=row["object_key"] or None,
                poster_key=poster_key(
                    row["thumbnail_key"], row["preview_key"] if current else None
                ),
                seconds=_seconds(row["video_seconds"]),
                liked=liked_mark(block),
                expired=version_expired(
                    object_key=row["object_key"], block=block, purged=bool(row["purged"]), now=now
                ),
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# reads and writes (tenant_session, RLS)

_CHILD = """
    FROM content_drafts p
    JOIN content_drafts c ON c.parent_draft_id = p.id AND c.part_index = :i
    WHERE p.id = :p AND p.parent_draft_id IS NULL
"""


def _child_id(session: Any, parent_id: UUID, part_index: int) -> UUID:
    child = session.execute(
        text("SELECT c.id" + _CHILD), {"p": parent_id, "i": part_index}
    ).scalar()
    if child is None:
        raise UnknownDraft(f"{parent_id}#{part_index}")
    return child


def _child(session: Any, parent_id: UUID, part_index: int) -> tuple[UUID, bool]:
    """The part's draft id and whether the owner removed it (`part_removed_at`, as
    `set_part_liked` reads it). `UnknownDraft` when it is not this business's."""
    row = (
        session.execute(
            text("SELECT c.id, c.part_removed_at IS NOT NULL AS removed" + _CHILD),
            {"p": parent_id, "i": part_index},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise UnknownDraft(f"{parent_id}#{part_index}")
    return row["id"], bool(row["removed"])


def set_part_liked(*, tenant_id: UUID, parent_id: UUID, part_index: int, liked: bool) -> bool:
    """«Me gusta así» on (or off) part `part_index` of `parent_id`: `liked_at` set with
    `jsonb_set` (removed with `#-`) in the draft block of its ACTIVE video. Idempotent:
    True only when this call changed the mark. Refuses (`PartNotReviewable`) a part that
    is not to review (`generated`/`rejected`), without an active video with its draft
    block, purged or expired; `UnknownDraft` for a part that is not this business's.
    Charges nothing and never touches the parent."""
    with tenant_session(tenant_id) as session:
        row = (
            session.execute(
                text(
                    "SELECT c.id, c.status, c.active_version_id, "
                    "c.media_purged_at IS NOT NULL OR p.media_purged_at IS NOT NULL AS purged, "
                    "c.part_removed_at IS NOT NULL AS removed" + _CHILD + " FOR UPDATE OF c"
                ),
                {"p": parent_id, "i": part_index},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise UnknownDraft(f"{parent_id}#{part_index}")
        if row["status"] not in REVIEWABLE or row["removed"]:
            raise PartNotReviewable("not_reviewable")
        asset = (
            session.execute(
                text("""
                SELECT id, object_key, params->'draft' AS block FROM image_assets
                WHERE draft_id = :c AND version_id = :v AND media_type = 'video'
                ORDER BY position, created_at LIMIT 1
                FOR UPDATE
                """),
                {"c": row["id"], "v": row["active_version_id"]},
            )
            .mappings()
            .first()
        )
        block = None if asset is None else asset["block"]
        if asset is None or not asset["object_key"] or not isinstance(block, Mapping):
            raise PartNotReviewable("no_video")
        if row["purged"] or draft_expired(block, time.time()):
            raise PartNotReviewable("expired")
        if liked_mark(block) == liked:
            return False
        if liked:
            session.execute(
                text(
                    "UPDATE image_assets SET params = jsonb_set(params, '{draft,liked_at}', "
                    "to_jsonb(CAST(:now AS bigint))) WHERE id = :a"
                ),
                {"a": asset["id"], "now": int(time.time())},
            )
        else:
            session.execute(
                text("UPDATE image_assets SET params = params #- '{draft,liked_at}' WHERE id = :a"),
                {"a": asset["id"]},
            )
        return True


def part_versions(
    *, tenant_id: UUID, parent_id: UUID, part_index: int, now: float | None = None
) -> tuple[PartVersion, ...]:
    """The versions of part `part_index` that came out, oldest first, with «n de m»,
    each with its own brief's description and photos and its own video. One read.
    A part the owner removed has none to show (empty). `UnknownDraft` for a part that is
    not this business's."""
    with tenant_session(tenant_id) as session:
        child, removed = _child(session, parent_id, part_index)
        if removed:
            return ()
        rows = (
            session.execute(
                text("""
                SELECT v.id, v.revision, v.id = c.active_version_id AS current,
                       b.media, a.object_key, a.params->'draft' AS block,
                       a.params->>'thumbnail_key' AS thumbnail_key, c.preview_key,
                       COALESCE(a.params->'draft'->>'duration_seconds',
                                a.params->>'duration_seconds') AS video_seconds,
                       c.media_purged_at IS NOT NULL OR p.media_purged_at IS NOT NULL
                           AS purged
                FROM content_drafts c
                JOIN content_drafts p ON p.id = c.parent_draft_id
                JOIN piece_versions v ON v.draft_id = c.id AND v.status = 'active'
                LEFT JOIN content_briefs b ON b.id = COALESCE(v.brief_id, c.brief_id)
                LEFT JOIN LATERAL (
                    SELECT object_key, params FROM image_assets a
                    WHERE a.draft_id = c.id AND a.version_id = v.id AND a.media_type = 'video'
                    ORDER BY a.position, a.created_at LIMIT 1
                ) a ON true
                WHERE c.id = :c
                ORDER BY v.revision
                """),
                {"c": child},
            )
            .mappings()
            .all()
        )
    return versions_from_rows([dict(r) for r in rows], time.time() if now is None else now)


def use_part_version(
    *,
    tenant_id: UUID,
    parent_id: UUID,
    part_index: int,
    version_id: UUID,
    user_id: UUID,
    content: ContentService | None = None,
) -> None:
    """«Usar esta versión»: version `version_id` of part `part_index` becomes the active
    one again (`ContentService.restore_version`, with the parent's fence and its join
    opened again). Generates nothing and charges nothing. Refuses (`PartNotReviewable`)
    a version that is not one of this part's that came out, one already expired, a part
    the owner removed, and — in `restore`'s own words — a scheduled video, a part still
    being made or purged files. `user_id` is who asked (kept for the screen's audit
    trail; restore needs none).

    The checks here read in their own transaction; `restore` checks again under its
    locks (status, schedule, purge, the version being active), so a race between the two
    is refused there, never written."""
    del user_id  # restore records no actor today; the signature keeps the screen's call
    with tenant_session(tenant_id) as session:
        child, removed = _child(session, parent_id, part_index)
    if removed:
        raise PartNotReviewable("not_reviewable")
    versions = part_versions(tenant_id=tenant_id, parent_id=parent_id, part_index=part_index)
    chosen = next((v for v in versions if v.version_id == version_id), None)
    if chosen is None:
        raise PartNotReviewable("unknown_version")
    if chosen.expired:
        raise PartNotReviewable("expired")
    if content is None:
        from qualify_api.creative.composition import production_content_service

        content = production_content_service()
    try:
        content.restore_version(tenant_id=tenant_id, draft_id=child, version_id=version_id)
    except ValueError as exc:
        reason = _RESTORE_REFUSALS.get(str(exc))
        if reason is None:
            raise
        raise PartNotReviewable(reason) from exc


def part_edit_fields(*, tenant_id: UUID, parent_id: UUID, part_index: int) -> PartEditFields:
    """The fields «Cambiar y crear otra versión» starts filled with: the mode,
    description and effective product photos of the part's ACTIVE brief, and where it
    comes from in the original reel. `UnknownDraft` for a part that is not this
    business's."""
    with tenant_session(tenant_id) as session:
        # a plain read — never `FOR UPDATE`: the panel must open while a join or a
        # generation holds the part's row (live test 2026-11-13)
        row = (
            session.execute(
                text(
                    "SELECT b.media, c.brand_id"
                    + _CHILD.replace(
                        "WHERE", "LEFT JOIN content_briefs b ON b.id = c.brief_id WHERE", 1
                    )
                ),
                {"p": parent_id, "i": part_index},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise UnknownDraft(f"{parent_id}#{part_index}")
    media = row["media"] if isinstance(row["media"], Mapping) else {}
    part = _part(media)
    source = part_source(part)
    return PartEditFields(
        mode=str(part.get("mode") or "reference"),
        description=str(part.get("description") or ""),
        photo_keys=product_photos(media),
        analysis_id=source["analysis_id"],
        shot_indexes=source["shot_indexes"],
        all_photo_keys=image_keys(media),
        brand_id=row["brand_id"],
    )


def reel_account(*, tenant_id: UUID, network: str, post_id: str) -> str:
    """The account of a public reel («thegoldenbalance»), as `public_reels` keeps it —
    for the «Video de inspiración» card (Deivid, 2026-11-13). "" when the reel is not
    stored. `public_reels` belongs to no business (no RLS); it is read through the
    business's own door, as `reel_analysis` reads the global analyses (the tenant-less
    `global_session` is pinned to the balance gate). No vendor call."""
    if not network or not post_id:
        return ""
    with tenant_session(tenant_id) as session:
        handle = session.scalar(
            text("SELECT handle FROM public_reels WHERE network = :n AND reel_id = :r"),
            {"n": network, "r": post_id},
        )
    return str(handle or "").strip()


__all__ = [
    "reel_account",
    "NOT_REVIEWABLE_TEXTS",
    "REVIEWABLE",
    "PartEditFields",
    "PartNotReviewable",
    "PartVersion",
    "part_edit_fields",
    "part_versions",
    "image_keys",
    "product_photos",
    "set_part_liked",
    "use_part_version",
    "version_expired",
    "versions_from_rows",
]
