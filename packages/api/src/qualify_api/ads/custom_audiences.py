"""Explicit Instagram audience requests and immutable promotion selections (m-24828983)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from qualify_api.ads.audience import AudienceUnavailable

KINDS = frozenset({"engagement", "messages", "lookalike"})
EVENTS = {"engagement": "ig_business_profile_all", "messages": "ig_user_messaged_business"}


def numeric_id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,30}", value):
        raise AudienceUnavailable("No pudimos comprobar la identidad del público en Meta.")
    return value


def audience_name(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value.strip()) <= 100
        or any(ord(c) < 32 for c in value)
    ):
        raise AudienceUnavailable("Escribe un nombre de hasta cien letras para el público.")
    return value.strip()


@dataclass(frozen=True)
class CustomAudienceSelection:
    local_id: str
    id: str
    name: str
    kind: str

    def validate(self) -> None:
        try:
            if str(UUID(self.local_id)) != self.local_id:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise AudienceUnavailable("Vuelve a elegir el público de este negocio.") from None
        numeric_id(self.id)
        audience_name(self.name)
        if not isinstance(self.kind, str) or self.kind not in KINDS:
            raise AudienceUnavailable("Vuelve a elegir el tipo de público.")


@dataclass(frozen=True)
class CustomAudienceRequest:
    name: str
    kind: str = "engagement"
    retention_days: int = 365
    seed_id: str = ""
    country: str = "CO"
    ratio: float = 0.01

    def validate(self) -> None:
        audience_name(self.name)
        if not isinstance(self.kind, str) or self.kind not in KINDS:
            raise AudienceUnavailable("Elige personas que interactuaron, escribieron o similares.")
        if type(self.retention_days) is not int or not 1 <= self.retention_days <= 730:
            raise AudienceUnavailable("Elige un periodo entre uno y setecientos treinta días.")
        if self.kind == "lookalike":
            try:
                UUID(self.seed_id)
            except (ValueError, TypeError, AttributeError):
                raise AudienceUnavailable(
                    "Elige primero un público de origen de este negocio."
                ) from None
            if not isinstance(self.country, str) or not re.fullmatch(r"[A-Z]{2}", self.country):
                raise AudienceUnavailable("Elige el país del público similar.")
            if (
                type(self.ratio) not in {float, int}
                or not math.isfinite(self.ratio)
                or not 0.01 <= self.ratio <= 0.20
            ):
                raise AudienceUnavailable("Revisa el tamaño del público similar.")
        elif self.seed_id:
            raise AudienceUnavailable("Este tipo de público no necesita un público de origen.")

    def payload(self, instagram_id: str, *, seed_meta_id: str = "") -> dict[str, Any]:
        self.validate()
        numeric_id(instagram_id)
        if self.kind == "lookalike":
            return {
                "name": audience_name(self.name),
                "subtype": "LOOKALIKE",
                "origin_audience_id": numeric_id(seed_meta_id),
                "lookalike_spec": {
                    "type": "custom_ratio",
                    "country": self.country,
                    "ratio": self.ratio,
                },
            }
        # Primary Meta SDK platform-engagement example + official IG event changelog.
        # Meta, rather than this local template, decides current regional eligibility.
        return {
            "name": audience_name(self.name),
            "subtype": "ENGAGEMENT",
            "rule": {
                "inclusions": {
                    "operator": "or",
                    "rules": [
                        {
                            "event_sources": [{"id": instagram_id, "type": "ig_business"}],
                            "retention_seconds": self.retention_days * 86400,
                            "filter": {
                                "operator": "and",
                                "filters": [
                                    {"field": "event", "operator": "eq", "value": EVENTS[self.kind]}
                                ],
                            },
                        }
                    ],
                }
            },
        }

    def snapshot(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class CustomAudienceSummary:
    id: UUID
    name: str
    kind: str
    status: str
    meta_audience_id: str = ""
    available: bool = False
    reason: str = ""

    def selection(self) -> CustomAudienceSelection:
        if not self.available or self.status != "created":
            raise AudienceUnavailable("Meta todavía no confirmó que puedas usar este público.")
        result = CustomAudienceSelection(str(self.id), self.meta_audience_id, self.name, self.kind)
        result.validate()
        return result


@dataclass(frozen=True)
class CustomAudienceCatalog:
    terms_accepted: bool | None
    creation_available: bool
    reason: str
    audiences: tuple[CustomAudienceSummary, ...] = ()


def accepted_terms(value: Any, account_id: str) -> bool | None:
    if not isinstance(value, dict) or value.get("account_id") != numeric_id(account_id):
        return None
    terms = value.get("tos_accepted")
    if not isinstance(terms, dict):
        return None
    accepted = terms.get("custom_audience_tos")
    # bool is an int subclass, but not evidence for Meta's map<string,int> contract.
    return accepted == 1 if type(accepted) is int and accepted in {0, 1} else None


def ready_audience(value: Any, *, remote_id: str, account_id: str) -> bool:
    return (
        isinstance(value, dict)
        and value.get("id") == remote_id
        and value.get("account_id") == account_id
        and all(
            isinstance(value.get(field), dict)
            and type(value[field].get("code")) is int
            and value[field]["code"] == 200
            for field in ("operation_status", "delivery_status")
        )
    )
