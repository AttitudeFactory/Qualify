"""Versioned pricing table for creative vendors.

Prices live in data files (``pricing_data/<version>.json``), never as literals in code:
aggregator and model prices move by multiples, so a hardcoded number is a margin bug
waiting for a release. The table carries two kinds of unit because the copy layer bills
by token while the image vendors bill by piece (`per_mtok_in`/`per_mtok_out` vs
`per_piece`), and the router's budget check has to compare like with like.

Every lookup is explicit: an unknown model or unit raises ``KeyError`` naming the pricing
version — a silent 0 is a margin bug.
"""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from qualify_creative.providers import PricingTable

_DATA_DIR = Path(__file__).parent / "pricing_data"


@lru_cache(maxsize=8)
def _load_entries(version: str) -> dict[str, dict[str, Decimal]]:
    """Read and cache one pricing file. Prices are parsed from strings straight into
    ``Decimal`` — they never pass through a float."""
    path = _DATA_DIR / f"{version}.json"
    if not path.is_file():
        raise KeyError(f"unknown pricing version {version!r}: no data file at {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    declared = raw.get("version")
    if declared != version:
        raise ValueError(
            f"pricing file {path.name} declares version {declared!r}, expected {version!r}"
        )
    return {
        model_id: {unit: Decimal(price) for unit, price in units.items()}
        for model_id, units in raw["entries"].items()
    }


class JsonPricingTable:
    """``PricingTable`` implementation backed by a versioned JSON data file.

    The file is read once per version (module-level cache), so constructing the table in
    a request path is cheap. ``version`` is part of the contract: cost rows written to
    ``creative_usage_events`` must be reproducible against the exact price sheet that
    produced them.
    """

    def __init__(self, version: str = "v1") -> None:
        self.version = version
        self._entries = _load_entries(version)

    def unit_price(self, *, model_id: str, unit: str) -> Decimal:
        """Price for one unit of ``unit`` on ``model_id``.

        Raises ``KeyError`` naming the pricing version when either the model or the unit
        is unknown — never returns a default. A model priced per piece has no token
        rates, and pretending it does (or quietly answering 0) would corrupt the
        router's budget math.
        """
        try:
            units = self._entries[model_id]
        except KeyError:
            raise KeyError(
                f"pricing table {self.version!r} has no entry for model {model_id!r}"
            ) from None
        try:
            return units[unit]
        except KeyError:
            raise KeyError(
                f"pricing table {self.version!r} has no unit {unit!r} for model {model_id!r} "
                f"(known units: {sorted(units)})"
            ) from None


SEEDREAM_PRO_MODEL = "dola-seedream-5-0-pro-260628"


def seedream_image_cost(
    pricing: PricingTable,
    *,
    model_id: str,
    size: str,
    references: int,
    pieces: int = 1,
) -> Decimal:
    """Price a successful Seedream request using its sent size and billable inputs."""
    if references < 0 or pieces < 0:
        raise ValueError("references and pieces cannot be negative")
    if model_id == SEEDREAM_PRO_MODEL and references > 10:
        raise ValueError("Seedream 5.0 pro takes at most 10 reference images")
    if model_id == SEEDREAM_PRO_MODEL:
        level = size.strip().upper()
        if level in {"1K", "1.5K"}:
            tier = "1k"
        elif level == "2K":
            tier = "2k"
        else:
            width, sep, height = level.lower().partition("x")
            if not sep or not width.isdigit() or not height.isdigit():
                raise ValueError(f"invalid Seedream 5.0 pro size {size!r}")
            pixels = int(width) * int(height)
            if not 921_600 <= pixels <= 4_624_220:
                raise ValueError(f"Seedream 5.0 pro size {size!r} is outside its pixel range")
            # Official localized price sheets disagree (2.36 vs 2.61 MP).
            # Use the lower cutoff so a quote cannot underreserve.
            tier = "1k" if pixels <= 2_360_000 else "2k"
        image_price = pricing.unit_price(model_id=model_id, unit=f"per_image_{tier}")
    else:
        image_price = pricing.unit_price(model_id=model_id, unit="per_piece")
    if pieces == 0:
        return Decimal(0)
    extras = max(references - 1, 0)
    reference_price = (
        pricing.unit_price(model_id=model_id, unit="per_extra_reference_image") * extras
        if extras and model_id == SEEDREAM_PRO_MODEL
        else Decimal(0)
    )
    return image_price * pieces + reference_price
