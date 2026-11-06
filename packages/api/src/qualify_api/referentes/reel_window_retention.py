"""The per-business half of the 30-day reel purge (VE-12 m-24921060, RA5 of ADR 44 F9;
design `docs/diseno-video-por-planos.md` §7 RA5, handoff
`docs/traspasos/historias-video-por-partes-backend.md` §2 VE-12).

A part in `edit` mode keeps a cut of the foreign reel in its own folder of reel cuts,
`reel-windows/{tenant}/{draft_id}/source-window-{analysis_id}-{start}-{end}.mp4` (VE-04d,
`reel_analysis_window`). The piece lives 90 days (ADR 39), but F9 says a foreign reel lives
30: so each cut is deleted 30 days after it was WRITTEN (its R2 `LastModified`; a re-cut of
the same key would only make it younger), whatever the piece's own deadline.
The root sits OUTSIDE `t/` because the production bucket keeps a lock rule on `t/` that
refuses deletes and overwrites (m-24971181, like the Galería's `gallery/`). Cuts written
under `t/{tenant}/generated/` before 2026-11-06 cannot be deleted at all and are not tried.

**No draft row decides anything.** The cuts live outside the piece folder, so the piece
purge never deletes them; a pass that finds work through draft rows would leave forever a
cut whose part row is gone (deleted with its parent) or already purged. So each business's
whole `reel-windows/{tenant}/` root is listed through the gate
(`ObjectGate.delete_source_windows`, root built from the tenant UUID, exact cut path only)
and every cut 30+ days old goes, orphans included.

- **Discovery** (`all_tenant_ids`, production only, `qualify_admin`): every business id —
  ids only, nothing else read. One listing per business per day (R2 Class A operations,
  negligible at this scale); a business with no cuts lists nothing. **Known gap
  (follow-up):** a DELETED business is no longer in `tenants`, so its
  `reel-windows/{tenant}/` root is never listed again — tenant deletion must empty it.
- **Per business** (`purge_source_windows`): one gate call. No row records a cut (it is not
  an output), so there is nothing to mark: idempotent because a second pass finds nothing
  left to delete.
- **A refused delete.** No lock rule is known on `reel-windows/`, but if one is ever
  added, a refusal by the bucket (`is_bucket_refusal`) stops the whole pass with ONE
  error line — every other business would be refused the same way — and the next day
  tries again; a transient error skips that business and goes on.

It runs in the calendar worker's daily chore (`creative.retention_job.daily_chore`), in its
own `try`: a failure here never stops the piece purge, nor the other way round. Same
switch as the piece purge (`QUALIFY_PIECE_PURGE_EXECUTE`); `just piece-purge` runs it too,
as a dry run unless `--execute`. Scope is explicit (`--tenant` locally). It never touches
`public/reel-analyses/` — that is `reel_retention`, run only by the `reels-worker`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from qualify_shared.objects.gate import PrefixDeletion, is_bucket_refusal

logger = logging.getLogger("qualify_api.referentes.reel_window_retention")

#: F9: a foreign reel — its source, its frames, and any cut of it — lives 30 days.
WINDOW_RETENTION = timedelta(days=30)


class WindowDeleter(Protocol):
    """`ObjectGate.delete_source_windows`, the only R2 call this module makes."""

    def delete_source_windows(
        self, tenant_id: UUID, *, written_before: datetime, execute: bool = False
    ) -> PrefixDeletion: ...


@dataclass
class WindowPurgeReport:
    tenant_id: UUID
    execute: bool
    #: Cuts deleted (or, in a dry run, that would be).
    objects: int = 0
    bytes: int = 0
    #: A transient R2 error: this business is tried again tomorrow.
    failed: bool = False
    #: The bucket refused a delete: the pass stopped there.
    refused: bool = False


def purge_source_windows(
    *, tenant_id: UUID, gate: WindowDeleter, now: datetime, execute: bool
) -> WindowPurgeReport:
    """Delete (or, without `execute`, only count) every cut of this business written more
    than 30 days before `now`. Raises nothing for R2; the report says what happened."""
    report = WindowPurgeReport(tenant_id=tenant_id, execute=execute)
    try:
        found = gate.delete_source_windows(
            tenant_id, written_before=now - WINDOW_RETENTION, execute=execute
        )
    except Exception as exc:  # noqa: BLE001 — this business waits for the next pass
        if is_bucket_refusal(exc):
            report.refused = True
        else:
            report.failed = True
            logger.exception("reel window purge failed tenant=%s", tenant_id)
        return report
    report.objects, report.bytes = found.objects, found.bytes
    return report


def all_tenant_ids(now: datetime) -> list[UUID]:
    """PRODUCTION discovery for `--all-tenants`: every business id. Read-only, ids only;
    `qualify_admin` holds SELECT on `tenants`. `now` is unused (the cut's own age decides)
    and kept for the shape every discovery shares."""
    from qualify_shared.db.admin import admin_session  # noqa: PLC0415 — production only
    from sqlalchemy import select  # noqa: PLC0415

    from qualify_api.tenancy.models import Tenant  # noqa: PLC0415

    with admin_session() as session:
        rows: Sequence[UUID] = session.scalars(select(Tenant.id)).all()
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
    discover: Callable[[datetime], list[UUID]] = all_tenant_ids,
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
        report = purge_source_windows(
            tenant_id=tenant_id, gate=deleter, now=moment, execute=execute
        )
        reports.append(report)
        if report.refused:
            logger.error(
                "reel windows purge STOPPED: R2 refused to delete a cut of tenant=%s; "
                "nothing else tried, the next pass tries again. Check the bucket lock "
                "rules (VE-12, m-24921060)",
                tenant_id,
            )
            break
    logger.info(
        "reel windows purge: tenants=%d objects=%d bytes=%d failed=%d refused=%s execute=%s",
        len(reports),
        sum(r.objects for r in reports),
        sum(r.bytes for r in reports),
        sum(r.failed for r in reports),
        any(r.refused for r in reports),
        execute,
    )
    return reports


__all__ = [
    "WINDOW_RETENTION",
    "WindowDeleter",
    "WindowPurgeReport",
    "all_tenant_ids",
    "production_gate",
    "purge_source_windows",
    "run_window_purge",
]
