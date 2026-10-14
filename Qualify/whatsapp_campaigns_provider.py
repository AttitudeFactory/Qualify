"""The seam between `/whatsapp` → Campañas (WA-20, QUA-219) and the real backend.

In-process calls to `qualify_api.whatsapp.campaigns.CampaignService`
(`production_campaign_service()`: Postgres campaign/template/opt-in repositories, all
`tenant_session`/RLS). `launch` does not talk to Meta: it inserts the sends and their
paced outbox rows in one transaction each, and WA-08's outbox sender does the sending —
so a Meta refusal (no payment method → `131042`, the per-user marketing limit →
`131049`) shows up later on the send rows, which the detail view reads.

The service is synchronous (SQLAlchemy); every function here is blocking and the state
runs it off-thread. Everything is injectable (`service`, `templates`) so
`test_whatsapp_campaigns.py` drives it with the Memory repositories.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from qualify_api.tenancy.models import Brand, User
from qualify_api.whatsapp.campaigns import (
    CampaignRecord,
    CampaignService,
    LaunchReport,
    production_campaign_service,
)
from qualify_api.whatsapp.optins import AudienceFilter
from qualify_api.whatsapp.templates import (
    PostgresTemplateRepository,
    TemplateRepository,
)
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from .whatsapp_campaigns_vm import (
    ERROR_PAYMENT,
    FINAL,
    NOT_LAUNCHED,
    CampaignDetailVM,
    CampaignRowVM,
    EstimateVM,
    SendVM,
    build_campaign_row,
    build_estimate_vm,
    build_send_vm,
    rate_label,
    retry_after_label,
)
from .whatsapp_templates_provider import template_vm
from .whatsapp_templates_vm import TemplateVM

MAX_SENDS_LISTED = 500


class UnknownUser(LookupError):
    """The session's email is not a user of the tenant (`created_by_user_id` is NOT NULL
    on `whatsapp_campaigns`, so a campaign needs one)."""


@dataclass(frozen=True)
class WizardTemplate:
    """A template the wizard can offer: its VM plus its raw components (kept backend-side
    by the state, never serialized)."""

    vm: TemplateVM
    category: str
    components: list[dict[str, Any]]


def _service(service: CampaignService | None) -> CampaignService:
    return service or production_campaign_service()


def user_id_for(tenant_id: UUID, email: str) -> UUID | None:
    if not email:
        return None
    with tenant_session(tenant_id) as session:
        return session.scalar(select(User.id).where(User.email == email))


def brands_for(tenant_id: UUID) -> list[tuple[str, str]]:
    with tenant_session(tenant_id) as session:
        rows = session.execute(select(Brand.id, Brand.name).order_by(Brand.name)).all()
    return [(str(brand_id), name) for brand_id, name in rows]


def wizard_templates(
    tenant_id: UUID, connection_id: UUID, *, templates: TemplateRepository | None = None
) -> list[WizardTemplate]:
    """Every template of the number's WABA (approved first) with its components."""
    repo = templates or PostgresTemplateRepository()
    ref = repo.waba_for_connection(tenant_id=tenant_id, connection_id=connection_id)
    if ref is None:
        return []
    out = [
        WizardTemplate(vm=template_vm(r), category=r.category, components=list(r.components))
        for r in repo.list(tenant_id=tenant_id, waba_id=ref.waba_id)
    ]
    return sorted(out, key=lambda t: (not t.vm.sendable, t.vm.name, t.vm.language))


def _template_labels(tenant_id: UUID, templates: TemplateRepository | None) -> dict[str, str]:
    repo = templates or PostgresTemplateRepository()
    return {str(r.id): f"{r.name} · {r.language}" for r in repo.list(tenant_id=tenant_id)}


def _row(
    service: CampaignService, record: CampaignRecord, labels: Mapping[str, str]
) -> CampaignRowVM:
    summary = service.summary(tenant_id=record.tenant_id, campaign_id=record.id)
    return build_campaign_row(
        campaign_id=str(record.id),
        name=record.name,
        template_label=labels.get(str(record.template_id), "Plantilla eliminada"),
        status=summary.status,
        counts=summary.counts,
        costs=[(c.currency, c.amount, c.sends) for c in summary.costs],
        created_at=record.created_at,
    )


def campaign_rows(
    tenant_id: UUID,
    connection_id: UUID,
    *,
    service: CampaignService | None = None,
    templates: TemplateRepository | None = None,
) -> list[CampaignRowVM]:
    """The number's campaigns, newest first, each with its send counts and cost."""
    svc = _service(service)
    labels = _template_labels(tenant_id, templates)
    records = [r for r in svc.list(tenant_id=tenant_id) if r.connection_id == connection_id]
    records.sort(key=lambda r: (r.created_at is None, r.created_at), reverse=True)
    return [_row(svc, r, labels) for r in records]


