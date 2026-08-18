"""Per-tenant Microsoft Clarity Data Export integration (migration 0006).

The published seam, mirroring `leads/__init__.py`:

- `ClarityService` (`service.py`) — configure / latest / refresh with the daily budget.
- `production_clarity_service` (`composition.py`) — the wired production instance.
- The client error family (`client.py`) — what callers catch to explain a failure.
"""

from qualify_api.clarity.client import (
    ALLOWED_DIMENSIONS,
    ClarityAPIError,
    ClarityBadRequest,
    ClarityQuotaExceeded,
    ClarityUnauthorized,
)
from qualify_api.clarity.composition import production_clarity_service
from qualify_api.clarity.service import (
    DAILY_REFRESH_BUDGET,
    ClarityNotConfigured,
    ClarityService,
    RefreshBudgetExhausted,
    SettingsStatus,
)

__all__ = [
    "ALLOWED_DIMENSIONS",
    "DAILY_REFRESH_BUDGET",
    "ClarityAPIError",
    "ClarityBadRequest",
    "ClarityNotConfigured",
    "ClarityQuotaExceeded",
    "ClarityService",
    "ClarityUnauthorized",
    "RefreshBudgetExhausted",
    "SettingsStatus",
    "production_clarity_service",
]
