"""Promotion UI projection: actual published sources, scoped commands and safe previews."""

from __future__ import annotations

import asyncio
import logging
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

from qualify_api.ads.lead_ads import published_lead_form
from qualify_api.ads.lead_forms_service import list_lead_forms
from qualify_api.ads.messaging_destinations import load_messaging_destinations
from qualify_api.ads.wizard import (
    WizardForm,
    confirm_promotion,
    list_promotion_sources,
    prepare_promotion_preview,
)
from qualify_api.tenancy.locale import read_business_locale
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from .ad_enhancements_provider import load_policy
from .ad_enhancements_vm import BrandEnhancementsVM
from .ad_health_provider import account_health_for, refresh_health
from .ad_health_vm import AccountHealthVM
from .promotion_audience_provider import audience_from_form
from .promotion_vm import (
    LeadFormChoiceVM,
    MessagingDestinationVM,
    PromotionDraftVM,
    PromotionResultVM,
    PromotionReviewVM,
    PromotionSourceVM,
    cop_minor,
    local_datetime,
    promotion_checks,
    promotion_result,
)

logger = logging.getLogger(__name__)


def messaging_destinations(tenant_id: UUID, connection_id: UUID) -> list[MessagingDestinationVM]:
    """A failed diagnosis cannot turn an unknown link into a missing link."""
    try:
        rows = load_messaging_destinations(tenant_id=tenant_id, connection_id=connection_id)
    except Exception as exc:
        logger.warning("messaging destinations read failed: %s", type(exc).__name__)
        return [
            MessagingDestinationVM(
                "instagram_direct",
                "Instagram Direct",
                "La creación de anuncios para abrir chats todavía no está habilitada.",
            ),
            MessagingDestinationVM(
                "whatsapp",
                "WhatsApp",
                "No pudimos comprobar el número de WhatsApp. "
                "Revisa tus cuentas en Tus redes y vuelve a abrir la promoción.",
            ),
        ]
    return [
        MessagingDestinationVM(
            key=row.key,
            label=row.label,
            notice=(
                "Tu número de WhatsApp está vinculado a esta página. "
                if row.key == "whatsapp" and row.linked is True
                else "El número de WhatsApp de este negocio no está vinculado a esta página. "
                if row.key == "whatsapp" and row.linked is False
                else ""
            )
            + (
                row.reason or "La creación de anuncios para abrir chats todavía no está habilitada."
            ),
        )
        for row in rows
        if row.key in {"whatsapp", "instagram_direct"}
    ]


LEAD_FORMS_FAILED = "No pudimos consultar tus formularios. Vuelve a abrir la promoción."


def last_used_lead_form(tenant_id: UUID) -> str:
    """The form of this business's most recent lead-ad promotion, or ""."""
    with tenant_session(tenant_id) as session:
        value = session.scalar(
            text("""SELECT request_snapshot->'lead_form_snapshot'->>'form_id'
            FROM ad_promotions WHERE request_snapshot ? 'lead_form_snapshot'
            ORDER BY created_at DESC LIMIT 1""")
        )
    return value or ""


def ready_lead_forms(tenant_id: UUID, connection_id: UUID) -> tuple[list[LeadFormChoiceVM], str]:
    """Forms Meta already accepted on this account, last used first; a failed read is
    reported as such, never as «no forms»."""
    try:
        rows = [
            row
            for row in list_lead_forms(tenant_id=tenant_id, connection_id=connection_id)
            if row.status == "published" and row.meta_form_id
        ]
        last = last_used_lead_form(tenant_id)
    except Exception as exc:
        logger.warning("lead forms read failed: %s", type(exc).__name__)
        return [], LEAD_FORMS_FAILED
    rows.sort(key=lambda row: str(row.id) != last)  # stable: newest first otherwise
    return [LeadFormChoiceVM(str(row.id), row.name) for row in rows], ""


