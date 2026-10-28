"""Explicit consent deletion, durable retries and a scrubbed audit (m-24789547).

Only disconnect/manual intent queues work. Runtime auth failure never calls this
module. An automatic request may be cancelled by reconsent before it is claimed;
manual deletion is irreversible once requested and cannot be cancelled by OAuth.
The worker is tenant-scoped, has no Meta API dependency, and never deletes authored
brand assets or externally published posts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from qualify_shared.db.connection_purge import connection_purge_session
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectGate, require_connection_object
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from qualify_api.connections.models import ConnectionEvent, SocialConnection
from qualify_api.connections.revoke import ConnectionNotFound

GRACE_PERIOD = timedelta(days=29)
DELETION_DEADLINE = timedelta(days=30)
SUPPORTED_PLATFORMS = frozenset({"instagram", "facebook"})
PurgeReason = Literal["disconnect", "manual"]


class UnsupportedConnectionPlatform(ValueError):
    """WhatsApp deletion is a separate, explicitly pending implementation."""


class ConnectionPurgeInProgress(ValueError):
    """Reconsent cannot race a manual or already-claimed deletion."""


class PurgeBlocked(RuntimeError):
    """Recoverable deletion failure; its code never carries personal data."""


@dataclass(frozen=True)
class PurgeRequest:
    request_id: UUID
    connection_id: UUID
    status: str
    reason: str
    due_at: datetime
    deadline_at: datetime
    last_error_code: str | None = None


def _request(row: object) -> PurgeRequest:
    return PurgeRequest(
        request_id=row.id,
        connection_id=row.connection_id,
        status=row.status,
        reason=row.reason,
        due_at=row.due_at,
        deadline_at=row.deadline_at,
        last_error_code=row.last_error_code,
    )


def _enqueue(
    session: Session, connection: SocialConnection, reason: PurgeReason, now: datetime
) -> PurgeRequest:
    if connection.platform not in SUPPORTED_PLATFORMS:
        raise UnsupportedConnectionPlatform("connection_purge_platform_unsupported")
    existing = session.execute(
        text("SELECT * FROM connection_purge_requests WHERE connection_id=:cid FOR UPDATE"),
        {"cid": connection.id},
    ).first()
    if existing is not None and existing.status != "cancelled":
        # A manual request accelerates a scheduled disconnect, without extending its
        # original legal deadline. A double-click never resets the clock.
        if reason == "manual" and existing.status == "scheduled" and existing.reason != "manual":
            session.execute(
                text("""UPDATE connection_purge_requests SET reason='manual', due_at=:now
                     WHERE connection_id=:cid"""),
                {"cid": connection.id, "now": now},
            )
        else:
            return _request(existing)
    else:
        session.execute(
            text("""INSERT INTO connection_purge_requests
                (tenant_id, connection_id, credential_version, reason, requested_at,
                 due_at, deadline_at)
                VALUES (:tid,:cid,:version,:reason,:now,:due,:deadline)
                ON CONFLICT (connection_id) DO UPDATE SET
                    credential_version=EXCLUDED.credential_version,
                    reason=EXCLUDED.reason, requested_at=EXCLUDED.requested_at,
                    due_at=EXCLUDED.due_at, deadline_at=EXCLUDED.deadline_at,
                    status='scheduled'
            """),
            {
                "tid": connection.tenant_id,
                "cid": connection.id,
                "version": connection.current_credential_version,
                "reason": reason,
                "now": now,
                "due": now + GRACE_PERIOD if reason == "disconnect" else now,
                "deadline": now + DELETION_DEADLINE,
            },
        )
    row = session.execute(
        text("SELECT * FROM connection_purge_requests WHERE connection_id=:cid"),
        {"cid": connection.id},
    ).one()
    return _request(row)


def request_connection_purge(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    reason: PurgeReason = "manual",
    now: datetime | None = None,
) -> PurgeRequest:
    """Revoke and queue explicit erasure atomically; no R2 or Meta call occurs here."""
    if reason not in {"manual", "disconnect"}:
        raise ValueError("invalid deletion reason")
    moment = now or datetime.now(UTC)
    with tenant_session(tenant_id) as session:
        connection = session.scalar(
            select(SocialConnection).where(SocialConnection.id == connection_id).with_for_update()
        )
        if connection is None:
            raise ConnectionNotFound()
        if connection.platform not in SUPPORTED_PLATFORMS:
            raise UnsupportedConnectionPlatform("connection_purge_platform_unsupported")
        if connection.status != "revoked":
            connection.status = "revoked"
            connection.disconnected_at = moment
            connection.recovery_refresh_pending = False
            session.add(
                ConnectionEvent(
                    connection_id=connection.id,
                    tenant_id=tenant_id,
                    credential_version=connection.current_credential_version,
                    event_type="revoked",
                    actor="user",
                    occurred_at=moment,
                )
            )
            session.flush()
        return _enqueue(session, connection, reason, moment)


def cancel_disconnect_purge(session: Session, connection: SocialConnection) -> None:
    """Called under the grant's connection lock before inserting a new credential."""
    row = session.execute(
        text(
            "SELECT reason,status FROM connection_purge_requests "
            "WHERE connection_id=:cid FOR UPDATE"
        ),
        {"cid": connection.id},
    ).first()
    if connection.purge_started_at is not None or (
        row is not None
        and row.status != "cancelled"
        and (row.reason == "manual" or row.status != "scheduled")
    ):
        raise ConnectionPurgeInProgress("connection_deletion_in_progress")
    if row is not None and row.status == "scheduled":
        session.execute(
            text(
                "UPDATE connection_purge_requests SET status='cancelled' WHERE connection_id=:cid"
            ),
            {"cid": connection.id},
        )


