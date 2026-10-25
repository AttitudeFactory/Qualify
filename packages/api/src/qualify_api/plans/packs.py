"""The 90-day packs on the request path (m-24852129): what a brand's live packs still
bring, and which source pays a charge (D17). Pure, plus one read in the caller's session.

A pack (`creation_packs`, 0095) is one of the three fixed packs of `precios-planes-v1`
granted by the team after the payment (D19, D23). It counts from the moment it is granted
until `expires_at` = granted + 90 days (D12): on day 91 what is left of it stops
counting, whatever the month. Its units are spent only after the plan's month, the pack
that expires first first (`expires_at`, then `id`) — D17, design of principal-architect
(second review in m-24852129).

Which source paid each unit is written at charge time (`creation_allocations`) and never
recomputed: when an old charge is given back, the history does not move. A unit given
back to a pack that already expired is lost (rare, documented in
`docs/planes-suscripcion.md`).

Never imports `admin_session`: the request path reads packs, it never creates units.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from qualify_api.plans.models import CreationAllocation, CreationPack

CREATIONS = "creations"
VIDEOS = "videos"
PREVIEWS = "previews"
DIMENSIONS = (CREATIONS, VIDEOS, PREVIEWS)

SOURCE_PLAN = "plan"
SOURCE_PACK = "pack"


@dataclass(frozen=True)
class PackBalance:
    """One pack as the ledger sees it at a moment: what it adds, what was spent of it
    (net of what came back) in total and in the month being read, and whether it still
    counts (not revoked, not expired)."""

    id: UUID
    code: str
    expires_at: datetime
    live: bool
    units: Mapping[str, int]
    used: Mapping[str, int] = field(default_factory=dict)
    used_in_period: Mapping[str, int] = field(default_factory=dict)

    def left(self, dimension: str) -> int:
        if not self.live:
            return 0
        return max(self.units.get(dimension, 0) - self.used.get(dimension, 0), 0)


@dataclass(frozen=True)
class Allocation:
    """Units of one dimension of one charge, and who paid them."""

    dimension: str
    source: str
    units: int
    pack_id: UUID | None = None


class SourcesExhausted(Exception):
    """The plan and the packs together cannot pay: the caller checked the balance first,
    so reaching this means the two disagree — nothing is written."""


def pack_order(packs: Iterable[PackBalance]) -> list[PackBalance]:
    """D17: the pack that expires first is spent first; ties by id, so it is stable."""
    return sorted(packs, key=lambda p: (p.expires_at, str(p.id)))


def split(
    dimension: str, needed: int, plan_left: int | None, packs: Sequence[PackBalance]
) -> list[Allocation]:
    """Who pays `needed` units of `dimension`: the plan's month first (`plan_left`; None =
    the plan does not cap this dimension, so it pays everything), then the live packs by
    expiry. Raises `SourcesExhausted` when they cannot."""
    if needed <= 0:
        return []
    if plan_left is None:
        return [Allocation(dimension, SOURCE_PLAN, needed)]
    out: list[Allocation] = []
    take = min(needed, max(plan_left, 0))
    if take:
        out.append(Allocation(dimension, SOURCE_PLAN, take))
    rest = needed - take
    for pack in pack_order(packs):
        if rest <= 0:
            break
        take = min(rest, pack.left(dimension))
        if take:
            out.append(Allocation(dimension, SOURCE_PACK, take, pack.id))
            rest -= take
    if rest > 0:
        raise SourcesExhausted(f"{dimension}: {rest} of {needed} units have no source")
    return out


@dataclass(frozen=True)
class DimensionBalance:
    """One counter of the month, split: what the plan's month still has, what the live
    packs still have, and the nearest expiry among the packs that still have some."""

    plan_quota: int
    used: int
    plan_left: int
    extra_left: int
    extra_expires_at: datetime | None
    #: Whether any pack touches this month (live, or spent in it): the owner's total
    #: is then «what was used + what is left» instead of the plan's quota.
    has_packs: bool

    @property
    def left(self) -> int:
        return self.plan_left + self.extra_left

    @property
    def quota(self) -> int:
        """The «de N» the owner reads: the plan's quota, plus what the packs brought into
        the month (what they had left when it began and what was added in it)."""
        if not self.has_packs:
            return self.plan_quota
        return self.used + self.left


def dimension_balance(
    dimension: str, plan_quota: int, used: int, packs: Sequence[PackBalance]
) -> DimensionBalance:
    """`used` is the month's total (every source); the packs' share of it comes from
    their allocations, the rest is the plan's. A dimension the plan does not cap
    (`plan_quota <= 0`: a weights table without video quota) ignores packs."""
    if plan_quota <= 0:
        return DimensionBalance(plan_quota, used, 0, 0, None, False)
    from_packs = sum(p.used_in_period.get(dimension, 0) for p in packs)
    plan_used = max(used - from_packs, 0)
    live = [p for p in packs if p.left(dimension) > 0]
    touched = any(
        p.units.get(dimension, 0) > 0 and (p.live or p.used_in_period.get(dimension, 0) > 0)
        for p in packs
    )
    return DimensionBalance(
        plan_quota=plan_quota,
        used=used,
        plan_left=max(plan_quota - plan_used, 0),
        extra_left=sum(p.left(dimension) for p in live),
        extra_expires_at=min((p.expires_at for p in live), default=None),
        has_packs=touched,
    )


def local_day(moment: datetime | None, zone: str) -> date | None:
    """The day `moment` falls on in the business's zone (UTC when unknown)."""
    if moment is None:
        return None
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    return moment.astimezone(tz).date()


