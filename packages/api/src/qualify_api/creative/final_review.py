"""Night scheduling and the owner's second look at the exact final (ADR 41)."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from qualify_shared.db.session import tenant_session
from qualify_shared.objects.keys import require_tenant_prefix
from sqlalchemy import select

from qualify_api.creative import models as orm
from qualify_api.creative.draft_mode import draft_state
from qualify_api.creative.versions import visible_version
from qualify_api.tenancy.models import TenantMember

FINAL_SCHEDULED = "final_scheduled"
FINAL_READY = "final_ready"
FINAL_FAILED_TEXT = "No pudimos preparar el video final. Inténtalo de nuevo; no usa otro video."


@dataclass(frozen=True)
class FinalSchedule:
    not_before: datetime
    deadline: datetime | None
    lane: str
    priority: int


def schedule_final(
    *,
    now: datetime,
    timezone: str,
    preview_created_at: float | None,
    publications: Sequence[datetime] = (),
    manual: bool = False,
    night_start: int = 0,
    night_end: int = 6,
) -> FinalSchedule:
    """First night after approval; same-day/manual/too-tight work goes immediately."""
    if not 0 <= night_start < night_end <= 24:
        raise ValueError("night hours must satisfy 0 <= start < end <= 24")
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    zone = ZoneInfo(timezone)
    local = now.astimezone(zone)
    next_start = datetime.combine(local.date(), time(night_start), zone)
    if next_start <= local:
        next_start += timedelta(days=1)
    limits = []
    if preview_created_at is not None:
        limits.append(
            datetime.fromtimestamp(preview_created_at, UTC) + timedelta(days=7, minutes=-15)
        )
    if publications:
        target = min(publications) - timedelta(hours=12)
        # Same-day/now cannot meet a twelve-hour review target. It must not
        # invent a deadline already in the past; the vendor TTL still applies.
        if target > now:
            limits.append(target)
    deadline = min(limits) if limits else None
    same_day = any(date.astimezone(zone).date() <= local.date() for date in publications)
    immediate = manual or same_day or (deadline is not None and next_start >= deadline)
    return FinalSchedule(
        not_before=now.astimezone(UTC) if immediate else next_start.astimezone(UTC),
        deadline=deadline,
        lane="immediate" if immediate else "nightly",
        priority=8 if immediate else 0,
    )


def final_confirmed(
    params: Mapping[str, object] | None, *, object_key: str | None, revision: int | None = None
) -> bool:
    """Only the same final key, digest and generation the owner actually reviewed."""
    block = draft_state(params)
    if block is None:
        return True  # No preview/final lifecycle (images, uploads, non-draft video).
    digest = block.get("final_sha256")
    return bool(
        block.get("status") == "final"
        and isinstance(digest, str)
        and len(digest) == 64
        and block.get("confirmed_sha256") == digest
        and block.get("final_object_key") == object_key
        and block.get("confirmed_object_key") == object_key
        and block.get("confirmed_by")
        and block.get("confirmed_at")
        and (revision is None or block.get("confirmed_revision") == revision)
    )


@dataclass(frozen=True)
class FinalIdentity:
    asset_id: UUID
    object_key: str
    sha256: str
    revision: int


class FinalReviewUnavailable(ValueError):
    pass


def _require_approver(session: object, user_id: UUID) -> None:
    member = session.scalar(select(TenantMember).where(TenantMember.user_id == user_id))
    if member is None or member.role not in {"owner", "admin"}:
        raise PermissionError("Solo los dueños y administradores pueden confirmar videos.")


def review_manifest(
    *,
    tenant_id: UUID,
    draft_id: UUID,
    user_id: UUID,
    read_object: Callable[[str], bytes] | None = None,
    digest_object: Callable[[str], str] | None = None,
) -> tuple[FinalIdentity, ...]:
    """Prepare an immutable panel manifest, including old finals without a digest.

    Storage reads occur outside the transaction. The second read locks and compares
    identity before storing a digest: a concurrently replaced file is never confirmed.
    """
    with tenant_session(tenant_id) as session:
        _require_approver(session, user_id)
        draft = session.get(orm.ContentDraft, draft_id)
        if draft is None or draft.status != "approved":
            raise FinalReviewUnavailable("El video todavía no está listo para revisar.")
        revision = draft.revision
        rows = session.scalars(
            select(orm.ImageAsset).where(
                orm.ImageAsset.draft_id == draft_id, visible_version(orm.ImageAsset)
            )
        ).all()
        snapshot = [
            (row.id, row.object_key, dict(draft_state(row.params) or {}))
            for row in rows
            if draft_state(row.params) is not None
        ]
    if not snapshot or any(
        block.get("status") not in {FINAL_READY, "final"} for _, _, block in snapshot
    ):
        raise FinalReviewUnavailable("El video todavía no está listo para revisar.")
    identities = []
    for asset_id, key, block in snapshot:
        if not key:
            raise FinalReviewUnavailable("El video todavía no está listo para revisar.")
        require_tenant_prefix(tenant_id, key)
        if digest_object is not None:
            digest = digest_object(key)
        elif read_object is not None:
            digest = hashlib.sha256(read_object(key)).hexdigest()
        else:
            raise ValueError("review requires a storage digest reader")
        identities.append(FinalIdentity(asset_id, key, digest, revision))
    with tenant_session(tenant_id) as session:
        draft = session.get(orm.ContentDraft, draft_id, with_for_update=True)
        if draft is None or draft.revision != revision or draft.status != "approved":
            raise FinalReviewUnavailable("El video cambió. Ábrelo de nuevo para revisarlo.")
        for item in identities:
            row = session.get(orm.ImageAsset, item.asset_id, with_for_update=True)
            block = dict(draft_state(row.params) or {}) if row is not None else {}
            if (
                row is None
                or row.object_key != item.object_key
                or block.get("status") not in {FINAL_READY, "final"}
            ):
                raise FinalReviewUnavailable("El video cambió. Ábrelo de nuevo para revisarlo.")
            block.update(
                final_sha256=item.sha256, final_object_key=item.object_key, final_revision=revision
            )
            if not final_confirmed({"draft": block}, object_key=row.object_key, revision=revision):
                block["status"] = FINAL_READY
            row.params = {**dict(row.params or {}), "draft": block}
    return tuple(identities)


def confirm_final(
    *,
    tenant_id: UUID,
    draft_id: UUID,
    user_id: UUID,
    expected: Sequence[FinalIdentity],
    now: datetime | None = None,
) -> None:
    """Idempotent human confirmation, fenced by every object shown in the panel."""
    moment = now or datetime.now(UTC)
    with tenant_session(tenant_id) as session:
        _require_approver(session, user_id)
        draft = session.get(orm.ContentDraft, draft_id, with_for_update=True)
        if draft is None or draft.status != "approved":
            raise FinalReviewUnavailable("El video todavía no está listo para revisar.")
        rows = list(
            session.scalars(
                select(orm.ImageAsset)
                .where(orm.ImageAsset.draft_id == draft_id, visible_version(orm.ImageAsset))
                .order_by(orm.ImageAsset.id)
                .with_for_update()
            )
        )
        finals = [row for row in rows if draft_state(row.params) is not None]
        identities = {item.asset_id: item for item in expected}
        if (
            not finals
            or len(identities) != len(expected)
            or set(identities) != {row.id for row in finals}
        ):
            raise FinalReviewUnavailable("El video cambió. Ábrelo de nuevo para revisarlo.")
        for row in finals:
            item = identities[row.id]
            block = dict(draft_state(row.params) or {})
            if (
                block.get("status") not in {FINAL_READY, "final"}
                or row.object_key != item.object_key
                or block.get("final_object_key") != item.object_key
                or block.get("final_sha256") != item.sha256
                or item.revision != draft.revision
                or block.get("final_revision") != draft.revision
            ):
                raise FinalReviewUnavailable("El video cambió. Ábrelo de nuevo para revisarlo.")
            if final_confirmed(row.params, object_key=row.object_key, revision=draft.revision):
                continue
            row.params = {
                **dict(row.params or {}),
                "draft": {
                    **block,
                    "status": "final",
                    "confirmed_by": str(user_id),
                    "confirmed_at": moment.isoformat(),
                    "confirmed_sha256": item.sha256,
                    "confirmed_object_key": item.object_key,
                    "confirmed_revision": draft.revision,
                },
            }


def configured_night_hours() -> tuple[int, int]:
    return (
        int(os.getenv("QUALIFY_CREATIVE_NIGHT_START", "0")),
        int(os.getenv("QUALIFY_CREATIVE_NIGHT_END", "6")),
    )


def nightly_maintenance(tenant_ids: Sequence[UUID], *, now: datetime | None = None) -> int:
    """Promote missed windows and retry a known terminal failure at most three times."""
    from sqlalchemy import text

    from qualify_api.creative.final_retries import retry_final_asset
    from qualify_api.tenancy.models import Tenant

    moment = now or datetime.now(UTC)
    _, end = configured_night_hours()
    changed_count = 0
    for tenant_id in tenant_ids:
        with tenant_session(tenant_id) as session:
            tenant = session.get(Tenant, tenant_id)
            local = moment.astimezone(ZoneInfo(tenant.timezone if tenant else "UTC"))
            rows = (
                []
                if local.hour < end
                else session.execute(
                    text("""
                SELECT id, draft_id, position FROM creative_jobs
                WHERE lane = 'nightly' AND status = 'queued' AND not_before <= :now
                  AND vendor_task_id IS NULL ORDER BY draft_id, position
            """),
                    {"now": moment},
                ).all()
            )
            for job_id, draft_id, position in rows:
                draft = session.get(orm.ContentDraft, draft_id, with_for_update=True)
                asset = session.scalar(
                    select(orm.ImageAsset)
                    .where(
                        orm.ImageAsset.draft_id == draft_id,
                        visible_version(orm.ImageAsset),
                        orm.ImageAsset.position == position,
                    )
                    .with_for_update()
                )
                if draft is None or asset is None:
                    continue
                changed = session.execute(
                    text("""
                    UPDATE creative_jobs SET lane = 'immediate', priority = greatest(priority, 8)
                    WHERE id = :id AND lane = 'nightly' AND status = 'queued'
                      AND vendor_task_id IS NULL RETURNING id
                """),
                    {"id": job_id},
                ).scalar_one_or_none()
                if changed is not None:
                    block = dict(draft_state(asset.params) or {})
                    block.update(final_lane="immediate", final_priority=8, status="rendering")
                    asset.params = {**dict(asset.params or {}), "draft": block}
                    changed_count += 1
            failures = session.execute(
                text("""
                SELECT a.draft_id,a.id FROM image_assets a JOIN content_drafts d ON d.id=a.draft_id
                WHERE d.status='approved' AND a.params->'draft'->>'status'='failed'
                  AND a.params->'draft'->>'final_origin'='approval'
                ORDER BY a.draft_id,a.position LIMIT 100
            """)
            ).all()
        # Separate transactions, after releasing the promotion locks.
        for draft_id, asset_id in failures:
            result = retry_final_asset(
                tenant_id=tenant_id,
                draft_id=draft_id,
                asset_id=asset_id,
                now=moment,
                automatic=True,
            )
            changed_count += result in {"created", "resumed"}
    return changed_count


def promote_scheduled_final(
    session: object, *, tenant_id: UUID, draft_id: UUID, now: datetime | None = None
) -> None:
    """Schedule changes and queue promotion share the calendar's transaction."""
    from sqlalchemy import text

    from qualify_api.planner.models import CalendarEvent
    from qualify_api.tenancy.models import Tenant

    moment = now or datetime.now(UTC)
    draft = session.get(orm.ContentDraft, draft_id, with_for_update=True)
    if draft is None:
        return
    tenant = session.get(Tenant, tenant_id)
    dates = tuple(
        session.scalars(
            select(CalendarEvent.scheduled_at).where(
                CalendarEvent.post_id == draft_id, CalendarEvent.status == "scheduled"
            )
        )
    )
    assets = session.scalars(
        select(orm.ImageAsset)
        .where(orm.ImageAsset.draft_id == draft_id, visible_version(orm.ImageAsset))
        .order_by(orm.ImageAsset.id)
        .with_for_update()
    ).all()
    start, end = configured_night_hours()
    for asset in assets:
        block = dict(draft_state(asset.params) or {})
        if block.get("status") not in {FINAL_SCHEDULED, "rendering"}:
            continue
        created = block.get("created_at")
        policy = schedule_final(
            now=moment,
            timezone=tenant.timezone if tenant else "UTC",
            publications=dates,
            preview_created_at=float(created) if isinstance(created, int | float) else None,
            night_start=start,
            night_end=end,
        )
        # Never postpone an already ordered final when another date is added.
        original = block.get("final_not_before")
        when = (
            min(datetime.fromisoformat(original), policy.not_before)
            if original
            else policy.not_before
        )
        block.update(
            final_not_before=when.isoformat(),
            final_lane=policy.lane,
            final_priority=policy.priority,
            final_deadline=policy.deadline.isoformat() if policy.deadline else None,
        )
        if when <= moment:
            block["status"] = "rendering"
        asset.params = {**dict(asset.params or {}), "draft": block}
        session.execute(
            text("""
            UPDATE creative_jobs SET
              lane = :lane, priority = greatest(priority, :priority),
              deadline = CASE WHEN deadline IS NULL THEN CAST(:deadline AS timestamptz)
                              ELSE least(deadline, CAST(:deadline AS timestamptz)) END,
              not_before = CASE WHEN not_before > '9998-01-01'::timestamptz THEN not_before
                                ELSE least(not_before, CAST(:when AS timestamptz)) END
            WHERE draft_id = :draft AND kind = 'final' AND position = :position
              AND status = 'queued' AND vendor_task_id IS NULL AND revision = :revision
        """),
            {
                "lane": policy.lane,
                "priority": policy.priority,
                "deadline": policy.deadline,
                "when": when,
                "draft": draft_id,
                "position": asset.position,
                "revision": draft.revision,
            },
        )


