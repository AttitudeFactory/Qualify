"""Advertising data is typed; URLs are declarations, not generated content."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from qualify_creative.ad_destination import (
    AD_CTA_LABELS,
    AdCTA,
    normalize_legacy_ad_cta,
    validate_ad_destination_url,
)
from qualify_creative.schemas import BrandKit, CopyPayload, ToneAxes


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("Más información", AdCTA.LEARN_MORE),
        ("Comprar ahora", AdCTA.SHOP_NOW),
        ("Solicitar cotización", AdCTA.GET_QUOTE),
        ("INSTAGRAM_MESSAGE", AdCTA.MESSAGE_PAGE),
        ("Enviar mensaje por WhatsApp", AdCTA.WHATSAPP_MESSAGE),
        ("new-unknown-button", AdCTA.LEARN_MORE),
    ],
)
def test_old_free_text_is_projected_without_changing_input(stored: str, expected: AdCTA) -> None:
    raw = {"hook": "Hoy", "caption": "Un mensaje", "ads_cta_type": stored}
    before = dict(raw)
    copy = CopyPayload.model_validate(raw)
    assert copy.ads_cta_type is expected
    assert copy.model_dump(mode="json")["ads_cta_type"] == expected.value
    assert raw == before
    assert normalize_legacy_ad_cta(stored) is expected


def test_new_inputs_and_generation_do_not_silently_accept_unknown_buttons() -> None:
    with pytest.raises(ValidationError):
        CopyPayload.model_validate(
            {"hook": "Hoy", "caption": "Un mensaje", "ads_cta_type": "invented"},
            context={"strict_ad_cta": True},
        )
    assert set(AD_CTA_LABELS) == set(AdCTA)
    assert normalize_legacy_ad_cta(None) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/catalogo?q=arepas#combo",
        "https://wa.me/573001234567",
        "https://tienda.example.com:8443/pedido",
        "https://café.example/pedir",
    ],
)
def test_destination_keeps_the_owners_exact_https_url(url: str) -> None:
    assert validate_ad_destination_url(url) == url
    assert (
        CopyPayload(hook="Hoy", caption="Hola", ads_destination_url=url).ads_destination_url == url
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://",
        "https://user:secret@example.com",
        "https://example.com:invalid",
        "https://example.com/with space",
        "https://example.com\n/",
        "https://example.com\\other",
        "javascript:alert(1)",
        "https://localhost/a",
        "https://127.0.0.1/a",
    ],
)
def test_invalid_destination_is_rejected_before_any_network(url: str) -> None:
    with pytest.raises(ValueError, match="https://"):
        validate_ad_destination_url(url)


def test_brand_default_uses_the_same_validation_and_can_be_cleared() -> None:
    kit = BrandKit(
        brand_id=uuid4(),
        positioning="Arepas",
        audience="Vecinos",
        tone_axes=ToneAxes(
            formal_casual=50, sober_enthusiastic=50, technical_plain=50, brief_elaborate=50
        ),
        ads_destination_url="https://example.com/menu",
    )
    assert kit.ads_destination_url == "https://example.com/menu"
    assert validate_ad_destination_url("") is None
    assert validate_ad_destination_url(None) is None
    with pytest.raises(ValidationError):
        BrandKit.model_validate(kit.model_dump() | {"ads_destination_url": "http://example.com"})
