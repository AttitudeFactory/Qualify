"""Small, documented messaging-ad contracts; never authorizes live activation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

PIPELINE_VERSION = "ad-messaging-v1"


def numeric_id(value: Any) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[0-9]{1,40}", value) else None


def referral_ad_id(value: Any, *, channel: str) -> str | None:
    """Accept only the published referral subset; unknown data is simply unattributed.

    IG: Meta's harvested business-messaging/instagram-messaging/webhooks.md94–103.
    WA: Meta-owned WhatsApp Node SDK webhooks.ts ReferralObject and enums.ts139–142.
    The latter is historical, not evidence of a live 2026 payload.
    """
    if not isinstance(value, Mapping):
        return None
    if channel == "whatsapp" and value.get("source_type") == "ad":
        return numeric_id(value.get("source_id"))
    if channel == "dm" and value.get("source") == "ADS" and value.get("type") == "OPEN_THREAD":
        return numeric_id(value.get("ad_id"))
    return None


@dataclass(frozen=True)
class MessagingTarget:
    """Exact destination included in the immutable human-approved request snapshot.

    No legacy promotion acquires a destination from today's brand or phone mapping.
    Creating/activating a real ad still needs the existing measured eligibility gate.
    """

    destination_type: str
    source_connection_id: UUID
    target_connection_id: UUID
    page_id: str
    source_credential_version: int
    target_credential_version: int
    phone_number_id: str = ""
    whatsapp_phone_number: str = ""

    def snapshot(self) -> dict[str, Any]:
        if (
            self.destination_type not in {"WHATSAPP", "INSTAGRAM_DIRECT"}
            or not isinstance(self.source_connection_id, UUID)
            or not isinstance(self.target_connection_id, UUID)
            or numeric_id(self.page_id) is None
            or type(self.source_credential_version) is not int
            or self.source_credential_version < 1
            or type(self.target_credential_version) is not int
            or self.target_credential_version < 1
        ):
            raise ValueError("invalid messaging destination")
        if self.destination_type == "WHATSAPP":
            if numeric_id(self.phone_number_id) is None or not re.fullmatch(
                r"[1-9][0-9]{6,14}", self.whatsapp_phone_number
            ):
                raise ValueError("invalid WhatsApp destination")
        elif (
            self.target_connection_id != self.source_connection_id
            or self.phone_number_id
            or self.whatsapp_phone_number
        ):
            raise ValueError("Instagram destination must be the source account")
        return {
            key: str(value) if isinstance(value, UUID) else value
            for key, value in asdict(self).items()
        }

    @classmethod
    def from_snapshot(cls, value: dict[str, Any]) -> MessagingTarget:
        try:
            target = cls(
                destination_type=value["destination_type"],
                source_connection_id=UUID(value["source_connection_id"]),
                target_connection_id=UUID(value["target_connection_id"]),
                page_id=value["page_id"],
                source_credential_version=value["source_credential_version"],
                target_credential_version=value["target_credential_version"],
                phone_number_id=value.get("phone_number_id", ""),
                whatsapp_phone_number=value.get("whatsapp_phone_number", ""),
            )
            if target.snapshot() != value:
                raise ValueError("unexpected destination fields")
            return target
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("invalid messaging destination snapshot") from exc

    @property
    def cta_type(self) -> str:
        return "WHATSAPP_MESSAGE" if self.destination_type == "WHATSAPP" else "INSTAGRAM_MESSAGE"

    def validate_request(self, request: Any) -> None:
        self.snapshot()
        options = request.adset_options
        promoted = options.get("promoted_object")
        creative = request.creative
        creative_keys = {"source_instagram_media_id", "instagram_user_id", "call_to_action"}
        if getattr(request, "enhancements_snapshot", None):
            from qualify_api.ads.enhancements import validate_request_policy

            validate_request_policy(request)
            creative_keys.add("degrees_of_freedom_spec")
        promoted_keys = {"page_id"}
        if self.destination_type == "WHATSAPP":
            promoted_keys.add("whatsapp_phone_number")
        if (
            request.objective != "OUTCOME_ENGAGEMENT"
            or request.cta_type != self.cta_type
            or request.link_url
            or options.get("destination_type") != self.destination_type
            or options.get("optimization_goal") != "CONVERSATIONS"
            or not isinstance(creative, dict)
            or set(creative) != creative_keys
            or numeric_id(creative.get("instagram_user_id")) is None
            or creative.get("source_instagram_media_id") != request.source_media_id
            or creative.get("call_to_action") != {"type": self.cta_type}
            or not isinstance(promoted, dict)
            or set(promoted) != promoted_keys
            or promoted.get("page_id") != self.page_id
            or (
                self.destination_type == "WHATSAPP"
                and promoted.get("whatsapp_phone_number") != self.whatsapp_phone_number
            )
        ):
            raise ValueError("messaging destination differs from approved request")
