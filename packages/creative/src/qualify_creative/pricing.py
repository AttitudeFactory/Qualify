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
