"""Audience service adapters. The authenticated state owns acting-login context."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from uuid import UUID

from qualify_api.ads.audience import AudienceDraft, InterestOption, LocationOption, MapPoint
from qualify_api.ads.audience_service import (
    estimate_audience,
    load_audience,
    save_audience,
    search_audience_interests,
    search_audience_locations,
    suggest_audience_interests,
)
from qualify_api.ads.business_location import get_business_location, save_business_location
from qualify_api.ads.custom_audiences import CustomAudienceSelection
from qualify_api.ads.market_size import estimate_market, record_market_estimate

from .ad_custom_audiences_vm import CustomAudienceVM
from .promotion_audience_vm import (
    NO_RANGE_NEXT,
    POINT_NAME,
    SIZE_LABELS,
    AudienceInterestVM,
    AudiencePlaceVM,
    AudienceReachVM,
    captured_point,
    place_kind_label,
    reach_label,
)
from .promotion_market_vm import market_estimate
from .promotion_vm import PromotionDraftVM

logger = logging.getLogger(__name__)


def audience_from_form(form: PromotionDraftVM) -> AudienceDraft:
    return AudienceDraft(
        location=(
            LocationOption(
                key=form.location_key,
                name=form.city_name,
                type=form.location_kind,
                country_code=form.location_country,
                region=form.location_region,
            )
            if form.location_key
            else None
        ),
        radius_km=int(form.radius_km) if form.radius_km else None,
        point=(
            MapPoint(float(form.point_latitude), float(form.point_longitude), POINT_NAME)
            if form.near and form.point_latitude and form.point_longitude
            else None
        ),
        age_min=18 if form.housing else int(form.age_min),
        age_max=65 if form.housing else int(form.age_max),
        gender="all" if form.housing else form.gender,
        interests=(
            ()
            if form.housing
            else tuple(
                InterestOption(row.id, row.label, row.notice or "unknown") for row in form.interests
            )
        ),
        advantage_audience=form.advantage_audience,
        housing=form.housing,
        placements=tuple(form.placements) if form.placement_mode == "manual" else (),
        custom_audiences=tuple(
            CustomAudienceSelection(row.local_id, row.meta_id, row.name, row.kind)
            for row in form.custom_audiences
        ),
    )


def form_audience_changes(audience: AudienceDraft) -> dict[str, object]:
    place = audience.location
    return {
        "city_name": place.name if place else "",
        "location_key": place.key if place else "",
        "location_kind": place.type if place else "city",
        "location_country": place.country_code if place else "",
        "location_region": place.region if place else "",
        "radius_km": str(audience.radius_km) if audience.radius_km is not None else "",
        "near": audience.point is not None,
        "point_latitude": str(audience.point.latitude) if audience.point else "",
        "point_longitude": str(audience.point.longitude) if audience.point else "",
        "age_min": str(audience.age_min),
        "age_max": str(audience.age_max),
        "gender": audience.gender,
        "housing": audience.housing,
        "advantage_audience": audience.advantage_audience,
        "interests": [
            AudienceInterestVM(row.id, row.name, row.status) for row in audience.interests
        ],
        "placement_mode": "manual" if audience.placements else "automatic",
        "placements": list(audience.placements),
        "custom_audiences": [
            CustomAudienceVM(
                row.local_id,
                row.id,
                row.name,
                row.kind,
                notice="Vuelve a consultar este público antes de usarlo.",
            )
            for row in audience.custom_audiences
        ],
    }


def audience_scope(tenant: str, piece: str, source: str, account: str) -> dict[str, UUID]:
    return {
        "tenant_id": UUID(tenant),
        "content_draft_id": UUID(piece),
        "publish_attempt_id": UUID(source),
        "ad_account_id": UUID(account),
    }


def find_places(scope: dict[str, UUID], query: str, kind: str) -> list[AudiencePlaceVM]:
    """«En una ciudad o región» searches both kinds in one Meta call; cities come first."""
    kinds = ("country",) if kind == "country" else ("city", "region")
    found = asyncio.run(search_audience_locations(**scope, query=query, location_types=kinds))
    return [
        AudiencePlaceVM(
            row.key,
            row.type,
            row.country_code,
            row.name,
            row.region,
            place_kind_label(row.type) if kind != "country" else "",
        )
        for row in sorted(found, key=lambda row: kinds.index(row.type))
    ]


def find_interests(scope: dict[str, UUID], query: str) -> list[AudienceInterestVM]:
    rows = asyncio.run(search_audience_interests(**scope, query=query))
    return [AudienceInterestVM(row.id, row.name, row.status) for row in rows]


def suggest_interests(scope: dict[str, UUID], form: PromotionDraftVM) -> list[AudienceInterestVM]:
    rows = asyncio.run(
        suggest_audience_interests(**scope, interest_ids=tuple(row.id for row in form.interests))
    )
    return [AudienceInterestVM(row.id, row.name, row.status) for row in rows]


def read_reach(
    scope: dict[str, UUID], form: PromotionDraftVM, brand_id: str = ""
) -> AudienceReachVM:
    """Meta's range for the form's audience, with the market class and CPM of `brand_id`
    (the selected source's brand: always set, unlike the permissions check's)."""
    estimate = asyncio.run(estimate_audience(**scope, audience=audience_from_form(form)))
    if not estimate.ready or estimate.lower is None or estimate.upper is None:
        message = (
            estimate.message or "Meta aún no tiene una estimación disponible para este público."
        )
        return AudienceReachVM(label=f"{message} {NO_RANGE_NEXT}", status="unavailable")
    reach = AudienceReachVM(
        label=reach_label(estimate.lower, estimate.upper),
        available=True,
        status="ready",
        lower=estimate.lower,
        upper=estimate.upper,
        audience_hash=estimate.audience_hash,
    )
    try:
        # The class and the CPM `estimate_market` picks (the brand's own, else the table's):
        # a nominal amount only makes it name the CPM; the budget step does the arithmetic.
        market = estimate_market(
            tenant_id=scope["tenant_id"],
            brand_id=UUID(brand_id),
            reach=estimate,
            country=form.location_country,
            currency=form.currency,
            budget_minor=100,
            days=7,
        )
    except Exception as exc:  # the range stays useful without the class or the CPM
        logger.warning("market estimate failed: %s", type(exc).__name__)
        return replace(reach, market_failed=True)
    if market is None:
        return replace(reach, market_failed=True)
    label, hint = SIZE_LABELS[market.market_class]
    return replace(
        reach,
        market_class=market.market_class,
        size_label=label,
        size_hint=hint,
        cpm_minor=market.cpm_minor or 0,
        cpm_source=market.cpm_source or "",
    )


def keep_market_estimate(
    tenant_id: UUID,
    promotion_id: UUID,
    reach: AudienceReachVM,
    form: PromotionDraftVM,
    timezone_name: str,
) -> None:
    """The estimate shown before approval, kept with the prepared promotion (provenance).
    Never blocks the preview: a failed write is logged and the promotion goes on."""
    try:
        estimate = market_estimate(reach, form, timezone_name)
        if estimate is None:
            return
        record_market_estimate(tenant_id=tenant_id, promotion_id=promotion_id, estimate=estimate)
    except Exception as exc:
        logger.warning("market estimate record failed: %s", type(exc).__name__)


def read_saved_audience(scope: dict[str, UUID]) -> tuple[dict[str, object], int] | None:
    saved = load_audience(**scope)
    return (form_audience_changes(saved.audience), saved.version) if saved else None


def store_audience(scope: dict[str, UUID], form: PromotionDraftVM, version: int) -> int:
    saved = save_audience(**scope, audience=audience_from_form(form), expected_version=version)
    return saved.version


def read_business_location(tenant_id: UUID) -> tuple[str, str] | None:
    """The business's saved point as the form's 6-decimal strings, or None."""
    saved = get_business_location(tenant_id)
    return captured_point({"latitude": saved[0], "longitude": saved[1]}) if saved else None


def store_business_location(tenant_id: UUID, user_id: UUID, latitude: str, longitude: str) -> None:
    """Only on the owner's explicit tap; raises AudienceUnavailable with a Spanish message."""
    save_business_location(tenant_id, user_id, float(latitude), float(longitude))
