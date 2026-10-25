"""The plans and their prices, versioned in code (m-24852145).

`planes-v1` (founder, 2026-10-24: D14, D15, D17, D18) says what each plan brings a month
— creations, videos, vistas previas — the team's USD alert cap (D18: an alert, never a
pause) and how many businesses a subscription on that plan includes (ADR 43 F4: 2 / 3 / 5,
ceiling 8). `precios-planes-v1` (founder, 2026-10-24, option C of
`docs/precios-planes-qualify.md`) says what the team charges for them, by hand, outside
the app (D19): the monthly price, the first month at half price, and the 90-day packs.

Both live in `data/<version>.json`, never as literals here: a new price or a new plan is a
new file and a new constant (`precios-planes-v2`), never an edit of a v1 already used to
bill. Every assignment and every line of the team's report records the version it used.

The owner never sees a price (D19). The only thing of this module the owner reads is
`owner_plan_text`, in Configuración.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA_DIR = Path(__file__).parent / "data"

#: The plans in force. A new table is a new file and a new constant, never an edit.
PLANS_VERSION = "planes-v1"
#: The prices in force.
PRICES_VERSION = "precios-planes-v1"


class UnknownPlan(KeyError):
    """A plan code the catalog does not define."""


@dataclass(frozen=True)
class Plan:
    code: str
    #: What the owner reads: «Básico», «Plus», «Pro».
    name: str
    #: Orders the plans: a higher rank is an upgrade (applies at once), a lower one a
    #: downgrade (applies from the next month).
    rank: int
    creations: int
    videos: int
    previews: int
    #: D18: the month's vendor cost that triggers ONE alert to the team. Never a pause.
    usd_alert_cap: Decimal
    #: ADR 43 F4: businesses a subscription on this plan includes.
    included_businesses: int


@dataclass(frozen=True)
class PlansCatalog:
    version: str
    default_code: str
    businesses_ceiling: int
    plans: dict[str, Plan]

    @property
    def default(self) -> Plan:
        return self.plans[self.default_code]

    def get(self, code: str) -> Plan:
        try:
            return self.plans[code]
        except KeyError:
            raise UnknownPlan(f"{self.version} has no plan {code!r}") from None

    def codes(self) -> tuple[str, ...]:
        return tuple(sorted(self.plans, key=lambda c: self.plans[c].rank))


@dataclass(frozen=True)
class PlanPrice:
    monthly: Decimal
    first_month: Decimal


@dataclass(frozen=True)
class Pack:
    code: str
    creations: int
    videos: int
    previews: int
    price: Decimal


@dataclass(frozen=True)
class PriceList:
    version: str
    plans_version: str
    currency: str
    plans: dict[str, PlanPrice]
    packs: dict[str, Pack]

    def plan(self, code: str) -> PlanPrice:
        try:
            return self.plans[code]
        except KeyError:
            raise UnknownPlan(f"{self.version} has no price for plan {code!r}") from None

    def pack(self, code: str) -> Pack:
        try:
            return self.packs[code]
        except KeyError:
            raise KeyError(f"{self.version} has no pack {code!r}") from None


def _read(version: str) -> dict[str, Any]:
    path = _DATA_DIR / f"{version}.json"
    if not path.is_file():
        raise KeyError(f"unknown catalog {version!r}: no data file at {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("version") != version:
        raise ValueError(f"{path.name} declares {raw.get('version')!r}, expected {version!r}")
    return raw


@lru_cache(maxsize=4)
def load_plans(version: str = PLANS_VERSION) -> PlansCatalog:
    raw = _read(version)
    plans = {
        code: Plan(
            code=code,
            name=str(row["name"]),
            rank=int(row["rank"]),
            creations=int(row["creations"]),
            videos=int(row["videos"]),
            previews=int(row["previews"]),
            usd_alert_cap=Decimal(str(row["usd_alert_cap"])),
            included_businesses=int(row["included_businesses"]),
        )
        for code, row in raw["plans"].items()
    }
    default = str(raw["default_plan"])
    if default not in plans:
        raise ValueError(f"{version}: default plan {default!r} is not defined")
    if len({p.rank for p in plans.values()}) != len(plans):
        raise ValueError(f"{version}: two plans share a rank")
    return PlansCatalog(
        version=version,
        default_code=default,
        businesses_ceiling=int(raw["businesses_ceiling"]),
        plans=plans,
    )


@lru_cache(maxsize=4)
def load_prices(version: str = PRICES_VERSION) -> PriceList:
    raw = _read(version)
    prices = PriceList(
        version=version,
        plans_version=str(raw["plans_version"]),
        currency=str(raw["currency"]),
        plans={
            code: PlanPrice(
                monthly=Decimal(str(row["monthly"])), first_month=Decimal(str(row["first_month"]))
            )
            for code, row in raw["plans"].items()
        },
        packs={
            code: Pack(
                code=code,
                creations=int(row["creations"]),
                videos=int(row["videos"]),
                previews=int(row["previews"]),
                price=Decimal(str(row["price"])),
            )
            for code, row in raw["packs"].items()
        },
    )
    missing = set(load_plans(prices.plans_version).plans) - set(prices.plans)
    if missing:
        raise ValueError(f"{version} prices no plan {sorted(missing)}")
    return prices


#: D12: a pack lasts 90 days from the moment it is granted.
PACK_DAYS = 90

#: The fixed packs by the name the team and the founder use (D23). A pack is chosen by
#: this name (or its code); there are no free quantities.
PACK_NAMES: dict[str, str] = {
    "videos_2": "+2 videos",
    "creations_20": "+20 creaciones",
    "previews_10": "+10 vistas previas",
}


class UnknownPack(ValueError):
    """Not one of the fixed packs: a free quantity or a name that does not exist."""


def _fold(name: str) -> str:
    return " ".join(name.lower().split())


def pack_by_name(name: str, prices: PriceList | None = None) -> Pack:
    """The fixed pack «+2 videos» / «+20 creaciones» / «+10 vistas previas» (or its code),
    with the units and price of `prices`; anything else raises `UnknownPack`."""
    table = prices or load_prices()
    wanted = _fold(name)
    for code, label in PACK_NAMES.items():
        if wanted in (_fold(label), code) and code in table.packs:
            return table.pack(code)
    names = ", ".join(f"«{label}»" for label in PACK_NAMES.values())
    raise UnknownPack(f"{name!r} is not a pack; the packs are {names}")


def pack_name(code: str) -> str:
    return PACK_NAMES.get(code, code)


def _units(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def owner_plan_text(plan: Plan) -> str:
    """What the owner reads in Configuración, and nowhere else (founder, 2026-10-24):
    «Tu plan: Básico · 30 creaciones, 4 videos y 20 vistas previas al mes». No money."""
    creations = _units(plan.creations, "creación", "creaciones")
    videos = _units(plan.videos, "video", "videos")
    previews = _units(plan.previews, "vista previa", "vistas previas")
    return f"Tu plan: {plan.name} · {creations}, {videos} y {previews} al mes"


__all__ = [
    "PACK_DAYS",
    "PACK_NAMES",
    "PLANS_VERSION",
    "PRICES_VERSION",
    "Pack",
    "Plan",
    "PlanPrice",
    "PlansCatalog",
    "PriceList",
    "UnknownPack",
    "UnknownPlan",
    "load_plans",
    "load_prices",
    "owner_plan_text",
    "pack_by_name",
    "pack_name",
]
