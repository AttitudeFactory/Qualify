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
- The quota is the business's plan (m-24852145: Básico 30/4/20, Plus 60/8/40, Pro
  120/16/80, `qualify_api.plans`; no plan = Básico), read from `business_plans` inside
  the same locked transaction; `QUALIFY_CREATIONS_QUOTA=off` stays the
  installation-wide emergency switch.
- An unlimited plan (`ilimitado`, founder 2026-11-02, m-24921124) never refuses for
  quota: `MonthlyQuota.unlimited` / `CreationsBalance.unlimited`. Unlike the switch, the
  charges and their allocations are still written (source `plan`, `plan_code`
  `ilimitado`), so the month's use stays on record; the dollar cap keeps alerting.
- On top of it, the brand's live 90-day packs (m-24852129, `qualify_api.plans.packs`):
  spent only once the plan's month is used up, the one that expires first first (D17).
  Which source paid each unit is written with the charge (`creation_allocations`) and
  given back with it. The dollar cap of `creative_engine_config` stays
  the team's safety net; the owner never sees money (decision 8).

**Video in seconds (ADR 44 F1 = (b), m-24921139; D29 replaces D5).** With
`pesos-creaciones-v3` (`CreationWeights.video_in_seconds`) the third counter is
**seconds of video**, not videos: a charge at approval uses its videos' REQUESTED seconds
(`video_seconds`, migration 0126; `videos` still says how many videos it holds), the
plan's month brings `Plan.video_seconds` (Básico 40 / Plus 80 / Pro 160, `[PROPUESTO]`)
and a pack its seconds (`pack_video_seconds`). The allocations of these charges are in
the dimension `video_seconds`. A failed final gives back its share of the charge's
seconds (`refunded_seconds`: the whole of a one-video charge — a clip, a part — and
`seconds × k ÷ videos` of a gallery). `charge_videos_many` charges the parts of a video
by parts in one locked transaction, all or nothing. The transition (§13.5 of
`docs/diseno-video-por-planos.md`): a video counted under D5 — a charge or a pack
allocation without seconds — counts as `seconds_per_legacy_video` (10 s), so the month in
course and the packs bought in videos lose nothing. In every balance, quota and refusal
below, «videos» means the table's unit: seconds under v3.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from qualify_creative.creations import (
    REQUEST_GENERATED_VIDEO,
    CreationPrice,
    CreationWeights,
    load_weights,
)
from qualify_shared.db.session import tenant_session
from sqlalchemy import case, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from qualify_api.creative.models import CreationCharge
from qualify_api.plans.catalog import PACK_DAYS, PLANS_VERSION, Pack, Plan
from qualify_api.plans.models import CreationAllocation
from qualify_api.plans.packs import (
    CREATIONS,
    PREVIEWS,
    SOURCE_PACK,
    SOURCE_PLAN,
    VIDEO_SECONDS,
    VIDEOS,
    Allocation,
    PackBalance,
    dimension_balance,
    legacy_seconds_per_video,
    local_day,
    pack_video_seconds,
    packs_in_session,
    split,
    with_video_seconds,
)
from qualify_api.plans.read import plan_in_session
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
        video_in_seconds: bool = False,
        video_quota: int = 0,
    ) -> None:
        unit = "video seconds" if video_in_seconds else "videos"
        super().__init__(
            f"needs {weight} creations ({left} left), {previews} previews "
            f"({previews_left} left), {videos} {unit} ({videos_left} left)"
        )
        #: `videos`/`videos_left` are seconds (ADR 44 F1 = (b)) when True.
        self.video_in_seconds = video_in_seconds
        #: The brand's own month of video (its plan + live packs) at approval, so the
        #: words say «tus 80 segundos» for a Plus brand; 0 = unknown.
        self.video_quota = video_quota
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
    """What one brand's month brings: creations, video (seconds under the v3 weights,
    videos under v2) and vistas previas."""

    creations: int
    videos: int
    previews: int
    #: The plan sets no monthly limit (`Plan.unlimited`): the counts above are 0 and mean
    #: nothing; nothing is refused for quota.
    unlimited: bool = False
    #: ADR 44 F1 = (b): `videos` is seconds of video.
    video_in_seconds: bool = False


