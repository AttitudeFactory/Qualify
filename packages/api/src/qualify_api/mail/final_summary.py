"""Tenant-scoped morning batch and frozen mail outbox (m-24852235)."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.mail import Mailer, OutgoingMail, default_mailer
from qualify_api.mail.final_template import VERSION, FinalVideo, build_summary

logger = logging.getLogger(__name__)
APPROVERS = ("owner", "admin")


def batch_cut(now: datetime, timezone: str) -> tuple[date, datetime] | None:
    local = now.astimezone(ZoneInfo(timezone))
    if local.hour != 7:
        return None
    return local.date(), datetime.combine(local.date(), time(7), local.tzinfo).astimezone(UTC)


def preference(
    tenant_id: UUID,
    user_id: UUID,
    *,
    enabled: bool | None = None,
    token: UUID | None = None,
) -> tuple[bool, UUID]:
    with tenant_session(tenant_id) as session:
        if token is None:
            member = session.execute(
                text("""
                SELECT 1 FROM tenant_members m JOIN users u ON u.id=m.user_id
                WHERE m.user_id=:user AND m.tenant_id=:tenant AND u.tenant_id=m.tenant_id
                  AND m.role IN ('owner','admin')
            """),
                {"user": user_id, "tenant": tenant_id},
            ).scalar_one_or_none()
            if member is None:
                raise LookupError("preference unavailable")
            session.execute(
                text("""
                INSERT INTO final_mail_preferences(tenant_id,user_id) VALUES(:tenant,:user)
                ON CONFLICT(tenant_id,user_id) DO NOTHING
            """),
                {"tenant": tenant_id, "user": user_id},
            )
        row = session.execute(
            text("""
            SELECT enabled,token FROM final_mail_preferences
            WHERE user_id=:user
              AND (CAST(:token AS uuid) IS NULL OR token=CAST(:token AS uuid)) FOR UPDATE
        """),
            {"user": user_id, "token": str(token) if token else None},
        ).one_or_none()
        if row is None:
            raise LookupError("preference unavailable")
        if enabled is not None:
            session.execute(
                text("""
                UPDATE final_mail_preferences SET enabled=:enabled,updated_at=now()
                WHERE user_id=:user
            """),
                {"user": user_id, "enabled": enabled},
            )
        return enabled if enabled is not None else row.enabled, row.token


def _new_videos(session: Any, cut: datetime) -> tuple[FinalVideo, ...]:
    rows = session.execute(
        text("""
        SELECT DISTINCT ON(d.id) d.id,d.title,d.revision,j.id AS source_job_id,
            a.params->'draft'->>'status' AS status,
            a.params->>'thumbnail_key' AS thumbnail_key,
            (SELECT min(e.scheduled_at) FROM calendar_events e
             WHERE e.post_id=d.id AND e.status='scheduled') AS scheduled_at
        FROM content_drafts d JOIN image_assets a ON a.draft_id=d.id
        JOIN creative_jobs j ON j.draft_id=d.id AND j.revision=d.revision AND j.position=a.position
        WHERE d.status='approved' AND j.kind='final' AND j.status IN ('succeeded','failed')
          AND j.finished_at > :start AND j.finished_at <= :cut
          AND a.params->'draft'->>'status' IN ('final_ready','failed')
          AND a.params->'draft'->>'final_origin' = 'approval'
          AND a.params->'draft'->>'final_nightly' = 'true'
          AND NOT EXISTS (SELECT 1 FROM image_assets pending WHERE pending.draft_id=d.id
              AND pending.params ? 'draft'
              AND COALESCE(pending.params->'draft'->>'status','draft')
                  NOT IN ('final_ready','final','failed'))
        ORDER BY d.id,(a.params->'draft'->>'status'='failed') DESC,j.finished_at DESC
    """),
        {"start": cut - timedelta(days=1), "cut": cut},
    ).mappings()
    return tuple(
        FinalVideo(
            r["id"],
            r["title"] or "Tu publicación",
            r["status"] == "failed",
            r["scheduled_at"],
            r["thumbnail_key"] or "",
            r["revision"],
            str(r["source_job_id"]),
        )
        for r in rows
    )


def thumbnail_url(tenant_id: UUID, key: str, base_url: str) -> str:
    if not key:
        return ""
    import redis
    from qualify_shared.objects.keys import require_tenant_prefix

    from qualify_api.config import redis_url
    from qualify_api.publishing.media_token import MediaTokenStore

    require_tenant_prefix(tenant_id, key)
    client = redis.Redis.from_url(redis_url(), decode_responses=True)
    try:
        token = MediaTokenStore(client, ttl_seconds=7 * 86400).issue(
            tenant_id=tenant_id, object_key=key, content_type="image/jpeg"
        )
    finally:
        client.close()
    return base_url.rstrip("/") + "/public/media/" + token


def stage_batch(
    tenant_id: UUID,
    *,
    now: datetime,
    base_url: str,
    thumbnail: Callable[[UUID, str, str], str] = thumbnail_url,
) -> int:
    with tenant_session(tenant_id) as session:
        business = session.execute(text("SELECT name,timezone FROM tenants")).one_or_none()
        if business is None or (cut_info := batch_cut(now, business.timezone)) is None:
            return 0
        day, cut = cut_info
        videos = _new_videos(session, cut)
        if not videos:
            return 0
        users = (
            session.execute(
                text("""
            SELECT u.id,u.email,u.display_name FROM tenant_members m
            JOIN users u ON u.id=m.user_id AND u.tenant_id=m.tenant_id
            WHERE m.role IN ('owner','admin') AND NOT EXISTS (
                SELECT 1 FROM final_mail_batches b WHERE b.user_id=u.id AND b.batch_date=:day
            ) ORDER BY u.id
        """),
                {"day": day},
            )
            .mappings()
            .all()
        )
        if not users:
            return 0
        # Mint protected thumbnails only for a new frozen batch.
        prepared = []
        for item in videos:
            try:
                poster = thumbnail(tenant_id, item.thumbnail, base_url) if item.thumbnail else ""
            except Exception:
                logger.warning("final summary thumbnail unavailable tenant_id=%s", tenant_id)
                poster = ""
            prepared.append(
                FinalVideo(
                    item.piece_id,
                    item.title,
                    item.failed,
                    item.scheduled_at,
                    poster,
                    item.revision,
                    item.source_job_id,
                )
            )
        count = 0
        for user in users:
            session.execute(
                text("""
                INSERT INTO final_mail_preferences(tenant_id,user_id) VALUES(:tenant,:user)
                ON CONFLICT(tenant_id,user_id) DO NOTHING
            """),
                {"tenant": tenant_id, "user": user["id"]},
            )
            pref = session.execute(
                text("""
                SELECT enabled,token FROM final_mail_preferences WHERE user_id=:user
            """),
                {"user": user["id"]},
            ).one()
            if not pref.enabled:
                continue
            key = f"final-morning/{tenant_id}/{user['id']}/{day.isoformat()}"
            url = (
                base_url.rstrip("/") + f"/api/mail/finals/preferences/{tenant_id}/"
                f"{user['id']}/{pref.token}"
            )
            mail = build_summary(
                to=user["email"],
                name=user["display_name"],
                business=business.name,
                videos=tuple(prepared),
                day=day,
                timezone=business.timezone,
                base_url=base_url,
                preference_url=url,
                idempotency_key=key,
            )
            count += session.execute(
                text("""
                INSERT INTO final_mail_batches
                    (tenant_id,user_id,batch_date,payload,idempotency_key,source_version)
                VALUES(:tenant,:user,:day,CAST(:payload AS jsonb),:key,:version)
                ON CONFLICT(tenant_id,user_id,batch_date) DO NOTHING
            """),
                {
                    "tenant": tenant_id,
                    "user": user["id"],
                    "day": day,
                    "payload": json.dumps(
                        {
                            "mail": asdict(mail),
                            "context": {
                                "to": user["email"],
                                "name": user["display_name"],
                                "business": business.name,
                                "day": day.isoformat(),
                                "timezone": business.timezone,
                                "base_url": base_url,
                                "preference_url": url,
                                "idempotency_key": key,
                                "videos": [
                                    {
                                        **asdict(v),
                                        "piece_id": str(v.piece_id),
                                        "scheduled_at": v.scheduled_at.isoformat()
                                        if v.scheduled_at
                                        else None,
                                    }
                                    for v in prepared
                                ],
                            },
                        }
                    ),
                    "key": key,
                    "version": VERSION,
                },
            ).rowcount
        return count


def send_pending(tenant_id: UUID, *, now: datetime, mailer: Mailer) -> int:
    sent = 0
    while True:
        lease = uuid4()
        with tenant_session(tenant_id) as session:
            # Revalidate membership and opt-out immediately before claiming a send.
            row = (
                session.execute(
                    text("""
                SELECT b.* FROM final_mail_batches b
                JOIN final_mail_preferences p USING(tenant_id,user_id)
                JOIN tenant_members m USING(tenant_id,user_id)
                WHERE b.sent_at IS NULL AND NOT b.uncertain AND NOT b.discarded AND p.enabled
                  AND m.role IN ('owner','admin')
                  AND (b.lease_until IS NULL OR b.lease_until <= :now)
                ORDER BY b.batch_date,b.user_id FOR UPDATE OF b SKIP LOCKED LIMIT 1
            """),
                    {"now": now},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                break
            identity = {"user": row["user_id"], "day": row["batch_date"]}
            first = row["first_attempt_at"]
            if first is not None and now - first >= timedelta(hours=23):
                session.execute(
                    text("""
                    UPDATE final_mail_batches SET uncertain=true,lease_token=NULL,lease_until=NULL
                    WHERE user_id=:user AND batch_date=:day
                """),
                    identity,
                )
                logger.error("final summary needs reconciliation tenant_id=%s", tenant_id)
                continue
            payload = row["payload"]
            if first is None:
                context = dict(payload["context"])
                snapshots = context.pop("videos")
                ids = [UUID(v["piece_id"]) for v in snapshots]
                live = set(
                    session.execute(
                        text("""
                    SELECT DISTINCT d.id,d.revision FROM content_drafts d
                    JOIN image_assets a ON a.draft_id=d.id
                    WHERE d.id=ANY(CAST(:ids AS uuid[])) AND d.status='approved'
                      AND a.params->'draft'->>'status' IN ('final_ready','failed')
                      AND NOT EXISTS (SELECT 1 FROM image_assets pending
                          WHERE pending.draft_id=d.id AND pending.params ? 'draft'
                            AND COALESCE(pending.params->'draft'->>'status','draft')
                                NOT IN ('final_ready','final','failed'))
                """),
                        {"ids": ids},
                    ).all()
                )
                current = [v for v in snapshots if (UUID(v["piece_id"]), v["revision"]) in live]
                if not current:
                    session.execute(
                        text("""
                        UPDATE final_mail_batches SET discarded=true
                        WHERE user_id=:user AND batch_date=:day
                    """),
                        identity,
                    )
                    continue
                videos = tuple(
                    FinalVideo(
                        UUID(v["piece_id"]),
                        v["title"],
                        v["failed"],
                        datetime.fromisoformat(v["scheduled_at"]) if v["scheduled_at"] else None,
                        v["thumbnail"],
                        v["revision"],
                        v["source_job_id"],
                    )
                    for v in current
                )
                context["day"] = date.fromisoformat(context["day"])
                refreshed = build_summary(**context, videos=videos)
                payload = {
                    "mail": asdict(refreshed),
                    "context": {**row["payload"]["context"], "videos": current},
                }
                session.execute(
                    text("""
                    UPDATE final_mail_batches SET payload=CAST(:payload AS jsonb)
                    WHERE user_id=:user AND batch_date=:day
                """),
                    {**identity, "payload": json.dumps(payload)},
                )
            session.execute(
                text("""
                UPDATE final_mail_batches SET lease_token=:lease,lease_until=:until,
                    first_attempt_at=COALESCE(first_attempt_at,:now)
                WHERE user_id=:user AND batch_date=:day
            """),
                {**identity, "lease": lease, "until": now + timedelta(minutes=2), "now": now},
            )
            mail = OutgoingMail(**payload["mail"])
        try:
            provider_id = mailer.send(mail)
        except Exception:
            # Keep the frozen payload and lease: retry the SAME provider key, within
            # its documented 24h lifetime. Never move an unknown send to a new batch.
            logger.warning("final summary send deferred tenant_id=%s", tenant_id)
            break
        with tenant_session(tenant_id) as session:
            updated = session.execute(
                text("""
                UPDATE final_mail_batches SET provider_id=:provider,sent_at=:now,
                    lease_token=NULL,lease_until=NULL
                WHERE user_id=:user AND batch_date=:day AND lease_token=:lease
            """),
                {**identity, "provider": provider_id, "now": now, "lease": lease},
            ).rowcount
            sent += updated
    return sent


def morning_chore(tenant_ids: Sequence[UUID] | None) -> Callable[[], int]:
    def run() -> int:
        from qualify_shared.db.admin import admin_session

        now = datetime.now(UTC)
        if tenant_ids is None:
            with admin_session() as session:
                ids = tuple(
                    session.scalars(
                        text("""
                    SELECT DISTINCT tenant_id FROM creative_jobs WHERE kind='final'
                    AND (finished_at > :since OR status IN ('queued','claimed','submitted'))
                    UNION SELECT DISTINCT tenant_id FROM final_mail_batches
                    WHERE sent_at IS NULL AND NOT discarded AND NOT uncertain
                """),
                        {"since": now - timedelta(days=2)},
                    )
                )
        else:
            ids = tuple(tenant_ids)
        count = 0
        for tenant_id in ids:
            try:
                stage_batch(tenant_id, now=now, base_url=os.environ["QUALIFY_PUBLIC_URL"])
                count += send_pending(tenant_id, now=now, mailer=default_mailer())
            except Exception:
                logger.exception("final summary pass failed tenant_id=%s", tenant_id)
        return count

    return run


def mark_delivery(provider_id: str, *, kind: str, at: datetime) -> bool:
    from qualify_shared.db.admin import admin_session

    with admin_session() as session:
        tenant_id = session.scalar(
            text("SELECT tenant_id FROM final_mail_batches WHERE provider_id=:id"),
            {"id": provider_id},
        )
    if tenant_id is None:
        return False
    with tenant_session(tenant_id) as session:
        session.execute(
            text("""
            UPDATE final_mail_batches SET delivery_status=:kind,delivery_at=:at
            WHERE provider_id=:id AND (delivery_at IS NULL OR delivery_at < :at)
        """),
            {"id": provider_id, "kind": kind, "at": at},
        )
    return True
