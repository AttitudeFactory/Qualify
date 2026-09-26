"""Versioned pricing table: exact lookups, loud failures."""

from decimal import Decimal

import pytest

from qualify_creative.pricing import JsonPricingTable


def test_version_is_v1() -> None:
    assert JsonPricingTable().version == "v1"


def test_known_token_prices() -> None:
    table = JsonPricingTable()
    assert table.unit_price(model_id="claude-opus-5", unit="per_mtok_in") == Decimal("5.00")
    assert table.unit_price(model_id="claude-opus-5", unit="per_mtok_out") == Decimal("25.00")


def test_known_per_piece_prices() -> None:
    table = JsonPricingTable()
    assert table.unit_price(model_id="flux2_pro", unit="per_piece") == Decimal("0.03")
    assert table.unit_price(model_id="seedream_v4", unit="per_piece") == Decimal("0.03")
    assert table.unit_price(model_id="ideogram_v3_default", unit="per_piece") == Decimal("0.06")


def test_prices_are_decimal_not_float() -> None:
    price = JsonPricingTable().unit_price(model_id="claude-opus-5", unit="per_mtok_out")
    assert isinstance(price, Decimal)


def test_unknown_model_raises_keyerror_naming_version() -> None:
    with pytest.raises(KeyError) as excinfo:
        JsonPricingTable().unit_price(model_id="no-such-model", unit="per_piece")
    message = str(excinfo.value)
    assert "v1" in message
    assert "no-such-model" in message


def test_unknown_unit_raises_keyerror_naming_version() -> None:
    # A token-priced model has no per-piece rate; answering 0 would be a margin bug.
    with pytest.raises(KeyError) as excinfo:
        JsonPricingTable().unit_price(model_id="claude-opus-5", unit="per_piece")
    message = str(excinfo.value)
    assert "v1" in message
    assert "per_piece" in message


def test_v2_keeps_v1_prices_and_adds_per_second_video() -> None:
    v1, v2 = JsonPricingTable("v1"), JsonPricingTable("v2")
    for model_id, unit in (("claude-opus-5", "per_mtok_in"), ("flux2_pro", "per_piece")):
        assert v2.unit_price(model_id=model_id, unit=unit) == v1.unit_price(
            model_id=model_id, unit=unit
        )
    assert v2.unit_price(model_id="heygen_avatar_iv", unit="per_second_1080p") == Decimal("0.0667")


def test_unknown_version_raises_keyerror_naming_version() -> None:
    with pytest.raises(KeyError) as excinfo:
        JsonPricingTable(version="v999")
    assert "v999" in str(excinfo.value)
