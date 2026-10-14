"""WA-20 — campaigns over memory repositories: audience, idempotent launch with pacing,
the outbox mirror, receipts (incl. 131049), cancel, finalize, estimate and pricing.
Fully offline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from qualify_api.webhooks.repository import ClaimedEvent
from qualify_api.whatsapp import pricing
from qualify_api.whatsapp.campaigns import (
    ERROR_NOT_OPTED_IN,
    CampaignService,
    CampaignStateError,
    MemoryCampaignRepository,
    TemplateNotSendable,
    receipt_status,
)
from qualify_api.whatsapp.handler import whatsapp_messages_handler
from qualify_api.whatsapp.optins import AudienceFilter, MemoryOptInRepository, OptInService
from qualify_api.whatsapp.repository import MemoryWhatsAppInboxRepository
from qualify_api.whatsapp.resolve import PhoneResolution, PhoneResolutionOutcome
from qualify_api.whatsapp.templates import MemoryTemplateRepository, TemplateRecord

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
TENANT = UUID("a0000000-0000-4000-8000-0000000020aa")
USER = uuid4()
CONNECTION = uuid4()
WABA = "waba-20"
PHONES = ["+573000000001", "+573000000002", "+573000000003", "+5215500000004"]


@pytest.fixture(autouse=True)
def _no_overrides():
    pricing.clear_rate_overrides()
    yield
    pricing.clear_rate_overrides()


@pytest.fixture
def world():
    templates = MemoryTemplateRepository()
    templates.add_number(
        tenant_id=TENANT, connection_id=CONNECTION, waba_id=WABA, phone_row_id=uuid4()
    )
    template = templates.insert(
        TemplateRecord(
            id=uuid4(),
            tenant_id=TENANT,
            waba_id=WABA,
            name="promo_viernes",
            language="es",
            category="marketing",
            status="APPROVED",
        )
    )
    opt_ins = MemoryOptInRepository()
    optin_service = OptInService(opt_ins, clock=lambda: NOW - timedelta(days=1))
    for phone in PHONES:
        optin_service.record(tenant_id=TENANT, phone=phone, source="menu", consent_text="Sí")
    repo = MemoryCampaignRepository()
    service = CampaignService(repo, templates, opt_ins, clock=lambda: NOW)
    return {
        "service": service,
        "repo": repo,
        "templates": templates,
        "template": template,
        "opt_ins": optin_service,
    }


def _create(world, **overrides):
    kwargs = dict(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        template_id=world["template"].id,
        name="Viernes 2x1",
        created_by_user_id=USER,
        send_components=[{"type": "body", "parameters": [{"type": "text", "text": "Ana"}]}],
        max_per_minute=2,
    )
    return world["service"].create(**{**kwargs, **overrides})


def test_create_validates(world) -> None:
    campaign = _create(world)
    assert campaign.status == "draft"
    assert _create(world, scheduled_at=NOW + timedelta(hours=1)).status == "scheduled"
    with pytest.raises(ValueError):
        _create(world, name=" ")
    with pytest.raises(ValueError):
        _create(world, max_per_minute=0)
    with pytest.raises(TemplateNotSendable):
        _create(world, connection_id=uuid4())  # a connection with no number/WABA


def test_build_audience_uses_live_opt_ins_and_the_filter(world) -> None:
    service = world["service"]
    world["opt_ins"].revoke(tenant_id=TENANT, phone=PHONES[0])
    everyone = service.build_audience(tenant_id=TENANT, audience_filter=None)
    assert sorted(r.phone_e164 for r in everyone) == sorted(PHONES[1:])
    colombia = service.build_audience(tenant_id=TENANT, audience_filter={"phone_prefixes": ["+57"]})
    assert sorted(r.phone_e164 for r in colombia) == PHONES[1:3]


def test_launch_paces_enqueues_and_is_idempotent(world) -> None:
    service, repo = world["service"], world["repo"]
    campaign = _create(world, audience=AudienceFilter(phone_prefixes=("+57",)))
    report = service.launch(tenant_id=TENANT, campaign_id=campaign.id, user_id=USER)
    assert (report.audience, report.inserted, report.enqueued, report.skipped) == (3, 3, 3, 0)
    # max_per_minute=2 → one every 30 s, starting now.
    dues = sorted(item["next_attempt_at"] for item in repo.outbox.values())
    assert dues == [NOW, NOW + timedelta(seconds=30), NOW + timedelta(seconds=60)]
    assert (report.first_due_at, report.last_due_at) == (dues[0], dues[-1])
    payload = next(iter(repo.outbox.values()))["payload"]
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "promo_viernes"
    assert payload["template"]["components"][0]["type"] == "body"
    assert all(item["kind"] == "campaign_send" for item in repo.outbox.values())
    sends = service.sends(tenant_id=TENANT, campaign_id=campaign.id)
    assert {s.status for s in sends} == {"queued"}
    assert {s.currency for s in sends} == {"USD"}  # [RATE CARD PENDING] placeholders
    assert service.get(tenant_id=TENANT, campaign_id=campaign.id).status == "running"

    # Relaunch: nothing new, nothing re-enqueued.
    again = service.launch(tenant_id=TENANT, campaign_id=campaign.id, user_id=USER)
    assert (again.inserted, again.enqueued) == (0, 0)
    assert len(repo.outbox) == 3

    # A new opt-in joins on the next launch, and only it is enqueued.
    world["opt_ins"].record(
        tenant_id=TENANT, phone="+573000000099", source="manual", consent_text="Sí"
    )
    third = service.launch(tenant_id=TENANT, campaign_id=campaign.id, user_id=USER)
    assert (third.inserted, third.enqueued) == (1, 1)


def test_scheduled_campaign_starts_at_its_time(world) -> None:
    at = NOW + timedelta(hours=2)
    campaign = _create(world, scheduled_at=at, audience=AudienceFilter(phone_prefixes=("+52",)))
    world["service"].launch(tenant_id=TENANT, campaign_id=campaign.id, user_id=USER)
    (item,) = world["repo"].outbox.values()
    assert item["next_attempt_at"] == at


def test_a_revocation_between_audience_and_enqueue_skips_the_phone(world) -> None:
    service, repo = world["service"], world["repo"]
    campaign = _create(world)
    # Simulate the race: the send rows exist, then the person says STOP.
    repo.insert_sends(
        tenant_id=TENANT,
        campaign_id=campaign.id,
        sends=CampaignService._new_sends(
            service.build_audience(tenant_id=TENANT, audience_filter=None), world["template"]
        ),
    )
    world["opt_ins"].revoke(tenant_id=TENANT, phone=PHONES[1])
    report = service.launch(tenant_id=TENANT, campaign_id=campaign.id, user_id=USER)
    assert (report.enqueued, report.skipped) == (3, 1)
    skipped = service.sends(tenant_id=TENANT, campaign_id=campaign.id, status="skipped")
    assert [(s.phone_e164, s.error_code) for s in skipped] == [(PHONES[1], ERROR_NOT_OPTED_IN)]
    assert skipped[0].note == "sin opt-in vigente al encolar"


def test_launch_guards(world) -> None:
    service, templates = world["service"], world["templates"]
    campaign = _create(world)
    templates.apply_status(
        tenant_id=TENANT,
        waba_id=WABA,
        meta_template_id="x",
        name="promo_viernes",
        language="es",
        status="PAUSED",
        rejected_reason=None,
    )
    with pytest.raises(TemplateNotSendable):
        service.launch(tenant_id=TENANT, campaign_id=campaign.id, user_id=USER)
    service.cancel(tenant_id=TENANT, campaign_id=campaign.id)
    with pytest.raises(CampaignStateError):
        service.launch(tenant_id=TENANT, campaign_id=campaign.id, user_id=USER)
    with pytest.raises(CampaignStateError):
        service.cancel(tenant_id=TENANT, campaign_id=campaign.id)


def test_mirror_receipts_131049_and_finalize(world) -> None:
    service, repo = world["service"], world["repo"]
    campaign = _create(world)
    service.launch(tenant_id=TENANT, campaign_id=campaign.id, user_id=USER)
    sends = service.sends(tenant_id=TENANT, campaign_id=campaign.id)
    a, b, c, d = sends

    repo.settle_outbox(a.outbox_id, status="sent", wamid="wamid.A")
    repo.settle_outbox(b.outbox_id, status="sent", wamid="wamid.B")
    repo.settle_outbox(c.outbox_id, status="failed", error_code="131026")
    assert not service.finalize_if_complete(tenant_id=TENANT, campaign_id=campaign.id)
    repo.settle_outbox(d.outbox_id, status="sent", wamid="wamid.D")

    # Receipts: read before delivered never regresses; pricing kept; 131049 → skipped.
    assert repo.apply_receipt(
        tenant_id=TENANT, wamid="wamid.A", status="read", error_code=None, price_category=None
    )
    repo.apply_receipt(
        tenant_id=TENANT,
        wamid="wamid.A",
        status="delivered",
        error_code=None,
        price_category="marketing",
    )
    repo.apply_receipt(
        tenant_id=TENANT, wamid="wamid.B", status="failed", error_code="131049", price_category=None
    )
    assert not repo.apply_receipt(
        tenant_id=uuid4(), wamid="wamid.D", status="read", error_code=None, price_category=None
    )
    by_phone = {s.phone_e164: s for s in service.sends(tenant_id=TENANT, campaign_id=campaign.id)}
    assert (by_phone[a.phone_e164].status, by_phone[a.phone_e164].price_category) == (
        "read",
        "marketing",
    )
    skipped = by_phone[b.phone_e164]
    assert (skipped.status, skipped.error_code, skipped.note) == (
        "skipped",
        "131049",
        "reintentar ≥24 h",
    )
    assert skipped.retry_not_before is not None
    assert by_phone[c.phone_e164].status == "failed"

    summary = service.summary(tenant_id=TENANT, campaign_id=campaign.id)
    assert summary.counts["read"] == 1 and summary.counts["skipped"] == 1
    assert summary.retry_after_24h == 1
    assert service.finalize_if_complete(tenant_id=TENANT, campaign_id=campaign.id)
    done = service.get(tenant_id=TENANT, campaign_id=campaign.id)
    assert (done.status, done.finished_at) == ("done", NOW)


def test_cancel_withdraws_unclaimed_sends(world) -> None:
    service, repo = world["service"], world["repo"]
    campaign = _create(world)
    service.launch(tenant_id=TENANT, campaign_id=campaign.id, user_id=USER)
    first = service.sends(tenant_id=TENANT, campaign_id=campaign.id)[0]
    repo.settle_outbox(first.outbox_id, status="sent", wamid="wamid.1")
    assert service.cancel(tenant_id=TENANT, campaign_id=campaign.id) == 3
    statuses = sorted(s.status for s in service.sends(tenant_id=TENANT, campaign_id=campaign.id))
    assert statuses == ["sent", "skipped", "skipped", "skipped"]
    assert service.get(tenant_id=TENANT, campaign_id=campaign.id).status == "cancelled"


def test_estimate_uses_the_rate_card_and_flags_placeholders(world) -> None:
    campaign = _create(world)
    estimate = world["service"].estimate(tenant_id=TENANT, campaign_id=campaign.id)
    assert estimate.recipients == 4 and estimate.unpriced == 0
    assert estimate.placeholder and estimate.rate_card_status == "[RATE CARD PENDING]"
    (line,) = estimate.costs
    assert line.currency == "USD" and line.sends == 4

    pricing.set_rate_override("57", "marketing", "60.5", "COP")
    pricing.set_rate_override("+52", "marketing", "0.03", "usd")
    estimate = world["service"].estimate(tenant_id=TENANT, campaign_id=campaign.id)
    assert not estimate.placeholder
    assert {c.currency: (c.amount, c.sends) for c in estimate.costs} == {
        "COP": (Decimal("181.5"), 3),
        "USD": (Decimal("0.03"), 1),
    }


def test_pricing_lookup_and_override_validation() -> None:
    assert pricing.country_prefix_of("+573001234567") == "57"
    assert pricing.country_prefix_of("+4915112345678") is None
    assert pricing.estimate_cost("+4915112345678", "marketing") is None
    cost = pricing.estimate_cost("+573001234567", "utility")
    assert cost is not None and cost.placeholder
    for bad in (("x", "marketing", "1", "USD"), ("57", "promo", "1", "USD")):
        with pytest.raises(ValueError):
            pricing.set_rate_override(*bad)
    with pytest.raises(ValueError):
        pricing.set_rate_override("57", "marketing", "-1", "USD")
    with pytest.raises(ValueError):
        pricing.set_rate_override("57", "marketing", "1", "PESOS")


def test_receipt_status_mapping() -> None:
    assert receipt_status("failed", "131049") == "skipped"
    assert receipt_status("failed", "131026") == "failed"
    assert receipt_status("read", None) == "read"
    with pytest.raises(ValueError):
        receipt_status("warning", None)


async def test_handler_offers_receipts_to_the_campaign_sink(world) -> None:
    service, repo = world["service"], world["repo"]
    campaign = _create(world)
    service.launch(tenant_id=TENANT, campaign_id=campaign.id, user_id=USER)
    send = service.sends(tenant_id=TENANT, campaign_id=campaign.id)[0]
    repo.settle_outbox(send.outbox_id, status="sent", wamid="wamid.CAMPAIGN")

    handle = whatsapp_messages_handler(
        resolve=lambda _: PhoneResolution(
            outcome=PhoneResolutionOutcome.RESOLVED,
            tenant_id=TENANT,
            connection_id=CONNECTION,
            phone_row_id=uuid4(),
        ),
        repo=MemoryWhatsAppInboxRepository(),
        clock=lambda: NOW,
        campaign_receipts=repo,
    )
    event = ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object="whatsapp_business_account",
        entry_id=WABA,
        field="messages",
        value={
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "15550000000", "phone_number_id": "1393"},
            "statuses": [
                {
                    "id": "wamid.CAMPAIGN",
                    "status": "delivered",
                    "timestamp": str(int(NOW.timestamp())),
                    "recipient_id": send.phone_e164.lstrip("+"),
                    "pricing": {
                        "billable": True,
                        "pricing_model": "PMP",
                        "category": "marketing",
                        "type": "regular",
                    },
                }
            ],
        },
        attempts=1,
    )
    assert (await handle(event)).status == "processed"
    after = repo.sends[send.id]
    assert (after.status, after.price_category) == ("delivered", "marketing")
