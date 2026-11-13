"""Immutable promotion requests and crash-safe, paused-only creation (m-24828974)."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_api.ads.client import MarketingAPI, Resource, _validate
from qualify_api.ads.errors import MarketingError

STEPS: tuple[Resource, ...] = ("campaigns", "adsets", "adcreatives", "ads")
ID_COLUMNS = dict(
    zip(STEPS, ("meta_campaign_id", "meta_adset_id", "meta_creative_id", "meta_ad_id"))
)
ADAPTER_VERSION = "ad-promotions-v1"


@dataclass(frozen=True)
class PromotionRequest:
    tenant_id: UUID
    brand_id: UUID
    request_key: str
    meta_ad_account_id: str
    objective: str
    cta_type: str
    link_url: str
    budget_kind: str
    budget_minor: int
    currency: str
    start_time: datetime
    end_time: datetime
    approved_by: UUID
    approved_at: datetime
    content_draft_id: UUID | None = None
    publish_attempt_id: UUID | None = None
    source_media_id: str | None = None
    special_ad_categories: tuple[str, ...] = ()
    targeting: dict[str, Any] = field(default_factory=dict)
    creative: dict[str, Any] = field(default_factory=dict)
    adset_options: dict[str, Any] = field(default_factory=dict)
    audience_snapshot: dict[str, Any] = field(default_factory=dict)
    messaging_snapshot: dict[str, Any] = field(default_factory=dict)
    enhancements_snapshot: dict[str, Any] = field(default_factory=dict)
    meta_currency_offset: int | None = None
    lead_form_snapshot: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        from qualify_api.ads.enhancements import validate_request_policy

        validate_request_policy(self)
        if self.messaging_snapshot:
            from qualify_api.ads.messaging import MessagingTarget

            MessagingTarget.from_snapshot(self.messaging_snapshot).validate_request(self)
        if self.lead_form_snapshot:
            from qualify_api.ads.lead_ads import LeadFormTarget

            LeadFormTarget.from_snapshot(self.lead_form_snapshot).validate_request(self)
        elif self.objective == "OUTCOME_LEADS":
            raise ValueError("a lead promotion requires an approved published form")
        if self.audience_snapshot:
            from qualify_api.ads.audience import AudienceDraft

            audience = AudienceDraft.from_snapshot(self.audience_snapshot)
            if audience.targeting() != self.targeting or audience.housing != (
                "HOUSING" in self.special_ad_categories
            ):
                raise ValueError("audience selection differs from approved targeting")
        elif "custom_audiences" in self.targeting:
            raise ValueError("custom audiences require a canonical audience selection")
        if not self.request_key.strip() or len(self.request_key) > 200:
            raise ValueError("invalid promotion request key")
        if not re.fullmatch(r"[0-9]+", self.meta_ad_account_id):
            raise ValueError("expected a numeric ad account id without act_ prefix")
        if self.budget_kind not in {"daily", "lifetime"} or type(self.budget_minor) is not int:
            raise ValueError("invalid budget kind or amount")
        if self.budget_minor <= 0 or not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("invalid budget or currency")
        if self.meta_currency_offset is not None and (
            type(self.meta_currency_offset) is not int
            or self.meta_currency_offset != 1
            or self.currency != "COP"
            or self.budget_minor * self.meta_currency_offset % 100
        ):
            raise ValueError("unrepresentable verified Meta currency amount")
        if (
            any(
                t.tzinfo is None or t.utcoffset() is None
                for t in (self.start_time, self.end_time, self.approved_at)
            )
            or self.end_time <= self.start_time
        ):
            raise ValueError("expected timezone-aware approval and increasing schedule")
        if (
            not self.objective
            or not self.cta_type
            or (
                not self.messaging_snapshot
                and not self.lead_form_snapshot
                and not self.link_url.startswith("https://")
            )
        ):
            raise ValueError("objective, CTA and HTTPS destination are required")
        if not (self.content_draft_id or self.publish_attempt_id or self.source_media_id):
            raise ValueError("promotion provenance is required")
        reserved = {
            "name",
            "status",
            "campaign_id",
            "adset_id",
            "creative",
            "account_id",
            "daily_budget",
            "lifetime_budget",
            "targeting",
            "start_time",
            "end_time",
        }
        if reserved.intersection(self.adset_options):
            raise ValueError("adset options cannot override promotion fields")
        if {"name", "status", "account_id"}.intersection(self.creative):
            raise ValueError("creative cannot override orchestration fields")
        _validate(
            {"targeting": self.targeting, "creative": self.creative, "options": self.adset_options}
        )

        def check_creative(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "call_to_action" and (
                        not isinstance(child, dict) or child.get("type") != self.cta_type
                    ):
                        raise ValueError("creative CTA differs from approved metadata")
                    if key == "link" and child != self.link_url:
                        raise ValueError("creative link differs from approved metadata")
                    if key == "source_instagram_media_id" and child != self.source_media_id:
                        raise ValueError("creative source differs from approved media")
                    check_creative(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    check_creative(child)
            elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
                raise ValueError("creative structures must be objects, not serialized JSON")

        check_creative(self.creative)
        snapshot = json.loads(json.dumps(asdict(self), default=_json_value))
        if not self.messaging_snapshot:
            # Preserve hashes/idempotency of approvals created before messaging support.
            snapshot.pop("messaging_snapshot", None)
        if not self.enhancements_snapshot:
            snapshot.pop("enhancements_snapshot", None)
        if not self.lead_form_snapshot:
            snapshot.pop("lead_form_snapshot", None)
        if self.meta_currency_offset is None:
            snapshot.pop("meta_currency_offset", None)
        return snapshot


def _json_value(value: Any) -> str:
    if isinstance(value, (UUID, datetime)):
        return str(value) if isinstance(value, UUID) else value.isoformat()
    raise TypeError("unsupported promotion value")


def fingerprint(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class Promotion:
    id: UUID
    request: dict[str, Any]
    status: str = "pending"
    ids: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CreationStep:
    resource: Resource
    payload: dict[str, Any]
    state: str
    claim_token: UUID
    meta_id: str | None = None


class PromotionRepository(Protocol):
    def current_enhancements(self, tenant_id: UUID, brand_id: UUID) -> dict[str, Any]: ...
    def by_request_key(self, tenant_id: UUID, request_key: str) -> Promotion | None: ...
    def create_or_get(self, request: PromotionRequest) -> Promotion: ...
    def get(self, tenant_id: UUID, promotion_id: UUID) -> Promotion | None: ...
    def step(
        self, tenant_id: UUID, promotion_id: UUID, resource: Resource
    ) -> CreationStep | None: ...
    def claim(
        self,
        tenant_id: UUID,
        promotion_id: UUID,
        resource: Resource,
        payload: dict[str, Any],
        token: UUID,
    ) -> bool: ...
    def complete(
        self, tenant_id: UUID, promotion_id: UUID, resource: Resource, token: UUID, meta_id: str
    ) -> bool: ...


@dataclass(frozen=True)
class AccountAccess:
    tenant_id: UUID
    brand_id: UUID
    meta_ad_account_id: str
    currency: str
    client: MarketingAPI


class AccountBinding(Protocol):
    """m-24828972 must implement this from authorized persisted account selection.

    No permissive production implementation is supplied in this module.
    """

    async def resolve(
        self, tenant_id: UUID, brand_id: UUID, meta_ad_account_id: str
    ) -> AccountAccess: ...


def step_payload(promotion: Promotion, resource: Resource) -> dict[str, Any]:
    request = promotion.request
    # A stable correlation label is a recovery hint, never a Meta idempotency key.
    name = f"qualify:{promotion.id}:{resource}:{fingerprint(request)[:16]}"
    if resource == "campaigns":
        return {
            "name": name,
            "status": "PAUSED",
            "objective": request["objective"],
            "special_ad_categories": request["special_ad_categories"],
        }
    if resource == "adsets":
        return {
            **request["adset_options"],
            "name": name,
            "status": "PAUSED",
            "campaign_id": promotion.ids["campaigns"],
            request["budget_kind"] + "_budget": (
                request["budget_minor"] * request["meta_currency_offset"] // 100
                if request.get("meta_currency_offset") is not None
                else request["budget_minor"]
            ),
            "start_time": request["start_time"],
            "end_time": request["end_time"],
            "targeting": request["targeting"],
        }
    if resource == "adcreatives":
        return {**request["creative"], "name": name}
    return {
        "name": name,
        "status": "PAUSED",
        "adset_id": promotion.ids["adsets"],
        "creative": {"creative_id": promotion.ids["adcreatives"]},
    }


class PromotionService:
    def __init__(self, repository: PromotionRepository, binding: AccountBinding) -> None:
        self.repository = repository
        self.binding = binding

    async def _access(self, promotion: Promotion) -> AccountAccess:
        request = promotion.request
        tenant, brand = UUID(request["tenant_id"]), UUID(request["brand_id"])
        access = await self.binding.resolve(tenant, brand, request["meta_ad_account_id"])
        if (access.tenant_id, access.brand_id, access.meta_ad_account_id, access.currency) != (
            tenant,
            brand,
            request["meta_ad_account_id"],
            request["currency"],
        ):
            raise ValueError("account binding does not match immutable promotion")
        return access

    async def start(
        self,
        request: PromotionRequest,
        *,
        before_write: Callable[[], Awaitable[None] | None] | None = None,
        validate_step: Callable[[Promotion, Resource, dict[str, Any]], Awaitable[None]]
        | None = None,
    ) -> Promotion:
        # Persist before resolving credentials or issuing any platform operation.
        promotion = self.repository.create_or_get(request)
        return await self.resume(
            request.tenant_id, promotion.id, before_write=before_write, validate_step=validate_step
        )

    async def resume(
        self,
        tenant_id: UUID,
        promotion_id: UUID,
        *,
        before_write: Callable[[], Awaitable[None] | None] | None = None,
        validate_step: Callable[[Promotion, Resource, dict[str, Any]], Awaitable[None]]
        | None = None,
    ) -> Promotion:
        promotion = self.repository.get(tenant_id, promotion_id)
        if promotion is None:
            raise LookupError("promotion not found")
        if not promotion.request.get("enhancements_snapshot") and len(promotion.ids) != len(STEPS):
            from qualify_api.ads.enhancements import EnhancementsUnavailable

            raise EnhancementsUnavailable(
                "Esta aprobación es anterior a los permisos de cambios. Prepara otra promoción."
            )
        for resource in STEPS:
            promotion = self.repository.get(tenant_id, promotion_id)
            assert promotion is not None
            if resource in promotion.ids:
                continue
            access = await self._access(promotion)
            existing = self.repository.step(tenant_id, promotion_id, resource)
            if existing is not None:
                # Never reset an in-flight claim to create-ready, even after a crash.
                found = await self._recover(access.client, existing)
                if found is None:
                    return promotion
                if not self.repository.complete(
                    tenant_id, promotion_id, resource, existing.claim_token, found
                ):
                    return self.repository.get(tenant_id, promotion_id) or promotion
                continue
            payload = step_payload(promotion, resource)
            if validate_step is not None:
                await validate_step(promotion, resource, payload)
            token = uuid4()
            if not self.repository.claim(tenant_id, promotion_id, resource, payload, token):
                return self.repository.get(tenant_id, promotion_id) or promotion
            # claim() must COMMIT independently before this call; cancellation or
            # persistence failure leaves a durable claim, which only recovery can finish.
            try:
                if before_write is None:
                    identifier = await access.client.create(resource, params=payload)
                else:
                    identifier = await access.client.create(
                        resource, params=payload, before_write=before_write
                    )
            except MarketingError:
                return self.repository.get(tenant_id, promotion_id) or promotion
            if not self.repository.complete(tenant_id, promotion_id, resource, token, identifier):
                return self.repository.get(tenant_id, promotion_id) or promotion
        result = self.repository.get(tenant_id, promotion_id)
        assert result is not None
        return result

    async def _recover(self, client: MarketingAPI, step: CreationStep) -> str | None:
        # Enumerate the bound account, never GET an arbitrary caller-provided id.
        # Zero matches (even after full pagination) does NOT prove remote absence.
        fields = ["id", "name"]
        if step.resource != "adcreatives":
            fields.append("status")
        if step.resource == "adsets":
            fields.append("campaign_id")
        if step.resource == "ads":
            fields.extend(("adset_id", "creative"))
        candidates: list[str] = []
        after: str | None = None
        visited: set[str] = set()
        while True:
            params: dict[str, Any] = {"fields": ",".join(fields), "limit": 100}
            if after:
                params["after"] = after
            page = await client.list(step.resource, params=params)
            for row in page.data:
                if row.get("name") != step.payload["name"]:
                    continue
                if step.resource != "adcreatives" and row.get("status") != "PAUSED":
                    continue
                if (
                    step.resource == "adsets"
                    and row.get("campaign_id") != step.payload["campaign_id"]
                ):
                    continue
                if step.resource == "ads":
                    creative = row.get("creative")
                    creative_id = (
                        creative.get("id", creative.get("creative_id"))
                        if isinstance(creative, dict)
                        else None
                    )
                    if (
                        row.get("adset_id") != step.payload["adset_id"]
                        or creative_id != step.payload["creative"]["creative_id"]
                    ):
                        continue
                identifier = row.get("id")
                if isinstance(identifier, str) and identifier.isdigit():
                    candidates.append(identifier)
            after = page.after
            if not after:
                break
            if after in visited:
                return None
            visited.add(after)
        return candidates[0] if len(candidates) == 1 else None
