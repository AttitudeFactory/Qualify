"""Backend access for «Tu plan del mes» (m-25091392). Call inside `acting_login`."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from qualify_api.ads.investment_profile import load_investment_profile
from qualify_api.ads.month_plan import month_plan
from qualify_api.planner.composition import tenant_timezone

from .ad_month_plan_vm import MonthPlanVM, month_pair, month_plan_vm


def read_month_plans(tenant_id: UUID, brand_id: UUID) -> list[MonthPlanVM]:
    """This month and the next one, in the business's own calendar; [] when the owner has no
    investment profile yet (the profile card above already asks for it, so the plan hides).
    Raises `MonthPlanUnavailable` with a message to show as is."""
    if load_investment_profile(tenant_id=tenant_id, brand_id=brand_id) is None:
        return []
    today = datetime.now(UTC).astimezone(ZoneInfo(tenant_timezone(tenant_id))).date()
    return [
        month_plan_vm(
            month_plan(tenant_id=tenant_id, brand_id=brand_id, year=year, month=month),
            year,
            month,
        )
        for year, month in month_pair(today)
    ]
