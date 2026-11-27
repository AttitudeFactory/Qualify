"""Translate authenticated backend observations to display-only view models."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
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
    ADVICE_LABELS,
    ADVICE_TONES,
    ALERTS_ALREADY_ON,
    ALERTS_ON,
    EDIT_ACTION_LABELS,
    EDIT_UNKNOWN,
    AdAdviceVM,
    AdDayVM,
    AdDetailVM,
    AdEditOutcomeVM,
    AdEditReviewVM,
    AdResultVM,
    AlertAccountVM,
    backend_action,
    budget_down_summary,
    budget_input,
    date_label,
    day_label,
    end_input,
    floor_label,
    money_label,
    number_label,
    rejection_text,
    status_tone,
)

logger = logging.getLogger(__name__)


def summary_vm(row: PromotionResultSummary) -> AdResultVM:
    current_budget = getattr(row, "current_budget_minor", None)
    current_end = getattr(row, "current_end_time", None)
    current_budget_valid = type(current_budget) is int and current_budget > 0
    current_end_valid = isinstance(current_end, datetime) and current_end.utcoffset() is not None
    operation_pending = getattr(row, "operation_pending", False) is True
    story = getattr(row, "story", False) is True
    fresh = not row.stale and not row.refresh_failed and not operation_pending
    return AdResultVM(
        id=str(row.id),
        title=row.caption or ("Anuncio de tu historia" if story else "Anuncio de tu publicación"),
        story=story,
        account=row.account_name or "Cuenta por comprobar",
        status=row.status,
        status_label=("Último estado: " if row.stale or row.refresh_failed else "")
        + row.status_label,
        tone="warn" if row.stale or row.refresh_failed else status_tone(row.status),
        approved_budget=money_label(Decimal(row.budget_minor) / 100, row.currency),
        end_label=date_label(row.end_time, row.timezone_name),
        checked_label=date_label(row.checked_at, row.timezone_name),
        # m-25072681: an unresolved edit does not hide the pause (the brake).
        can_pause=row.can_pause is True and not row.stale and not row.refresh_failed,
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
        rejected=row.status == "DISAPPROVED",
        rejection_reason=rejection_text(row.status, row.rejection_reason),
        fix_href=f"/drafts/{draft}"
        if (draft := getattr(row, "content_draft_id", None))
        else "/drafts",
    )


def advice_vm(result: PromotionResults) -> AdAdviceVM:
    """The stored traffic light of these results; hidden when absent or stale (the backend
    only returns one with QUALIFY_ADS_TRAFFIC_LIGHT on)."""
    from qualify_api.ads.traffic_light import message, meta_notices, suggested_budget

    advice, row = getattr(result, "advice", None), result.promotion
    if advice is None or result.insights_stale or result.insights_refresh_failed:
        return AdAdviceVM()
    current = row.current_budget_minor
    amount = (
        suggested_budget(advice, current, row.currency)
        if type(current) is int and row.can_manage
        else None
    )
    return AdAdviceVM(
        shown=True,
        tone=ADVICE_TONES[advice.light],
        label=ADVICE_LABELS[advice.action],
        message=message(advice, row.currency),
        meta=list(meta_notices(advice)),
        can_raise=amount is not None,
        raise_label=f"Subir a {money_label(Decimal(amount) / 100, row.currency)}"
        if amount is not None
        else "",
        raise_input=budget_input(amount, row.currency) if amount is not None else "",
        new_piece=advice.action == "fatigue" or "CREATIVE_FATIGUE" in advice.meta,
        profile_link=advice.reason == "no_profile",
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
        advice=advice_vm(result),
    )


def read_floor(tenant_id: UUID, promotion_id: UUID, currency: str) -> tuple[str, str]:
    """(label, floor in whole units of `currency`) for lowering a budget; read-only."""
    from qualify_api.ads.results_service import read_budget_floor

    floor = asyncio.run(read_budget_floor(tenant_id=tenant_id, promotion_id=promotion_id))
    if any(
        # USD/UYU minimums and spend may carry cents; the input is rounded up to a whole unit.
        type(value) is not int or value < 0
        for value in (floor.floor_minor, floor.spent_minor)
    ):
        raise ResultsUnavailable("Vuelve a consultar el mínimo con Meta.")
    whole = -(-floor.floor_minor // 100)  # a cents floor shows and checks as the next unit
    return floor_label(whole * 100, floor.spent_minor, currency), str(whole)


def alert_accounts(tenant_id: UUID) -> list[AlertAccountVM]:
    """The ad accounts this business chose for ads (one per brand), for «Activar avisos»."""
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import text

    with tenant_session(tenant_id) as session:
        rows = session.execute(
            text("SELECT id,name FROM ad_accounts WHERE selected AND available ORDER BY name,id")
        ).all()
    return [AlertAccountVM(str(row.id), row.name or "Tu cuenta publicitaria") for row in rows]


def activate_alerts(tenant_id: UUID, ad_account_id: UUID) -> str:
    """Owner-confirmed subscription to Meta's ad-account notices; never automatic."""
    from qualify_api.ads.status_webhook import subscribe_ad_account_webhooks

    created = asyncio.run(
        subscribe_ad_account_webhooks(
            tenant_id=tenant_id, ad_account_id=ad_account_id, confirmed=True
        )
    )
    return ALERTS_ON if created else ALERTS_ALREADY_ON