def connection_purge_status(*, tenant_id: UUID, connection_id: UUID) -> PurgeRequest | None:
    with tenant_session(tenant_id) as session:
        row = session.execute(
            text("SELECT * FROM connection_purge_requests WHERE connection_id=:cid"),
            {"cid": connection_id},
        ).first()
        return _request(row) if row is not None else None


_SOURCE_KEYS = {
    "messages": ("raw_payload_r2_key", "media_object_key"),
    "monitored_media": ("thumbnail_key",),
    "conversation_outbox": ("media_object_key",),
    "connection_events": ("raw_response_r2_key",),
    "publish_attempts": ("raw_response_r2_key",),
}
_PROTECTED_KEYS = {
    "scheduled_posts": ("media_object_key",),
    "publish_attempt_children": ("media_object_key",),
    "content_briefs": ("source_media_key",),
    "brand_kit_assets": ("object_key",),
    "product_media": ("object_key",),
    "stock_assets": ("object_key", "poster_object_key"),
    "canva_design_links": ("source_object_key", "exported_object_key"),
    "brand_voice_clones": ("sample_object_key", "preview_object_key"),
    "content_drafts": ("preview_key",),
    "image_assets": ("object_key", "mask_object_key"),
}
_PROTECTED_JSON = {"content_briefs": ("media", "video_plan"), "template_runs": ("outputs", "props")}
_DELETE_DIRECT = (
    "interaction_followups",
    "conversation_outbox",
    "comment_reply_drafts",
    "comment_intent_results",
    "comment_sentiment_results",
    "messages",
    "threads",
    "monitored_media",
    "mentions",
    "inbox_meta_call_log",
    "conversation_sync_state",
    "conversation_reply_templates",
    "conversation_reply_template_seeds",
    "conversation_ice_breakers",
    "oauth_credentials",
    "connection_events",
)


