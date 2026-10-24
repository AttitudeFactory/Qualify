"""«Creaciones del mes» ledger (CREAR-5, m-24848531): the month's balance, the charge
when a generation is asked for, the refund when it does not come out.

The weights are `qualify_creative.creations` (versioned data). This module only keeps the
account: one `creation_charges` row per generation (`draft_id` + `revision`, unique), the
balance = the month's quota − the weights still `charged`, and a refund that turns a row
`refunded` (never deleted — provenance). «Este mes» is the calendar month in the tenant's
zone, the one the owner lives in.

- `charge` takes a per-brand advisory lock, re-reads the month and inserts in one
  transaction, so two asks at once cannot both spend the last creations; a generation
  already charged is not charged again (idempotent by its unique key).
- `refund` is idempotent too: only a `charged` row turns.
- **Videos (founder, 2026-10-24).** Generated (Seedance) videos have their own monthly
  quota (`monthly_video_quota`, 4) apart from the 30 creations: a charge records
  `videos` next to its `weight`, and the balance says both. The same quota for every
  business; `QUALIFY_CREATIONS_QUOTA=off` stays the installation-wide emergency switch.
- `refund_final` gives back the video of a 1080p final that fails: the row stays
  `charged`, the failed video's asset joins `final_refunded_assets` (at most `videos` of
  them), `final_refunded_at` and why are recorded, and the balance stops counting it.
  Idempotent per video: the same final failing again gives nothing more, and a retried
  final that then comes out is not charged again — the failure was ours or the
  vendor's, never the owner's.
- The dollar cap of `creative_engine_config` stays as the team's safety net; the owner
  never sees money (decision 8).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from qualify_creative.creations import CreationPrice, CreationWeights, load_weights
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from qualify_api.creative.models import CreationCharge
from qualify_api.tenancy.models import Tenant

logger = logging.getLogger(__name__)

CHARGED = "charged"
REFUNDED = "refunded"


class NotEnoughCreations(Exception):
    """The month's balance cannot pay for the request — its creations, or (v2) its
    generated videos: nothing was created."""

    def __init__(
        self, *, weight: int, left: int, videos: int = 0, videos_left: int | None = None
    ) -> None:
        super().__init__(
            f"needs {weight} creations ({left} left) and {videos} videos ({videos_left} left)"
        )
        self.weight = weight
        self.left = left
        self.videos = videos
        self.videos_left = videos if videos_left is None else videos_left

    @property
    def missing(self) -> int:
        """Creations missing (0 when only videos are)."""
        return max(self.weight - self.left, 0)

    @property
    def missing_videos(self) -> int:
        return max(self.videos - self.videos_left, 0)


def not_enough_text(missing: int) -> str:
    """What the owner reads when the month cannot pay (CREAR-5): never a half creation."""
    if missing == 1:
        return "Te falta 1 creación este mes."
    return f"Te faltan {missing} creaciones este mes."


@dataclass(frozen=True)
class CreationsBalance:
    """What the owner reads: «Te quedan {left} de {quota} creaciones y {videos_left} de
    {video_quota} videos este mes»."""

    quota: int
    used: int
    weights_version: str
    #: The day the quota renews (the next month's first day, tenant's timezone); None
    #: when the ledger does not know the tenant's month.
    renews_on: date | None = None
    #: v2: the month's generated videos (0 = the table has no video quota).
    video_quota: int = 0
    videos_used: int = 0

    @property
    def left(self) -> int:
        return max(self.quota - self.used, 0)

    @property
    def videos_left(self) -> int:
        return max(self.video_quota - self.videos_used, 0)

    def can_pay(self, weight: int, videos: int = 0) -> bool:
        return weight <= self.left and videos <= self.videos_left

    def shortfall(self, price: CreationPrice) -> NotEnoughCreations | None:
        """Why the month cannot pay `price`, or None when it can."""
        if self.can_pay(price.weight, price.videos):
            return None
        return NotEnoughCreations(
            weight=price.weight, left=self.left, videos=price.videos, videos_left=self.videos_left
        )


class CreationsLedger(Protocol):
    def balance(self, *, tenant_id: UUID, brand_id: UUID) -> CreationsBalance: ...

    def charge(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        draft_id: UUID,
        revision: int,
        price: CreationPrice,
    ) -> bool:
        """Charge one generation; False when it was already charged. Raises
        `NotEnoughCreations` when the month cannot pay for it."""
        ...

    def refund(self, *, tenant_id: UUID, draft_id: UUID, revision: int, reason: str) -> bool:
        """Give back one generation's creations; False when nothing was charged."""
        ...

    def refund_final(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        revision: int,
        reason: str,
        asset_ids: Sequence[UUID],
    ) -> bool:
        """Give back the video of each failed final (`asset_ids`, one per video); False
        when there is none to give (no videos, each already given, or the whole charge
        refunded)."""
        ...


