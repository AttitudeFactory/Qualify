"""«Creaciones del mes» ledger (CREAR-5, m-24848531): the month's balance, the charge
when a generation is asked for, the refund when it does not come out.

The weights are `qualify_creative.creations` (versioned data). This module only keeps the
account: one `creation_charges` row per generation (`draft_id` + `revision`, unique), the
balance = the month's quota − what is still `charged`, and a refund that turns a row
`refunded` (never deleted — provenance). «Este mes» is the calendar month in the tenant's
zone, the one the owner lives in.

Three counters per month (founder, 2026-10-24), none of them money:

- **creaciones** (30): images, carousels, templates, scripts, the presenter — charged at
  creation (`weight`).
- **vistas previas** (20): each Seedance draft made — a clip, a Seedance avatar, each
  animated carousel slide, each «Pedir otra versión» of them — charged at creation
  (`previews`). Like the creations, they come back only when the generation does not
  come out (`refund`); discarding, rejecting or letting a draft expire gives nothing back.
- **videos** (4): charged when the owner APPROVES the piece and its final is ordered
  (`charge_videos`: `videos`, `videos_period_month` — the month of the approval). A
  draft discarded, rejected or expired costs no video. A 1080p final that fails gives
  its video back (`refund_final`, once per video asset); a retried final is free.

- Every charge takes a per-brand advisory lock, re-reads the month and writes in one
  transaction, so two asks at once cannot both spend the last of anything; a generation
  already charged is not charged again (idempotent by its unique key), nor are its
  videos.
- The same quota for every business; `QUALIFY_CREATIONS_QUOTA=off` stays the
  installation-wide emergency switch. The dollar cap of `creative_engine_config` stays
  the team's safety net; the owner never sees money (decision 8).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from qualify_creative.creations import (
    REQUEST_GENERATED_VIDEO,
    CreationPrice,
    CreationWeights,
    load_weights,
)
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
    """The month cannot pay for the request — its creations, its vistas previas (at
    creation) or its videos (at approval): nothing was created or approved."""

    def __init__(
        self,
        *,
        weight: int = 0,
        left: int = 0,
        videos: int = 0,
        videos_left: int | None = None,
        previews: int = 0,
        previews_left: int | None = None,
    ) -> None:
        super().__init__(
            f"needs {weight} creations ({left} left), {previews} previews "
            f"({previews_left} left), {videos} videos ({videos_left} left)"
        )
        self.weight = weight
        self.left = left
        self.videos = videos
        self.videos_left = videos if videos_left is None else videos_left
        self.previews = previews
        self.previews_left = previews if previews_left is None else previews_left

    @property
    def missing(self) -> int:
        """Creations missing (0 when only previews or videos are)."""
        return max(self.weight - self.left, 0)

    @property
    def missing_previews(self) -> int:
        return max(self.previews - self.previews_left, 0)

    @property
    def missing_videos(self) -> int:
        return max(self.videos - self.videos_left, 0)


@dataclass(frozen=True)
class MonthlyQuota:
    """What one brand's month brings: creations, videos and vistas previas."""

    creations: int
    videos: int
    previews: int


def quota_for(
    *, tenant_id: UUID, brand_id: UUID, period: date, weights: CreationWeights
) -> MonthlyQuota:
    """THE one place a brand's monthly quota is decided (principal-architect,
    2026-10-24): today the base of the weights table, the same for every business
    (founder, 2026-10-24). Grants (a later migration) add to it here and nowhere else.
    Pure; `session`-free on purpose so a grants reader can be passed in later."""
    del tenant_id, brand_id, period  # the base quota does not depend on them yet
    return MonthlyQuota(
        creations=weights.monthly_quota,
        videos=weights.monthly_video_quota,
        previews=weights.monthly_preview_quota,
    )


def not_enough_text(missing: int) -> str:
    """What the owner reads when the month cannot pay (CREAR-5): never a half creation."""
    if missing == 1:
        return "Te falta 1 creación este mes."
    return f"Te faltan {missing} creaciones este mes."


