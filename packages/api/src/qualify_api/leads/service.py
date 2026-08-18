"""Lead intake service — the logic between the public HTTP surface and the repository.

Identity note (C1): there is no `Principal` here and that is not an oversight. This is
a PUBLIC surface; the tenant uuid from `?e=` is never believed as authorization — it is
only the scope of an RLS session, and a tenant that does not exist or has no active
form produces the same `FormNotFound` as one that was never provisioned. What C1
forbids is *trusting* a client-supplied tenant for access to tenant data; here the only
"access" granted is the right to append one consented row inside that same scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import quote
from uuid import UUID

from qualify_api.leads.rate_limit import RateLimiter
from qualify_api.leads.repository import (
    FormSettingsRow,
    LeadRecord,
    LeadRepository,
    normalize_phone,
)


class FormNotFound(Exception):
    """No active form for that tenant scope — deliberately also the unknown-tenant case."""


class RateLimited(Exception):
    pass


@dataclass(frozen=True)
class PublicForm:
    business_name: str
    promo_text: str | None
    interest_options: list[str]
    consent_text: str
    consent_policy_version: str
    custom_fields: list[dict]


@dataclass(frozen=True)
class LeadSubmission:
    full_name: str
    whatsapp_phone: str  # raw, as typed; normalized here
    email: str | None = None
    birthday: date | None = None
    interest: str | None = None
    source_declared: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_term: str | None = None
    extra: dict[str, str] | None = None


@dataclass(frozen=True)
class IntakeAccepted:
    lead_id: UUID
    promo_text: str | None
    whatsapp_url: str


def build_whatsapp_url(settings: FormSettingsRow, *, lead_name: str) -> str:
    """The handoff: the lead lands in the business's own WhatsApp with the promo named.

    `.replace`, not `.format`: the template is tenant-authored text and a stray `{` in
    it must stay a stray `{`, not a KeyError at intake time.
    """
    template = settings.whatsapp_greeting or "Hola, soy {name}. Vengo por: {promo}"
    message = template.replace("{name}", lead_name).replace(
        "{promo}", settings.promo_text or settings.business_name
    )
    return f"https://wa.me/{settings.whatsapp_phone.lstrip('+')}?text={quote(message)}"


class LeadIntakeService:
    def __init__(self, *, repository: LeadRepository, limiter: RateLimiter) -> None:
        self._repository = repository
        self._limiter = limiter

    def public_form(self, *, tenant_id: UUID) -> PublicForm:
        settings = self._repository.get_active_settings(tenant_id=tenant_id)
        if settings is None:
            raise FormNotFound
        return PublicForm(
            business_name=settings.business_name,
            promo_text=settings.promo_text,
            interest_options=settings.interest_options,
            consent_text=settings.consent_text,
            consent_policy_version=settings.consent_policy_version,
            custom_fields=settings.custom_fields,
        )

    def submit(
        self, *, tenant_id: UUID, submission: LeadSubmission, client_key: str
    ) -> IntakeAccepted:
        """Raises `RateLimited`, `FormNotFound`, or `ValueError` (bad phone).

        Rate limit first: it must fire before any DB read, or the limiter is only
        protecting the cheap half of the endpoint.
        """
        if not self._limiter.allow(f"{tenant_id}:{client_key}"):
            raise RateLimited
        settings = self._repository.get_active_settings(tenant_id=tenant_id)
        if settings is None:
            raise FormNotFound
        # Only answers to fields the tenant DECLARED are stored: the public surface
        # must not be a way to write arbitrary keys into `extra`.
        declared = {spec["key"] for spec in settings.custom_fields if "key" in spec}
        extra = {
            key: value.strip()
            for key, value in (submission.extra or {}).items()
            if key in declared and value.strip()
        }
        record = LeadRecord(
            full_name=submission.full_name.strip(),
            whatsapp_phone=normalize_phone(submission.whatsapp_phone),
            # Consent is stamped with the version the ACTIVE settings row carries — the
            # policy text the form was rendering when the person ticked the box.
            consent_at=datetime.now(UTC),
            consent_policy_version=settings.consent_policy_version,
            email=submission.email,
            birthday=submission.birthday,
            interest=submission.interest,
            source_declared=submission.source_declared,
            utm_source=submission.utm_source,
            utm_medium=submission.utm_medium,
            utm_campaign=submission.utm_campaign,
            utm_content=submission.utm_content,
            utm_term=submission.utm_term,
            extra=extra,
        )
        lead_id = self._repository.upsert_lead(tenant_id=tenant_id, record=record)
        return IntakeAccepted(
            lead_id=lead_id,
            promo_text=settings.promo_text,
            whatsapp_url=build_whatsapp_url(settings, lead_name=record.full_name),
        )