def quota_for(
    *,
    tenant_id: UUID,
    brand_id: UUID,
    period: date,
    weights: CreationWeights,
    plan: Plan | None = None,
) -> MonthlyQuota:
    """THE one place a brand's monthly quota is decided (principal-architect,
    2026-10-24): the plan's monthly quota (m-24852145), resolved by the caller from
    `business_plans` (`plans.read`; no plan = Básico). Without a plan, the base of the
    weights table (what Básico equals). A weights table with no video quota (v1) keeps
    videos and vistas previas uncapped whatever the plan. Packs — 90-day extras bought
    on top — are NOT part of the monthly quota: they live in `qualify_api.plans.packs`
    (m-24852129) and the ledger adds them next to this. Pure; no session."""
    del tenant_id, brand_id, period  # the plan already says which month it is for
    seconds = weights.video_in_seconds
    if plan is None:
        return MonthlyQuota(
            creations=weights.monthly_quota,
            videos=weights.monthly_video_quota,
            previews=weights.monthly_preview_quota,
            video_in_seconds=seconds,
        )
    if plan.unlimited:
        return MonthlyQuota(
            creations=0, videos=0, previews=0, unlimited=True, video_in_seconds=seconds
        )
    plan_videos = plan.video_seconds if seconds else plan.videos
    return MonthlyQuota(
        creations=plan.creations or 0,
        videos=(plan_videos or 0) if weights.monthly_video_quota > 0 else 0,
        previews=(plan.previews or 0) if weights.monthly_preview_quota > 0 else 0,
        video_in_seconds=seconds,
    )


def not_enough_text(missing: int) -> str:
    """What the owner reads when the month cannot pay (CREAR-5): never a half creation."""
    if missing == 1:
        return "Te falta 1 creación este mes."
    return f"Te faltan {missing} creaciones este mes."


@dataclass(frozen=True)
class CreationsBalance:
    """What the owner reads: «Te quedan {left} de {quota} creaciones y {videos_left} de
    {video_quota} segundos de video este mes» (and the vistas previas when few are left)."""

    quota: int
    used: int
    weights_version: str
    #: The day the quota renews (the next month's first day, tenant's timezone); None
    #: when the ledger does not know the tenant's month.
    renews_on: date | None = None
    #: v3 (VE-21): the month's video seconds (counted at approval) and vistas previas (at creation);
    #: a quota of 0 = the table has none.
    video_quota: int = 0
    videos_used: int = 0
    preview_quota: int = 0
    previews_used: int = 0
    #: m-24852129: what the live 90-day packs still bring, per counter, and the day
    #: (business's zone) the one that expires first stops counting. `quota` and `left`
    #: already include them («Te quedan 50 de 60 segundos de video este mes (20 extra, …)»).
    extra_left: int = 0
    extra_expires_on: date | None = None
    extra_videos_left: int = 0
    extra_videos_expires_on: date | None = None
    extra_previews_left: int = 0
    extra_previews_expires_on: date | None = None
    #: The plan sets no monthly limit (`ilimitado`): every check passes and the quota
    #: fields are 0. The screens read such a balance as «no quota» and say nothing.
    unlimited: bool = False
    #: ADR 44 F1 = (b): every `video*`/`extra_videos_*` field is SECONDS of video
    #: («Te quedan 25 segundos de video este mes»), never a count of videos.
    video_in_seconds: bool = False

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
        if self.unlimited:
            return True
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
        """Why the month cannot pay `videos` (seconds under v3) AT APPROVAL — all or
        nothing — or None."""
        if self.unlimited or self.video_quota <= 0 or videos <= self.videos_left:
            return None
        return NotEnoughCreations(
            videos=videos,
            videos_left=self.videos_left,
            video_in_seconds=self.video_in_seconds,
            video_quota=self.video_quota,
        )


@dataclass(frozen=True)
class VideoCharge:
    """One generation's videos to charge at approval: how many videos it holds and their
    REQUESTED seconds (ADR 44 F1 = (b)) — a part of a video by parts is one of these."""

    draft_id: UUID
    revision: int
    videos: int
    seconds: int = 0


def refunded_seconds(seconds: int, videos: int, failed: int) -> int:
    """The seconds a charge of `videos` videos and `seconds` seconds gives back once
    `failed` of its finals failed (D9): all of a one-video charge (a clip, a part of a
    video by parts), a proportional share of a gallery, and every second once every
    final failed — never more than was charged."""
    if videos <= 0 or failed <= 0:
        return 0
    return seconds * min(failed, videos) // videos


