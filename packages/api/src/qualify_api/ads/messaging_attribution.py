"""Authenticated webhook evidence → scoped message attribution, without Meta writes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from qualify_shared.db.webhook import webhook_worker_session
from sqlalchemy import bindparam, text

from qualify_api.ads.messaging import PIPELINE_VERSION, MessagingTarget, referral_ad_id
from qualify_api.webhooks.repository import ClaimedEvent


def _owner(event_id: UUID) -> dict[str, Any] | None:
    with webhook_worker_session() as session:
        return session.execute(
            text("SELECT ad_message_event_owner(:id)"), {"id": event_id}
        ).scalar_one_or_none()


def attribute_inbound_message(
    *,
    event: ClaimedEvent,
    tenant_id: UUID,
    connection_id: UUID,
    thread_id: UUID,
    external_message_id: str,
    channel: str,
    referral: Any,
) -> bool:
    """Idempotent even after a crash between message INSERT and attribution INSERT.

    A missing/unknown referral or unproven legacy custody never labels a message.
    Malformed attribution does not prevent the ordinary inbound message from landing.
    Database failures propagate so the recorded webhook can retry this independent step.
    """
    evidence = event_message_evidence(event, external_message_id, channel=channel)
    if evidence is None:
        return False
    ad_id, sender = evidence
    proof = _owner(event.id)
    if not proof or (proof["tenant_id"], proof["connection_id"]) != (
        str(tenant_id),
        str(connection_id),
    ):
        return False
    with tenant_session(tenant_id, independent=True) as session:
        promotion = (
            session.execute(text("SELECT * FROM ad_promotions WHERE meta_ad_id=:ad"), {"ad": ad_id})
            .mappings()
            .one_or_none()
        )
        if promotion is None:
            return False
        snapshot = promotion["request_snapshot"]
        try:
            target = MessagingTarget.from_snapshot(snapshot.get("messaging_snapshot", {}))
            target.validate_request(SimpleNamespace(**snapshot))
        except (ValueError, TypeError, AttributeError):
            return False
        expected = "WHATSAPP" if channel == "whatsapp" else "INSTAGRAM_DIRECT"
        if target.destination_type != expected or target.target_connection_id != connection_id:
            return False
        binding = (
            session.execute(
                text("""
                SELECT source.current_credential_version AS source_version,
                       destination.current_credential_version AS target_version,
                       source.linked_page_id,
                       source.external_account_id AS instagram_id,
                       phone.phone_number_id,phone.display_phone_number
                  FROM social_connections source
                  JOIN social_connections destination ON destination.id=:destination
                    AND destination.tenant_id=source.tenant_id
                    AND destination.brand_id=source.brand_id
                  JOIN publish_attempts pub ON pub.id=:published
                    AND pub.connection_id=source.id AND pub.tenant_id=source.tenant_id
                    AND pub.status='published' AND pub.published_media_id=:media
                  LEFT JOIN whatsapp_phone_numbers phone ON phone.connection_id=destination.id
                    AND phone.tenant_id=destination.tenant_id
                    AND phone.brand_id=destination.brand_id
                    AND phone.phone_number_id=:phone
                 WHERE source.id=:source AND source.brand_id=:brand
                   AND source.platform='instagram' AND source.status='active'
                   AND source.purge_started_at IS NULL AND source.purged_at IS NULL
                   AND destination.status='active' AND destination.purge_started_at IS NULL
                   AND destination.purged_at IS NULL
                   AND destination.platform=:platform
                 FOR SHARE OF source,destination,pub
            """),
                {
                    "destination": connection_id,
                    "source": target.source_connection_id,
                    "brand": promotion["brand_id"],
                    "published": promotion["publish_attempt_id"],
                    "media": promotion["source_media_id"],
                    "phone": target.phone_number_id,
                    "platform": "whatsapp" if channel == "whatsapp" else "instagram",
                },
            )
            .mappings()
            .one_or_none()
        )
        if (
            binding is None
            or binding["source_version"] != target.source_credential_version
            or binding["target_version"] != target.target_credential_version
            or binding["target_version"] != proof["credential_version"]
            or binding["linked_page_id"] != target.page_id
            or binding["instagram_id"] != snapshot["creative"]["instagram_user_id"]
        ):
            return False
        if channel == "whatsapp" and (
            binding["phone_number_id"] != target.phone_number_id
            or _digits(binding["display_phone_number"]) != target.whatsapp_phone_number
        ):
            return False
        result = session.execute(
            text("""
                INSERT INTO ad_message_attributions
                    (message_id,tenant_id,brand_id,connection_id,source_connection_id,
                     promotion_id,webhook_event_id,attributed_at,pipeline_version)
                SELECT m.id,m.tenant_id,:brand,m.connection_id,:source,:promotion,
                       :event,:at,:version
                  FROM messages m JOIN threads t ON t.id=m.thread_id AND t.tenant_id=m.tenant_id
                 WHERE m.connection_id=:connection AND m.external_message_id=:mid
                   AND m.thread_id=:thread AND t.connection_id=m.connection_id
                   AND m.author_external_id=:sender AND t.external_thread_id=:sender
                   AND t.channel=:channel AND m.direction='inbound' AND m.deleted_at IS NULL
                ON CONFLICT DO NOTHING
            """),
            {
                "brand": promotion["brand_id"],
                "source": target.source_connection_id,
                "promotion": promotion["id"],
                "event": event.id,
                "at": datetime.now(UTC),
                "version": PIPELINE_VERSION,
                "connection": connection_id,
                "mid": external_message_id,
                "thread": thread_id,
                "channel": channel,
                "sender": sender,
            },
        )
        return result.rowcount == 1


def _digits(value: Any) -> str:
    if not isinstance(value, str) or any(c not in "0123456789 +()-" for c in value):
        return ""
    return "".join(c for c in value if c in "0123456789")


_VISIBLE_ORIGINS = """
    FROM ad_message_attributions a
    JOIN messages m ON m.id=a.message_id AND m.tenant_id=a.tenant_id
    JOIN threads thread ON thread.id=m.thread_id AND thread.tenant_id=m.tenant_id
    JOIN ad_promotions p ON p.id=a.promotion_id AND p.tenant_id=a.tenant_id
      AND p.brand_id=a.brand_id
    JOIN social_connections target ON target.id=a.connection_id AND target.tenant_id=a.tenant_id
      AND target.brand_id=a.brand_id AND target.status='active'
      AND target.purge_started_at IS NULL AND target.purged_at IS NULL
    JOIN social_connections source ON source.id=a.source_connection_id
      AND source.tenant_id=a.tenant_id AND source.brand_id=a.brand_id AND source.status='active'
      AND source.purge_started_at IS NULL AND source.purged_at IS NULL
    JOIN publish_attempts pub ON pub.id=p.publish_attempt_id AND pub.tenant_id=p.tenant_id
      AND pub.connection_id=source.id AND pub.status='published'
      AND pub.published_media_id=p.source_media_id
    WHERE m.direction='inbound' AND m.deleted_at IS NULL
      AND m.connection_id=target.id AND thread.connection_id=target.id
