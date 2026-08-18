"""Persistence seam for the leads module.

`PostgresLeadRepository` goes through `tenant_session` exclusively — the query-param
tenant uuid is only ever used to scope an RLS transaction, so an unknown tenant and a
tenant with no form are the same read: zero rows. That equivalence is what lets the
public surface answer one 404 for both without ever confirming a tenant exists.

`MemoryLeadRepository` exists for the route/service tests (same house pattern as
`MemoryPublishAttemptRepository`): the HTTP chain runs with zero network and zero DB.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from qualify_api.leads.models import Lead, LeadFormSettings

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(raw: str) -> str:
    """Collapse spacing/punctuation and require full international E.164.

    Strict on purpose: guessing a default country prefix here would silently attach a
    Colombian +57 to a Uruguayan lead. The form UI owns the country selector; the
    backend only accepts the unambiguous spelling.
    """
    candidate = re.sub(r"[\s\-().]", "", raw)
    if not _E164.fullmatch(candidate):
        raise ValueError("whatsapp_phone must be E.164 (+<country><number>)")
    return candidate


@dataclass(frozen=True)
class FormSettingsRow:
    business_name: str
    whatsapp_phone: str
    whatsapp_greeting: str | None
    promo_text: str | None
    interest_options: list[str]
    consent_text: str
    consent_policy_version: str
    custom_fields: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class LeadRecord:
    full_name: str
    whatsapp_phone: str  # already normalized
    consent_at: datetime
    consent_policy_version: str
    email: str | None = None
    birthday: date | None = None
    interest: str | None = None
    source_declared: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    # Answers to the tenant's custom fields — already filtered to declared keys.
    extra: dict[str, str] = field(default_factory=dict)


class LeadRepository(Protocol):
    def get_active_settings(self, *, tenant_id: UUID) -> FormSettingsRow | None: ...

    def upsert_lead(self, *, tenant_id: UUID, record: LeadRecord) -> UUID: ...


# The optional fields keep their stored value when a re-submission omits them —
# a person adding their birthday later must not erase the interest they gave first.
_COALESCE_ON_CONFLICT = (
    "email",
    "birthday",
    "interest",
    "source_declared",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
)


class PostgresLeadRepository:
    def get_active_settings(self, *, tenant_id: UUID) -> FormSettingsRow | None:
        with tenant_session(tenant_id) as session:
            row = session.scalar(select(LeadFormSettings).where(LeadFormSettings.active.is_(True)))
            if row is None:
                return None
            return FormSettingsRow(
                business_name=row.business_name,
                whatsapp_phone=row.whatsapp_phone,
                whatsapp_greeting=row.whatsapp_greeting,
                promo_text=row.promo_text,
                interest_options=list(row.interest_options),
                consent_text=row.consent_text,
                consent_policy_version=row.consent_policy_version,
                custom_fields=list(row.custom_fields),
            )

    def upsert_lead(self, *, tenant_id: UUID, record: LeadRecord) -> UUID:
        stmt = insert(Lead).values(
            tenant_id=tenant_id,
            full_name=record.full_name,
            whatsapp_phone=record.whatsapp_phone,
            email=record.email,
            birthday=record.birthday,
            interest=record.interest,
            source_declared=record.source_declared,
            utm_source=record.utm_source,
            utm_medium=record.utm_medium,
            utm_campaign=record.utm_campaign,
            utm_content=record.utm_content,
            utm_term=record.utm_term,
            extra=record.extra,
            consent_at=record.consent_at,
            consent_policy_version=record.consent_policy_version,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_lead_tenant_phone",
            set_={
                # A re-submission is a fresh consent — always restamped.
                "full_name": stmt.excluded.full_name,
                "consent_at": stmt.excluded.consent_at,
                "consent_policy_version": stmt.excluded.consent_policy_version,
                # jsonb concat: later answers win per key, earlier keys survive.
                "extra": Lead.__table__.c.extra.op("||")(stmt.excluded.extra),
                "updated_at": func.now(),
                **{
                    column: func.coalesce(
                        getattr(stmt.excluded, column), getattr(Lead.__table__.c, column)
                    )
                    for column in _COALESCE_ON_CONFLICT
                },
            },
        ).returning(Lead.id)
        with tenant_session(tenant_id) as session:
            return session.execute(stmt).scalar_one()


class MemoryLeadRepository:
    """Test double. Mirrors the upsert semantics of the Postgres implementation."""

    def __init__(self) -> None:
        self.settings: dict[UUID, FormSettingsRow] = {}
        self.leads: dict[tuple[UUID, str], tuple[UUID, LeadRecord]] = {}

    def get_active_settings(self, *, tenant_id: UUID) -> FormSettingsRow | None:
        return self.settings.get(tenant_id)

    def upsert_lead(self, *, tenant_id: UUID, record: LeadRecord) -> UUID:
        key = (tenant_id, record.whatsapp_phone)
        existing = self.leads.get(key)
        if existing is None:
            lead_id = uuid4()
            self.leads[key] = (lead_id, record)
            return lead_id
        lead_id, stored = existing
        merged = replace(
            record,
            extra={**stored.extra, **record.extra},
            **{
                column: getattr(record, column) or getattr(stored, column)
                for column in _COALESCE_ON_CONFLICT
            },
        )
        self.leads[key] = (lead_id, merged)
        return lead_id