def counted_amount(
    *, videos: int, seconds: int, given_back: int, in_seconds: bool, legacy: int
) -> int:
    """What one charge still counts of the month's video, in the table's unit: under v3
    its seconds less what failed finals gave back — or, for a charge from before the
    seconds (`seconds == 0`), its videos at the legacy rate."""
    left_videos = max(videos - given_back, 0)
    if not in_seconds:
        return left_videos
    if seconds <= 0:
        return left_videos * legacy
    return max(seconds - refunded_seconds(seconds, videos, given_back), 0)


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
    ) -> UUID | None:
        """Charge one generation at creation (creations + vistas previas): the charge
        row's id, or None when it was already charged. Raises `NotEnoughCreations` when
        the month cannot pay."""
        ...

    def charge_videos(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        draft_id: UUID,
        revision: int,
        videos: int,
        seconds: int = 0,
    ) -> UUID | None:
        """Charge a generation's videos at approval, all or nothing — under v3 their
        requested `seconds`: the charge row's id, or None when they were already charged
        (or there are none). Raises `NotEnoughCreations` when the month has not enough."""
        ...

    def charge_videos_many(
        self, *, tenant_id: UUID, brand_id: UUID, charges: Sequence[VideoCharge]
    ) -> list[UUID]:
        """Charge several generations' videos at approval in ONE transaction, all or
        nothing (the parts of a video by parts, ADR 44): the ids of the rows charged now
        (those already charged are skipped). Raises `NotEnoughCreations` — nothing
        charged — when the month cannot pay their sum."""
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
        """Give back the video of each failed final (`asset_ids`, one per video) — under
        v3 its seconds (`refunded_seconds`); False when there is none to give (no videos
        charged, each already given, or the whole charge refunded)."""
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


def video_dimension(weights: CreationWeights) -> str:
    """The allocation dimension of the month's video: seconds under v3, videos before."""
    return VIDEO_SECONDS if weights.video_in_seconds else VIDEOS


def charge_amount(weights: CreationWeights, item: VideoCharge) -> int:
    """What approving `item` uses of the month's video, in the table's unit: its
    requested seconds under v3 (its videos at the legacy rate when a caller gave no
    seconds, so it is never charged less), else its videos."""
    if not weights.video_in_seconds:
        return item.videos
    if item.seconds > 0:
        return item.seconds
    return item.videos * legacy_seconds_per_video()


def carve(allocations: Sequence[Allocation], sizes: Sequence[int]) -> list[list[Allocation]]:
    """Split the allocations of a sum (`split` over `sum(sizes)`) into one list per
    charge, in order: each charge takes its units from the sources in the order D17
    spends them (the plan first, then the packs by expiry)."""
    rest = [(a, a.units) for a in allocations]
    out: list[list[Allocation]] = []
    for size in sizes:
        mine: list[Allocation] = []
        need = size
        while need > 0 and rest:
            alloc, left = rest[0]
            take = min(need, left)
            mine.append(Allocation(alloc.dimension, alloc.source, take, alloc.pack_id))
            need -= take
            if take == left:
                rest.pop(0)
            else:
                rest[0] = (alloc, left - take)
        if need > 0:
            raise ValueError("the allocations do not cover the charges")
        out.append(mine)
    return out


