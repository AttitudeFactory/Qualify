"""Injected spending-edit orchestration. No production preflight adapter is supplied.

The UI production wrapper permits only pause. A future measured eligibility adapter
must supply fresh, exact approval evidence before composing these paid edits.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from qualify_api.ads.client import MarketingAPI
from qualify_api.ads.promotions import fingerprint
from qualify_api.ads.results import MANAGEMENT_REASON, PromotionResults, ResultsUnavailable
from qualify_api.ads.results_service import ResultScope, _pause, _scope
from qualify_api.tenancy.acting import current_acting_login


def edit_scope_hash(scope: ResultScope) -> str:
    return fingerprint(
        {
            "tenant": str(scope.tenant_id),
            "promotion": str(scope.promotion_id),
            "account": str(scope.account_id),
            "connection": str(scope.connection.connection_id),
            "version": scope.connection.version,
            "ad": scope.ad_id,
            "adset": scope.adset_id,
            "campaign": scope.campaign_id,
            "currency": scope.currency,
            "timezone": scope.timezone_name,
        }
    )


@dataclass(frozen=True)
class PromotionEdit:
    action: str
    budget_kind: str = ""
    budget_minor: int | None = None
    end_time: datetime | None = None

    def payload(self) -> dict[str, Any]:
        if self.action == "resume" and self.budget_minor is None and self.end_time is None:
            return {"status": "ACTIVE"}
        if (
            self.action == "budget"
            and self.budget_kind in {"daily", "lifetime"}
            and type(self.budget_minor) is int
            and self.budget_minor > 0
            and self.end_time is None
        ):
            return {f"{self.budget_kind}_budget": self.budget_minor}
        if (
            self.action == "end_time"
            and self.budget_minor is None
            and isinstance(self.end_time, datetime)
            and self.end_time.utcoffset() is not None
        ):
            return {"end_time": self.end_time.isoformat()}
        raise ResultsUnavailable("Revisa el cambio y vuelve a confirmarlo.")


@dataclass(frozen=True)
class VerifiedEditApproval:
    """Exact-intent consent plus measured preflight. Never generated from cached health."""

    tenant_id: UUID
    promotion_id: UUID
    account_id: UUID
    credential_version: int
    acting_login: UUID
    intent_hash: str
    expires_at: datetime
    confirmed: bool
    billing_ready: bool
    eligible: bool
    budget_kind: str
    minimum_budget_minor: int
    spend_minor: int
    current_start_time: datetime
    pipeline_version: str
    scope_hash: str = ""

    def validate(self, scope: ResultScope, edit: PromotionEdit, now: datetime) -> None:
        if (
            (self.tenant_id, self.promotion_id, self.account_id, self.credential_version)
            != (scope.tenant_id, scope.promotion_id, scope.account_id, scope.connection.version)
            or self.acting_login != current_acting_login()
            or self.scope_hash != edit_scope_hash(scope)
            or self.intent_hash != fingerprint({"action": edit.action, "payload": edit.payload()})
            or self.confirmed is not True
            or self.billing_ready is not True
            or self.eligible is not True
            or not self.pipeline_version
            or self.expires_at.utcoffset() is None
            or self.expires_at <= now
            or self.budget_kind not in {"daily", "lifetime"}
            or type(self.minimum_budget_minor) is not int
            or self.minimum_budget_minor <= 0
            or type(self.spend_minor) is not int
            or self.spend_minor < 0
            or self.current_start_time.utcoffset() is None
        ):
            raise ResultsUnavailable(MANAGEMENT_REASON)
        if edit.action == "budget" and (
            edit.budget_kind != self.budget_kind
            or edit.budget_minor < self.minimum_budget_minor
            or (self.budget_kind == "lifetime" and edit.budget_minor < self.spend_minor)
        ):
            raise ResultsUnavailable(
                "El presupuesto debe cubrir lo gastado y el mínimo comprobado."
            )
        if edit.action == "end_time" and edit.end_time <= max(now, self.current_start_time):
            raise ResultsUnavailable(
                "La fecha de fin debe ser posterior al inicio y al momento actual."
            )


class EditApprovalGateway(Protocol):
    async def verify(self, scope: ResultScope, edit: PromotionEdit) -> VerifiedEditApproval: ...


async def apply_verified_edit(
    *,
    tenant_id: UUID,
    promotion_id: UUID,
    request_key: str,
    edit: PromotionEdit,
    api: MarketingAPI,
    approvals: EditApprovalGateway,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> PromotionResults:
    """For explicitly injected verified adapters/tests; production never calls this."""
    payload = edit.payload()
    scope = _scope(tenant_id, promotion_id)
    approval = await approvals.verify(scope, edit)

    def guard(current: ResultScope) -> None:
        approval.validate(current, edit, clock())

    guard(scope)
    evidence = asdict(approval)
    evidence = {
        key: str(value) if isinstance(value, (UUID, datetime)) else value
        for key, value in evidence.items()
    }
    return await _pause(
        tenant_id,
        promotion_id,
        request_key,
        api=api,
        action=edit.action,
        payload=payload,
        evidence=evidence,
        spending_guard=guard,
    )
