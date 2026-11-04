"""Strict, reconstructable audience selections; no policy or delivery guarantees."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

PLACEMENTS = {
    "instagram_feed": ("instagram", "stream"),
    "instagram_story": ("instagram", "story"),
    "instagram_reels": ("instagram", "reels"),
    "instagram_explore": ("instagram", "explore"),
    "facebook_feed": ("facebook", "feed"),
}


class AudienceUnavailable(ValueError):
    """A safe explanation, never a provider response."""


def _label(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value.strip()) <= 200
        and all(ord(c) >= 32 for c in value)
    )


@dataclass(frozen=True)
class LocationOption:
    key: str
    name: str
    type: str
    country_code: str = ""
    region: str = ""

    def validate(self) -> None:
        if (
            not isinstance(self.type, str)
            or self.type not in {"country", "region", "city"}
            or not _label(self.name)
        ):
            raise AudienceUnavailable("Elige un país, una región o una ciudad de la búsqueda.")
        if not isinstance(self.country_code, str) or not re.fullmatch(
            r"[A-Z]{2}", self.country_code
        ):
            raise AudienceUnavailable("Vuelve a buscar el lugar para comprobar su país.")
        if (
            not isinstance(self.key, str)
            or (self.type == "country" and self.key != self.country_code)
            or (self.type != "country" and not re.fullmatch(r"[0-9]{1,30}", self.key))
        ):
            raise AudienceUnavailable("Vuelve a elegir el lugar de la búsqueda.")
        if not isinstance(self.region, str) or len(self.region) > 200:
            raise AudienceUnavailable("Vuelve a elegir el lugar de la búsqueda.")


@dataclass(frozen=True)
class InterestOption:
    id: str
    name: str
    status: str = "unknown"

    def validate(self) -> None:
        if (
            not isinstance(self.id, str)
            or not re.fullmatch(r"[0-9]{1,30}", self.id)
            or not _label(self.name)
            or not isinstance(self.status, str)
            or self.status not in {"unknown", "active", "retiring", "unavailable"}
        ):
            raise AudienceUnavailable("Vuelve a elegir los intereses de la búsqueda.")


@dataclass(frozen=True)
class AudienceDraft:
    location: LocationOption | None = None
    radius_km: int | None = None
    age_min: int = 18
    age_max: int = 65
    gender: str = "all"
    interests: tuple[InterestOption, ...] = ()
    advantage_audience: bool = False
    housing: bool = False
    placements: tuple[str, ...] = ()

    def validate(self) -> None:
        if not isinstance(self.location, LocationOption):
            raise AudienceUnavailable("Busca y elige el lugar donde quieres mostrar el anuncio.")
        self.location.validate()
        if self.radius_km is not None and (
            type(self.radius_km) is not int
            or not 1 <= self.radius_km <= 80
            or self.location.type != "city"
        ):
            raise AudienceUnavailable("Revisa el radio de la ciudad elegida.")
        if (
            type(self.age_min) is not int
            or type(self.age_max) is not int
            or not 18 <= self.age_min <= self.age_max <= 65
            or not isinstance(self.gender, str)
            or self.gender not in {"all", "men", "women"}
            or type(self.housing) is not bool
            or type(self.advantage_audience) is not bool
        ):
            raise AudienceUnavailable("Revisa las edades y las opciones del público.")
        if not isinstance(self.interests, tuple) or len(self.interests) > 20:
            raise AudienceUnavailable("Elige hasta veinte intereses.")
        for interest in self.interests:
            if not isinstance(interest, InterestOption):
                raise AudienceUnavailable("Vuelve a elegir los intereses de la búsqueda.")
            interest.validate()
        if len({item.id for item in self.interests}) != len(self.interests):
            raise AudienceUnavailable("Hay intereses repetidos. Revisa la selección.")
        if (
            not isinstance(self.placements, tuple)
            or any(not isinstance(p, str) for p in self.placements)
            or len(set(self.placements)) != len(self.placements)
            or any(p not in PLACEMENTS for p in self.placements)
        ):
            raise AudienceUnavailable("Elige dónde quieres mostrar el anuncio.")

    def snapshot(self) -> dict[str, Any]:
        self.validate()
        return json.loads(json.dumps(asdict(self)))

    @classmethod
    def from_snapshot(cls, value: dict[str, Any]) -> AudienceDraft:
        try:
            if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
                raise ValueError
            result = cls(
                **{
                    **value,
                    "location": LocationOption(**value["location"]),
                    "interests": tuple(InterestOption(**item) for item in value["interests"]),
                    "placements": tuple(value["placements"]),
                }
            )
            result.validate()
            return result
        except (TypeError, KeyError, ValueError):
            raise AudienceUnavailable(
                "No pudimos recuperar este público. Elígelo de nuevo."
            ) from None

    def targeting(self) -> dict[str, Any]:
        self.validate()
        assert self.location is not None
        location = self.location
        if location.type == "country":
            geo = {"countries": [location.key]}
        else:
            item: dict[str, Any] = {"key": location.key}
            if self.radius_km is not None:
                item.update(radius=self.radius_km, distance_unit="kilometer")
            geo = {"cities" if location.type == "city" else "regions": [item]}
        result: dict[str, Any] = {
            "geo_locations": geo,
            "targeting_automation": {"advantage_audience": int(self.advantage_audience)},
            "publisher_platforms": ["facebook", "instagram"],
        }
        # An allowlist, rather than deleting known keys from untrusted targeting.
        if not self.housing:
            result.update(age_min=self.age_min, age_max=self.age_max)
            if self.gender != "all":
                result["genders"] = [1 if self.gender == "men" else 2]
            if self.interests:
                if any(item.status in {"retiring", "unavailable"} for item in self.interests):
                    raise AudienceUnavailable("Quita los intereses que Meta ya no permite usar.")
                result["flexible_spec"] = [
                    {"interests": [{"id": item.id} for item in self.interests]}
                ]
        if self.placements:
            result["publisher_platforms"] = sorted({PLACEMENTS[p][0] for p in self.placements})
            for platform in result["publisher_platforms"]:
                result[f"{platform}_positions"] = [
                    PLACEMENTS[p][1] for p in self.placements if PLACEMENTS[p][0] == platform
                ]
        return result

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class ReachEstimate:
    ready: bool = False
    lower: int | None = None
    upper: int | None = None
    message: str = "No hay una estimación disponible para este público."
    audience_hash: str = ""

    @classmethod
    def from_graph(cls, value: dict[str, Any], audience_hash: str) -> ReachEstimate:
        lower, upper = value.get("users_lower_bound"), value.get("users_upper_bound")
        if (
            value.get("estimate_ready") is True
            and type(lower) is int
            and type(upper) is int
            and 0 <= lower <= upper
        ):
            return cls(
                True,
                lower,
                upper,
                "Es una estimación de Meta, no un resultado garantizado.",
                audience_hash,
            )
        return cls(audience_hash=audience_hash)


@dataclass(frozen=True)
class SavedAudience:
    audience: AudienceDraft
    version: int