class PostgresCreationsLedger:
    def __init__(
        self,
        *,
        weights: CreationWeights | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._weights = weights or load_weights()
        self._clock = clock or (lambda: datetime.now(UTC))

    def _zone(self, session: Session, tenant_id: UUID) -> str:
        tenant = session.get(Tenant, tenant_id)
        return tenant.timezone if tenant is not None and tenant.timezone else "UTC"

    def _period(self, session: Session, tenant_id: UUID) -> date:
        return month_start(self._clock(), self._zone(session, tenant_id))

    def _balance(
        self, session: Session, tenant_id: UUID, brand_id: UUID, period: date
    ) -> CreationsBalance:
        return self._state(session, tenant_id, brand_id, period).balance

    def _state(self, session: Session, tenant_id: UUID, brand_id: UUID, period: date) -> _State:
        """The month's three counters: creations and vistas previas by the month they
        were asked in; videos by the month they were approved in, less the ones a
        failed final gave back (`final_refunded_assets`) — plus the brand's live packs
        and what the plan's month alone still has (who pays the next charge, D17)."""
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
        left_videos = func.greatest(CreationCharge.videos - given_back, 0)
        counted = left_videos
        if self._weights.video_in_seconds:
            # `counted_amount` in SQL: seconds less the failed finals' share; a charge
            # from before the seconds counts its videos at the legacy rate
            share = (
                CreationCharge.video_seconds
                * func.least(given_back, CreationCharge.videos)
                // func.nullif(CreationCharge.videos, 0)
            )
            counted = case(
                (
                    CreationCharge.video_seconds > 0,
                    func.greatest(CreationCharge.video_seconds - func.coalesce(share, 0), 0),
                ),
                else_=left_videos * legacy_seconds_per_video(),
            )
        videos = session.scalar(
            select(func.coalesce(func.sum(counted), 0)).where(
                *mine, CreationCharge.videos_period_month == period
            )
        )
        plan = plan_in_session(session, tenant_id, period)
        quota = quota_for(
            tenant_id=tenant_id, brand_id=brand_id, period=period, weights=self._weights, plan=plan
        )
        packs = packs_in_session(session, tenant_id, brand_id, period, self._clock())
        used = {
            CREATIONS: int(made[0] or 0),
            video_dimension(self._weights): int(videos or 0),
            PREVIEWS: int(made[1] or 0),
        }
        return compose_state(
            quota=quota,
            used=used,
            packs=packs,
            plan=plan,
            weights_version=self._weights.version,
            renews_on=next_month_start(period),
            zone=self._zone(session, tenant_id),
            video_dimension=video_dimension(self._weights),
        )

    def _allocate(
        self,
        session: Session,
        tenant_id: UUID,
        charge_id: UUID,
        allocations: list[Allocation],
        period: date,
        plan: Plan | None,
    ) -> None:
        """Write who paid each unit of `charge_id` (D17), numbered after the charge's
        earlier rows of the same dimension (a video charged again after an undo)."""
        if not allocations:
            return
        last: dict[str, int] = {
            dimension: int(seq or 0)
            for dimension, seq in session.execute(
                select(CreationAllocation.dimension, func.max(CreationAllocation.seq))
                .where(CreationAllocation.charge_id == charge_id)
                .group_by(CreationAllocation.dimension)
            ).all()
        }
        session.execute(
            insert(CreationAllocation)
            .values(allocation_rows(tenant_id, charge_id, allocations, period, plan, last))
            .on_conflict_do_nothing(constraint="uq_creation_alloc_seq")
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
    ) -> UUID | None:
        with tenant_session(tenant_id) as session:
            self._lock(session, brand_id)
            already = session.scalar(
                select(CreationCharge.id).where(
                    CreationCharge.draft_id == draft_id, CreationCharge.revision == revision
                )
            )
            if already is not None:
                return None
            period = self._period(session, tenant_id)
            state = self._state(session, tenant_id, brand_id, period)
            short = state.balance.shortfall(price)
            if short is not None:
                raise short
            values = self._row(tenant_id, brand_id, draft_id, revision, price, period, state.quota)
            charge_id = session.scalar(
                insert(CreationCharge)
                .values(**values)
                .on_conflict_do_nothing(constraint="uq_creation_charges_generation")
                .returning(CreationCharge.id)
            )
            if charge_id is not None:
                previews = int(values["previews"])  # type: ignore[call-overload]
                allocations = state.split(CREATIONS, price.weight) + state.split(PREVIEWS, previews)
                self._allocate(session, tenant_id, charge_id, allocations, period, state.plan)
            return charge_id

    def _row(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        draft_id: UUID,
        revision: int,
        price: CreationPrice,
        period: date,
        quota: MonthlyQuota,
    ) -> dict[str, object]:
        return {
            "tenant_id": tenant_id,
            "brand_id": brand_id,
            "draft_id": draft_id,
            "revision": revision,
            "request_kind": price.request_kind,
            "weight": price.weight,
            "previews": price.videos if self._weights.monthly_preview_quota > 0 else 0,
            # the quotas in force when it was charged: the plan's (provenance; the packs
            # that paid are in `creation_allocations`)
            "monthly_quota": quota.creations,
            "monthly_preview_quota": quota.previews,
            "monthly_video_quota": quota.videos,
            "weights_version": self._weights.version,
            "pricing_table_version": self._weights.pricing_table_version,
            "period_month": period,
            "status": CHARGED,
        }

    def charge_videos(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        draft_id: UUID,
        revision: int,
        videos: int,
        seconds: int = 0,
    ) -> UUID | None:
        charged = self.charge_videos_many(
            tenant_id=tenant_id,
            brand_id=brand_id,
            charges=(VideoCharge(draft_id, revision, videos, seconds),),
        )
        return charged[0] if charged else None

    def charge_videos_many(
        self, *, tenant_id: UUID, brand_id: UUID, charges: Sequence[VideoCharge]
    ) -> list[UUID]:
        wanted = [c for c in charges if c.videos > 0]
        if not wanted:
            return []
        with tenant_session(tenant_id) as session:
            self._lock(session, brand_id)
            pending: list[tuple[VideoCharge, CreationCharge | None]] = []
            for item in wanted:
                row = session.scalar(
                    select(CreationCharge)
                    .where(
                        CreationCharge.draft_id == item.draft_id,
                        CreationCharge.revision == item.revision,
                    )
                    .with_for_update()
                )
                if row is not None and (row.videos > 0 or row.status != CHARGED):
                    continue  # already charged (or refunded): never twice
                pending.append((item, row))
            if not pending:
                return []
            period = self._period(session, tenant_id)
            state = self._state(session, tenant_id, brand_id, period)
            amounts = [charge_amount(self._weights, item) for item, _ in pending]
            # all or nothing: the parts together, or none of them
            short = state.balance.video_shortfall(sum(amounts))
            if short is not None:
                raise short
            dimension = video_dimension(self._weights)
            shares = carve(state.split(dimension, sum(amounts)), amounts)
            ids: list[UUID] = []
            for (item, row), share in zip(pending, shares, strict=True):
                if row is None:
                    # a piece created before the quota (or with it switched off): its
                    # row is written now, with nothing charged at creation
                    price = CreationPrice(REQUEST_GENERATED_VIDEO, 0)
                    values = self._row(
                        tenant_id,
                        brand_id,
                        item.draft_id,
                        item.revision,
                        price,
                        period,
                        state.quota,
                    )
                    row = CreationCharge(**{**values, "previews": 0})
                    session.add(row)
                row.videos = item.videos
                row.video_seconds = (
                    charge_amount(self._weights, item) if self._weights.video_in_seconds else 0
                )
                row.monthly_video_quota = state.quota.videos
                row.videos_period_month = period
                row.videos_charged_at = self._clock()
                session.flush()
                self._allocate(session, tenant_id, row.id, share, period, state.plan)
                ids.append(row.id)
            return ids

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
            reverse_allocations(session, row.id, VIDEOS)
            reverse_allocations(session, row.id, VIDEO_SECONDS)
            row.videos = 0
            row.video_seconds = 0
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
            return refund_final_in_session(
                session,
                draft_id=draft_id,
                revision=revision,
                reason=reason,
                asset_ids=asset_ids,
                now=self._clock(),
            )


def refund_final_in_session(
    session: Session,
    *,
    draft_id: UUID,
    revision: int,
    reason: str,
    asset_ids: Sequence[UUID],
    now: datetime,
) -> bool:
    """The final's existing refund, inside a caller's atomic cancellation transaction."""
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
    already = list(row.final_refunded_assets or ())
    given = _given_back(already, asset_ids, row.videos)
    if given is None:
        return False
    if row.video_seconds > 0:
        # ADR 44 F1 = (b), D9 in seconds: the failed finals' share of the seconds
        back = refunded_seconds(row.video_seconds, row.videos, len(given))
        before = refunded_seconds(row.video_seconds, row.videos, len(already))
        reverse_allocations(session, row.id, VIDEO_SECONDS, units=back - before)
    else:
        reverse_allocations(session, row.id, VIDEOS, units=len(given) - len(already))
    row.final_refunded_assets = given
    row.final_refunded_at = now
    row.final_refund_reason = reason[:200]
    return True


@dataclass(frozen=True)
class _State:
    """A brand's month at one moment: what the owner reads, the plan's monthly quota and
    what of it is left, and the packs — who pays the next charge (D17)."""

    balance: CreationsBalance
    quota: MonthlyQuota
    plan: Plan | None
    #: None = the plan does not cap that counter (it pays everything).
    plan_left: dict[str, int | None]
    packs: list[PackBalance]

    def split(self, dimension: str, needed: int) -> list[Allocation]:
        return split(dimension, needed, self.plan_left[dimension], self.packs)


def compose_state(
    *,
    quota: MonthlyQuota,
    used: dict[str, int],
    packs: list[PackBalance],
    plan: Plan | None,
    weights_version: str,
    renews_on: date | None,
    zone: str,
    video_dimension: str = VIDEOS,
) -> _State:
    """The plan's month plus the brand's packs (m-24852129) as one balance. Pure.
    `video_dimension` is the month's video counter: `video_seconds` under the v3
    weights (ADR 44 F1 = (b)), `videos` before; `used` is keyed by it."""
    vd = video_dimension
    plan_quota = {CREATIONS: quota.creations, vd: quota.videos, PREVIEWS: quota.previews}
    dims = {d: dimension_balance(d, plan_quota[d], used[d], packs) for d in plan_quota}
    balance = CreationsBalance(
        quota=dims[CREATIONS].quota,
        used=used[CREATIONS],
        weights_version=weights_version,
        renews_on=renews_on,
        video_quota=dims[vd].quota,
        videos_used=used[vd],
        preview_quota=dims[PREVIEWS].quota,
        previews_used=used[PREVIEWS],
        extra_left=dims[CREATIONS].extra_left,
        extra_expires_on=local_day(dims[CREATIONS].extra_expires_at, zone),
        extra_videos_left=dims[vd].extra_left,
        extra_videos_expires_on=local_day(dims[vd].extra_expires_at, zone),
        extra_previews_left=dims[PREVIEWS].extra_left,
        extra_previews_expires_on=local_day(dims[PREVIEWS].extra_expires_at, zone),
        unlimited=quota.unlimited,
        video_in_seconds=vd == VIDEO_SECONDS,
    )
    return _State(
        balance=balance,
        quota=quota,
        plan=plan,
        # None = the plan pays every unit of that counter (no cap, or no limit at all)
        plan_left={
            d: (dims[d].plan_left if plan_quota[d] > 0 and not quota.unlimited else None)
            for d in plan_quota
        },
        packs=packs,
    )


def allocation_rows(
    tenant_id: UUID,
    charge_id: UUID,
    allocations: Iterable[Allocation],
    period: date,
    plan: Plan | None,
    last_seq: dict[str, int],
) -> list[dict[str, object]]:
    """The `creation_allocations` rows of one charge, `seq` continuing per dimension."""
    rows: list[dict[str, object]] = []
    for allocation in allocations:
        seq = last_seq.get(allocation.dimension, 0) + 1
        last_seq[allocation.dimension] = seq
        from_plan = allocation.source == SOURCE_PLAN and plan is not None
        rows.append(
            {
                "tenant_id": tenant_id,
                "charge_id": charge_id,
                "dimension": allocation.dimension,
                "source": allocation.source,
                "pack_id": allocation.pack_id if allocation.source == SOURCE_PACK else None,
                "plan_code": plan.code if from_plan and plan is not None else None,
                "plans_version": PLANS_VERSION if from_plan else None,
                "period_month": period,
                "units": allocation.units,
                "seq": seq,
            }
        )
    return rows


def reverse_allocations(
    session: Session, charge_id: UUID, dimension: str | None = None, units: int | None = None
) -> None:
    """Give units of a charge back to whoever paid them (m-24852129): all of them, or —
    a failed final's video — `units` of `dimension`, the last source used first (highest
    `seq`: a pack, when one paid). A unit given back to an expired pack is lost."""
    query = select(CreationAllocation).where(
        CreationAllocation.charge_id == charge_id,
        CreationAllocation.reversed_units < CreationAllocation.units,
    )
    if dimension is not None:
        query = query.where(CreationAllocation.dimension == dimension)
    rest = units
    for row in session.scalars(query.order_by(CreationAllocation.seq.desc()).with_for_update()):
        if rest is not None and rest <= 0:
            break
        open_units = row.units - row.reversed_units
        take = open_units if rest is None else min(open_units, rest)
        row.reversed_units += take
        if rest is not None:
            rest -= take


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
        reverse_allocations(session, row.id)
        row.status = REFUNDED
        row.refund_reason = reason[:200]
        row.refunded_at = at
        turned += 1
    return turned


@dataclass
class _MemoryRow:
    brand_id: UUID
    price: CreationPrice
    id: UUID = field(default_factory=uuid4)
    status: str = CHARGED
    reason: str | None = None
    #: The videos charged at approval (0 until then).
    videos: int = 0
    #: ADR 44 F1 = (b): their requested seconds (0 = charged before the seconds).
    video_seconds: int = 0
    final_refunded_assets: list[UUID] = field(default_factory=list)
    final_reason: str | None = None
    #: m-24852129: who paid each unit, in the order they were taken (D17).
    allocations: list[_MemoryAllocation] = field(default_factory=list)

    @property
    def videos_given_back(self) -> int:
        return len(self.final_refunded_assets)

    @property
    def counted_videos(self) -> int:
        return max(self.videos - self.videos_given_back, 0)

    def add(self, allocations: Iterable[Allocation]) -> None:
        self.allocations.extend(
            _MemoryAllocation(a.dimension, a.source, a.pack_id, a.units) for a in allocations
        )

    def give_back(self, dimension: str | None = None, units: int | None = None) -> None:
        """`reverse_allocations` without a database: the last source used first."""
        rest = units
        for alloc in reversed(self.allocations):
            if rest is not None and rest <= 0:
                break
            if dimension is not None and alloc.dimension != dimension:
                continue
            take = alloc.net if rest is None else min(alloc.net, rest)
            alloc.reversed += take
            if rest is not None:
                rest -= take


@dataclass
class _MemoryAllocation:
    dimension: str
    source: str
    pack_id: UUID | None
    units: int
    reversed: int = 0

    @property
    def net(self) -> int:
        return self.units - self.reversed


@dataclass
class _MemoryPack:
    code: str
    units: dict[str, int]
    expires_at: datetime
    id: UUID = field(default_factory=uuid4)
    revoked: bool = False


class InMemoryCreationsLedger:
    """The same contract without a database — for tests and local fakes (one month)."""

    def __init__(
        self,
        *,
        weights: CreationWeights | None = None,
        used: int = 0,
        videos_used: int = 0,
        previews_used: int = 0,
        plan: Plan | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._weights = weights or load_weights()
        self.plan = plan
        self._opening = used
        self._opening_videos = videos_used
        self._opening_previews = previews_used
        self._clock = clock or (lambda: datetime.now(UTC))
        self.rows: dict[tuple[UUID, int], _MemoryRow] = {}
        #: m-24852129: the brand-agnostic packs of this one-month fake.
        self.packs: list[_MemoryPack] = []

    def add_pack(self, pack: Pack, *, granted_at: datetime | None = None) -> UUID:
        """Grant one fixed pack (the team's `just add-pack`, without a database)."""
        at = granted_at or self._clock()
        row = _MemoryPack(
            code=pack.code,
            units={
                CREATIONS: pack.creations,
                VIDEOS: pack.videos,
                PREVIEWS: pack.previews,
                VIDEO_SECONDS: pack_video_seconds(pack.code, pack.videos),
            },
            expires_at=at + timedelta(days=PACK_DAYS),
        )
        self.packs.append(row)
        return row.id

    def revoke_pack(self, pack_id: UUID) -> bool:
        for pack in self.packs:
            if pack.id == pack_id and not pack.revoked:
                pack.revoked = True
                return True
        return False

    def _charged(self, brand_id: UUID) -> list[_MemoryRow]:
        return [r for r in self.rows.values() if r.brand_id == brand_id and r.status == CHARGED]

    def _pack_balances(self) -> list[PackBalance]:
        now = self._clock()
        out: list[PackBalance] = []
        for pack in self.packs:
            used: dict[str, int] = {}
            for row in self.rows.values():
                for alloc in row.allocations:
                    if alloc.pack_id == pack.id:
                        used[alloc.dimension] = used.get(alloc.dimension, 0) + alloc.net
            out.append(
                PackBalance(
                    id=pack.id,
                    code=pack.code,
                    expires_at=pack.expires_at,
                    live=not pack.revoked and now < pack.expires_at,
                    units=pack.units,
                    used=with_video_seconds(used),
                    used_in_period=with_video_seconds(used),
                )
            )
        return out

    def _state(self, tenant_id: UUID, brand_id: UUID) -> _State:
        rows = self._charged(brand_id)
        quota = quota_for(
            tenant_id=tenant_id,
            brand_id=brand_id,
            period=date.min,
            weights=self._weights,
            plan=self.plan,
        )
        # as `_row`: an unlimited plan still counts vistas previas when the table has them
        previews = quota.previews > 0 or (
            quota.unlimited and self._weights.monthly_preview_quota > 0
        )
        legacy = legacy_seconds_per_video()
        in_seconds = self._weights.video_in_seconds
        counted = sum(
            counted_amount(
                videos=row.videos,
                seconds=row.video_seconds,
                given_back=row.videos_given_back,
                in_seconds=in_seconds,
                legacy=legacy,
            )
            for row in rows
        )
        used = {
            CREATIONS: self._opening + sum(row.price.weight for row in rows),
            video_dimension(self._weights): self._opening_videos + counted,
            PREVIEWS: self._opening_previews
            + (sum(row.price.videos for row in rows) if previews else 0),
        }
        return compose_state(
            quota=quota,
            used=used,
            packs=self._pack_balances(),
            plan=self.plan,
            weights_version=self._weights.version,
            renews_on=None,
            zone="UTC",
            video_dimension=video_dimension(self._weights),
        )

    def balance(self, *, tenant_id: UUID, brand_id: UUID) -> CreationsBalance:
        return self._state(tenant_id, brand_id).balance

    def charge(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        draft_id: UUID,
        revision: int,
        price: CreationPrice,
    ) -> UUID | None:
        if (draft_id, revision) in self.rows:
            return None
        state = self._state(tenant_id, brand_id)
        short = state.balance.shortfall(price)
        if short is not None:
            raise short
        row = _MemoryRow(brand_id=brand_id, price=price)
        counted = state.quota.previews > 0 or (
            state.quota.unlimited and self._weights.monthly_preview_quota > 0
        )
        previews = price.videos if counted else 0
        row.add(state.split(CREATIONS, price.weight) + state.split(PREVIEWS, previews))
        self.rows[(draft_id, revision)] = row
        return row.id

    def charge_videos(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        draft_id: UUID,
        revision: int,
        videos: int,
        seconds: int = 0,
    ) -> UUID | None:
        charged = self.charge_videos_many(
            tenant_id=tenant_id,
            brand_id=brand_id,
            charges=(VideoCharge(draft_id, revision, videos, seconds),),
        )
        return charged[0] if charged else None

    def charge_videos_many(
        self, *, tenant_id: UUID, brand_id: UUID, charges: Sequence[VideoCharge]
    ) -> list[UUID]:
        pending: list[VideoCharge] = []
        for item in charges:
            if item.videos <= 0:
                continue
            row = self.rows.get((item.draft_id, item.revision))
            if row is not None and (row.videos > 0 or row.status != CHARGED):
                continue
            pending.append(item)
        if not pending:
            return []
        state = self._state(tenant_id, brand_id)
        amounts = [charge_amount(self._weights, item) for item in pending]
        short = state.balance.video_shortfall(sum(amounts))
        if short is not None:
            raise short
        shares = carve(state.split(video_dimension(self._weights), sum(amounts)), amounts)
        ids: list[UUID] = []
        for item, amount, share in zip(pending, amounts, shares, strict=True):
            row = self.rows.get((item.draft_id, item.revision))
            if row is None:
                row = _MemoryRow(brand_id=brand_id, price=CreationPrice(REQUEST_GENERATED_VIDEO, 0))
                self.rows[(item.draft_id, item.revision)] = row
            row.videos = item.videos
            row.video_seconds = amount if self._weights.video_in_seconds else 0
            row.add(share)
            ids.append(row.id)
        return ids

    def uncharge_videos(self, *, tenant_id: UUID, draft_id: UUID, revision: int) -> bool:
        row = self.rows.get((draft_id, revision))
        if row is None or row.videos <= 0:
            return False
        row.give_back(VIDEOS)
        row.give_back(VIDEO_SECONDS)
        row.videos = 0
        row.video_seconds = 0
        row.final_refunded_assets = []
        return True

    def refund(self, *, tenant_id: UUID, draft_id: UUID, revision: int, reason: str) -> bool:
        row = self.rows.get((draft_id, revision))
        if row is None or row.status != CHARGED:
            return False
        row.give_back()
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
        already = len(row.final_refunded_assets)
        if row.video_seconds > 0:
            back = refunded_seconds(row.video_seconds, row.videos, len(given))
            before = refunded_seconds(row.video_seconds, row.videos, already)
            row.give_back(VIDEO_SECONDS, back - before)
        else:
            row.give_back(VIDEOS, len(given) - already)
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
    "VideoCharge",
    "carve",
    "charge_amount",
    "counted_amount",
    "month_start",
    "next_month_start",
    "not_enough_text",
    "quota_for",
    "refund_in_session",
    "refunded_seconds",
    "video_dimension",
]