def packs_in_session(
    session: Session, tenant_id: UUID, brand_id: UUID, period: date, now: datetime
) -> list[PackBalance]:
    """The brand's packs that matter for `period` read at `now`: the live ones and any
    spent in the month (a pack that expired mid-month still explains its share of it).
    Inside the caller's transaction — the ledger's brand lock."""
    # a pack spent in the month was live in it: it expired after the month began (a
    # two-day margin covers every business zone)
    since = datetime(period.year, period.month, 1, tzinfo=UTC) - timedelta(days=2)
    rows = list(
        session.scalars(
            select(CreationPack).where(
                CreationPack.tenant_id == tenant_id,
                CreationPack.brand_id == brand_id,
                CreationPack.expires_at > since,
            )
        )
    )
    if not rows:
        return []
    net = CreationAllocation.units - CreationAllocation.reversed_units
    spent = session.execute(
        select(
            CreationAllocation.pack_id,
            CreationAllocation.dimension,
            func.coalesce(func.sum(net), 0),
            func.coalesce(
                func.sum(case((CreationAllocation.period_month == period, net), else_=0)), 0
            ),
        )
        .where(CreationAllocation.pack_id.in_([r.id for r in rows]))
        .group_by(CreationAllocation.pack_id, CreationAllocation.dimension)
    ).all()
    used: dict[UUID, dict[str, int]] = {}
    in_period: dict[UUID, dict[str, int]] = {}
    for pack_id, dimension, total, month in spent:
        used.setdefault(pack_id, {})[dimension] = int(total or 0)
        in_period.setdefault(pack_id, {})[dimension] = int(month or 0)
    return [
        PackBalance(
            id=r.id,
            code=r.pack_code,
            expires_at=r.expires_at,
            live=r.revoked_at is None and now < r.expires_at,
            units={CREATIONS: r.creations, VIDEOS: r.videos, PREVIEWS: r.previews},
            used=used.get(r.id, {}),
            used_in_period=in_period.get(r.id, {}),
        )
        for r in rows
    ]


__all__ = [
    "CREATIONS",
    "DIMENSIONS",
    "PREVIEWS",
    "SOURCE_PACK",
    "SOURCE_PLAN",
    "VIDEOS",
    "Allocation",
    "DimensionBalance",
    "PackBalance",
    "SourcesExhausted",
    "dimension_balance",
    "local_day",
    "pack_order",
    "packs_in_session",
    "split",
]
