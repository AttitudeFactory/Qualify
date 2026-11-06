"""Versioned permission for four explicit Meta creative changes (m-24828984)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any
from uuid import UUID

FEATURES = ("image_touchups", "text_optimizations", "enhance_cta", "image_animation")
FEATURE_LABELS = {
    "image_touchups": "Retocar imágenes",
    "text_optimizations": "Ajustar textos",
    "enhance_cta": "Modificar el botón",
    "image_animation": "Animar imágenes",
}
PIPELINE_VERSION = "ad-enhancements-v1"
UNVERIFIED = (
    "Puedes guardar qué cambios permites a Meta. Todavía falta comprobar cuáles se pueden "
    "usar con una publicación ya publicada y revisar su vista previa antes de activarlos."
)


class EnhancementsUnavailable(ValueError):
    """Safe owner-readable error without database/provider material."""


def normalize(values: Any) -> dict[str, bool]:
    if (
        not isinstance(values, dict)
        or set(values) != set(FEATURES)
        or any(type(value) is not bool for value in values.values())
    ):
        raise EnhancementsUnavailable("Revisa los cambios que permites para tus anuncios.")
    return {key: values[key] for key in FEATURES}


@dataclass(frozen=True)
class BrandEnhancementSettings:
    tenant_id: UUID
    brand_id: UUID
    version: int = 0
    values: dict[str, bool] = field(default_factory=lambda: dict.fromkeys(FEATURES, False))
    updated_at: datetime | None = None

    def snapshot(self) -> dict[str, Any]:
        if (
            not isinstance(self.tenant_id, UUID)
            or not isinstance(self.brand_id, UUID)
            or type(self.version) is not int
            or self.version < 0
            or (self.version == 0 and any(normalize(self.values).values()))
        ):
            raise EnhancementsUnavailable("Vuelve a cargar los permisos de esta marca.")
        return {
            "tenant_id": str(self.tenant_id),
            "brand_id": str(self.brand_id),
            "version": self.version,
            "values": normalize(self.values),
            "pipeline_version": PIPELINE_VERSION,
        }

    @classmethod
    def from_snapshot(cls, value: Any) -> BrandEnhancementSettings:
        try:
            result = cls(
                UUID(value["tenant_id"]),
                UUID(value["brand_id"]),
                value["version"],
                normalize(value["values"]),
            )
            if result.snapshot() != value:
                raise ValueError("noncanonical settings")
            return result
        except (KeyError, TypeError, AttributeError, ValueError) as error:
            raise EnhancementsUnavailable("Vuelve a comprobar los permisos de la marca.") from error

    @property
    def enabled(self) -> bool:
        return any(normalize(self.values).values())

    @property
    def fingerprint(self) -> str:
        from qualify_api.ads.promotions import fingerprint

        return fingerprint(self.snapshot())

    def creative_spec(self) -> dict[str, Any]:
        return {
            "creative_features_spec": {
                key: {"enroll_status": "OPT_IN" if value else "OPT_OUT"}
                for key, value in normalize(self.values).items()
            }
        }


def validate_request_policy(
    request: Any, *, require: bool = False
) -> BrandEnhancementSettings | None:
    policy = request.enhancements_snapshot
    if not policy:
        if require:
            raise EnhancementsUnavailable(
                "Falta revisar los permisos de esta marca para el anuncio."
            )
        if "degrees_of_freedom_spec" in request.creative:
            raise EnhancementsUnavailable(
                "Los cambios del anuncio necesitan aprobación de la marca."
            )
        return None
    settings = BrandEnhancementSettings.from_snapshot(policy)
    if (str(settings.tenant_id), str(settings.brand_id)) != (
        str(request.tenant_id),
        str(request.brand_id),
    ):
        raise EnhancementsUnavailable("Estos permisos corresponden a otra marca.")
    if request.creative.get("degrees_of_freedom_spec") != settings.creative_spec():
        raise EnhancementsUnavailable("Los cambios del anuncio difieren de lo aprobado.")
    return settings


def compose_brand_policy(request: Any, settings: BrandEnhancementSettings) -> Any:
    """Build the exact request BEFORE approval; never mutate a stored approval."""
    if (request.tenant_id, request.brand_id) != (settings.tenant_id, settings.brand_id):
        raise EnhancementsUnavailable("Estos permisos corresponden a otra marca.")
    return replace(
        request,
        enhancements_snapshot=settings.snapshot(),
        creative={
            **request.creative,
            "degrees_of_freedom_spec": settings.creative_spec(),
        },
    )


def verify_compatibility(
    settings: BrandEnhancementSettings, source: Any, evidence: Any, now: datetime
) -> None:
    """An injected measured adapter must bind more than an eligibility boolean."""
    if not settings.enabled:
        return
    from qualify_api.ads.promotions import fingerprint

    expected = {
        "policy_fingerprint": settings.fingerprint,
        "creative_spec_fingerprint": fingerprint(settings.creative_spec()),
        "connection_id": str(source.connection_id),
        "credential_version": source.credential_version,
        "source_media_id": source.source_media_id,
        "instagram_user_id": source.instagram_user_id,
        "meta_ad_account_id": source.meta_ad_account_id,
        "eligible": True,
    }
    if (
        not isinstance(evidence, dict)
        or set(evidence) != set(expected) | {"checked_at", "expires_at", "pipeline_version"}
        or type(source.credential_version) is not int
        or source.credential_version <= 0
        or type(evidence.get("credential_version")) is not int
        or any(evidence.get(key) != value for key, value in expected.items())
        or evidence.get("eligible") is not True
        or not isinstance(evidence.get("pipeline_version"), str)
        or not evidence["pipeline_version"]
    ):
        raise EnhancementsUnavailable(UNVERIFIED)
    try:
        checked = datetime.fromisoformat(evidence["checked_at"])
        expiry = datetime.fromisoformat(evidence["expires_at"])
        valid = (
            checked.utcoffset() is not None
            and expiry.utcoffset() is not None
            and checked <= now < expiry
            and (now - checked).total_seconds() <= 300
            and (expiry - checked).total_seconds() <= 300
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise EnhancementsUnavailable("La comprobación de los cambios venció. Vuelve a revisarlos.")


def preview_receipt(
    promotion: Any,
    source: Any,
    actor: UUID,
    preview_hash: str,
    expires_at: datetime,
    observed_at: datetime,
) -> dict[str, Any]:
    from qualify_api.ads.promotions import fingerprint

    policy = BrandEnhancementSettings.from_snapshot(promotion.request["enhancements_snapshot"])
    return {
        "request_hash": fingerprint(promotion.request),
        "policy_fingerprint": policy.fingerprint,
        "creative_fingerprint": fingerprint(promotion.request["creative"]),
        "publish_attempt_id": str(source.publish_attempt_id),
        "connection_id": str(source.connection_id),
        "source_media_id": source.source_media_id,
        "credential_version": source.credential_version,
        "instagram_user_id": source.instagram_user_id,
        "ad_account_id": source.meta_ad_account_id,
        "ad_id": promotion.ids["ads"],
        "creative_id": promotion.ids["adcreatives"],
        "actor": str(actor),
        "preview_hash": preview_hash,
        "expires_at": expires_at.isoformat(),
        "observed_at": observed_at.isoformat(),
        "pipeline_version": "ad-enhancements-preview-v1",
    }


def verify_remote_preview(proof: Any, receipt: dict[str, Any], now: datetime) -> None:
    """Measured adapter's remote identity/payload proof, never inferred from HTML."""
    stable = {
        key: value
        for key, value in receipt.items()
        if key not in {"observed_at", "expires_at", "pipeline_version"}
    }
    if (
        not isinstance(proof, dict)
        or set(proof)
        != set(stable)
        | {"observed_at", "expires_at", "pipeline_version", "remote_creative_fingerprint"}
        or type(proof.get("credential_version")) is not int
        or any(proof.get(key) != value for key, value in stable.items())
        or proof.get("remote_creative_fingerprint") != receipt["creative_fingerprint"]
        or not isinstance(proof.get("pipeline_version"), str)
        or not proof["pipeline_version"]
    ):
        raise EnhancementsUnavailable(
            "Falta comprobar la pieza y los cambios reales de la vista previa."
        )
    try:
        observed = datetime.fromisoformat(proof["observed_at"])
        expiry = datetime.fromisoformat(proof["expires_at"])
        valid = (
            observed.utcoffset() is not None
            and expiry.utcoffset() is not None
            and observed <= now < expiry
            and (now - observed).total_seconds() <= 300
            and (expiry - observed).total_seconds() <= 300
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise EnhancementsUnavailable(
            "La comprobación de la vista previa venció. Vuelve a prepararla."
        )
