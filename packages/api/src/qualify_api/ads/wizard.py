"""Published-post preparation and an explicitly injected promotion execution boundary.

Real execution stays unavailable until eligibility, billing and targeting contracts
are verified. No automatic fake or environment switch can enable paid writes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.tenancy.acting import require_acting_member

LIVE_UNAVAILABLE = (
    "Puedes preparar la promoción. Crear la vista previa y activar anuncios aún no está "
    "habilitado: falta verificar los permisos, el público y los pagos con Meta."
)


class WizardUnavailable(ValueError):
    """A safe explanation for the owner, never a raw provider response."""


@dataclass(frozen=True)
class PromotionSource:
    publish_attempt_id: UUID
    content_draft_id: UUID
    connection_id: UUID
    brand_id: UUID
    instagram_user_id: str
    source_media_id: str
    caption: str
    account_label: str
    default_link_url: str = ""
    meta_ad_account_id: str = ""
    currency: str = ""
    account_name: str = ""
    timezone_name: str = ""
    published_at: datetime | None = None
    unavailable_reason: str = LIVE_UNAVAILABLE
    ad_account_id: UUID | None = None
    blocks_preparation: bool = False
    health_reason: str = ""
    billing_url: str = ""


@dataclass(frozen=True)
class WizardForm:
    link_url: str
    city_name: str
    start_time: datetime
    end_time: datetime
    city_key: str = ""
    radius_km: int = 10
    age_min: int = 18
    age_max: int = 65
    advantage_audience: bool = False
    housing: bool = False
    budget_minor: int = 0
    currency: str = "COP"

    def validate(self, *, for_execution: bool = False) -> None:
        try:
            parsed = urlsplit(self.link_url)
            valid_url = (
                parsed.scheme == "https"
                and parsed.hostname
                and not parsed.username
                and not parsed.password
                and not any(c.isspace() for c in self.link_url)
            )
        except ValueError:
            valid_url = False
        if not valid_url:
            raise WizardUnavailable("Escribe un enlace completo que empiece por https://.")
        if not self.city_name.strip():
            raise WizardUnavailable("Indica la ciudad donde quieres mostrar la promoción.")
        if for_execution and not self.city_key:
            raise WizardUnavailable("Falta verificar la ciudad con Meta antes de crear el anuncio.")
        if type(self.radius_km) is not int or not 1 <= self.radius_km <= 80:
            raise WizardUnavailable("El radio debe estar entre 1 y 80 kilómetros.")
        if (
            type(self.age_min) is not int
            or type(self.age_max) is not int
            or not 18 <= self.age_min <= self.age_max <= 65
        ):
            raise WizardUnavailable("Revisa las edades: deben estar entre 18 y 65 años.")
        if type(self.advantage_audience) is not bool or type(self.housing) is not bool:
            raise WizardUnavailable("Revisa las opciones del público.")
        if self.currency != "COP" or type(self.budget_minor) is not int or self.budget_minor <= 0:
            raise WizardUnavailable("Indica un presupuesto total válido en pesos colombianos.")
        if (
            any(t.tzinfo is None or t.utcoffset() is None for t in (self.start_time, self.end_time))
            or self.end_time <= self.start_time
        ):
            raise WizardUnavailable("Revisa las fechas y la zona horaria de la promoción.")


@dataclass(frozen=True)
class PromotionPreview:
    promotion_id: UUID
    review_id: UUID
    preview_html: str
    charge_notice: str
    expires_at: datetime
    status: str = "paused"


@dataclass(frozen=True)
class PromotionResult:
    promotion_id: UUID
    status: str
    message: str


def list_promotion_sources(
    *, tenant_id: UUID, content_draft_id: UUID, calendar_event_id: UUID | None = None
) -> tuple[PromotionSource, ...]:
    """Read only persisted, successfully published Instagram provenance for this POST.

    An event filter never degrades to a different publication when it is missing.
    An unbranded or purged connection cannot authorize an advertisement.
    """
    require_acting_member(tenant_id)
    with tenant_session(tenant_id) as session:
        rows = session.execute(
            text(
                """SELECT DISTINCT p.id AS publish_attempt_id,d.id AS content_draft_id,
                c.id AS connection_id,d.brand_id,c.external_account_id AS instagram_user_id,
                p.published_media_id AS source_media_id,COALESCE(p.caption,'') AS caption,
                COALESCE(c.external_username,c.external_account_id) AS account_label,
                COALESCE(a.ad_account_id,'') AS meta_ad_account_id,
                COALESCE(a.currency,'') AS currency,COALESCE(a.name,'') AS account_name,
                COALESCE(a.timezone_name,'') AS timezone_name,p.settled_at AS published_at,
                a.id AS ad_account_id
                FROM content_drafts d
                JOIN calendar_events e ON e.post_id=d.id AND e.tenant_id=d.tenant_id
                  AND e.brand_id=d.brand_id AND e.status='published'
                JOIN publish_attempts p ON p.id=e.publish_attempt_id AND p.tenant_id=e.tenant_id
                  AND p.connection_id=e.connection_id AND p.status='published'
                JOIN social_connections c ON c.id=p.connection_id AND c.tenant_id=p.tenant_id
                  AND c.brand_id=d.brand_id AND c.platform='instagram'
                LEFT JOIN ad_accounts a ON a.connection_id=c.id AND a.tenant_id=c.tenant_id
                  AND a.brand_id=d.brand_id AND a.selected AND a.available
                  AND a.credential_version=c.current_credential_version
                WHERE d.id=:draft AND c.purged_at IS NULL AND c.purge_started_at IS NULL
                  AND p.published_media_id ~ '^[0-9]+$'
                  AND p.media_product_type <> 'STORIES'
                  AND (e.destination IS NULL OR e.destination <> 'story')
                  AND (CAST(:event AS uuid) IS NULL OR e.id=CAST(:event AS uuid))
                ORDER BY p.id"""
            ),
            {"draft": content_draft_id, "event": calendar_event_id},
        ).mappings()
        sources = tuple(PromotionSource(**dict(row)) for row in rows)
    from qualify_api.ads.account_health import get_account_health
    from qualify_api.connections.ad_accounts import AdAccountUnavailable

    enriched = []
    for source in sources:
        if source.ad_account_id is None:
            enriched.append(source)
            continue
        try:
            health = get_account_health(tenant_id=tenant_id, ad_account_id=source.ad_account_id)
        except AdAccountUnavailable:
            enriched.append(source)
        else:
            enriched.append(
                replace(
                    source,
                    blocks_preparation=health.blocks_preparation,
                    health_reason=health.reason,
                    billing_url=health.action_url,
                )
            )
    return tuple(enriched)


async def prepare_promotion_preview(
    *,
    tenant_id: UUID,
    content_draft_id: UUID,
    publish_attempt_id: UUID,
    form: WizardForm,
    approved_by: UUID,
    request_key: str,
) -> PromotionPreview:
    require_acting_member(tenant_id)
    sources = list_promotion_sources(tenant_id=tenant_id, content_draft_id=content_draft_id)
    if not any(s.publish_attempt_id == publish_attempt_id for s in sources):
        raise WizardUnavailable("Esta publicación de Instagram ya no está disponible.")
    source = next(s for s in sources if s.publish_attempt_id == publish_attempt_id)
    if source.ad_account_id is not None:
        from qualify_api.ads.account_health import refresh_account_health

        health = await refresh_account_health(
            tenant_id=tenant_id, ad_account_id=source.ad_account_id, force=True
        )
        if not health.can_promote:
            raise WizardUnavailable(health.reason)
    form.validate()
    raise WizardUnavailable(LIVE_UNAVAILABLE)


async def confirm_promotion(
    *,
    tenant_id: UUID,
    promotion_id: UUID,
    review_id: UUID,
    approved_by: UUID,
    confirm_charge: bool,
) -> PromotionResult:
    require_acting_member(tenant_id)
    raise WizardUnavailable(LIVE_UNAVAILABLE)
