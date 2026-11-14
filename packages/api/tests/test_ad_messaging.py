"""Documented referral subsets, exact consent and replay-safe handler integration."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qualify_api.ads.messaging import MessagingTarget, referral_ad_id
from qualify_api.ads.messaging_attribution import event_message_evidence, origin_label
from qualify_api.ads.messaging_destinations import page_phone_link
from qualify_api.ads.promotions import PromotionRequest, fingerprint
from qualify_api.conversations.repository import MemoryConversationRepository
from qualify_api.conversations.sync import ConversationSyncService
from qualify_api.conversations.webhook import instagram_messages_handler
from qualify_api.mentions.resolve import ResolutionOutcome, TenantResolution
from qualify_api.webhooks.repository import ClaimedEvent
from qualify_api.whatsapp.handler import whatsapp_messages_handler
from qualify_api.whatsapp.repository import MemoryWhatsAppInboxRepository
from qualify_api.whatsapp.resolve import PhoneResolution, PhoneResolutionOutcome


@pytest.mark.parametrize(
    "value,channel,expected",
    [
        ({"source_type": "ad", "source_id": "123"}, "whatsapp", "123"),
        ({"source_type": "post", "source_id": "123"}, "whatsapp", None),
        ({"source_type": "ad", "source_id": True}, "whatsapp", None),
        ({"source_type": "ad", "source_id": 123}, "whatsapp", None),
        ({"source_type": "ad", "source_url": "https://example.org/123"}, "whatsapp", None),
        ({"source": "ADS", "type": "OPEN_THREAD", "ad_id": "123"}, "dm", "123"),
        ({"source": "SHORTLINK", "type": "OPEN_THREAD", "ad_id": "123"}, "dm", None),
        ({"source": "ADS", "ad_id": "123"}, "dm", None),
        ({"source": "ADS", "type": "OPEN_THREAD", "ref": "123"}, "dm", None),
        (None, "dm", None),
        ({"source_type": "ad", "source_id": "123\n"}, "whatsapp", None),
    ],
)
def test_referral_subset(value, channel, expected) -> None:
    assert referral_ad_id(value, channel=channel) == expected


def _request(target: MessagingTarget | None = None) -> PromotionRequest:
    now = datetime.now(UTC)
    return (
        PromotionRequest(
            uuid4(),
            uuid4(),
            str(uuid4()),
            "123",
            "OUTCOME_TRAFFIC",
            "LEARN_MORE",
            "https://example.org",
            "lifetime",
            10000,
            "COP",
            now,
            now + timedelta(days=2),
            uuid4(),
            now,
            source_media_id="777",
        )
        if target is None
        else replace(
            _request(),
            objective="OUTCOME_ENGAGEMENT",
            cta_type=target.cta_type,
            link_url="",
            messaging_snapshot=target.snapshot(),
            creative=target.creative(source_media_id="777", instagram_user_id="42"),
            adset_options=target.adset_options(),
        )
    )


def test_destination_roundtrip_and_exact_immutable_intent() -> None:
    source, target = uuid4(), uuid4()
    destination = MessagingTarget("WHATSAPP", source, target, "77", 1, 2, "88", "584240000000")
    request = _request(destination)
    snapshot = request.snapshot()
    assert MessagingTarget.from_snapshot(snapshot["messaging_snapshot"]) == destination
    with pytest.raises(ValueError, match="differs"):
        replace(request, cta_type="INSTAGRAM_MESSAGE").snapshot()
    with pytest.raises(ValueError, match="differs"):
        replace(
            request, adset_options={**request.adset_options, "destination_type": "WEBSITE"}
        ).snapshot()
    assert fingerprint(snapshot) != fingerprint(
        replace(
            request,
            messaging_snapshot=replace(destination, target_credential_version=3).snapshot(),
        ).snapshot()
    )


def test_empty_destination_does_not_change_legacy_approval_hash() -> None:
    request = _request()
    assert "messaging_snapshot" not in request.snapshot()
    assert fingerprint(request.snapshot()) == fingerprint(
        replace(request, messaging_snapshot={}).snapshot()
    )


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"id": "7", "has_whatsapp_number": False}, False),
        ({"id": "7", "has_whatsapp_number": True, "whatsapp_number": "+58 424 0000000"}, True),
        ({"id": "7", "has_whatsapp_number": True, "whatsapp_number": "+58 414 0000000"}, False),
        ({"id": "7", "has_whatsapp_number": True}, None),
        ({"id": "7"}, None),
        ({"id": "8", "has_whatsapp_number": False}, None),
        ({"error": "permission denied"}, None),
    ],
)
def test_page_absence_is_never_inferred_from_missing_or_failed_reads(payload, expected) -> None:
    assert page_phone_link(payload, page_id="7", phone="584240000000") is expected


def _event(channel: str) -> ClaimedEvent:
    instagram = channel == "dm"
    return ClaimedEvent(
        uuid4(),
        uuid4(),
        "instagram" if instagram else "whatsapp_business_account",
        "42" if instagram else "99",
        "messages",
        {
            "sender": {"id": "customer"},
            "recipient": {"id": "42"},
            "timestamp": 1760616000000,
            "message": {
                "mid": "mid.1",
                "text": "hola",
                "referral": {
                    "source": "ADS",
                    "type": "OPEN_THREAD",
                    "ad_id": "123",
                },
            },
        }
        if instagram
        else {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": "88", "display_phone_number": "584240000000"},
            "messages": [
                {
                    "id": "mid.1",
                    "from": "customer",
                    "timestamp": "1760616000",
                    "type": "text",
                    "text": {"body": "hola"},
                    "referral": {"source_type": "ad", "source_id": "123"},
                }
            ],
        },
        1,
    )


@pytest.mark.parametrize("channel", ["dm", "whatsapp"])
def test_referral_provenance_cannot_label_another_message(channel) -> None:
    event = _event(channel)
    assert event_message_evidence(event, "mid.1", channel=channel) == ("123", "customer")
    assert event_message_evidence(event, "other.mid", channel=channel) is None
    assert (
        event_message_evidence(replace(event, field="comments"), "mid.1", channel=channel) is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["dm", "whatsapp"])
async def test_callback_retries_after_message_insert_without_duplicating_message(channel) -> None:
    tenant, connection, phone = uuid4(), uuid4(), uuid4()
    calls = []

    def attribute(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("simulated database failure after message insert")
        return True

    if channel == "dm":
        repo = MemoryConversationRepository()
        handler = instagram_messages_handler(
            resolve=lambda **kwargs: TenantResolution(
                ResolutionOutcome.RESOLVED, tenant, connection
            ),
            sync=ConversationSyncService(repository=repo),
            attribute_ad=attribute,
        )
    else:
        repo = MemoryWhatsAppInboxRepository()
        handler = whatsapp_messages_handler(
            resolve=lambda *_: PhoneResolution(
                PhoneResolutionOutcome.RESOLVED, tenant, connection, phone
            ),
            repo=repo,
            attribute_ad=attribute,
        )
    event = _event(channel)
    with pytest.raises(RuntimeError):
        await handler(event)
    assert (await handler(event)).status == "processed"
    assert len(calls) == 2
    assert calls[0]["thread_id"] == calls[1]["thread_id"]


def test_origin_is_local_published_text_bounded_plain_copy() -> None:
    assert origin_label(None) == "Vino de un anuncio de este negocio"
    assert origin_label("  Texto\npublicado  ") == "Vino de un anuncio: Texto publicado"
    assert len(origin_label("x" * 300)) == len("Vino de un anuncio: ") + 160