def recheck_messaging_destinations(
    tenant_id: UUID, piece_id: UUID, publish_attempt_id: UUID, connection_id: UUID
) -> list[MessagingDestinationVM]:
    from qualify_api.ads.wizard import WizardUnavailable  # noqa: PLC0415

    candidates = list_promotion_sources(tenant_id=tenant_id, content_draft_id=piece_id)
    if not any(
        row.publish_attempt_id == publish_attempt_id and row.connection_id == connection_id
        for row in candidates
    ):
        raise WizardUnavailable(
            "La publicación o sus cuentas cambiaron. Abre la promoción de nuevo."
        )
    return messaging_destinations(tenant_id, connection_id)


def recheck_enhancement_permissions(
    tenant_id: UUID, piece_id: UUID, publish_attempt_id: UUID, brand_id: UUID
) -> BrandEnhancementsVM:
    from qualify_api.ads.wizard import WizardUnavailable  # noqa: PLC0415

    candidates = list_promotion_sources(tenant_id=tenant_id, content_draft_id=piece_id)
    matches = [
        row
        for row in candidates
        if row.publish_attempt_id == publish_attempt_id and row.brand_id == brand_id
    ]
    if len(matches) != 1:
        raise WizardUnavailable("La publicación o su marca cambiaron. Abre la promoción de nuevo.")
    return load_policy(tenant_id, brand_id)


def load_sources(
    tenant_id: UUID,
    draft_id: UUID,
    event_id: UUID | None = None,
    check_health: bool = False,
) -> tuple[list[PromotionSourceVM], str]:
    sources = list_promotion_sources(
        tenant_id=tenant_id, content_draft_id=draft_id, calendar_event_id=event_id
    )
    locale = read_business_locale(tenant_id)
    zone = locale.timezone if locale is not None else ""
    health_by_account: dict[UUID, AccountHealthVM] = {}
    messaging_by_connection: dict[UUID, list[MessagingDestinationVM]] = {}
    enhancements_by_brand: dict[UUID, BrandEnhancementsVM] = {}
    forms_by_connection: dict[UUID, tuple[list[LeadFormChoiceVM], str]] = {}
    for source in sources:
        if source.ad_account_id is not None and source.ad_account_id not in health_by_account:
            health_by_account[source.ad_account_id] = (
                refresh_health if check_health else account_health_for
            )(tenant_id, source.ad_account_id, source.timezone_name or zone)
        if check_health and source.connection_id not in messaging_by_connection:
            messaging_by_connection[source.connection_id] = messaging_destinations(
                tenant_id, source.connection_id
            )
            forms_by_connection[source.connection_id] = ready_lead_forms(
                tenant_id, source.connection_id
            )
        if check_health and source.brand_id not in enhancements_by_brand:
            try:
                enhancements_by_brand[source.brand_id] = load_policy(tenant_id, source.brand_id)
            except Exception as exc:
                logger.warning("promotion permissions read failed: %s", type(exc).__name__)
                enhancements_by_brand[source.brand_id] = BrandEnhancementsVM()
    return [
        PromotionSourceVM(
            id=str(source.publish_attempt_id),
            account_label=source.account_label,
            caption=source.caption,
            account_name=source.account_name,
            currency=source.currency,
            default_link_url=source.default_link_url,
            timezone_name=source.timezone_name,
            published_label=(
                source.published_at.astimezone(ZoneInfo(source.timezone_name or zone)).strftime(
                    "%d/%m/%Y %H:%M"
                )
                if source.published_at is not None and (source.timezone_name or zone)
                else "Fecha por comprobar"
            ),
            unavailable_reason=source.unavailable_reason,
            health=health_by_account.get(source.ad_account_id, AccountHealthVM()),
            ad_account_id=str(source.ad_account_id) if source.ad_account_id else "",
            messaging_destinations=messaging_by_connection.get(source.connection_id, []),
            connection_id=str(source.connection_id),
            enhancements=enhancements_by_brand.get(source.brand_id, BrandEnhancementsVM()),
            brand_id=str(source.brand_id),
            lead_forms=forms_by_connection.get(source.connection_id, ([], ""))[0],
            lead_forms_error=forms_by_connection.get(source.connection_id, ([], ""))[1],
        )
        for source in sources
    ], zone


