"""Network-free tests for `/whatsapp` → Campañas (WA-20, QUA-219).

They pin:
1. The VM boundary (frozen, no credential field, no wamid/payload) and the copy Meta's
   rules require: the rate-card placeholder notice, `131049` → «reintentar ≥ 24 h»,
   `131042` → the payment method, always with the Meta code.
2. The wizard's pure steps: audience filter → `AudienceFilter` JSON, pacing, basics.
3. The provider over the Memory repositories: draft → estimate (placeholder) → launch
   (paced outbox rows, no resend) → detail → cancel; an unknown user cannot create.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import reflex as rx
from qualify_api.whatsapp.campaigns import CampaignService, MemoryCampaignRepository
from qualify_api.whatsapp.optins import AudienceFilter, MemoryOptInRepository, OptInRecord
from qualify_api.whatsapp.templates import MemoryTemplateRepository, TemplateRecord

from . import whatsapp_tab_campaigns
from .whatsapp_campaigns_provider import (
    UnknownUser,
    campaign_detail,
    campaign_rows,
    cancel,
    count_audience,
    create_draft,
    estimate,
    launch,
    wizard_templates,
)
from .whatsapp_campaigns_vm import (
    EMPTY_TEMPLATE,
    PAYMENT_FAILED,
    RATE_CARD_NOTICE,
    AudienceForm,
    CampaignDetailVM,
    CampaignRowVM,
    EstimateVM,
    OptionVM,
    SendVM,
    VariableFieldVM,
    audience_filter_json,
    build_campaign_row,
    build_send_vm,
    format_money,
    pacing_hint,
    send_error_note,
    validate_basics,
    validate_pacing,
)

_FORBIDDEN = ("token", "credential", "cipher", "secret", "key_id", "wamid", "payload", "outbox")
TENANT = UUID("00000000-0000-0000-0000-0000000000a3")
CONNECTION = UUID("00000000-0000-0000-0000-0000000000c3")
USER = UUID("00000000-0000-0000-0000-0000000000e3")
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


# --- 1. VM ----------------------------------------------------------------------------


def test_whatsapp_campaigns_vm_has_no_credential_fields() -> None:
    for vm in (CampaignRowVM, CampaignDetailVM, SendVM, EstimateVM, VariableFieldVM, OptionVM):
        assert vm.__dataclass_params__.frozen  # type: ignore[attr-defined]
        for f in dataclasses.fields(vm):
            assert not any(bad in f.name.lower() for bad in _FORBIDDEN), (vm, f.name)


def test_row_counts_are_cumulative() -> None:
    row = build_campaign_row(
        campaign_id="c",
        name="Promo",
        template_label="promo · es",
        status="running",
        counts={"pending": 1, "queued": 2, "sent": 3, "delivered": 4, "read": 5, "failed": 1},
        costs=[("USD", Decimal("1.5"), 12)],
        created_at=NOW,
    )
    assert (row.sent, row.delivered, row.read, row.queued) == ("12", "9", "5", "3")
    assert row.cost_label == "USD 1,50" and row.status_label == "En curso"


def test_meta_codes_are_explained_with_the_code() -> None:
    assert "24 h" in send_error_note("131049") and "131049" in send_error_note("131049")
    assert "método de pago" in send_error_note("131042")
    assert send_error_note("999999") == "Meta rechazó el envío (código 999999)"
    assert send_error_note("not_opted_in", "sin opt-in vigente al encolar").startswith("Sin opt-in")
    assert "131042" in PAYMENT_FAILED
    assert RATE_CARD_NOTICE == "Tarifas de referencia pendientes: el costo es aproximado."


def test_send_vm_retry_time() -> None:
    vm = build_send_vm(
        phone_e164="+573001112233",
        status="skipped",
        error_code="131049",
        service_note="reintentar ≥24 h",
        retry_not_before=NOW + timedelta(hours=24),
        cost_estimate=Decimal("0.0125"),
        currency="USD",
    )
    assert vm.status_tone == "warn" and vm.retry_after.startswith("Reintentar desde 15 Oct")
    assert vm.cost_label == "USD 0,0125"


def test_money() -> None:
    assert format_money(Decimal("1234.5"), "COP") == "COP 1.234,50"
    assert format_money(Decimal("0.0305"), "USD") == "USD 0,0305"


# --- 2. wizard ------------------------------------------------------------------------


def test_audience_filter_json_matches_the_backend() -> None:
    form = AudienceForm(
        brand_id="todas",
        sources=("manual", "lead_form"),
        captured_from="2026-10-01",
        captured_to="2026-10-13",
        phone_prefixes="+57, +52",
    )
    data, problem = audience_filter_json(form)
    assert problem == ""
    parsed = AudienceFilter.from_json(data)  # the backend accepts exactly this shape
    assert parsed.sources == ("lead_form", "manual")
    assert parsed.captured_before == datetime(2026, 10, 14, tzinfo=UTC)  # «hasta» inclusive
    assert parsed.phone_prefixes == ("+57", "+52")


@pytest.mark.parametrize(
    ("form", "fragment"),
    [
        (AudienceForm("todas", (), "", "", "57"), "prefijo"),
        (AudienceForm("todas", (), "2026-10-10", "2026-10-01", ""), "anterior"),
        (AudienceForm("todas", ("ads",), "", "", ""), "orígenes"),
    ],
)
def test_audience_filter_problems(form: AudienceForm, fragment: str) -> None:
    data, problem = audience_filter_json(form)
    assert data == {} and fragment in problem


def test_pacing_and_basics() -> None:
    assert validate_pacing("30") == (30, "")
    assert validate_pacing("0")[1] and validate_pacing("x")[1]
    assert pacing_hint(90, 30) == "≈ 3 min para enviar a 90 contactos."
    assert "nombre" in validate_basics("", None)
    assert "plantilla" in validate_basics("Promo", None)
    pending = dataclasses.replace(EMPTY_TEMPLATE, template_id="t", status="PENDING")
    assert "aprobada" in validate_basics("Promo", pending)


# --- 3. provider ----------------------------------------------------------------------


def _world() -> tuple[CampaignService, MemoryTemplateRepository, MemoryCampaignRepository, UUID]:
    templates = MemoryTemplateRepository()
    templates.add_number(
        tenant_id=TENANT, connection_id=CONNECTION, waba_id="waba-3", phone_row_id=uuid4()
    )
    template = templates.insert(
        TemplateRecord(
            id=uuid4(),
            tenant_id=TENANT,
            waba_id="waba-3",
            name="promo",
            language="es",
            category="marketing",
            status="APPROVED",
            components=[
                {"type": "BODY", "text": "Hola {{1}} hoy", "example": {"body_text": [["Ana"]]}}
            ],
        )
    )
    opt_ins = MemoryOptInRepository()
    for phone in ("+573001112233", "+573004445566", "+525511112222"):
        opt_ins.save(
            OptInRecord(
                id=uuid4(),
                tenant_id=TENANT,
                phone_e164=phone,
                source="manual",
                consent_text="Acepto recibir mensajes de WhatsApp de Bianki",
                captured_at=NOW - timedelta(days=2),
            )
        )
    campaigns = MemoryCampaignRepository()
    service = CampaignService(campaigns, templates, opt_ins, clock=lambda: NOW)
    return service, templates, campaigns, template.id


def test_wizard_templates_and_count() -> None:
    service, templates, _campaigns, _tid = _world()
    [option] = wizard_templates(TENANT, CONNECTION, templates=templates)
    assert option.vm.sendable and option.category == "marketing"
    assert count_audience(TENANT, {}, service=service) == 3
    assert count_audience(TENANT, {"phone_prefixes": ["+52"]}, service=service) == 1


def test_draft_estimate_launch_detail_cancel() -> None:
    service, templates, campaigns, template_id = _world()
    campaign_id = create_draft(
        TENANT,
        CONNECTION,
        email="ops@bianki.co",
        name="Promo octubre",
        template_id=template_id,
        send_components=[{"type": "body", "parameters": [{"type": "text", "text": "Ana"}]}],
        audience={"phone_prefixes": ["+57"]},
        max_per_minute=30,
        service=service,
        user_lookup=lambda _tenant, _email: USER,
    )
    est = estimate(TENANT, campaign_id, service=service)
    assert est.recipients == "2" and est.placeholder and est.rate_card_status
    assert est.cost_label == "USD 0,0250"

    detail = campaign_detail(TENANT, campaign_id, service=service, templates=templates)
    assert detail.detail.can_launch and detail.estimate is not None
    assert detail.detail.row.template_label == "promo · es"

    report = launch(
        TENANT, campaign_id, email="ops@bianki.co", service=service, user_lookup=lambda *_: USER
    )
    assert (report.audience, report.enqueued) == (2, 2)
    again = launch(
        TENANT, campaign_id, email="ops@bianki.co", service=service, user_lookup=lambda *_: USER
    )
    assert again.enqueued == 0  # resumes, never resends
    assert len(campaigns.outbox) == 2

    # Meta refuses one send for the payment method, the other for the per-user limit.
    first, second = campaigns.list_sends(tenant_id=TENANT, campaign_id=campaign_id)
    campaigns.settle_outbox(first.outbox_id, status="failed", error_code="131042")
    campaigns.settle_outbox(second.outbox_id, status="failed", error_code="131049")
    detail = campaign_detail(TENANT, campaign_id, service=service, templates=templates)
    assert detail.detail.payment_failed
    assert "131049" in detail.detail.retry_after_24h
    assert {s.status_label for s in detail.sends} == {"Falló", "Omitido"}
    assert detail.detail.row.status_label == "Terminada"  # finalize_if_complete ran
    assert not detail.detail.can_cancel

    rows = campaign_rows(TENANT, CONNECTION, service=service, templates=templates)
    assert [r.name for r in rows] == ["Promo octubre"]


def test_cancel_a_draft() -> None:
    service, templates, _campaigns, template_id = _world()
    campaign_id = create_draft(
        TENANT,
        CONNECTION,
        email="ops@bianki.co",
        name="Borrador",
        template_id=template_id,
        send_components=[],
        audience={},
        max_per_minute=10,
        service=service,
        user_lookup=lambda *_: USER,
    )
    assert cancel(TENANT, campaign_id, service=service) == 0
    detail = campaign_detail(TENANT, campaign_id, service=service, templates=templates)
    assert detail.detail.row.status_label == "Cancelada" and detail.estimate is None


def test_unknown_user_cannot_create() -> None:
    service, _templates, _campaigns, template_id = _world()
    with pytest.raises(UnknownUser):
        create_draft(
            TENANT,
            CONNECTION,
            email="nobody@x.co",
            name="X",
            template_id=template_id,
            send_components=[],
            audience={},
            max_per_minute=10,
            service=service,
            user_lookup=lambda *_: None,
        )


def test_tab_renders() -> None:
    component = whatsapp_tab_campaigns.campaigns_tab()
    assert isinstance(component, rx.Component)
    rendered = str(component.render())
    for text in ("Nueva campa", "Lanzar", "Cancelar campa", "Mensajes por minuto"):
        assert text in rendered, text
