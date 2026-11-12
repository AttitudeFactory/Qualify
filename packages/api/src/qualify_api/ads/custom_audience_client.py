"""Account-bound audience edge, separate from paused ad resource orchestration."""

from __future__ import annotations

from typing import Any

from qualify_api.ads.client import BeforeWrite, MarketingClient, MarketingPage, Payload, _id, _page
from qualify_api.ads.errors import MarketingError

AUDIENCE_FIELDS = "id,account_id,name,subtype,rule,lookalike_spec,operation_status,delivery_status"


class CustomAudienceClient:
    def __init__(self, marketing: MarketingClient) -> None:
        self.marketing = marketing

    async def terms(self) -> dict[str, Any]:
        return await self.marketing.read_account(fields="account_id,tos_accepted")

    async def read(self, audience_id: str) -> dict[str, Any]:
        return await self.marketing.read_object(_id(audience_id), fields=AUDIENCE_FIELDS)

    async def list(self, *, after: str | None = None) -> MarketingPage:
        return _page(
            await self.marketing._request(
                "GET",
                f"{self.marketing._account}/customaudiences",
                {"fields": AUDIENCE_FIELDS, "limit": 50, **({"after": after} if after else {})},
            )
        )

    async def create(self, params: Payload, *, before_write: BeforeWrite) -> str:
        if set(params) - {"name", "subtype", "rule", "origin_audience_id", "lookalike_spec"}:
            raise ValueError("unsupported custom audience fields")
        if params.get("subtype") == "ENGAGEMENT":
            expected = {"name", "subtype", "rule"}
        elif params.get("subtype") == "LOOKALIKE":
            expected = {"name", "subtype", "origin_audience_id", "lookalike_spec"}
        else:
            raise ValueError("unsupported custom audience subtype")
        if set(params) != expected:
            raise ValueError("incomplete custom audience request")
        value = await self.marketing._request(
            "POST",
            f"{self.marketing._account}/customaudiences",
            params,
            before_write=before_write,
        )
        identifier = value.get("id")
        if not isinstance(identifier, str) or not identifier.isascii() or not identifier.isdigit():
            raise MarketingError(
                "No pudimos confirmar la creación del público.", outcome_unknown=True
            )
        return identifier