class _PreviewFrame(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "iframe":
            self.urls.extend(value for name, value in attrs if name == "src" and value)


def safe_preview_url(html: str) -> str:
    """Never render provider HTML, scripts, inline attributes or arbitrary frame URLs."""
    parser = _PreviewFrame()
    parser.feed(html)
    if len(parser.urls) != 1:
        return ""
    value = parser.urls[0]
    try:
        url = urlsplit(value)
        if (
            len(value) > 8000
            or any(char in value for char in "\r\n")
            or url.scheme != "https"
            or url.hostname not in {"www.facebook.com", "business.facebook.com"}
            or url.path != "/ads/api/preview_iframe.php"
            or url.username
            or url.password
            or url.port not in {None, 443}
            or {"access_token", "appsecret_proof"}.intersection(
                key.lower() for key in parse_qs(url.query)
            )
        ):
            return ""
    except ValueError:
        return ""
    return value


def prepare_preview(
    tenant_id: UUID,
    draft_id: UUID,
    approved_by: UUID,
    form: PromotionDraftVM,
    timezone_name: str,
    request_key: str,
) -> PromotionReviewVM:
    from qualify_api.ads.enhancements import BrandEnhancementSettings

    if not form.enhancements.loaded:
        raise ValueError(
            "Vuelve a consultar los permisos de la marca antes de preparar el anuncio."
        )
    lead = form.goal == "lead"
    backend_form = WizardForm(
        link_url="" if lead else form.link_url.strip(),
        city_name=form.city_name.strip(),
        radius_km=int(form.radius_km) if form.radius_km else 1,
        age_min=int(form.age_min),
        age_max=int(form.age_max),
        advantage_audience=form.advantage_audience,
        housing=form.housing,
        budget_minor=cop_minor(form.budget),
        currency="COP",
        start_time=local_datetime(form.start_local, timezone_name),
        end_time=local_datetime(form.end_local, timezone_name),
        audience=audience_from_form(form),
        enhancements=BrandEnhancementSettings(
            tenant_id,
            UUID(form.enhancements.brand_id),
            form.enhancements.version,
            dict(form.enhancements.values),
        ),
        lead_form=published_lead_form(tenant_id, UUID(form.lead_form_id)) if lead else None,
        lead_cta=form.lead_cta if lead else "",
    )
    preview = asyncio.run(
        prepare_promotion_preview(
            tenant_id=tenant_id,
            content_draft_id=draft_id,
            publish_attempt_id=UUID(form.source_id),
            form=backend_form,
            approved_by=approved_by,
            request_key=request_key,
        )
    )
    url = safe_preview_url(preview.preview_html)
    if not url:
        raise ValueError("unsafe or unavailable promotion preview")
    return PromotionReviewVM(
        promotion_id=str(preview.promotion_id),
        review_id=str(preview.review_id),
        preview_url=url,
        charge_notice=preview.charge_notice,
        expires_label=preview.expires_at.astimezone(ZoneInfo(timezone_name)).strftime(
            "%d/%m/%Y %H:%M"
        ),
        checks=promotion_checks(getattr(preview, "checks", ())),
    )


def confirm_review(
    tenant_id: UUID, approved_by: UUID, review: PromotionReviewVM, confirm_charge: bool
) -> PromotionResultVM:
    result = asyncio.run(
        confirm_promotion(
            tenant_id=tenant_id,
            promotion_id=UUID(review.promotion_id),
            review_id=UUID(review.review_id),
            approved_by=approved_by,
            confirm_charge=confirm_charge,
        )
    )
    return promotion_result(result, review.promotion_id)