def _manifest(session: Session, connection: object, objects: ObjectGate) -> list[str]:
    params = {"cid": connection.id, "tid": connection.tenant_id}
    candidates = set(
        objects.list_connection_objects(connection.tenant_id, connection.id, connection.platform)
    )
    protected: set[str] = set()
    for table, columns in _SOURCE_KEYS.items():
        for column in columns:
            own = f"SELECT {column} FROM {table} WHERE tenant_id=:tid AND connection_id=:cid"
            candidates.update(key for key in session.scalars(text(own), params) if key)
            # Even a raw object can be shared by another consented connection.
            others = own.replace("connection_id=:cid", "connection_id<>:cid")
            protected.update(key for key in session.scalars(text(others), params) if key)
    for table, columns in _PROTECTED_KEYS.items():
        for column in columns:
            protected.update(
                key
                for key in session.scalars(
                    text(f"SELECT {column} FROM {table} WHERE tenant_id=:tid"), params
                )
                if key
            )
    protected.update(
        key
        for key in session.scalars(
            text("""SELECT thumbnail_key FROM monitored_media
            WHERE tenant_id=:tid AND thumbnail_source='published_asset'"""),
            params,
        )
        if key
    )

    def strings(value: object) -> set[str]:
        if isinstance(value, str):
            return {value}
        if isinstance(value, dict):
            return set().union(*(strings(item) for item in value.values())) if value else set()
        if isinstance(value, list):
            return set().union(*(strings(item) for item in value)) if value else set()
        return set()

    for table, columns in _PROTECTED_JSON.items():
        for column in columns:
            for value in session.scalars(
                text(f"SELECT {column} FROM {table} WHERE tenant_id=:tid"), params
            ):
                protected.update(strings(value))
    result = sorted(candidates - protected)
    for key in result:
        require_connection_object(connection.tenant_id, connection.id, connection.platform, key)
    return result


def _prepare(tenant_id: UUID, connection_id: UUID, now: datetime, objects: ObjectGate) -> object:
    with connection_purge_session(tenant_id) as session:
        connection = session.execute(
            text("SELECT * FROM social_connections WHERE id=:cid FOR UPDATE"),
            {"cid": connection_id},
        ).first()
        if connection is None:
            raise ConnectionNotFound()
        if connection.platform not in SUPPORTED_PLATFORMS:
            raise UnsupportedConnectionPlatform("connection_purge_platform_unsupported")
        request = session.execute(
            text("SELECT * FROM connection_purge_requests WHERE connection_id=:cid FOR UPDATE"),
            {"cid": connection_id},
        ).first()
        if request is None:
            raise PurgeBlocked("explicit_request_required")
        if request.status in {"completed", "cancelled"} or request.due_at > now:
            return request
        if request.status == "scheduled":
            if connection.current_credential_version != request.credential_version:
                if request.reason == "disconnect":
                    session.execute(
                        text("""UPDATE connection_purge_requests
                        SET status='cancelled' WHERE connection_id=:cid"""),
                        {"cid": connection_id},
                    )
                    return session.execute(
                        text("""SELECT * FROM connection_purge_requests
                        WHERE connection_id=:cid"""),
                        {"cid": connection_id},
                    ).one()
                raise PurgeBlocked("credential_generation_changed")
            keys = _manifest(session, connection, objects)
            session.execute(
                text("""UPDATE social_connections SET status='revoked',
                purge_started_at=:now, recovery_refresh_pending=false WHERE id=:cid"""),
                {"cid": connection_id, "now": now},
            )
            session.execute(
                text("""UPDATE connection_purge_requests SET status='running',
                object_keys=CAST(:keys AS jsonb), last_error_code=NULL
                WHERE connection_id=:cid"""),
                {"cid": connection_id, "keys": json.dumps(keys)},
            )
        session.execute(
            text("""UPDATE connection_purge_requests SET attempts=attempts+1
            WHERE connection_id=:cid"""),
            {"cid": connection_id},
        )
        return session.execute(
            text("SELECT * FROM connection_purge_requests WHERE connection_id=:cid"),
            {"cid": connection_id},
        ).one()


def _delete_rows(tenant_id: UUID, connection_id: UUID) -> None:
    params = {"cid": connection_id, "tid": tenant_id}
    with connection_purge_session(tenant_id) as session:
        session.execute(text("SELECT id FROM social_connections WHERE id=:cid FOR UPDATE"), params)
        request = session.execute(
            text("""SELECT * FROM connection_purge_requests
            WHERE connection_id=:cid FOR UPDATE"""),
            params,
        ).one()
        if request.db_deleted:
            return
        counts: dict[str, int] = {}
        for table, column, parent in (
            ("conversation_drafts", "thread_id", "threads"),
            ("mention_sentiment_results", "mention_id", "mentions"),
            ("mention_sentiment_failures", "mention_id", "mentions"),
        ):
            counts[table] = session.execute(
                text(f"""DELETE FROM {table}
                WHERE tenant_id=:tid AND {column} IN (
                    SELECT id FROM {parent} WHERE tenant_id=:tid AND connection_id=:cid)
            """),
                params,
            ).rowcount
        # The global claim is deleted only through this worker's tenant RLS. A claim
        # moved to tenant B is structurally invisible and cannot be removed here.
        session.execute(
            text("""DELETE FROM social_account_claims WHERE tenant_id=:tid
            AND network='instagram' AND handle_key IN (
                SELECT lower(ltrim(external_username, '@')) FROM social_connections WHERE id=:cid
            )"""),
            params,
        )
        for table in _DELETE_DIRECT:
            counts[table] = session.execute(
                text(f"DELETE FROM {table} WHERE tenant_id=:tid AND connection_id=:cid"), params
            ).rowcount
        session.execute(
            text("""UPDATE publish_attempts SET raw_response_r2_key=NULL
            WHERE tenant_id=:tid AND connection_id=:cid"""),
            params,
        )
        session.execute(
            text("""UPDATE connection_purge_requests SET db_deleted=true,
            counts=CAST(:counts AS jsonb) WHERE connection_id=:cid"""),
            {**params, "counts": json.dumps(counts)},
        )