def month_start(now: datetime, zone: str) -> date:
    """The first day of `now`'s month in `zone` (UTC when the zone is unknown)."""
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    local = now.astimezone(tz)
    return date(local.year, local.month, 1)


def next_month_start(period: date) -> date:
    """The first day of the month after `period` — when the quota renews."""
    if period.month == 12:
        return date(period.year + 1, 1, 1)
    return date(period.year, period.month + 1, 1)


def _brand_lock_key(brand_id: UUID) -> int:
    """A stable signed 64-bit key for `pg_advisory_xact_lock` (one per brand)."""
    return int.from_bytes(brand_id.bytes[:8], "big", signed=True)


class PostgresCreationsLedger:
    def __init__(
        self,
        *,
        weights: CreationWeights | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._weights = weights or load_weights()
        self._clock = clock or (lambda: datetime.now(UTC))

    def _period(self, session: Session, tenant_id: UUID) -> date:
        tenant = session.get(Tenant, tenant_id)
        zone = tenant.timezone if tenant is not None and tenant.timezone else "UTC"
        return month_start(self._clock(), zone)

    @staticmethod
    def _used(session: Session, tenant_id: UUID, brand_id: UUID, period: date) -> tuple[int, int]:
        """(creations, videos) the month's `charged` rows still take — a video whose final
        failed was given back (`final_refunded_assets`) and is not counted."""
        videos = func.greatest(
            CreationCharge.videos
            - func.coalesce(func.cardinality(CreationCharge.final_refunded_assets), 0),
            0,
        )
        row = session.execute(
            select(
                func.coalesce(func.sum(CreationCharge.weight), 0),
                func.coalesce(func.sum(videos), 0),
            ).where(
                CreationCharge.tenant_id == tenant_id,
                CreationCharge.brand_id == brand_id,
                CreationCharge.period_month == period,
                CreationCharge.status == CHARGED,
            )
        ).one()
        return int(row[0] or 0), int(row[1] or 0)

    def balance(self, *, tenant_id: UUID, brand_id: UUID) -> CreationsBalance:
        with tenant_session(tenant_id) as session:
            period = self._period(session, tenant_id)
            used, videos_used = self._used(session, tenant_id, brand_id, period)
        return CreationsBalance(
            quota=self._weights.monthly_quota,
            used=used,
            weights_version=self._weights.version,
            renews_on=next_month_start(period),
            video_quota=self._weights.monthly_video_quota,
            videos_used=videos_used,
        )

    def charge(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        draft_id: UUID,
        revision: int,
        price: CreationPrice,
    ) -> bool:
        with tenant_session(tenant_id) as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": _brand_lock_key(brand_id)}
            )
            already = session.scalar(
                select(CreationCharge.id).where(
                    CreationCharge.draft_id == draft_id, CreationCharge.revision == revision
                )
            )
            if already is not None:
                return False
            period = self._period(session, tenant_id)
            used, videos_used = self._used(session, tenant_id, brand_id, period)
            balance = CreationsBalance(
                quota=self._weights.monthly_quota,
                used=used,
                weights_version=self._weights.version,
                video_quota=self._weights.monthly_video_quota,
                videos_used=videos_used,
            )
            short = balance.shortfall(price)
            if short is not None:
                raise short
            result = session.execute(
                insert(CreationCharge)
                .values(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    draft_id=draft_id,
                    revision=revision,
                    request_kind=price.request_kind,
                    weight=price.weight,
                    videos=price.videos,
                    monthly_quota=self._weights.monthly_quota,
                    monthly_video_quota=self._weights.monthly_video_quota,
                    weights_version=self._weights.version,
                    pricing_table_version=self._weights.pricing_table_version,
                    period_month=period,
                    status=CHARGED,
                )
                .on_conflict_do_nothing(constraint="uq_creation_charges_generation")
            )
            return bool(result.rowcount)

    def refund(self, *, tenant_id: UUID, draft_id: UUID, revision: int, reason: str) -> bool:
        with tenant_session(tenant_id) as session:
            return refund_in_session(session, ((draft_id, revision),), reason, self._clock()) > 0

    def refund_final(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        revision: int,
        reason: str,
        asset_ids: Sequence[UUID],
    ) -> bool:
        with tenant_session(tenant_id) as session:
            row = session.scalar(
                select(CreationCharge)
                .where(
                    CreationCharge.draft_id == draft_id,
                    CreationCharge.revision == revision,
                    CreationCharge.status == CHARGED,
                    CreationCharge.videos > 0,
                )
                .with_for_update()
            )
            if row is None:
                return False
            given = _given_back(list(row.final_refunded_assets or ()), asset_ids, row.videos)
            if given is None:
                return False
            row.final_refunded_assets = given
            row.final_refunded_at = self._clock()
            row.final_refund_reason = reason[:200]
            return True


