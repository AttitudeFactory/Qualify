"""Versioned pricing table: exact lookups, loud failures."""

import json
from decimal import Decimal
from pathlib import Path

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


# --- v6 (m-24849234): Seedream 5.0 pro for the color/texture eval --------------------

PRO = "dola-seedream-5-0-pro-260628"


def test_v6_pins_seedream_5_pro_rows() -> None:
    v6 = JsonPricingTable("v6")
    expected = {
        "per_image_1k": Decimal("0.045"),
        "per_image_2k": Decimal("0.09"),
        "per_extra_reference_image": Decimal("0.003"),
        "per_layer_1k": Decimal("0.0225"),
        "per_layer_2k": Decimal("0.045"),
    }
    for unit, price in expected.items():
        assert v6.unit_price(model_id=PRO, unit=unit) == price
    # no flat price on purpose: the production router cannot pick pro up from v6 by accident
    with pytest.raises(KeyError, match="per_piece"):
        v6.unit_price(model_id=PRO, unit="per_piece")


def test_v6_prices_flash_and_states_free_references_of_lite() -> None:
    v6 = JsonPricingTable("v6")
    flash = "dola-seedream-5-0-flash-260915"
    assert v6.unit_price(model_id=flash, unit="per_piece") == Decimal("0.018")
    for model_id in (flash, "seedream-5-0-lite-260128", "seedream-5-0-260128"):
        assert v6.unit_price(model_id=model_id, unit="per_extra_reference_image") == Decimal(0)
    with pytest.raises(KeyError):
        v6.unit_price(model_id=flash, unit="per_layer_1k")  # not read on the sheet


def test_v6_keeps_every_v5_row_unchanged() -> None:
    data = Path(__file__).resolve().parents[1] / "src" / "qualify_creative" / "pricing_data"
    v5 = json.loads((data / "v5.json").read_text(encoding="utf-8"))["entries"]
    v6 = json.loads((data / "v6.json").read_text(encoding="utf-8"))
    assert v6["version"] == "v6"
    for model_id, units in v5.items():
        for unit, price in units.items():
            assert v6["entries"][model_id][unit] == price, (model_id, unit)
    assert PRO in v6["sources"] and "model-pricing" in v6["sources"][PRO]


def test_v5_is_not_edited_for_seedream_5_pro() -> None:
    with pytest.raises(KeyError):
        JsonPricingTable("v5").unit_price(model_id=PRO, unit="per_image_1k")
