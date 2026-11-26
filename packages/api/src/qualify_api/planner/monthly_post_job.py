"""«Publicación del mes» — the calendar worker's daily chore (m-25120705, epic m-25120477).

For each brand whose owner turned the setting on (`planner.monthly_post`, off by default),
once per month: the month's most relevant date (`ads.month_plan.event_of_month`, for the
business's country and the Brand Kit's sector) becomes ONE draft through
`ContentService.create_draft` — the same path, quota charge and dispatch as any piece. The
draft lands in «Por aprobar»; nothing here schedules or publishes it (assisted, never
autonomous).

The post spends a monthly creation, so the order is the guarantee:

1. **Opt-in** read on every run; a brand with the setting off is never touched.
2. **Not useful → nothing.** The event must start at least `LEAD_DAYS` from today; turning
   the setting on after the date passed writes no row and charges nothing. From day
   `NEXT_MONTH_FROM_DAY` the next month's period is considered too (founder, 2026-11-25),
   so a date in a month's first days still gets its post.
3. **Claim** `monthly_posts` (`UNIQUE (brand_id, period)`, insert-on-conflict) BEFORE the
   generator: only the winner goes on. A `pending` claim older than `STALE_CLAIM` (a run
   that died midway) may be taken again by a later run.
4. **Generator with a deterministic `request_key`** (`uuid5` of
   `monthly-post:<brand>:<YYYY-MM>[:<attempt>]`): if a crashed run already created the
   draft, the retry gets that draft back with no second charge or dispatch
   (`create_draft`'s contract).
5. **Settle**: `created` + `draft_id`, or `skipped` + reason when nothing was charged —
   no event, no country/calendar, no owner, Brand Kit not ready, not enough creations, a
   brief the generator refuses (a kind that needs the owner's inputs: an avatar's voice, a
   template's product photo, a carousel's slides). All final except `not_enough_creations`
   (founder, 2026-11-25): while the date is still `LEAD_DAYS` ahead the next daily run
   claims it again with `attempt + 1` — a new key, since `create_draft` may have left a
   draft failed uncharged under the old one. Any OTHER error first looks the draft up
   by its key: found → `created` (it may be charged, so it is never redone); not found or
   the lookup failed → the row stays `pending`, retried by the next daily run once stale.

The user the draft is attributed to is the tenant's first owner (`planner.immediate.owner_of`,
the same rule as the publication sweep), else its first user.

`--tenant` scope = the worker's scope; `--all-tenants` = every tenant (`all_tenant_ids`),
each read through its own `tenant_session`.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final, Protocol
from uuid import UUID, uuid5

from qualify_creative.enums import BriefIntent, BriefObjective, ImageRoute
from qualify_creative.schemas import ContentBrief
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.month_plan import TABLE_VERSION, PlanDate, event_of_month
from qualify_api.planner.monthly_post import MONTHLY_POST_KEY, _from_document

logger = logging.getLogger("qualify_api.planner.monthly_post_job")

PIPELINE_VERSION: Final = "monthly-post-v1"
LEAD_DAYS: Final = 3
NEXT_MONTH_FROM_DAY: Final = 25
#: The one skip reason a later run retries (the owner may get more creations).
RETRYABLE_SKIP: Final = "not_enough_creations"
STALE_CLAIM: Final = timedelta(hours=1)
#: Fixed namespace of the request keys: the same brand and month always give the same key.
_KEY_NAMESPACE: Final = UUID("6f1d3c2a-5b0e-4f7a-9c61-0d2e8a4b7c15")


def request_key(brand_id: UUID, period: date, attempt: int = 0) -> UUID:
    suffix = f":{attempt}" if attempt else ""
    return uuid5(_KEY_NAMESPACE, f"monthly-post:{brand_id}:{period:%Y-%m}{suffix}")


def periods(today: date) -> list[date]:
    """The months the chore prepares on `today`: this one, and the next from day 25."""
    this = today.replace(day=1)
    if today.day < NEXT_MONTH_FROM_DAY:
        return [this]
    return [this, (this + timedelta(days=32)).replace(day=1)]


def event_brief(brand_id: UUID, event: PlanDate, kind: Any) -> ContentBrief:
    """The brief of the month's post: the date is the theme; images come from the Brand
    Kit (`TEMPLATE_ONLY`, as /create does for a piece without the owner's photos). Raises
    `ValueError` (pydantic) for a kind that needs inputs only the owner can give."""
    return ContentBrief(
        brand_id=brand_id,
        objective=BriefObjective.SALE,
        topic=event.name,
        intent=BriefIntent.ORGANIC,
        image_route=ImageRoute.TEMPLATE_ONLY,
        kind=kind,
        format=kind.default_format,
    )


@dataclass(frozen=True)
class EnabledBrand:
    brand_id: UUID
    kind: Any  # ContentKind
    sector: str | None


class MonthlyPostStore(Protocol):
    def enabled_brands(self, tenant_id: UUID) -> list[EnabledBrand]: ...

    def claim(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        period: date,
        event: PlanDate | None,
        kind: str,
    ) -> int | None: ...

    def settle(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        period: date,
        status: str,
        skip_reason: str | None = None,
        draft_id: UUID | None = None,
    ) -> None: ...


class Drafts(Protocol):
    def create_draft(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        brief: ContentBrief,
        user_id: UUID,
        request_key: UUID | None = None,
    ) -> UUID: ...

    def draft_for_request(self, *, tenant_id: UUID, request_key: UUID) -> UUID | None: ...


_ENABLED = text(
    "SELECT brand_id, connect -> :key AS setting, connect ->> 'sector' AS sector "
    "FROM brand_kit_details WHERE (connect -> :key ->> 'enabled') = 'true'"
)
# Insert the claim; a stale `pending` claim (a run that died) is taken over with its
# attempt (and key), a month skipped for lack of creations with the next one. RETURNING
# the attempt = this run won.
_CLAIM = text(
    "INSERT INTO monthly_posts (tenant_id, brand_id, period, event_id, event_date, "
    "calendar_version, kind, pipeline_version) VALUES (:tenant, :brand, :period, :event_id, "
    ":event_date, :calendar, :kind, :pipeline) "
    "ON CONFLICT ON CONSTRAINT uq_monthly_post DO UPDATE SET claimed_at = now(), "
    "updated_at = now(), status = 'pending', skip_reason = NULL, kind = EXCLUDED.kind, "
    "attempt = monthly_posts.attempt "
    "+ CASE WHEN monthly_posts.status = 'skipped' THEN 1 ELSE 0 END "
    "WHERE (monthly_posts.status = 'pending' "
    "AND monthly_posts.claimed_at < now() - make_interval(secs => :stale)) "
    "OR (monthly_posts.status = 'skipped' AND monthly_posts.skip_reason = :retryable) "
    "RETURNING attempt"
)
_SETTLE = text(
    "UPDATE monthly_posts SET status = :status, skip_reason = :reason, draft_id = :draft, "
    "updated_at = now() WHERE brand_id = :brand AND period = :period AND status = 'pending'"
)


class PostgresMonthlyPostStore:
    def enabled_brands(self, tenant_id: UUID) -> list[EnabledBrand]:
        with tenant_session(tenant_id) as session:
            rows = session.execute(_ENABLED, {"key": MONTHLY_POST_KEY}).all()
        brands = []
        for brand_id, setting, sector in rows:
            parsed = _from_document(setting)
            if parsed.enabled:  # the same reading as the screen: malformed = off
                brands.append(EnabledBrand(brand_id, parsed.kind, sector))
        return brands

    def claim(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        period: date,
        event: PlanDate | None,
        kind: str,
    ) -> int | None:
        with tenant_session(tenant_id) as session:
            return session.execute(
                _CLAIM,
                {
                    "tenant": tenant_id,
                    "brand": brand_id,
                    "period": period,
                    "event_id": event.id if event else None,
                    "event_date": event.start if event else None,
                    "calendar": TABLE_VERSION,
                    "kind": kind,
                    "pipeline": PIPELINE_VERSION,
                    "stale": STALE_CLAIM.total_seconds(),
                    "retryable": RETRYABLE_SKIP,
                },
            ).scalar_one_or_none()

    def settle(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        period: date,
        status: str,
        skip_reason: str | None = None,
        draft_id: UUID | None = None,
    ) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                _SETTLE,
                {
                    "status": status,
                    "reason": skip_reason,
                    "draft": draft_id,
                    "brand": brand_id,
                    "period": period,
                },
            )


@dataclass
class MonthlyPostJob:
    store: MonthlyPostStore
    drafts: Callable[[], Drafts]  # built only when a post is due (the real one is heavy)
    country_of: Callable[[UUID], str | None]
    owner_of: Callable[[UUID], UUID | None]

    def run(self, tenant_ids: Iterable[UUID], today: date) -> None:
        for tenant_id in tenant_ids:
            try:
                brands = self.store.enabled_brands(tenant_id)
            except Exception:  # noqa: BLE001 — one tenant must not stop the rest
                logger.exception("monthly_post.tenant_failed tenant=%s", tenant_id)
                continue
            for brand in brands:
                try:
                    self.run_brand(tenant_id, brand, today)
                except Exception:  # noqa: BLE001 — the row (if any) stays pending
                    logger.exception(
                        "monthly_post.brand_failed tenant=%s brand=%s", tenant_id, brand.brand_id
                    )

    def run_brand(self, tenant_id: UUID, brand: EnabledBrand, today: date) -> list[str]:
        """One brand, each period due today; returns what happened (logs and tests)."""
        return [self._run_period(tenant_id, brand, today, period) for period in periods(today)]

    def _run_period(self, tenant_id: UUID, brand: EnabledBrand, today: date, period: date) -> str:
        country = self.country_of(tenant_id)
        event: PlanDate | None = None
        reason: str | None = None
        if not country:
            reason = "no_country"
        else:
            try:
                event = event_of_month(country, brand.sector, period.year, period.month)
            except ValueError:
                reason = "no_calendar"
            else:
                if event is None:
                    reason = "no_event"
                elif event.start < today + timedelta(days=LEAD_DAYS):
                    return "too_late"  # nothing written, nothing charged
        attempt = self.store.claim(
            tenant_id=tenant_id,
            brand_id=brand.brand_id,
            period=period,
            event=event,
            kind=brand.kind.value,
        )
        if attempt is None:
            return "already_claimed"
        if reason is None and (user_id := self.owner_of(tenant_id)) is None:
            reason = "no_owner"
        if reason is not None:
            return self._skip(tenant_id, brand, period, reason)
        assert event is not None and user_id is not None
        return self._create(tenant_id, brand, period, event, user_id, attempt)

    def _create(
        self,
        tenant_id: UUID,
        brand: EnabledBrand,
        period: date,
        event: PlanDate,
        user_id: UUID,
        attempt: int,
    ) -> str:
        from qualify_api.creative.creations import NotEnoughCreations  # noqa: PLC0415
        from qualify_api.creative.service import (  # noqa: PLC0415
            BrandNotReady,
            RouteBlockedByPolicy,
        )

        key = request_key(brand.brand_id, period, attempt)
        drafts = self.drafts()
        try:
            brief = event_brief(brand.brand_id, event, brand.kind)
            draft_id = drafts.create_draft(
                tenant_id=tenant_id,
                brand_id=brand.brand_id,
                brief=brief,
                user_id=user_id,
                request_key=key,
            )
        except BrandNotReady:
            return self._skip(tenant_id, brand, period, "brand_not_ready")
        except NotEnoughCreations:
            # refused before the row, or the draft was failed uncharged (`create_draft`)
            return self._skip(tenant_id, brand, period, RETRYABLE_SKIP)  # retried daily
        except Exception as exc:
            # the draft may exist (and be charged): never assume, look it up by its key
            try:
                found = drafts.draft_for_request(tenant_id=tenant_id, request_key=key)
            except Exception:  # noqa: BLE001 — stays pending, the next run retries
                logger.exception("monthly_post.lookup_failed brand=%s", brand.brand_id)
                return "pending"
            if found is not None:
                logger.warning("monthly_post.created_with_error brand=%s: %s", brand.brand_id, exc)
                draft_id = found
            elif isinstance(exc, ValueError | RouteBlockedByPolicy):
                # the brief or the route is refused before any row or charge
                logger.info("monthly_post.refused brand=%s: %s", brand.brand_id, exc)
                return self._skip(tenant_id, brand, period, "brief_refused")
            else:
                logger.exception("monthly_post.create_failed brand=%s", brand.brand_id)
                return "pending"
        self.store.settle(
            tenant_id=tenant_id,
            brand_id=brand.brand_id,
            period=period,
            status="created",
            draft_id=draft_id,
        )
        logger.info(
            "monthly_post.created tenant=%s brand=%s event=%s draft=%s",
            tenant_id,
            brand.brand_id,
            event.id,
            draft_id,
        )
        return "created"

    def _skip(self, tenant_id: UUID, brand: EnabledBrand, period: date, reason: str) -> str:
        self.store.settle(
            tenant_id=tenant_id,
            brand_id=brand.brand_id,
            period=period,
            status="skipped",
            skip_reason=reason,
        )
        logger.info(
            "monthly_post.skipped tenant=%s brand=%s reason=%s", tenant_id, brand.brand_id, reason
        )
        return "skipped"


def _country_of(tenant_id: UUID) -> str | None:
    from qualify_api.tenancy.locale import read_business_locale  # noqa: PLC0415

    locale = read_business_locale(tenant_id)
    return locale.country if locale is not None else None


def production_job() -> MonthlyPostJob:
    from qualify_api.creative.composition import production_content_service  # noqa: PLC0415
    from qualify_api.planner.immediate import owner_of  # noqa: PLC0415

    return MonthlyPostJob(
        store=PostgresMonthlyPostStore(),
        drafts=functools.cache(production_content_service),  # built once per run
        country_of=_country_of,
        owner_of=owner_of,
    )


def daily_monthly_posts(tenant_ids: Iterable[UUID] | None) -> Callable[[], object]:
    """The calendar worker's chore: the same scope as its ticks."""
    scope = list(tenant_ids) if tenant_ids is not None else None

    def run() -> None:
        from qualify_api.referentes.reel_window_retention import (  # noqa: PLC0415
            all_tenant_ids,
        )

        now = datetime.now(UTC)
        production_job().run(scope if scope is not None else all_tenant_ids(now), now.date())

    return run
