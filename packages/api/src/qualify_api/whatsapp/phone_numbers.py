"""Persistence for `whatsapp_phone_numbers` (WA-05).

A Protocol plus the Postgres implementation, same split `connections/repository.py`
uses: the connect command's decision tree runs against an in-memory fake with no
database, while the real write goes through `tenant_session`, the RLS-scoped door.

The natural key is `phone_number_id` — Meta's global identifier, UNIQUE across the whole
table (migration 0057), because the webhook resolves the owning tenant from it alone. An
upsert therefore never produces a second row for a number: re-running the connect
command refreshes the Graph metadata in place and moves `last_synced_at`.

Two consequences of RLS worth stating. A row owned by ANOTHER tenant is invisible to this
session, so the upsert sees "no row" and INSERTs — and Postgres refuses it on
`uq_wa_phone_number_id`. That `IntegrityError` is the correct outcome: a number cannot
be connected to two tenants, and the command must not silently steal it. And
`connection_id`/`tenant_id` are a composite FK to `social_connections` (R2), so a phone
row whose tenant disagrees with its connection is structurally unbuildable.

`automation` is deliberately NOT touched here: it is the object WA-15/WA-16 publish to
Meta, and a reconnect must not reset what the editor last published.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.whatsapp.models import WhatsAppPhoneNumber


@dataclass(frozen=True)
class PhoneNumberUpsert:
    """What one connect run knows about the number: identity plus the Graph metadata
    read moments before. Every metadata field is nullable because Meta omits fields it
    has no value for (see `PhoneNumberInfo`)."""

    tenant_id: UUID
    brand_id: UUID | None
    connection_id: UUID
    waba_id: str
    phone_number_id: str
    display_phone_number: str
    verified_name: str | None
    name_status: str | None
    quality_rating: str | None
    messaging_limit_tier: str | None
    platform_status: str | None
    synced_at: datetime


class WhatsAppPhoneNumberRepository(Protocol):
    def upsert(self, record: PhoneNumberUpsert) -> bool:
        """Create or refresh the row for `record.phone_number_id`. Returns True when a
        row was CREATED, False when an existing one was refreshed."""
        ...


class PostgresWhatsAppPhoneNumberRepository:
    """Writes through `tenant_session` — `qualify_app` holds SELECT/INSERT/UPDATE on the
    table (0057's grant matrix), and RLS scopes the SELECT to the record's tenant."""

    def upsert(self, record: PhoneNumberUpsert) -> bool:
        with tenant_session(record.tenant_id) as session:
            existing = session.scalar(
                select(WhatsAppPhoneNumber).where(
                    WhatsAppPhoneNumber.phone_number_id == record.phone_number_id
                )
            )
            if existing is None:
                session.add(
                    WhatsAppPhoneNumber(
                        tenant_id=record.tenant_id,
                        brand_id=record.brand_id,
                        connection_id=record.connection_id,
                        waba_id=record.waba_id,
                        phone_number_id=record.phone_number_id,
                        display_phone_number=record.display_phone_number,
                        verified_name=record.verified_name,
                        name_status=record.name_status,
                        quality_rating=record.quality_rating,
                        messaging_limit_tier=record.messaging_limit_tier,
                        platform_status=record.platform_status,
                        last_synced_at=record.synced_at,
                    )
                )
                session.flush()
                return True
            # A re-run refreshes what Meta now reports. `brand_id=None` means "leave
            # what is there", the same convention `persist_grant` uses for the connection.
            existing.brand_id = record.brand_id or existing.brand_id
            existing.connection_id = record.connection_id
            existing.waba_id = record.waba_id
            existing.display_phone_number = record.display_phone_number
            existing.verified_name = record.verified_name
            existing.name_status = record.name_status
            existing.quality_rating = record.quality_rating
            existing.messaging_limit_tier = record.messaging_limit_tier
            existing.platform_status = record.platform_status
            existing.last_synced_at = record.synced_at
            session.flush()
            return False