def _given_back(already: list[UUID], asset_ids: Sequence[UUID], videos: int) -> list[UUID] | None:
    """The failed finals' assets after adding `asset_ids` — one video back per asset,
    never the same asset twice, never more than the charge's `videos`. None when nothing
    new is given."""
    given = list(already)
    for asset_id in asset_ids:
        if len(given) >= videos:
            break
        if asset_id not in given:
            given.append(asset_id)
    return None if len(given) == len(already) else given


def refund_in_session(
    session: Session,
    generations: Iterable[tuple[UUID, int]],
    reason: str,
    now: datetime | None = None,
) -> int:
    """Refund generations inside a caller's transaction (the reaper's); returns how many
    rows turned. Only a `charged` row turns, so a second refund is a no-op."""
    turned = 0
    at = now or datetime.now(UTC)
    for draft_id, revision in generations:
        row = session.scalar(
            select(CreationCharge)
            .where(
                CreationCharge.draft_id == draft_id,
                CreationCharge.revision == revision,
                CreationCharge.status == CHARGED,
            )
            .with_for_update()
        )
        if row is None:
            continue
        row.status = REFUNDED
        row.refund_reason = reason[:200]
        row.refunded_at = at
        turned += 1
    return turned


@dataclass
class _MemoryRow:
    brand_id: UUID
    price: CreationPrice
    status: str = CHARGED
    reason: str | None = None
    final_refunded_assets: list[UUID] | None = None
    final_reason: str | None = None

    @property
    def videos_given_back(self) -> int:
        return len(self.final_refunded_assets or ())

    @property
    def counted_videos(self) -> int:
        return max(self.price.videos - self.videos_given_back, 0)


class InMemoryCreationsLedger:
    """The same contract without a database — for tests and local fakes."""

    def __init__(
        self, *, weights: CreationWeights | None = None, used: int = 0, videos_used: int = 0
    ) -> None:
        self._weights = weights or load_weights()
        self._opening = used
        self._opening_videos = videos_used
        self.rows: dict[tuple[UUID, int], _MemoryRow] = {}

    def _charged(self, brand_id: UUID) -> list[_MemoryRow]:
        return [r for r in self.rows.values() if r.brand_id == brand_id and r.status == CHARGED]

    def balance(self, *, tenant_id: UUID, brand_id: UUID) -> CreationsBalance:
        rows = self._charged(brand_id)
        return CreationsBalance(
            quota=self._weights.monthly_quota,
            used=self._opening + sum(row.price.weight for row in rows),
            weights_version=self._weights.version,
            video_quota=self._weights.monthly_video_quota,
            videos_used=self._opening_videos + sum(row.counted_videos for row in rows),
        )

    def charge(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        draft_id: UUID,
        revision: int,
        price: CreationPrice,
    ) -> bool:
        if (draft_id, revision) in self.rows:
            return False
        short = self.balance(tenant_id=tenant_id, brand_id=brand_id).shortfall(price)
        if short is not None:
            raise short
        self.rows[(draft_id, revision)] = _MemoryRow(brand_id=brand_id, price=price)
        return True

    def refund(self, *, tenant_id: UUID, draft_id: UUID, revision: int, reason: str) -> bool:
        row = self.rows.get((draft_id, revision))
        if row is None or row.status != CHARGED:
            return False
        row.status = REFUNDED
        row.reason = reason
        return True

    def refund_final(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        revision: int,
        reason: str,
        asset_ids: Sequence[UUID],
    ) -> bool:
        row = self.rows.get((draft_id, revision))
        if row is None or row.status != CHARGED or row.price.videos <= 0:
            return False
        given = _given_back(list(row.final_refunded_assets or ()), asset_ids, row.price.videos)
        if given is None:
            return False
        row.final_refunded_assets = given
        row.final_reason = reason
        return True


__all__ = [
    "CHARGED",
    "REFUNDED",
    "CreationsBalance",
    "CreationsLedger",
    "InMemoryCreationsLedger",
    "NotEnoughCreations",
    "PostgresCreationsLedger",
    "month_start",
    "not_enough_text",
    "refund_in_session",
]
