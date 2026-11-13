"""Translate authenticated backend observations to display-only view models."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from qualify_api.ads.results import PromotionResults, PromotionResultSummary, ResultsUnavailable
from qualify_api.ads.results_service import (
    edit_promotion,
    list_promotion_results,
    load_promotion_results,
    refresh_promotion_results,
)

from .ad_results_vm import (
    EDIT_ACTION_LABELS,
    EDIT_UNKNOWN,
    AdDayVM,
    AdDetailVM,
    AdEditOutcomeVM,
    AdEditReviewVM,
    AdResultVM,
    budget_input,
    date_label,
    day_label,
    end_input,
    money_label,
    number_label,
    status_tone,
)


def summary_vm(row: PromotionResultSummary) -> AdResultVM:
    current_budget = getattr(row, "current_budget_minor", None)
    current_end = getattr(row, "current_end_time", None)
    current_budget_valid = type(current_budget) is int and current_budget > 0
    current_end_valid = isinstance(current_end, datetime) and current_end.utcoffset() is not None
    operation_pending = getattr(row, "operation_pending", False) is True
    fresh = not row.stale and not row.refresh_failed and not operation_pending
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
        can_pause=row.can_pause is True and fresh,
        can_manage=row.can_manage is True and fresh,
        management_reason=row.management_reason,
        currency=row.currency,
        timezone_name=row.timezone_name,
        stale=row.stale,
        refresh_failed=row.refresh_failed,
        current_budget=money_label(Decimal(current_budget) / 100, row.currency)
        if current_budget_valid
        else "Presupuesto actual por comprobar",
        current_end_label=date_label(current_end, row.timezone_name)
        if current_end_valid
        else "Final actual por comprobar",
        current_budget_input=budget_input(current_budget, row.currency),
        current_end_input=end_input(current_end, row.timezone_name) if current_end_valid else "",
        can_resume=getattr(row, "can_resume", False) is True and fresh,
        operation_pending=operation_pending,
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
        observed_conversations=number_label(result.observed_conversations),
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


@dataclass(frozen=True)
class PreparedAdEdit:
    review: AdEditReviewVM
    approval_token: str = field(repr=False)
    expires_at: datetime


def prepare_edit(
    tenant_id: UUID,
    promotion_id: UUID,
    request_key: str,
    action: str,
    timezone_name: str,
    *,
    budget_minor: int | None = None,
    end_time: datetime | None = None,
) -> PreparedAdEdit:
    from qualify_api.ads.results_service import prepare_promotion_edit

    result = asyncio.run(
        prepare_promotion_edit(
            tenant_id=tenant_id,
            promotion_id=promotion_id,
            request_key=request_key,
            action=action,
            budget_minor=budget_minor,
            end_time=end_time,
        )
    )
    now = datetime.now(UTC)
    if (
        action not in EDIT_ACTION_LABELS
        or result.action != action
        or not isinstance(result.approval_token, str)
        or not result.approval_token
        or not isinstance(result.expires_at, datetime)
        or result.expires_at.utcoffset() is None
        or result.expires_at <= now
        or any(
            type(value) is not int or value <= 0 or value % 100
            for value in (result.current_budget_minor, result.new_budget_minor)
        )
        or any(
            not isinstance(value, datetime) or value.utcoffset() is None
            for value in (result.current_end_time, result.new_end_time)
        )
    ):
        raise ResultsUnavailable("Vuelve a comprobar este cambio antes de confirmarlo.")
    return PreparedAdEdit(
        AdEditReviewVM(
            action=action,
            title=EDIT_ACTION_LABELS[action],
            summary=result.summary,
            current_budget=money_label(Decimal(result.current_budget_minor) / 100, "COP"),
            new_budget=money_label(Decimal(result.new_budget_minor) / 100, "COP"),
            current_end=date_label(result.current_end_time, timezone_name),
            new_end=date_label(result.new_end_time, timezone_name),
            expires_label=date_label(result.expires_at, timezone_name),
            ready=True,
        ),
        result.approval_token,
        result.expires_at,
    )


def confirm_edit(
    tenant_id: UUID,
    promotion_id: UUID,
    request_key: str,
    action: str,
    approval_token: str,
) -> AdEditOutcomeVM:
    from qualify_api.ads.results_service import confirm_promotion_edit

    result = asyncio.run(
        confirm_promotion_edit(
            tenant_id=tenant_id,
            promotion_id=promotion_id,
            request_key=request_key,
            approval_token=approval_token,
            confirm_change=True,
        )
    )
    expected_id = str(promotion_id)
    valid = result.action == action and str(result.promotion_id) == expected_id
    status = (
        result.status
        if valid and result.status in {"completed", "unknown", "pending"}
        else "unknown"
    )
    details = result.results if valid else None
    if details is not None and str(details.promotion.id) != expected_id:
        status, details = "unknown", None
    return AdEditOutcomeVM(
        expected_id,
        action,
        status,
        result.message if valid and status != "unknown" else EDIT_UNKNOWN,
        detail_vm(details) if details is not None else None,
    )
