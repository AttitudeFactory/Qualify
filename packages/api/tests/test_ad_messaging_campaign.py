"""Ads that open a chat: request contract and greeting (m-24828980). Offline, no Meta."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.ads.audience import AudienceDraft, LocationOption
from qualify_api.ads.enhancements import BrandEnhancementSettings
from qualify_api.ads.messaging import MessagingTarget
from qualify_api.ads.messaging_greeting import GreetingUnavailable, MessageGreeting, clean
from qualify_api.ads.promotions import fingerprint
from qualify_api.ads.wizard import PromotionSource, WizardForm, WizardUnavailable
from qualify_api.ads.wizard_workflow import _form, _request

NOW = datetime(2030, 1, 1, tzinfo=UTC)
IDS = [UUID(int=i) for i in range(1, 9)]


def source() -> PromotionSource:
    return PromotionSource(
        *IDS[:4],
        "99",
        "88",
        "c",
        "l",
        meta_ad_account_id="12",
        currency="COP",
        linked_page_id="77",
        credential_version=1,
    )


def target(kind: str = "WHATSAPP") -> MessagingTarget:
    whatsapp = kind == "WHATSAPP"
    return MessagingTarget(
        kind,
        IDS[2],
        IDS[6] if whatsapp else IDS[2],
        "77",
        1,
        1,
        "555" if whatsapp else "",
        "573001112233" if whatsapp else "",
    )


def greeting(**changes) -> MessageGreeting:
    base = MessageGreeting(IDS[7], IDS[3], 1, "¡Hola!", ("¿Hacen domicilios?", "¿Precios?"))
    return replace(base, **changes)


def form(**changes) -> WizardForm:
    base = WizardForm(
        "",
        "Bogotá",
        NOW + timedelta(days=1),
        NOW + timedelta(days=3),
        budget_minor=150_00,
        audience=AudienceDraft(location=LocationOption("123", "Bogotá", "city", "CO")),
        enhancements=BrandEnhancementSettings(IDS[4], IDS[3]),
        messaging=target(),
        greeting=greeting(),
    )
    return replace(base, **changes)


def request(**changes):
    return _request(IDS[4], source(), form(**changes), IDS[5], "chat", NOW)


def test_page_welcome_message_is_the_documented_ice_breakers_template() -> None:
    assert json.loads(greeting().page_welcome_message()) == {
        "type": "VISUAL_EDITOR",
        "version": 2,
        "landing_screen_type": "welcome_message",
        "media_type": "text",
        "text_format": {
            "customer_action_type": "ice_breakers",
            "message": {
                "text": "¡Hola!",
                "ice_breakers": [{"title": "¿Hacen domicilios?"}, {"title": "¿Precios?"}],
            },
        },
    }


@pytest.mark.parametrize(
    "welcome,questions",
    [
        ("", ["¿Algo?"]),
        ("Hola", []),
        ("Hola", ["", "  "]),
        ("Hola", ["a", "b", "c", "d", "e"]),
        ("x" * 301, ["¿Algo?"]),
        ("Hola", ["x" * 81]),
        ("Hola", ["¿Algo?", "¿Algo?"]),
        ("Hola", [3]),
    ],
)
def test_greeting_limits_are_explained_in_spanish(welcome, questions) -> None:
    with pytest.raises(GreetingUnavailable):
        clean(welcome, questions)


def test_greeting_trims_and_skips_empty_boxes() -> None:
    assert clean("  Hola  ", [" ¿Uno? ", "", "¿Dos?"]) == ("Hola", ("¿Uno?", "¿Dos?"))


def test_whatsapp_request_carries_the_documented_fields() -> None:
    snapshot = request().snapshot()
    assert snapshot["objective"] == "OUTCOME_ENGAGEMENT"
    assert snapshot["cta_type"] == "WHATSAPP_MESSAGE" and snapshot["link_url"] == ""
    assert snapshot["adset_options"] == {
        "optimization_goal": "CONVERSATIONS",
        "billing_event": "IMPRESSIONS",
        "destination_type": "WHATSAPP",
        "promoted_object": {"page_id": "77", "whatsapp_phone_number": "573001112233"},
    }
    creative = snapshot["creative"]
    assert creative["object_id"] == "77" and creative["source_instagram_media_id"] == "88"
    assert creative["page_welcome_message"] == greeting().page_welcome_message()
    assert MessageGreeting.from_snapshot(snapshot["greeting_snapshot"]) == greeting()


def test_instagram_direct_without_greeting_has_no_welcome_or_greeting_snapshot() -> None:
    snapshot = request(messaging=target("INSTAGRAM_DIRECT"), greeting=None).snapshot()
    assert snapshot["cta_type"] == "INSTAGRAM_MESSAGE"
    assert snapshot["adset_options"]["promoted_object"] == {"page_id": "77"}
    assert "page_welcome_message" not in snapshot["creative"]
    assert "greeting_snapshot" not in snapshot


def test_greeting_is_part_of_the_approval_hash() -> None:
    base = fingerprint(request().snapshot())
    assert base != fingerprint(request(greeting=greeting(welcome_text="Buenas")).snapshot())
    assert base != fingerprint(request(greeting=greeting(version=2)).snapshot())
    assert base != fingerprint(request(greeting=None).snapshot())


def test_promotions_without_the_chat_goal_keep_their_snapshot_shape() -> None:
    website = _request(
        IDS[4],
        source(),
        form(link_url="https://example.org", messaging=None, greeting=None),
        IDS[5],
        "web",
        NOW,
    )
    snapshot = website.snapshot()
    assert "greeting_snapshot" not in snapshot and "messaging_snapshot" not in snapshot
    assert fingerprint(snapshot) == fingerprint(replace(website, greeting_snapshot={}).snapshot())


def test_approved_form_round_trips_from_the_stored_request() -> None:
    from types import SimpleNamespace

    from qualify_api.ads.promotions import Promotion

    stored = Promotion(uuid4(), request().snapshot())
    rebuilt = _form(stored, SimpleNamespace(checks_snapshot={}))
    assert rebuilt.messaging == target() and rebuilt.greeting == greeting()
    again = _request(IDS[4], source(), rebuilt, IDS[5], "chat", NOW)
    assert fingerprint(again.snapshot()) == fingerprint(stored.request)


@pytest.mark.parametrize(
    "creative_change",
    [
        {"page_welcome_message": greeting(welcome_text="Otro").page_welcome_message()},
        {"call_to_action": {"type": "WHATSAPP_MESSAGE"}},
        {"object_id": "78"},
        {"link": "https://example.org"},
    ],
)
def test_any_drift_between_creative_and_approved_chat_is_refused(creative_change) -> None:
    built = request()
    with pytest.raises(ValueError):
        replace(built, creative={**built.creative, **creative_change}).snapshot()


def test_greeting_or_chat_goal_never_rides_a_website_request() -> None:
    built = request()
    website = replace(
        built,
        objective="OUTCOME_TRAFFIC",
        cta_type="LEARN_MORE",
        link_url="https://example.org",
        messaging_snapshot={},
        greeting_snapshot={},
        adset_options={"optimization_goal": "LINK_CLICKS"},
        creative={
            **{k: v for k, v in built.creative.items() if k != "page_welcome_message"},
            "call_to_action": {"type": "LEARN_MORE", "value": {"link": "https://example.org"}},
        },
    )
    website.snapshot()  # The shape itself is fine without the chat parts.
    for change in (
        {"greeting_snapshot": built.greeting_snapshot},
        {"objective": "OUTCOME_ENGAGEMENT"},
        {"creative": {**website.creative, "page_welcome_message": "{}"}},
    ):
        with pytest.raises(ValueError):
            replace(website, **change).snapshot()


@pytest.mark.parametrize(
    "changes",
    [
        {"link_url": "https://example.org"},
        {"cta_type": "SHOP_NOW"},
        {"messaging": None},
        {"lead_cta": "SIGN_UP"},
    ],
)
def test_chat_form_refuses_mixed_goals_without_network(changes) -> None:
    with pytest.raises(WizardUnavailable):
        form(**changes).validate()


def test_chat_of_another_connection_or_page_is_refused_before_meta() -> None:
    from qualify_api.ads.wizard_workflow import VerifiedChecks, _guard_checks

    checks = VerifiedChecks(1, True, True, True, "123", NOW + timedelta(minutes=5))
    for changed in (
        replace(target(), source_connection_id=uuid4()),
        replace(target(), page_id="78"),
        replace(target(), source_credential_version=2),
    ):
        with pytest.raises(WizardUnavailable, match="chat"):
            _guard_checks(source(), form(messaging=changed), checks, NOW)
    with pytest.raises(WizardUnavailable, match="saludo"):
        _guard_checks(source(), form(greeting=greeting(brand_id=uuid4())), checks, NOW)
