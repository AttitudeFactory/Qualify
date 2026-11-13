"""Saved piece links and website buttons preload; chat buttons never become LEARN_MORE."""

from __future__ import annotations

from dataclasses import replace

import pytest
from packages.api.tests.test_live_promotion_wizard import live as shared_live

from qualify_api.ads.wizard import (
    WizardUnavailable,
    _saved_ad_destination,
    confirm_promotion,
    prepare_promotion_preview,
)

live = shared_live


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"hook": "", "caption": "Anterior"},
        {"ads_cta_type": "Más información"},
        {"ads_cta_type": "unrecognized historical free text", "caption": "old" * 10000},
        {"ads_cta_type": "LEARN_MORE", "ads_destination_url": ""},
        {"ads_cta_type": "LEARN_MORE", "ads_destination_url": None, "hook": None},
    ],
)
def test_legacy_missing_ad_fields_does_not_invent_link_or_brand_default(
    payload: dict | None,
) -> None:
    assert _saved_ad_destination(payload) == ("", "LEARN_MORE", "")


def test_saved_https_destination_preloads_exact_value_without_organic_mutation() -> None:
    payload = {
        "hook": "Hola",
        "caption": "Texto",
        "cta": "Pide por WhatsApp",
        "ads_cta_type": "LEARN_MORE",
        "ads_destination_url": "https://example.org/a?x=1",
    }
    before = dict(payload)
    assert _saved_ad_destination(payload) == ("https://example.org/a?x=1", "LEARN_MORE", "")
    assert payload == before


@pytest.mark.parametrize("cta", ["SHOP_NOW", "GET_QUOTE", "ORDER_NOW", "BOOK_TRAVEL"])
def test_saved_website_button_is_carried_to_the_promotion(cta: str) -> None:
    assert _saved_ad_destination(
        {"ads_cta_type": cta, "ads_destination_url": "https://example.org"}
    ) == ("https://example.org", cta, "")


@pytest.mark.parametrize("cta", ["WHATSAPP_MESSAGE", "MESSAGE_PAGE", "CALL_NOW", "not-a-button"])
def test_unsupported_saved_ad_button_blocks_instead_of_silently_substituting(cta: str) -> None:
    url, _, reason = _saved_ad_destination(
        {
            "hook": "Hola",
            "caption": "Texto",
            "ads_cta_type": cta,
            "ads_destination_url": "https://example.org",
        }
    )
    assert reason and "botón" in reason
    if cta != "not-a-button":
        assert url == "https://example.org"


def test_invalid_saved_url_requires_explicit_piece_correction() -> None:
    url, _, reason = _saved_ad_destination(
        {
            "hook": "Hola",
            "caption": "Texto",
            "ads_cta_type": "LEARN_MORE",
            "ads_destination_url": "http://example.org",
        }
    )
    assert not url and "guarda" in reason


@pytest.mark.parametrize("button", ["WhatsApp", "Enviar mensaje"])
def test_recognized_legacy_chat_button_is_still_explicitly_unsupported(button: str) -> None:
    url, _, reason = _saved_ad_destination({"ads_cta_type": button})
    assert not url and "chat" in reason


def test_recognized_legacy_website_button_is_carried() -> None:
    assert _saved_ad_destination({"ads_cta_type": "Comprar ahora"}) == ("", "SHOP_NOW", "")


def test_new_destination_validation_does_not_parse_unrelated_historical_copy_fields() -> None:
    assert _saved_ad_destination(
        {
            "ads_cta_type": "LEARN_MORE",
            "ads_destination_url": "https://example.org/declared",
            "hook": None,
            "ads_headline": "old" * 1000,
        }
    ) == ("https://example.org/declared", "LEARN_MORE", "")


@pytest.mark.asyncio
async def test_supported_piece_url_change_after_preview_requires_new_review(live):
    from qualify_api.ads.promotions import fingerprint

    live["sources"][0] = replace(
        live["sources"][0],
        default_link_url="https://example.org/first",
        ad_destination_fingerprint="first",
    )
    preview = await prepare_promotion_preview(**live["args"])
    stored = live["repo"].get(live["args"]["tenant_id"], preview.promotion_id)
    original_hash = fingerprint(stored.request)
    live["sources"][0] = replace(
        live["sources"][0],
        default_link_url="https://example.org/second",
        ad_destination_fingerprint="second",
    )
    with pytest.raises(WizardUnavailable):
        await confirm_promotion(
            tenant_id=live["args"]["tenant_id"],
            promotion_id=preview.promotion_id,
            review_id=preview.review_id,
            approved_by=live["args"]["approved_by"],
            confirm_charge=True,
        )
    assert (
        fingerprint(live["repo"].get(live["args"]["tenant_id"], preview.promotion_id).request)
        == original_hash
    )
    assert not any(params.get("status") == "ACTIVE" for _, _, params in live["remote"].calls)


@pytest.mark.asyncio
async def test_unsupported_button_appearing_during_meta_await_blocks_all_creation(live):
    def changed(method, path, params):
        if method == "GET" and path == "act_12":
            live["sources"][0] = replace(
                live["sources"][0],
                unavailable_reason="Este recorrido solo admite «Más información».",
            )

    live["remote"].before_request = changed
    with pytest.raises(WizardUnavailable, match="Más información"):
        await prepare_promotion_preview(**live["args"])
    assert not live["remote"].objects


@pytest.mark.asyncio
async def test_legacy_source_without_destination_keeps_original_preview_receipt(live):
    import json
    from types import SimpleNamespace

    from qualify_api.ads.enhancements import preview_receipt

    preview = await prepare_promotion_preview(**live["args"])
    saved = live["reviews"].get(live["args"]["tenant_id"], preview.review_id)
    promotion = live["repo"].get(live["args"]["tenant_id"], preview.promotion_id)
    source = live["sources"][0]
    before_field = SimpleNamespace(
        **{key: value for key, value in vars(source).items() if key != "ad_destination_fingerprint"}
    )
    observed = saved.checks_snapshot["enhancements_preview"]["observed_at"]
    from datetime import datetime

    args = (
        promotion,
        source,
        live["args"]["approved_by"],
        saved.preview_hash,
        saved.expires_at,
        datetime.fromisoformat(observed),
    )
    original = preview_receipt(args[0], before_field, *args[2:])
    current = preview_receipt(*args)
    assert "ad_destination_fingerprint" not in current
    assert json.dumps(original, separators=(",", ":")) == json.dumps(current, separators=(",", ":"))
