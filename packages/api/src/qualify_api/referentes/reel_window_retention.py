"""The per-business half of the 30-day reel purge (VE-12 m-24921060, RA5 of ADR 44 F9;
design `docs/diseno-video-por-planos.md` §7 RA5, handoff
`docs/traspasos/historias-video-por-partes-backend.md` §2 VE-12).

A part in `edit` mode keeps a cut of the foreign reel in its piece folder,
`t/{tenant}/generated/{draft_id}/source-window-{analysis_id}-{start}-{end}.mp4` (VE-04d,
`reel_analysis_window`). The piece lives 90 days (ADR 39), but F9 says a foreign reel lives
30: so each window is deleted 30 days after it was WRITTEN (its R2 `LastModified` — the
bucket refuses overwrites, so that is the first write), whatever the piece's own deadline.
Nothing else of the piece is touched: the gate (`ObjectGate.delete_source_windows`) builds
the folder from two UUIDs and only matches the exact window name directly inside it.

- **Discovery** (`tenants_with_part_drafts`, production only, `qualify_admin`): ids of the
  businesses with a part created at least 30 days ago whose files
  are still in R2 — a window cannot be older than the draft it was cut for. Ids only;
  everything after it is `tenant_session` (RLS).
- **Per business** (`purge_source_windows`): those drafts, read through `tenant_session`;
  for each, the gate lists and (with `execute`) deletes the old windows. No row records
  a window (it is not an output, `reel_analysis_window`), so there is nothing to mark:
  idempotent because a second pass finds nothing left to delete.
- **A refused delete.** The production bucket refuses overwrites
  (`ObjectLockedByBucketPolicy`, 2026-11-05) and nobody has measured whether it refuses
  deletes. A refusal by the bucket (`is_bucket_refusal`) stops the whole pass with ONE
  error line — every other window would be refused the same way — and the next day tries
  again; a transient error skips that draft and goes on.

It runs in the calendar worker's daily chore (`creative.retention_job.daily_chore`), in its
own `try`: a failure here never stops the piece purge, nor the other way round. Same
switch as the piece purge (`QUALIFY_PIECE_PURGE_EXECUTE`); `just piece-purge` runs it too,
as a dry run unless `--execute`. Scope is explicit (`--tenant` locally). It never touches
`public/reel-analyses/` — that is `reel_retention`, run only by the `reels-worker`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import PrefixDeletion, is_bucket_refusal
from sqlalchemy import select
from sqlalchemy.orm import Session

from qualify_api.creative.models import ContentDraft

logger = logging.getLogger("qualify_api.referentes.reel_window_retention")

#: F9: a foreign reel — its source, its frames, and any cut of it — lives 30 days.
WINDOW_RETENTION = timedelta(days=30)


class WindowDeleter(Protocol):
    """`ObjectGate.delete_source_windows`, the only R2 call this module makes."""

    def delete_source_windows(
        self, tenant_id: UUID, draft_id: UUID, *, written_before: datetime, execute: bool = False
    ) -> PrefixDeletion: ...


@dataclass
class WindowPurgeReport:
    tenant_id: UUID
    execute: bool
    #: Drafts whose folder was looked at.
    drafts: int = 0
    #: Windows deleted (or, in a dry run, that would be).
    objects: int = 0
    bytes: int = 0
    #: Drafts skipped by a transient R2 error (tried again tomorrow).
    errors: list[UUID] = field(default_factory=list)
    #: Set when the bucket refused a delete: the pass stopped there.
    refused: bool = False


def _part_drafts(session: Session, cutoff: datetime) -> list[UUID]:
    """Drafts that may hold a window older than `cutoff`: parts (a window is only ever cut
    into the PART's own folder, `creative.part_windows`), created at or before it, whose
    files were not purged. RLS scopes the session to one business."""
    return list(
        session.scalars(
            select(ContentDraft.id)
            .where(
                ContentDraft.created_at <= cutoff,
                ContentDraft.media_purged_at.is_(None),
                ContentDraft.parent_draft_id.is_not(None),
            )
            .order_by(ContentDraft.created_at, ContentDraft.id)
        ).all()
    )


def purge_source_windows(
    *,
    tenant_id: UUID,
    gate: WindowDeleter,
    now: datetime,
    execute: bool,
    drafts: Callable[[UUID, datetime], Sequence[UUID]] | None = None,
) -> WindowPurgeReport:
    """Delete (or, without `execute`, only count) this business's windows written more
    than 30 days before `now`. Raises nothing for R2; the report says what happened."""
    cutoff = now - WINDOW_RETENTION
    if drafts is None:
        with tenant_session(tenant_id) as session:
            ids: Sequence[UUID] = _part_drafts(session, cutoff)
    else:
        ids = drafts(tenant_id, cutoff)
    report = WindowPurgeReport(tenant_id=tenant_id, execute=execute)
    for draft_id in ids:
        report.drafts += 1
        try:
            found = gate.delete_source_windows(
                tenant_id, draft_id, written_before=cutoff, execute=execute
            )
        except Exception as exc:  # noqa: BLE001 — that draft waits for the next pass
            if is_bucket_refusal(exc):
                report.refused = True
                return report
            report.errors.append(draft_id)
            if len(report.errors) == 1:
                logger.exception("reel window purge failed tenant=%s draft=%s", tenant_id, draft_id)
            continue
        report.objects += found.objects
        report.bytes += found.bytes
    return report


def tenants_with_part_drafts(now: datetime) -> list[UUID]:
    """PRODUCTION discovery for `--all-tenants`: ids of businesses with a part
    created 30+ days ago whose files are still stored. Read-only, ids
    only; `qualify_admin` already holds SELECT on `content_drafts` (0009)."""
    from qualify_shared.db.admin import admin_session  # noqa: PLC0415 — production only

    with admin_session() as session:
        rows: Sequence[UUID] = session.scalars(
            select(ContentDraft.tenant_id)
            .where(
                ContentDraft.parent_draft_id.is_not(None),
                ContentDraft.created_at <= now - WINDOW_RETENTION,
                ContentDraft.media_purged_at.is_(None),
            )
            .distinct()
        ).all()
    return sorted(set(rows), key=str)


def production_gate() -> WindowDeleter:
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    return ObjectGate(R2ObjectStore(R2Settings.from_env()))


def run_window_purge(
    tenant_ids: Iterable[UUID] | None,
    *,
    execute: bool,
    now: datetime | None = None,
    gate: WindowDeleter | None = None,
    discover: Callable[[datetime], list[UUID]] = tenants_with_part_drafts,
    drafts: Callable[[UUID, datetime], Sequence[UUID]] | None = None,
) -> list[WindowPurgeReport]:
    """One pass over the scope (`None` = the production discovery). One business failing
    never stops the others; a refusal by the bucket stops the pass with one error line."""
    moment = now or datetime.now(UTC)
    scope = list(dict.fromkeys(tenant_ids)) if tenant_ids is not None else discover(moment)
    if not scope:
        logger.info("reel windows purge: nothing to do execute=%s", execute)
        return []
    deleter = gate or production_gate()
    reports: list[WindowPurgeReport] = []
    for tenant_id in scope:
        try:
            report = purge_source_windows(
                tenant_id=tenant_id, gate=deleter, now=moment, execute=execute, drafts=drafts
            )
        except Exception:  # noqa: BLE001 — one business must not stop the rest
            logger.exception("reel windows purge tenant failed tenant=%s", tenant_id)
            continue
        reports.append(report)
        if report.refused:
            logger.error(
                "reel windows purge STOPPED: R2 refused to delete a window of tenant=%s; "
                "nothing else tried, the next pass tries again. Check the bucket lock "
                "rules (VE-12, m-24921060)",
                tenant_id,
            )
            break
    logger.info(
        "reel windows purge: tenants=%d drafts=%d objects=%d bytes=%d errors=%d refused=%s "
        "execute=%s",
        len(reports),
        sum(r.drafts for r in reports),
        sum(r.objects for r in reports),
        sum(r.bytes for r in reports),
        sum(len(r.errors) for r in reports),
        any(r.refused for r in reports),
        execute,
    )
    return reports


__all__ = [
    "WINDOW_RETENTION",
    "WindowDeleter",
    "WindowPurgeReport",
    "production_gate",
    "purge_source_windows",
    "run_window_purge",
    "tenants_with_part_drafts",
]
