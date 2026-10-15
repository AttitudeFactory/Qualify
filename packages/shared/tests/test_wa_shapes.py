"""The WhatsApp webhook contract parses the live capture and the synthetic inbound
fixture, and its summaries never carry text (WA-03).

Fully offline: two JSON files, no network, no Postgres.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from qualify_shared.social.wa_shapes import (
    FIELD_POLICIES,
    FIELD_TEMPLATE_QUALITY,
    FIELD_TEMPLATE_STATUS,
    SHAPE_VERSION,
    WATemplateQualityUpdate,
    WATemplateStatusUpdate,
    parse_whatsapp_notification,
    summarize_notification,
)

FIXTURES = Path(__file__).parent / "fixtures"
LIVE_STATUS_READ = FIXTURES / "whatsapp_status_read_live_2026-10-14.json"
SYNTHETIC_INBOUND = FIXTURES / "whatsapp_inbound_synthetic.json"
TEMPLATE_APPROVED = FIXTURES / "whatsapp_template_status_approved_doc.json"
TEMPLATE_REJECTED = FIXTURES / "whatsapp_template_status_rejected_doc.json"
TEMPLATE_QUALITY = FIXTURES / "whatsapp_template_quality_doc.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_live_status_payload_parses_and_exposes_the_verified_fields() -> None:
    notification = parse_whatsapp_notification(_load(LIVE_STATUS_READ))

    assert notification.object == "whatsapp_business_account"
    (entry,) = notification.entry
    assert entry.id == "2338576026889338"
    (change,) = entry.changes
    assert change.field == "messages"
    value = change.messages_value()
    assert value is not None
    assert value.metadata.phone_number_id == "1393787420477981"
    assert value.metadata.display_phone_number == "15556336018"
    assert value.messages == []
    (status,) = value.statuses
    assert status.status == "read"
    assert status.id.startswith("wamid.")
    assert status.timestamp == "1791953775"  # a STRING of epoch seconds, as Meta sends it
    assert status.conversation is not None and status.conversation.origin is not None
    assert status.conversation.origin.type == "utility"
    assert status.pricing is not None
    assert (status.pricing.billable, status.pricing.pricing_model, status.pricing.category) == (
        True,
        "PMP",
        "utility",
    )


def test_live_status_payload_summary_is_identifiers_only() -> None:
    notification = parse_whatsapp_notification(_load(LIVE_STATUS_READ))

    (summary,) = summarize_notification(notification)

    assert summary.waba_id == "2338576026889338"
    assert summary.phone_number_id == "1393787420477981"
    assert summary.statuses == ("read",)
    assert summary.status_ids == ("wamid.HBgMNTg0MjQ3MDAwMjkxFQIAERgSQzUwREJGQjc1M0Y1QzEwOTU3AA==",)
    assert summary.message_ids == () and summary.message_types == ()
    assert summary.error_codes == ()
    # No phone number of the RECIPIENT leaks into the summary — only the business's own
    # phone_number_id and the WABA id, both Qualify-owned identifiers.
    assert "584240000000" not in repr(summary)


def test_synthetic_inbound_parses_text_interactive_and_unmodelled_types() -> None:
    notification = parse_whatsapp_notification(_load(SYNTHETIC_INBOUND))

    (entry,) = notification.entry
    messages_change, other_change = entry.changes
    value = messages_change.messages_value()
    assert value is not None
    text, interactive, image = value.messages
    assert (text.type, text.from_) == ("text", "584240000000")
    assert text.text is not None and text.text.body == "Hola, quiero hacer un pedido"
    assert interactive.interactive is not None
    assert interactive.interactive.reply is not None
    assert interactive.interactive.reply.id == "menu.pedido"  # the menu edge WA-09 follows
    # An unmodelled type still parses, with its `type` intact and nothing else asserted.
    assert image.type == "image" and image.text is None and image.interactive is None
    (contact,) = value.contacts
    assert contact.profile is not None and contact.profile.name == "Cliente de prueba"

    # A non-`messages` field parses (never rejected) and has no typed view.
    assert other_change.field == "phone_number_quality_update"
    assert other_change.messages_value() is None


def test_synthetic_inbound_summary_never_carries_text_or_names() -> None:
    notification = parse_whatsapp_notification(_load(SYNTHETIC_INBOUND))

    messages_summary, other_summary = summarize_notification(notification)

    assert messages_summary.message_types == ("text", "interactive", "image")
    assert messages_summary.message_ids == (
        "wamid.SYNTHETIC_TEXT_0001",
        "wamid.SYNTHETIC_LIST_0002",
        "wamid.SYNTHETIC_IMAGE_0003",
    )
    rendered = repr(messages_summary)
    assert "Hola" not in rendered and "Cliente de prueba" not in rendered
    assert other_summary.phone_number_id is None
    assert other_summary.message_ids == () and other_summary.statuses == ()


def test_messages_change_with_a_broken_value_is_summarized_not_raised() -> None:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "2338576026889338",
                "changes": [
                    {"field": "messages", "value": {"messaging_product": "whatsapp"}},
                    {"field": "account_update", "value": {"event": "VERIFIED_ACCOUNT"}},
                ],
            }
        ],
    }
    notification = parse_whatsapp_notification(payload)

    broken, sibling = summarize_notification(notification)

    assert broken.field == "messages" and broken.phone_number_id is None
    assert sibling.field == "account_update"
    with pytest.raises(ValidationError):
        notification.entry[0].changes[0].messages_value()


@pytest.mark.parametrize(
    "payload",
    [
        {"object": "instagram", "entry": []},
        {"object": "page", "entry": [{"id": "1", "changes": []}]},
        {"entry": []},
        "not a dict",
    ],
)
def test_anything_that_is_not_a_whatsapp_notification_is_rejected(payload: object) -> None:
    with pytest.raises(ValidationError):
        parse_whatsapp_notification(payload)


def test_contract_bookkeeping() -> None:
    assert SHAPE_VERSION.startswith("wa-webhook-shapes-")
    # The inbound half stays provisional until a live capture replaces the synthetic
    # fixture; flipping this flag without replacing the fixture is the thing this
    # assertion exists to make deliberate.
    assert FIELD_POLICIES["messages"]["provisional"] is True
    assert FIELD_POLICIES["statuses"]["provisional"] is False
    # WA-18: the template halves are doc-derived until a live capture replaces them.
    assert FIELD_POLICIES[FIELD_TEMPLATE_STATUS]["provisional"] is True
    assert FIELD_POLICIES[FIELD_TEMPLATE_QUALITY]["provisional"] is True


# --- template webhooks (WA-18, doc-derived) -------------------------------------------


def _only_change(path: Path):
    notification = parse_whatsapp_notification(_load(path))
    (entry,) = notification.entry
    (change,) = entry.changes
    return entry, change


def test_template_status_approved_doc_example_parses() -> None:
    entry, change = _only_change(TEMPLATE_APPROVED)
    assert entry.id == "102290129340398"  # the WABA id: the tenant is resolved from it
    assert change.field == FIELD_TEMPLATE_STATUS
    assert change.messages_value() is None
    value = WATemplateStatusUpdate.model_validate(change.value)
    assert value.event == "APPROVED"
    # A JSON integer in the webhook becomes the same string the Graph API returns.
    assert value.message_template_id == "1689556908129832"
    assert (value.message_template_name, value.message_template_language) == (
        "order_confirmation",
        "en-US",
    )
    assert (value.reason, value.message_template_category) == ("NONE", "UTILITY")
    assert value.rejection_info is None


def test_template_status_rejected_doc_example_carries_the_rejection_info() -> None:
    _, change = _only_change(TEMPLATE_REJECTED)
    value = WATemplateStatusUpdate.model_validate(change.value)
    assert (value.event, value.reason) == ("REJECTED", "INVALID_FORMAT")
    assert value.rejection_info is not None
    assert value.rejection_info.reason is not None
    assert value.rejection_info.recommendation is not None


def test_template_quality_doc_example_parses() -> None:
    _, change = _only_change(TEMPLATE_QUALITY)
    assert change.field == FIELD_TEMPLATE_QUALITY
    value = WATemplateQualityUpdate.model_validate(change.value)
    assert (value.previous_quality_score, value.new_quality_score) == ("GREEN", "YELLOW")
    assert value.message_template_id == "806312974732579"


def test_template_status_without_its_keys_is_rejected() -> None:
    with pytest.raises(ValidationError):
        WATemplateStatusUpdate.model_validate({"event": "APPROVED"})
    with pytest.raises(ValidationError):
        WATemplateStatusUpdate.model_validate(
            {
                "event": "APPROVED",
                "message_template_id": True,
                "message_template_name": "x",
                "message_template_language": "es",
            }
        )


def test_template_changes_summarize_with_empty_tuples() -> None:
    (summary,) = summarize_notification(parse_whatsapp_notification(_load(TEMPLATE_APPROVED)))
    assert summary.field == FIELD_TEMPLATE_STATUS
    assert summary.phone_number_id is None
    assert summary.message_ids == ()