def load_ads(tenant_id: UUID) -> list[AdResultVM]:
    return [
        replace(summary_vm(row), story_image=story_image(tenant_id, row.story_image_key))
        if getattr(row, "story", False) is True
        else summary_vm(row)
        for row in list_promotion_results(tenant_id=tenant_id)
    ]


def story_image(tenant_id: UUID, key: str) -> str:
    """N3: a story ad's 9:16 picture in «Anuncios»; "" (no picture) rather than a failure."""
    from .r2_media import issue_view_path  # noqa: PLC0415

    try:
        return issue_view_path(tenant_id, key, "image") if key else ""
    except Exception as exc:  # noqa: BLE001 — a thumbnail is not worth failing the list
        logger.warning("story ad image not issued: %s", type(exc).__name__)
        return ""


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
    currency: str,
    budget_minor: int | None = None,
    end_time: datetime | None = None,
    advised: bool = False,
) -> PreparedAdEdit:
    """`advised`: the traffic light's raise (m-25091390), prepared from the stored advice so
    its provenance travels with the owner's confirmation; it must match `budget_minor`."""
    from qualify_api.ads.results_service import prepare_promotion_edit
    from qualify_api.ads.traffic_light import prepare_advised_raise

    result = asyncio.run(
        prepare_advised_raise(
            tenant_id=tenant_id, promotion_id=promotion_id, request_key=request_key
        )
        if advised and action == "budget"
        else prepare_promotion_edit(
            tenant_id=tenant_id,
            promotion_id=promotion_id,
            request_key=request_key,
            action=backend_action(action),
            budget_minor=budget_minor,
            end_time=end_time,
        )
    )
    if advised and result.new_budget_minor != budget_minor:
        # The advice moved since the screen showed it: never confirm another amount.
        raise ResultsUnavailable("Vuelve a comprobar este cambio antes de confirmarlo.")
    now = datetime.now(UTC)
    if (
        action not in EDIT_ACTION_LABELS
        or result.action != backend_action(action)
        or (
            action == "budget_down"
            and not (
                type(result.new_budget_minor) is int
                and type(result.current_budget_minor) is int
                and result.new_budget_minor < result.current_budget_minor
            )
        )
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
            summary=budget_down_summary(
                result.current_budget_minor, result.new_budget_minor, currency
            )
            if action == "budget_down"
            else result.summary,
            current_budget=money_label(Decimal(result.current_budget_minor) / 100, currency),
            new_budget=money_label(Decimal(result.new_budget_minor) / 100, currency),
            current_end=date_label(result.current_end_time, timezone_name),
            new_end=date_label(result.new_end_time, timezone_name),
            expires_label=date_label(result.expires_at, timezone_name),
            ready=True,
            end_changed=result.new_end_time != result.current_end_time,
            budget_changed=result.new_budget_minor != result.current_budget_minor,
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
    valid = result.action == backend_action(action) and str(result.promotion_id) == expected_id
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