def purge_connection(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    objects: ObjectGate | None = None,
    now: datetime | None = None,
) -> PurgeRequest:
    """Execute a due explicit request; a crash/failure leaves a retryable running job.

    Every object key is committed BEFORE any source row is deleted. Object-store
    failures never mark completion; an ambiguous raw webhook remains blocked until
    its legitimate retention expires. Run every fifteen minutes and alert on retries
    to leave recovery time before the 30-day deadline.
    """
    moment = now or datetime.now(UTC)
    try:
        if objects is None:
            from qualify_shared.objects.config import R2Settings
            from qualify_shared.objects.s3 import R2ObjectStore

            objects = ObjectGate(R2ObjectStore(R2Settings.from_env()))
        request = _prepare(tenant_id, connection_id, moment, objects)
        if request.status != "running":
            return _request(request)
        _delete_rows(tenant_id, connection_id)
        _purge_webhooks(tenant_id, connection_id, moment)
        keys = list(request.object_keys)
        if keys:
            with connection_purge_session(tenant_id) as session:
                platform = session.scalar(
                    text("SELECT platform FROM social_connections WHERE id=:cid"),
                    {"cid": connection_id},
                )
            objects.delete_connection_objects(tenant_id, connection_id, platform, keys)
        with connection_purge_session(tenant_id) as session:
            session.execute(
                text("SELECT id FROM social_connections WHERE id=:cid FOR UPDATE"),
                {"cid": connection_id},
            )
            session.execute(
                text("""UPDATE social_connections SET
                external_account_id='purged:' || CAST(id AS text), external_username=NULL,
                linked_page_id='purged',
                granted_scopes='{}'::text[], data_access_expires_at=NULL, last_verified_at=NULL,
                last_health_checked_at=NULL, reconnect_reason=NULL, temporary_failure_count=0,
                recovery_refresh_pending=false, purged_at=:now WHERE id=:cid"""),
                {"cid": connection_id, "now": moment},
            )
            session.execute(
                text("""UPDATE connection_purge_requests SET status='completed',
                object_keys='[]'::jsonb, last_error_code=NULL, completed_at=:now
                WHERE connection_id=:cid"""),
                {"cid": connection_id, "now": moment},
            )
    except Exception as exc:
        # Persist only allowlisted failure classes/codes, never vendor SQL/token/key text.
        code = str(exc) if isinstance(exc, PurgeBlocked) else type(exc).__name__
        with connection_purge_session(tenant_id) as session:
            session.execute(
                text("""UPDATE connection_purge_requests SET last_error_code=:code
                WHERE connection_id=:cid AND status IN ('scheduled','running')"""),
                {"cid": connection_id, "code": code},
            )
        raise
    result = connection_purge_status(tenant_id=tenant_id, connection_id=connection_id)
    assert result is not None
    return result


def _purge_webhooks(tenant_id: UUID, connection_id: UUID, now: datetime) -> None:
    # Filled by the ownership-aware webhook seam; never call purge_by_entry_id here.
    from qualify_api.webhooks.purge import purge_connection_webhooks

    if not purge_connection_webhooks(tenant_id=tenant_id, connection_id=connection_id, now=now):
        raise PurgeBlocked("raw_ownership_unverified")
