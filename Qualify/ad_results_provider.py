"""Translate authenticated backend observations to display-only view models."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import UUID

from qualify_api.ads.results import PromotionResults, PromotionResultSummary
from qualify_api.ads.results_service import (
    edit_promotion,
    list_promotion_results,
    load_promotion_results,
    refresh_promotion_results,
)

from .ad_results_vm import (
    AdDayVM,
    AdDetailVM,
    AdResultVM,
    date_label,
    day_label,
    money_label,
    number_label,
    status_tone,
)


def summary_vm(row: PromotionResultSummary) -> AdResultVM:
    return AdResultVM(
        id=str(row.id),
        title=row.caption or "Anuncio de tu publicación",
        account=row.account_name or "Cuenta por comprobar",
        status=row.status,
        status_label=("Último estado: " if row.stale or row.refresh_failed else "")
        + row.status_label,
        tone="warn" if row.stale or row.refresh_failed else status_tone(row.status),
        approved_budget=money_label(Decimal(row.budget_minor) / 100, row.currency),
        end_label=date_label(row.end_time, row.timezone_name),
        checked_label=date_label(row.checked_at, row.timezone_name),
        rejection_reason=row.rejection_reason,
        can_pause=row.can_pause and not row.stale and not row.refresh_failed,
        can_manage=row.can_manage,
        management_reason=row.management_reason,
        currency=row.currency,
        timezone_name=row.timezone_name,
        stale=row.stale,
        refresh_failed=row.refresh_failed,
    )


def detail_vm(result: PromotionResults) -> AdDetailVM:
    zone = result.promotion.timezone_name
    return AdDetailVM(
        promotion=summary_vm(result.promotion),
        days=[
            AdDayVM(
                day=row.day.isoformat(),
                label=day_label(row.day, zone),
                spend=money_label(row.spend, row.currency),
                clicks=number_label(row.clicks),
                reach=number_label(row.reach),
                impressions=number_label(row.impressions),
                ctr=(number_label(row.ctr, decimals=2) + " %")
                if row.ctr is not None
                else "Sin datos",
                cpc=money_label(row.cpc, row.currency),
                cpm=money_label(row.cpm, row.currency),
            )
            for row in sorted(result.daily, key=lambda row: row.day, reverse=True)
        ],
        notice=result.notice,
        updated_label=date_label(result.updated_at, zone),
        insights_stale=result.insights_stale,
        insights_refresh_failed=result.insights_refresh_failed,
    )


def load_ads(tenant_id: UUID) -> list[AdResultVM]:
    return [summary_vm(row) for row in list_promotion_results(tenant_id=tenant_id)]


def load_ad(tenant_id: UUID, promotion_id: UUID) -> AdDetailVM:
    return detail_vm(load_promotion_results(tenant_id=tenant_id, promotion_id=promotion_id))


def refresh_ad(tenant_id: UUID, promotion_id: UUID) -> AdDetailVM:
    return detail_vm(
        asyncio.run(refresh_promotion_results(tenant_id=tenant_id, promotion_id=promotion_id))
    )


def pause_ad(tenant_id: UUID, promotion_id: UUID, request_key: str) -> AdDetailVM:
    return detail_vm(
        asyncio.run(
            edit_promotion(
                tenant_id=tenant_id,
                promotion_id=promotion_id,
                action="pause",
                request_key=request_key,
            )
        )
    )