"""


def origin_label(caption: str | None) -> str:
    excerpt = " ".join((caption or "").split())[:160]
    return "Vino de un anuncio: " + excerpt if excerpt else "Vino de un anuncio de este negocio"


def attach_ad_origins(tenant_id: UUID, records: Sequence[Any]) -> list[Any]:
    """One bounded batch read for both inbox repositories, never one query per message."""
    if not records:
        return list(records)
    query = text(
        "SELECT a.message_id,a.promotion_id,a.attributed_at,pub.caption "
        + _VISIBLE_ORIGINS
        + " AND a.message_id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    with tenant_session(tenant_id) as session:
        rows = session.execute(query, {"ids": [row.id for row in records]}).mappings().all()
    origins = {row["message_id"]: row for row in rows}
    return [
        replace(
            row,
            ad_promotion_id=origins[row.id]["promotion_id"],
            ad_origin_label=origin_label(origins[row.id]["caption"]),
            ad_origin_at=origins[row.id]["attributed_at"],
        )
        if row.id in origins
        else row
        for row in records
    ]


def promotion_conversation_count(*, tenant_id: UUID, promotion_id: UUID) -> int:
    """Observed distinct threads, not Meta's conversion or attribution-window metric."""
    from qualify_api.tenancy.acting import require_acting_member

    require_acting_member(tenant_id)
    with tenant_session(tenant_id) as session:
        return int(
            session.execute(
                text(
                    "SELECT count(DISTINCT m.thread_id) "
                    + _VISIBLE_ORIGINS
                    + " AND a.promotion_id=:promotion"
                ),
                {"promotion": promotion_id},
            ).scalar_one()
        )


def raw_whatsapp_referral(event: ClaimedEvent, message_id: str, sender: str) -> Any:
    value = event.value
    if not isinstance(value, dict) or not isinstance(value.get("messages"), list):
        return None
    matches = [
        m
        for m in value["messages"]
        if isinstance(m, dict) and m.get("id") == message_id and m.get("from") == sender
    ]
    return matches[0].get("referral") if len(matches) == 1 else None


def event_message_evidence(
    event: ClaimedEvent,
    message_id: str,
    *,
    channel: str,
) -> tuple[str, str] | None:
    """Bind provenance to this recorded message, never a caller-supplied referral."""
    value = event.value
    if not message_id or event.field != "messages" or not isinstance(value, dict):
        return None
    if channel == "whatsapp" and event.object == "whatsapp_business_account":
        messages = value.get("messages")
        if not isinstance(messages, list):
            return None
        matches = [m for m in messages if isinstance(m, dict) and m.get("id") == message_id]
        if len(matches) != 1:
            return None
        message = matches[0]
        sender = message.get("from")
    elif channel == "dm" and event.object == "instagram":
        message = value.get("message")
        if (
            not isinstance(message, dict)
            or message.get("mid") != message_id
            or message.get("is_echo") is True
            or message.get("is_deleted") is True
            or not isinstance(value.get("recipient"), dict)
            or value["recipient"].get("id") != event.entry_id
        ):
            return None
        sender = (
            value.get("sender", {}).get("id") if isinstance(value.get("sender"), dict) else None
        )
        if sender == event.entry_id:
            return None
    else:
        return None
    ad_id = referral_ad_id(message.get("referral"), channel=channel)
    return (ad_id, sender) if ad_id is not None and isinstance(sender, str) and sender else None
