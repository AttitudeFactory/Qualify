"""Published-source ownership and production composition for verified promotions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.audience import AudienceDraft, AudienceUnavailable
from qualify_api.ads.enhancements import BrandEnhancementSettings
from qualify_api.ads.lead_ads import LEAD_CTAS, LeadFormTarget
from qualify_api.tenancy.acting import require_acting_member

LIVE_UNAVAILABLE = (
    "Puedes preparar la promoción. Crear la vista previa y activar anuncios aún no está "
    "habilitado: falta verificar los permisos, el público y los pagos con Meta."
)
# Buttons a website (link) promotion may carry (m-24828976). Each is a link-type value of
# `AdCreativeLinkDataCallToAction.Type` in facebook-python-business-sdk
# (facebook_business/adobjects/adcreativelinkdatacalltoaction.py) and of the piece's `AdCTA`.
# Left out on purpose: CALL_NOW (opens a phone, not an https page, and Meta does not show it
# in stories, which these automatic placements include: docs/epica-anuncios-meta.md §2) and
# the chat buttons (WHATSAPP_MESSAGE, MESSAGE_PAGE), which belong to messaging promotions.
# Which button Meta accepts per objective is not in the enum reference; an invalid pair comes
# back as 1373054/2446383 (ads/errors.py) at validate_only, before anything is created.
WEBSITE_CTAS = (
    "LEARN_MORE",
    "SHOP_NOW",
    "ORDER_NOW",
    "BOOK_NOW",
    "BOOK_TRAVEL",
    "GET_QUOTE",
    "CONTACT_US",
    "SIGN_UP",
)


class WizardUnavailable(ValueError):
    """A safe explanation for the owner, never a raw provider response."""

    def __init__(self, message: str, *, diagnostics: tuple[dict[str, str], ...] = ()) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


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
    credential_version: int = 0
    linked_page_id: str = ""
    ad_destination_fingerprint: str = ""
    # The piece's saved button when a website promotion may carry it; else LEARN_MORE.
    default_cta_type: str = "LEARN_MORE"


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
    audience: AudienceDraft | None = None
    enhancements: BrandEnhancementSettings | None = None
    # A lead ad sends people to an already-published Meta form instead of a link.
    lead_form: LeadFormTarget | None = None
    lead_cta: str = ""
    # The website promotion's button; part of the approved request (and its hash).
    cta_type: str = "LEARN_MORE"

    def validate(self, *, for_execution: bool = False) -> None:
        if self.lead_form is not None or self.lead_cta:
            if self.lead_form is None or self.lead_cta not in LEAD_CTAS or self.link_url:
                raise WizardUnavailable("Elige el formulario y el botón del anuncio.")
        else:
            self._validate_link()
            if self.cta_type not in WEBSITE_CTAS:
                raise WizardUnavailable("Elige un botón del anuncio de la lista.")
        self._validate_audience(for_execution)

    def _validate_link(self) -> None:
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

    def _validate_audience(self, for_execution: bool) -> None:
        if self.audience is not None:
            try:
                self.audience.validate()
            except AudienceUnavailable as error:
                raise WizardUnavailable(str(error)) from None
            if (
                self.audience.housing != self.housing
                or self.audience.advantage_audience != self.advantage_audience
            ):
                raise WizardUnavailable("Revisa las opciones del público antes de continuar.")
        if self.audience is None and not self.city_name.strip():
            raise WizardUnavailable("Indica la ciudad donde quieres mostrar la promoción.")
        if self.audience is None and for_execution and not self.city_key:
            raise WizardUnavailable("Falta verificar la ciudad con Meta antes de crear el anuncio.")
        if self.audience is None and (
            type(self.radius_km) is not int or not 1 <= self.radius_km <= 80
        ):
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
    checks: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class PromotionResult:
    promotion_id: UUID
    status: str
    message: str


def _saved_ad_destination(payload: dict | None) -> tuple[str, str, str]:
    """Project the piece's link and button without inventing a brand default.

    Returns (destination, button for a website promotion, reason it cannot be promoted).
    """
    from qualify_creative.ad_destination import (
        AdCTA,
        normalize_legacy_ad_cta,
        validate_ad_destination_url,
    )

    if payload is None:
        return "", "LEARN_MORE", ""  # An old piece without an advertising choice.
    destination = payload.get("ads_destination_url")
    raw_button = payload.get("ads_cta_type")
    try:
        # Historical snapshots had free-text buttons and no destination. Project only
        # the ad fields; unrelated caption/schema evolution cannot revoke management.
        if destination is None or destination == "":
            button = normalize_legacy_ad_cta(raw_button)
            destination = ""
        else:
            button = AdCTA(raw_button)
            destination = validate_ad_destination_url(destination) or ""
    except (ValueError, TypeError):
        return (
            "",
            "LEARN_MORE",
            "Revisa y guarda el enlace y el botón del anuncio en la pieza antes de promocionarla.",
        )
    if button is None:
        return destination, "LEARN_MORE", ""
    if button not in WEBSITE_CTAS:
        # Never silently swap a chat or call button for another one.
        return (
            destination,
            "LEARN_MORE",
            (
                "El botón de esta pieza abre un chat o una llamada y no sirve para un anuncio "
                "que lleva a tu página. Cambia el botón en la pieza antes de promocionarla."
            ),
        )
    return destination, button.value, ""


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
                ,c.current_credential_version AS credential_version,c.linked_page_id,
                COALESCE(v.edited_copy,v.copy) AS ad_copy
                FROM content_drafts d
                JOIN calendar_events e ON e.post_id=d.id AND e.tenant_id=d.tenant_id
                  AND e.brand_id=d.brand_id AND e.status='published'
                JOIN publish_attempts p ON p.id=e.publish_attempt_id AND p.tenant_id=e.tenant_id
                  AND p.connection_id=e.connection_id AND p.status='published'
                JOIN social_connections c ON c.id=p.connection_id AND c.tenant_id=p.tenant_id
                  AND c.brand_id=d.brand_id AND c.platform='instagram'
                LEFT JOIN copy_variants v ON v.id=d.selected_variant_id
                  AND v.tenant_id=d.tenant_id AND v.draft_id=d.id
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
        sources = []
        for row in rows:
            values = dict(row)
            saved_copy = values.pop("ad_copy")
            default_link, default_cta, reason = _saved_ad_destination(saved_copy)
            destination_fingerprint = ""
            if default_link:
                from qualify_api.ads.promotions import fingerprint

                destination_fingerprint = fingerprint(
                    {
                        "ads_destination_url": default_link,
                        "ads_cta_type": saved_copy.get("ads_cta_type") or "LEARN_MORE",
                    }
                )
            sources.append(
                PromotionSource(
                    **values,
                    default_link_url=default_link,
                    default_cta_type=default_cta,
                    unavailable_reason=reason,
                    ad_destination_fingerprint=destination_fingerprint,
                )
            )
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
    return tuple(
        replace(
            source,
            unavailable_reason=(
                source.unavailable_reason
                if source.unavailable_reason
                else "Elige una cuenta publicitaria para esta marca en Tus redes."
                if source.ad_account_id is None
                else "Esta comprobación admite cuentas en pesos colombianos."
                if source.currency != "COP"
                else "Actualiza la cuenta para comprobar su zona horaria."
                if not source.timezone_name
                else ""
            ),
        )
        for source in enriched
    )


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
    if source.unavailable_reason:
        raise WizardUnavailable(source.unavailable_reason)
    from qualify_api.ads.live_wizard import production_wizard

    async with production_wizard(tenant_id, approved_by) as wizard:
        return await wizard.prepare(
            tenant_id=tenant_id,
            publish_attempt_id=publish_attempt_id,
            form=form,
            approved_by=approved_by,
            request_key=request_key,
        )


async def confirm_promotion(
    *,
    tenant_id: UUID,
    promotion_id: UUID,
    review_id: UUID,
    approved_by: UUID,
    confirm_charge: bool,
) -> PromotionResult:
    require_acting_member(tenant_id)
    from qualify_api.ads.live_wizard import production_wizard

    async with production_wizard(tenant_id, approved_by) as wizard:
        return await wizard.confirm(
            tenant_id=tenant_id,
            promotion_id=promotion_id,
            review_id=review_id,
            approved_by=approved_by,
            confirm_charge=confirm_charge,
        )
