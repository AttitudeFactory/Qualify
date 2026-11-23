"""Backend access for the budget step's suggestion (m-25091389). Call inside `acting_login`."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from uuid import UUID

from qualify_api.ads.budget_suggestion import (
    BudgetSuggestion,
    record_budget_suggestion,
    suggest_budget,
)
from qualify_api.ads.market_size import MarketEstimate

logger = logging.getLogger(__name__)


def read_budget_suggestion(
    tenant_id: UUID,
    source_id: UUID,
    market: MarketEstimate | None,
    start: datetime | None,
    end: datetime | None,
    daily_minimum_minor: int | None,
) -> BudgetSuggestion:
    """Reads Meta's daily minimum only when `daily_minimum_minor` is None (one GET)."""
    return asyncio.run(
        suggest_budget(
            tenant_id=tenant_id,
            publish_attempt_id=source_id,
            market=market,
            start_time=start,
            end_time=end,
            daily_minimum_minor=daily_minimum_minor,
        )
    )


def keep_budget_suggestion(
    tenant_id: UUID, promotion_id: UUID, suggestion: BudgetSuggestion
) -> None:
    """The suggestion shown before approval, kept with the prepared promotion (provenance).
    Never blocks the preview: a failed write is logged and the promotion goes on."""
    try:
        record_budget_suggestion(
            tenant_id=tenant_id, promotion_id=promotion_id, suggestion=suggestion
        )
    except Exception as exc:
        logger.warning("budget suggestion record failed: %s", type(exc).__name__)
