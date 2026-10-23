"""Network-free tests for `/whatsapp` → Campañas (WA-20, QUA-219).

They pin:
1. The VM boundary (frozen, no credential field, no wamid/payload) and the copy Meta's
   rules require: the rate-card placeholder notice, `131049` → the per-person limit,
   `131042` → the payment method — in words, never with the Meta code (m-24842996).
2. The wizard's pure steps (m-24842996: Mensaje → A quién → Revisar): audience filter →
   `AudienceFilter` JSON, the pace choice and its explanation, basics.
3. The provider over the Memory repositories: draft → estimate (placeholder) → launch
   (paced outbox rows, no resend) → detail → cancel; an unknown user cannot create.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import re
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
from .whatsapp_campaigns_state import draft_key
from .whatsapp_campaigns_vm import (
    EMPTY_TEMPLATE,
    PACE_OPTIONS,
    PAYMENT_FAILED,
    PER_USER_LIMIT_NOTICE,
    RATE_CARD_NOTICE,
    SCOPE_ALL,
    SCOPE_SINCE,
    SEE_REPLIES,
    STEPS,
    AudienceForm,
    CampaignDetailVM,
    CampaignRowVM,
    EstimateVM,
    OptionVM,
    SendVM,
    VariableFieldVM,
    audience_filter_json,
    audience_form_for,
    build_campaign_row,
    build_send_vm,
    campaign_name,
    default_campaign_name,
    everyone_label,
    format_money,
    pace_explanation,
    pace_value,
    retry_after_label,
    send_error_note,
    sending_time,
    validate_basics,
    validate_pacing,
    validate_scope,
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


def test_meta_codes_are_explained_without_the_code() -> None:
    """m-24842996: no error code on screen — the meaning only."""
    assert "muchas promociones" in send_error_note("131049")
    assert "método de pago" in send_error_note("131042")
    assert send_error_note("999999") == "WhatsApp no dejó salir este mensaje"
    note = send_error_note("not_opted_in", "sin opt-in vigente al encolar")
    assert note == "No se envió: esta persona ya no acepta recibir tus mensajes"
    for text in (
        PAYMENT_FAILED,
        retry_after_label(4),
        *(send_error_note(code) for code in ("131049", "131042", "131026", "132000", "1")),
    ):
        assert "código" not in text and not re.search(r"\d{6}", text), text
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


def test_three_steps_in_the_owners_words() -> None:
    assert STEPS == ("Mensaje", "A quién", "Revisar")


def test_pace_is_a_choice_with_a_default_and_explained() -> None:
    assert validate_pacing("30") == (30, "")
    assert validate_pacing("0")[1] and validate_pacing("x")[1]
    assert [key for key, _label in PACE_OPTIONS] == ["10", "30", "60"]
    assert pace_value("") == 30 and pace_value("999") == 30 and pace_value("60") == 60
    assert sending_time(90, 30) == "unos 3 minutos"
    assert sending_time(20, 30) == "un minuto"
    assert sending_time(3600, 30) == "unas 2 horas"
    assert sending_time(0, 30) == ""
    assert pace_explanation(90, 30) == (
        "Se envían de a poco (30 por minuto) para cuidar tu número: tarda unos 3 minutos."
    )
    assert PER_USER_LIMIT_NOTICE == (
        "Si alguien ya recibió muchas promociones esta semana, WhatsApp no le entrega la tuya "
        "y no se le cobra."
    )


def test_message_step_needs_an_approved_message_but_no_name() -> None:
    assert validate_basics("", None) == "Elige uno de tus mensajes aprobados."
    approved = dataclasses.replace(EMPTY_TEMPLATE, template_id="t", status="APPROVED")
    assert validate_basics("", approved) == ""  # the name is optional now
    pending = dataclasses.replace(EMPTY_TEMPLATE, template_id="t", status="PENDING")
    assert "aprobado" in validate_basics("Promo", pending)
    day = datetime(2026, 10, 23, tzinfo=UTC).date()
    assert default_campaign_name(day) == "Promoción del 23 de octubre"
    assert campaign_name("  ", day) == "Promoción del 23 de octubre"
    assert campaign_name(" Promo ", day) == "Promo"


def test_who_receives_it_defaults_to_everyone() -> None:
    assert everyone_label(12) == "A todos tus clientes que aceptaron (12)"
    assert everyone_label(-1) == "A todos tus clientes que aceptaron recibir tus mensajes"
    everyone = audience_form_for(
        scope=SCOPE_ALL,
        since="2026-10-01",
        brand_id="todas",
        sources=(),
        until="",
        phone_prefixes="",
    )
    assert audience_filter_json(everyone) == ({}, "")  # «desde» ignored for everyone
    since = dataclasses.replace(everyone, captured_from="2026-10-01")
    since_form = audience_form_for(
        scope=SCOPE_SINCE,
        since="2026-10-01",
        brand_id="todas",
        sources=(),
        until="",
        phone_prefixes="",
    )
    assert since_form == since
    assert "captured_after" in audience_filter_json(since_form)[0]
    assert validate_scope(SCOPE_SINCE, "") == "Elige desde qué día se sumaron."
    assert validate_scope(SCOPE_ALL, "") == ""


def test_draft_key_reuses_an_unchanged_draft() -> None:
    first = draft_key("t", [{"type": "body"}], {"sources": ["manual"]}, 30, "")
    assert first == draft_key("t", [{"type": "body"}], {"sources": ["manual"]}, 30, "")
    assert first != draft_key("t", [{"type": "body"}], {"sources": ["manual"]}, 60, "")


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
    assert est.cost_label == "USD 0,025"

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
    assert "muchas promociones" in detail.detail.retry_after_24h
    assert "131049" not in detail.detail.retry_after_24h
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
    for text in (
        "Enviar una promoción",
        "Enviar ahora",
        "¿Qué mensaje envías?",
        "¿A quién se la envías?",
        "Revisa y envía",
        "Más filtros",
        "Más opciones",
        "Solo a los que se sumaron desde…",
        SEE_REPLIES,
    ):
        escaped = json.dumps(text)[1:-1]  # the render escapes non-ASCII as \\uXXXX
        assert text in rendered or escaped in rendered.replace("\\\\", "\\"), text
    # No pace number to type, no code on screen (m-24842996).
    source = inspect.getsource(whatsapp_tab_campaigns)
    assert 'type="number"' not in source
    assert "código" not in source and "131049" not in source and "131042" not in source
