"""Network-free tests for `/whatsapp` → Contactos (WA-19, QUA-218).

They pin the VM boundary (no `proof`, no credential field), the manual opt-in rules Meta
imposes (WhatsApp + the business named), the import report copy, and the provider's
writes through `OptInService` over `MemoryOptInRepository` (no database).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.whatsapp.optins import LeadConsent, MemoryOptInRepository, OptInService

from . import whatsapp_tab_contacts
from .whatsapp_contacts_provider import import_from_leads, record_manual, revoke
from .whatsapp_contacts_vm import (
    IMPORT_CONDITION,
    OptInVM,
    build_opt_in_vm,
    import_report_message,
    normalize_phone_input,
    suggested_consent,
    validate_manual_opt_in,
)

_FORBIDDEN = ("token", "credential", "cipher", "secret", "key_id", "password", "proof")
TENANT = UUID("00000000-0000-0000-0000-0000000000a2")


def test_whatsapp_contacts_vm_has_no_credential_fields() -> None:
    assert OptInVM.__dataclass_params__.frozen  # type: ignore[attr-defined]
    for f in dataclasses.fields(OptInVM):
        assert not any(bad in f.name.lower() for bad in _FORBIDDEN), f.name
        assert f.type in ("str", "bool"), f.name  # pre-formatted, no datetime


def test_opt_in_vm_states() -> None:
    captured = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    active = build_opt_in_vm(
        phone_e164="+573001234567",
        source="lead_form",
        captured_at=captured,
        revoked_at=None,
        revoke_reason=None,
        consent_text="Acepto",
        brand="Bianki",
    )
    assert (active.status_label, active.status_tone, active.revoked_detail) == ("Activo", "ok", "")
    assert active.source_label == "Formulario de clientes interesados"
    revoked = build_opt_in_vm(
        phone_e164="+573001234567",
        source="menu",
        captured_at=captured,
        revoked_at=datetime(2026, 10, 2, 8, 30, tzinfo=UTC),
        revoke_reason="stop_keyword",
        consent_text="Acepto",
        brand=None,
    )
    assert not revoked.is_active and revoked.status_tone == "neutral"
    assert revoked.revoked_detail.startswith("Escribió STOP")


def test_manual_validation_follows_meta() -> None:
    ok_text = suggested_consent("Bianki")
    assert "Bianki" in ok_text and "WhatsApp" in ok_text
    assert validate_manual_opt_in("+57 300 123 4567", ok_text, "Bianki") == ""
    assert "indicativo" in validate_manual_opt_in("3001234567", ok_text, "Bianki")
    assert "Meta exige" in validate_manual_opt_in("+573001234567", " ", "Bianki")
    assert "WhatsApp" in validate_manual_opt_in(
        "+573001234567", "Acepto recibir correos de Bianki con promociones", "Bianki"
    )
    assert "Bianki" in validate_manual_opt_in(
        "+573001234567", "Acepto recibir mensajes de WhatsApp con promociones", "Bianki"
    )
    assert normalize_phone_input("+57 (300) 123-4567") == "+573001234567"


def test_import_report_copy() -> None:
    message, tone = import_report_message(
        leads=5, created=3, unchanged=1, reconsented=0, suppressed=1, skipped=0
    )
    assert tone == "ok" and "3 nuevos" in message and "STOP" in message
    empty, empty_tone = import_report_message(
        leads=0, created=0, unchanged=0, reconsented=0, suppressed=0, skipped=0
    )
    assert empty_tone == "info" and "aún no tiene" in empty
    assert "WhatsApp" in IMPORT_CONDITION


def test_provider_records_revokes_and_imports() -> None:
    repo = MemoryOptInRepository()
    service = OptInService(repo)
    result = record_manual(TENANT, "+573001112233", suggested_consent("Bianki"), service=service)
    assert str(result.outcome) == "created"
    assert result.record.source == "manual"
    again = record_manual(TENANT, "+573001112233", suggested_consent("Bianki"), service=service)
    assert str(again.outcome) == "unchanged"
    assert revoke(TENANT, "+573001112233", service=service) is True
    assert revoke(TENANT, "+573001112233", service=service) is False

    repo.leads[TENANT] = [
        LeadConsent(
            lead_id=uuid4(),
            phone_e164="+573004445566",
            consent_at=datetime(2026, 10, 1, tzinfo=UTC),
            consent_policy_version="v1",
            form_consent_text="Acepto recibir mensajes de WhatsApp de Bianki",
            form_policy_version="v1",
        )
    ]
    report = import_from_leads(TENANT, service=service)
    assert (report.leads, report.created) == (1, 1)


def test_tab_renders() -> None:
    component = whatsapp_tab_contacts.contacts_tab()
    assert isinstance(component, rx.Component)
    rendered = str(component.render())
    assert "Importar del formulario de clientes interesados" in rendered
    assert "Agregar contacto" in rendered
