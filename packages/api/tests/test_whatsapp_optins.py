"""WA-19 — opt-ins: the monotonic record rule, lead import, STOP detection and the
inbound handler's revocation hook. Fully offline (memory repositories)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.webhooks.repository import ClaimedEvent
from qualify_api.whatsapp.handler import PublishedMenu, whatsapp_messages_handler
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
from qualify_api.whatsapp.optins import (
    AudienceFilter,
    LeadConsent,
    MemoryOptInRepository,
    OptInService,
    RecordOutcome,
    is_stop_keyword,
    phone_from_wa_id,
)
from qualify_api.whatsapp.repository import MemoryWhatsAppInboxRepository
from qualify_api.whatsapp.resolve import PhoneResolution, PhoneResolutionOutcome

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
TENANT = UUID("a0000000-0000-4000-8000-0000000019aa")
OTHER = UUID("a0000000-0000-4000-8000-0000000019bb")
CONNECTION = uuid4()
PHONE = "+573001234567"
CONSENT = "Acepto recibir mensajes de Bianki por WhatsApp."


@pytest.fixture
def repo() -> MemoryOptInRepository:
    return MemoryOptInRepository()


@pytest.fixture
def service(repo: MemoryOptInRepository) -> OptInService:
    return OptInService(repo, clock=lambda: NOW)


def _record(service: OptInService, **overrides: Any):
    kwargs: dict[str, Any] = dict(
        tenant_id=TENANT, phone=PHONE, source="manual", consent_text=CONSENT
    )
    return service.record(**{**kwargs, **overrides})


# --- the monotonic rule ----------------------------------------------------------------


def test_record_creates_then_keeps_the_first_consent(service) -> None:
    first = _record(service, proof={"by": "operator"})
    assert first.outcome is RecordOutcome.CREATED
    again = _record(service, source="import", consent_text="otro texto")
    assert again.outcome is RecordOutcome.UNCHANGED
    assert (again.record.source, again.record.consent_text) == ("manual", CONSENT)
    assert service.is_opted_in(tenant_id=TENANT, phone="+57 300 123 4567")


def test_revoke_then_newer_consent_reopts_but_older_is_suppressed(service) -> None:
    _record(service, captured_at=NOW - timedelta(days=10))
    assert service.revoke(tenant_id=TENANT, phone=PHONE, at=NOW - timedelta(days=5))
    assert not service.is_opted_in(tenant_id=TENANT, phone=PHONE)
    assert not service.revoke(tenant_id=TENANT, phone=PHONE)  # nothing active to revoke

    stale = _record(service, source="lead_form", captured_at=NOW - timedelta(days=7))
    assert stale.outcome is RecordOutcome.SUPPRESSED
    assert not service.is_opted_in(tenant_id=TENANT, phone=PHONE)

    fresh = _record(service, source="menu", captured_at=NOW)
    assert fresh.outcome is RecordOutcome.RECONSENTED
    assert (fresh.record.source, fresh.record.revoked_at) == ("menu", None)
    assert service.is_opted_in(tenant_id=TENANT, phone=PHONE)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"phone": "3001234567"}, "E.164"),
        ({"source": "rumor"}, "source"),
        ({"consent_text": "   "}, "consent_text"),
    ],
)
def test_record_validates(service, overrides, match) -> None:
    with pytest.raises(ValueError, match=match):
        _record(service, **overrides)


def test_opt_ins_are_per_tenant(service) -> None:
    _record(service)
    assert not service.is_opted_in(tenant_id=OTHER, phone=PHONE)
    assert not service.is_opted_in(tenant_id=TENANT, phone="not a phone")


def test_list_active_with_an_audience_filter(service) -> None:
    brand = uuid4()
    _record(service, phone="+573000000001", source="lead_form", brand_id=brand)
    _record(service, phone="+573000000002", source="menu")
    _record(service, phone="+5215500000003", source="menu")
    _record(service, phone="+573000000004", source="menu")
    service.revoke(tenant_id=TENANT, phone="+573000000004")

    def phones(audience: AudienceFilter | None) -> list[str]:
        return [r.phone_e164 for r in service.list_active(tenant_id=TENANT, audience=audience)]

    assert len(phones(None)) == 3
    assert phones(AudienceFilter(sources=("menu",), phone_prefixes=("+57",))) == ["+573000000002"]
    assert phones(AudienceFilter(brand_id=brand)) == ["+573000000001"]


def test_audience_filter_round_trips_and_rejects_garbage() -> None:
    audience = AudienceFilter(
        brand_id=uuid4(),
        sources=("lead_form",),
        captured_after=NOW - timedelta(days=30),
        phone_prefixes=("+57",),
    )
    assert AudienceFilter.from_json(audience.to_json()) == audience
    assert AudienceFilter.from_json(None) == AudienceFilter()
    with pytest.raises(ValueError):
        AudienceFilter.from_json({"city": "Bogotá"})
    with pytest.raises(ValueError):
        AudienceFilter(sources=("rumor",))
    with pytest.raises(ValueError):
        AudienceFilter(phone_prefixes=("57",))


# --- import from leads -------------------------------------------------------------------


def test_import_from_leads_is_idempotent_and_honours_revocations(service, repo) -> None:
    def lead(phone: str, *, days_ago: int, text: str | None = CONSENT) -> LeadConsent:
        return LeadConsent(
            lead_id=uuid4(),
            phone_e164=phone,
            consent_at=NOW - timedelta(days=days_ago),
            consent_policy_version="v1",
            form_consent_text=text,
            form_policy_version="v2",
        )

    _record(service, phone="+573000000009", captured_at=NOW - timedelta(days=20))
    service.revoke(tenant_id=TENANT, phone="+573000000009", at=NOW - timedelta(days=2))
    repo.leads[TENANT] = [
        lead("+573000000001", days_ago=3),
        lead("+573000000009", days_ago=5),  # consented before the STOP → suppressed
        lead("+573000000002", days_ago=1, text=None),  # no form text → skipped
        lead("12345", days_ago=1),  # not E.164 → skipped
    ]
    report = service.import_from_leads(tenant_id=TENANT)
    assert (report.leads, report.created, report.suppressed, report.skipped) == (4, 1, 1, 2)
    row = service.get(tenant_id=TENANT, phone="+573000000001")
    assert row is not None and row.source == "lead_form"
    assert row.captured_at == NOW - timedelta(days=3)
    assert row.proof is not None and row.proof["text_matches_lead_policy"] is False

    again = service.import_from_leads(tenant_id=TENANT)
    assert (again.created, again.unchanged) == (0, 1)


# --- STOP --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["STOP", "stop", " Baja ", "BAJA.", "Cancelár", "¡CANCELAR!", "stop 🙏"],
)
def test_stop_keywords(text: str) -> None:
    assert is_stop_keyword(text)


@pytest.mark.parametrize(
    "text",
    [None, "", "no quiero cancelar mi pedido", "stopp", "baja de precio?", "hola"],
)
def test_not_stop_keywords(text: str | None) -> None:
    assert not is_stop_keyword(text)


def test_phone_from_wa_id() -> None:
    assert phone_from_wa_id("573001234567") == "+573001234567"
    with pytest.raises(ValueError):
        phone_from_wa_id("123")


def _text_event(body: str, *, wamid: str = "wamid.STOP1") -> ClaimedEvent:
    return ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object="whatsapp_business_account",
        entry_id="2338576026889338",
        field="messages",
        value={
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "15550000000", "phone_number_id": "1393"},
            "contacts": [{"wa_id": "573001234567", "profile": {"name": "Ana"}}],
            "messages": [
                {
                    "id": wamid,
                    "from": "573001234567",
                    "timestamp": str(int(NOW.timestamp())),
                    "type": "text",
                    "text": {"body": body},
                }
            ],
        },
        attempts=1,
    )


def _resolver(_: str) -> PhoneResolution:
    return PhoneResolution(
        outcome=PhoneResolutionOutcome.RESOLVED,
        tenant_id=TENANT,
        connection_id=CONNECTION,
        phone_row_id=uuid4(),
    )


async def test_inbound_stop_revokes_and_skips_the_menu(service, repo) -> None:
    _record(service, captured_at=NOW - timedelta(days=1))
    inbox = MemoryWhatsAppInboxRepository()
    handle = whatsapp_messages_handler(
        resolve=_resolver,
        repo=inbox,
        menu_loader=lambda _: PublishedMenu(definition=BIANKI_DEMO_MENU),
        clock=lambda: NOW,
        opt_outs=repo,
    )
    outcome = await handle(_text_event("BAJA"))
    assert outcome.status == "processed"
    row = repo.get(tenant_id=TENANT, phone_e164=PHONE)
    assert row is not None and (row.revoked_at, row.revoke_reason) == (NOW, "stop_keyword")
    assert inbox.outbox == []  # the menu did not answer the opt-out
    assert len(inbox.messages) == 1  # the message itself is still stored

    # A normal text still reaches the menu.
    await handle(_text_event("hola", wamid="wamid.HOLA"))
    assert inbox.outbox != []


async def test_without_the_sink_stop_is_just_a_message(repo) -> None:
    inbox = MemoryWhatsAppInboxRepository()
    handle = whatsapp_messages_handler(
        resolve=_resolver,
        repo=inbox,
        menu_loader=lambda _: PublishedMenu(definition=BIANKI_DEMO_MENU),
        clock=lambda: NOW,
    )
    await handle(_text_event("STOP"))
    assert inbox.outbox != []