@dataclass(frozen=True)
class CreationsBalance:
    """What the owner reads: «Te quedan {left} de {quota} creaciones y {videos_left} de
    {video_quota} videos este mes» (and the vistas previas when few are left)."""

    quota: int
    used: int
    weights_version: str
    #: The day the quota renews (the next month's first day, tenant's timezone); None
    #: when the ledger does not know the tenant's month.
    renews_on: date | None = None
    #: v2: the month's videos (counted at approval) and vistas previas (at creation);
    #: a quota of 0 = the table has none.
    video_quota: int = 0
    videos_used: int = 0
    preview_quota: int = 0
    previews_used: int = 0

    @property
    def left(self) -> int:
        return max(self.quota - self.used, 0)

    @property
    def videos_left(self) -> int:
        return max(self.video_quota - self.videos_used, 0)

    @property
    def previews_left(self) -> int:
        return max(self.preview_quota - self.previews_used, 0)

    def can_pay(self, weight: int, previews: int = 0) -> bool:
        """At creation: the creations and the vistas previas (videos wait for approval)."""
        previews_ok = self.preview_quota <= 0 or previews <= self.previews_left
        return weight <= self.left and previews_ok

    def shortfall(self, price: CreationPrice) -> NotEnoughCreations | None:
        """Why the month cannot pay `price` AT CREATION, or None when it can."""
        if self.can_pay(price.weight, price.videos):
            return None
        return NotEnoughCreations(
            weight=price.weight,
            left=self.left,
            previews=price.videos if self.preview_quota > 0 else 0,
            previews_left=self.previews_left,
        )

    def video_shortfall(self, videos: int) -> NotEnoughCreations | None:
        """Why the month cannot pay `videos` AT APPROVAL — all or nothing — or None."""
        if self.video_quota <= 0 or videos <= self.videos_left:
            return None
        return NotEnoughCreations(videos=videos, videos_left=self.videos_left)


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
        """Charge one generation at creation (creations + vistas previas); False when it
        was already charged. Raises `NotEnoughCreations` when the month cannot pay."""
        ...

    def charge_videos(
        self, *, tenant_id: UUID, brand_id: UUID, draft_id: UUID, revision: int, videos: int
    ) -> bool:
        """Charge a generation's videos at approval, all or nothing; False when they were
        already charged. Raises `NotEnoughCreations` when the month has not enough."""
        ...

    def uncharge_videos(self, *, tenant_id: UUID, draft_id: UUID, revision: int) -> bool:
        """Undo `charge_videos` when the approval could not be written."""
        ...

    def refund(self, *, tenant_id: UUID, draft_id: UUID, revision: int, reason: str) -> bool:
        """Give back one generation's creations and vistas previas; False when nothing
        was charged."""
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
        when there is none to give (no videos charged, each already given, or the whole
        charge refunded)."""
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

    def _balance(
        self, session: Session, tenant_id: UUID, brand_id: UUID, period: date
    ) -> CreationsBalance:
        """The month's three counters: creations and vistas previas by the month they
        were asked in; videos by the month they were approved in, less the ones a
        failed final gave back (`final_refunded_assets`)."""
        mine = (
            CreationCharge.tenant_id == tenant_id,
            CreationCharge.brand_id == brand_id,
            CreationCharge.status == CHARGED,
        )
        made = session.execute(
            select(
                func.coalesce(func.sum(CreationCharge.weight), 0),
                func.coalesce(func.sum(CreationCharge.previews), 0),
            ).where(*mine, CreationCharge.period_month == period)
        ).one()
        given_back = func.coalesce(func.cardinality(CreationCharge.final_refunded_assets), 0)
        videos = session.scalar(
            select(
                func.coalesce(func.sum(func.greatest(CreationCharge.videos - given_back, 0)), 0)
            ).where(*mine, CreationCharge.videos_period_month == period)
        )
        quota = quota_for(
            tenant_id=tenant_id, brand_id=brand_id, period=period, weights=self._weights
        )
        return CreationsBalance(
            quota=quota.creations,
            used=int(made[0] or 0),
            weights_version=self._weights.version,
            renews_on=next_month_start(period),
            video_quota=quota.videos,
            videos_used=int(videos or 0),
            preview_quota=quota.previews,
            previews_used=int(made[1] or 0),
        )

    def _lock(self, session: Session, brand_id: UUID) -> None:
        session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": _brand_lock_key(brand_id)}
        )

    def balance(self, *, tenant_id: UUID, brand_id: UUID) -> CreationsBalance:
        with tenant_session(tenant_id) as session:
            period = self._period(session, tenant_id)
            return self._balance(session, tenant_id, brand_id, period)

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
            self._lock(session, brand_id)
            already = session.scalar(
                select(CreationCharge.id).where(
                    CreationCharge.draft_id == draft_id, CreationCharge.revision == revision
                )
            )
            if already is not None:
                return False
            period = self._period(session, tenant_id)
            short = self._balance(session, tenant_id, brand_id, period).shortfall(price)
            if short is not None:
                raise short
            result = session.execute(
                insert(CreationCharge)
                .values(**self._row(tenant_id, brand_id, draft_id, revision, price, period))
                .on_conflict_do_nothing(constraint="uq_creation_charges_generation")
            )
            return bool(result.rowcount)

    def _row(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        draft_id: UUID,
        revision: int,
        price: CreationPrice,
        period: date,
    ) -> dict[str, object]:
        return {
            "tenant_id": tenant_id,
            "brand_id": brand_id,
            "draft_id": draft_id,
            "revision": revision,
            "request_kind": price.request_kind,
            "weight": price.weight,
            "previews": price.videos if self._weights.monthly_preview_quota > 0 else 0,
            "monthly_quota": self._weights.monthly_quota,
            "monthly_preview_quota": self._weights.monthly_preview_quota,
            "monthly_video_quota": self._weights.monthly_video_quota,
            "weights_version": self._weights.version,
            "pricing_table_version": self._weights.pricing_table_version,
            "period_month": period,
            "status": CHARGED,
        }

    def charge_videos(
        self, *, tenant_id: UUID, brand_id: UUID, draft_id: UUID, revision: int, videos: int
    ) -> bool:
        if videos <= 0:
            return False
        with tenant_session(tenant_id) as session:
            self._lock(session, brand_id)
            row = session.scalar(
                select(CreationCharge)
                .where(CreationCharge.draft_id == draft_id, CreationCharge.revision == revision)
                .with_for_update()
            )
            if row is not None and (row.videos > 0 or row.status != CHARGED):
                return False
            period = self._period(session, tenant_id)
            short = self._balance(session, tenant_id, brand_id, period).video_shortfall(videos)
            if short is not None:
                raise short
            if row is None:
                # a piece created before the quota (or with it switched off): its row
                # is written now, with nothing charged at creation
                price = CreationPrice(REQUEST_GENERATED_VIDEO, 0)
                values = self._row(tenant_id, brand_id, draft_id, revision, price, period)
                row = CreationCharge(**{**values, "previews": 0})
                session.add(row)
            row.videos = videos
            row.monthly_video_quota = self._weights.monthly_video_quota
            row.videos_period_month = period
            row.videos_charged_at = self._clock()
            return True

    def uncharge_videos(self, *, tenant_id: UUID, draft_id: UUID, revision: int) -> bool:
        with tenant_session(tenant_id) as session:
            row = session.scalar(
                select(CreationCharge)
                .where(
                    CreationCharge.draft_id == draft_id,
                    CreationCharge.revision == revision,
                    CreationCharge.videos > 0,
                )
                .with_for_update()
            )
            if row is None:
                return False
            row.videos = 0
            row.videos_period_month = None
            row.videos_charged_at = None
            row.final_refunded_assets = []
            row.final_refunded_at = None
            row.final_refund_reason = None
            return True

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
    #: The videos charged at approval (0 until then).
    videos: int = 0
    final_refunded_assets: list[UUID] = field(default_factory=list)
    final_reason: str | None = None

    @property
    def videos_given_back(self) -> int:
        return len(self.final_refunded_assets)

    @property
    def counted_videos(self) -> int:
        return max(self.videos - self.videos_given_back, 0)


class InMemoryCreationsLedger:
    """The same contract without a database — for tests and local fakes (one month)."""

    def __init__(
        self,
        *,
        weights: CreationWeights | None = None,
        used: int = 0,
        videos_used: int = 0,
        previews_used: int = 0,
    ) -> None:
        self._weights = weights or load_weights()
        self._opening = used
        self._opening_videos = videos_used
        self._opening_previews = previews_used
        self.rows: dict[tuple[UUID, int], _MemoryRow] = {}

    def _charged(self, brand_id: UUID) -> list[_MemoryRow]:
        return [r for r in self.rows.values() if r.brand_id == brand_id and r.status == CHARGED]

    def balance(self, *, tenant_id: UUID, brand_id: UUID) -> CreationsBalance:
        rows = self._charged(brand_id)
        quota = quota_for(
            tenant_id=tenant_id, brand_id=brand_id, period=date.min, weights=self._weights
        )
        previews = quota.previews > 0
        return CreationsBalance(
            quota=quota.creations,
            used=self._opening + sum(row.price.weight for row in rows),
            weights_version=self._weights.version,
            video_quota=quota.videos,
            videos_used=self._opening_videos + sum(row.counted_videos for row in rows),
            preview_quota=quota.previews,
            previews_used=self._opening_previews
            + (sum(row.price.videos for row in rows) if previews else 0),
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

    def charge_videos(
        self, *, tenant_id: UUID, brand_id: UUID, draft_id: UUID, revision: int, videos: int
    ) -> bool:
        if videos <= 0:
            return False
        row = self.rows.get((draft_id, revision))
        if row is not None and (row.videos > 0 or row.status != CHARGED):
            return False
        short = self.balance(tenant_id=tenant_id, brand_id=brand_id).video_shortfall(videos)
        if short is not None:
            raise short
        if row is None:
            row = _MemoryRow(brand_id=brand_id, price=CreationPrice(REQUEST_GENERATED_VIDEO, 0))
            self.rows[(draft_id, revision)] = row
        row.videos = videos
        return True

    def uncharge_videos(self, *, tenant_id: UUID, draft_id: UUID, revision: int) -> bool:
        row = self.rows.get((draft_id, revision))
        if row is None or row.videos <= 0:
            return False
        row.videos = 0
        row.final_refunded_assets = []
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
        if row is None or row.status != CHARGED or row.videos <= 0:
            return False
        given = _given_back(row.final_refunded_assets, asset_ids, row.videos)
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
    "MonthlyQuota",
    "NotEnoughCreations",
    "PostgresCreationsLedger",
    "month_start",
    "next_month_start",
    "not_enough_text",
    "quota_for",
    "refund_in_session",
]