def count_audience(
    tenant_id: UUID, audience: Mapping[str, Any], *, service: CampaignService | None = None
) -> int:
    """Live opt-ins matching the filter. Raises `ValueError` for an invalid filter."""
    return len(
        _service(service).build_audience(
            tenant_id=tenant_id, audience_filter=AudienceFilter.from_json(dict(audience))
        )
    )


def create_draft(
    tenant_id: UUID,
    connection_id: UUID,
    *,
    email: str,
    name: str,
    template_id: UUID,
    send_components: Sequence[Mapping[str, Any]],
    audience: Mapping[str, Any],
    max_per_minute: int,
    service: CampaignService | None = None,
    user_lookup: Any = user_id_for,
) -> UUID:
    """A `draft` campaign; raises `UnknownUser`, `TemplateNotFound`,
    `TemplateNotSendable` (another WABA) or `ValueError`."""
    user_id = user_lookup(tenant_id, email)
    if user_id is None:
        raise UnknownUser(email)
    audience_filter = AudienceFilter.from_json(dict(audience))
    record = _service(service).create(
        tenant_id=tenant_id,
        connection_id=connection_id,
        template_id=template_id,
        name=name,
        created_by_user_id=user_id,
        audience=audience_filter,
        send_components=[dict(c) for c in send_components],
        max_per_minute=max_per_minute,
        brand_id=audience_filter.brand_id,
    )
    return record.id


def estimate(
    tenant_id: UUID, campaign_id: UUID, *, service: CampaignService | None = None
) -> EstimateVM:
    result = _service(service).estimate(tenant_id=tenant_id, campaign_id=campaign_id)
    return build_estimate_vm(
        recipients=result.recipients,
        costs=[(c.currency, c.amount, c.sends) for c in result.costs],
        unpriced=result.unpriced,
        placeholder=result.placeholder,
        rate_card_status=result.rate_card_status,
    )


def launch(
    tenant_id: UUID,
    campaign_id: UUID,
    *,
    email: str,
    service: CampaignService | None = None,
    user_lookup: Any = user_id_for,
) -> LaunchReport:
    """Idempotent (the service resumes, never resends)."""
    return _service(service).launch(
        tenant_id=tenant_id, campaign_id=campaign_id, user_id=user_lookup(tenant_id, email)
    )


def cancel(tenant_id: UUID, campaign_id: UUID, *, service: CampaignService | None = None) -> int:
    return _service(service).cancel(tenant_id=tenant_id, campaign_id=campaign_id)


@dataclass(frozen=True)
class CampaignDetail:
    detail: CampaignDetailVM
    sends: list[SendVM]
    estimate: EstimateVM | None  # only for a campaign not launched yet


def campaign_detail(
    tenant_id: UUID,
    campaign_id: UUID,
    *,
    service: CampaignService | None = None,
    templates: TemplateRepository | None = None,
) -> CampaignDetail:
    """Summary + sends (+ the estimate while it is a draft). Calls
    `finalize_if_complete` first — cheap, and the docstring's own advice for the UI."""
    svc = _service(service)
    svc.finalize_if_complete(tenant_id=tenant_id, campaign_id=campaign_id)
    record = svc.get(tenant_id=tenant_id, campaign_id=campaign_id)
    labels = _template_labels(tenant_id, templates)
    row = _row(svc, record, labels)
    summary = svc.summary(tenant_id=tenant_id, campaign_id=campaign_id)
    records = svc.sends(tenant_id=tenant_id, campaign_id=campaign_id)
    sends = [
        build_send_vm(
            phone_e164=s.phone_e164,
            status=s.status,
            error_code=s.error_code,
            service_note=s.note,
            retry_not_before=s.retry_not_before,
            cost_estimate=s.cost_estimate,
            currency=s.currency,
        )
        for s in records[:MAX_SENDS_LISTED]
    ]
    not_launched = record.status in NOT_LAUNCHED
    return CampaignDetail(
        detail=CampaignDetailVM(
            row=row,
            # A running campaign resumes on its own; «Lanzar» is for one not launched yet.
            can_launch=record.status in NOT_LAUNCHED,
            can_cancel=record.status not in FINAL,
            retry_after_24h=retry_after_label(summary.retry_after_24h),
            payment_failed=any(s.error_code == ERROR_PAYMENT for s in records),
            rate_label=rate_label(record.max_per_minute),
        ),
        sends=sends,
        estimate=estimate(tenant_id, campaign_id, service=svc) if not_launched else None,
    )