def review_candidates(*, tenant_id: UUID, now: datetime | None = None) -> tuple[UUID, ...]:
    """Panel deep-link candidates: overdue first, then nearest dated, then undated."""
    from sqlalchemy import text

    moment = now or datetime.now(UTC)
    with tenant_session(tenant_id) as session:
        return tuple(
            session.scalars(
                text("""
            SELECT d.id FROM content_drafts d
            JOIN image_assets a ON a.draft_id = d.id
            LEFT JOIN calendar_events e ON e.post_id = d.id AND e.status = 'scheduled'
            WHERE d.status = 'approved' AND a.params->'draft'->>'status' IN ('final_ready','final')
              AND (a.params->'draft'->>'status' <> 'final'
                   OR a.params->'draft'->>'confirmed_sha256' IS NULL
                   OR a.params->'draft'->>'confirmed_sha256' IS DISTINCT FROM
                       a.params->'draft'->>'final_sha256'
                   OR a.params->'draft'->>'confirmed_object_key' IS DISTINCT FROM a.object_key
               OR a.params->'draft'->>'final_object_key' IS DISTINCT FROM a.object_key
               OR a.params->'draft'->>'confirmed_revision' IS DISTINCT FROM d.revision::text
               OR a.params->'draft'->>'confirmed_by' IS NULL
               OR a.params->'draft'->>'confirmed_at' IS NULL)
            AND NOT EXISTS (SELECT 1 FROM image_assets pending
                WHERE pending.draft_id=d.id AND pending.params ? 'draft'
                  AND pending.params->'draft'->>'status' NOT IN ('final_ready','final'))
            GROUP BY d.id
            ORDER BY (min(e.scheduled_at) <= :now) DESC NULLS LAST,
                     min(e.scheduled_at) NULLS LAST, d.id
        """),
                {"now": moment},
            )
        )
