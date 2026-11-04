"""Promotion UI projection: actual published sources, scoped commands and safe previews."""

from __future__ import annotations

import asyncio
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

from qualify_api.ads.wizard import (
    WizardForm,
    confirm_promotion,
    list_promotion_sources,
    prepare_promotion_preview,
)
from qualify_api.tenancy.locale import read_business_locale

from .promotion_vm import (
    PromotionDraftVM,
    PromotionReviewVM,
    PromotionSourceVM,
    cop_minor,
    local_datetime,
)


def load_sources(
    tenant_id: UUID, draft_id: UUID, event_id: UUID | None = None
) -> tuple[list[PromotionSourceVM], str]:
    sources = list_promotion_sources(
        tenant_id=tenant_id, content_draft_id=draft_id, calendar_event_id=event_id
    )
    locale = read_business_locale(tenant_id)
    zone = locale.timezone if locale is not None else ""
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
    backend_form = WizardForm(
        link_url=form.link_url.strip(),
        city_name=form.city_name.strip(),
        radius_km=int(form.radius_km),
        age_min=int(form.age_min),
        age_max=int(form.age_max),
        advantage_audience=form.advantage_audience,
        housing=form.housing,
        budget_minor=cop_minor(form.budget),
        currency="COP",
        start_time=local_datetime(form.start_local, timezone_name),
        end_time=local_datetime(form.end_local, timezone_name),
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
    )


def confirm_review(
    tenant_id: UUID, approved_by: UUID, review: PromotionReviewVM, confirm_charge: bool
) -> str:
    result = asyncio.run(
        confirm_promotion(
            tenant_id=tenant_id,
            promotion_id=UUID(review.promotion_id),
            review_id=UUID(review.review_id),
            approved_by=approved_by,
            confirm_charge=confirm_charge,
        )
    )
    return result.message
