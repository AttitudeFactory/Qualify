"""Audience service adapters. The authenticated state owns acting-login context."""

from __future__ import annotations

import asyncio
from uuid import UUID

from qualify_api.ads.audience import AudienceDraft, InterestOption, LocationOption
from qualify_api.ads.audience_service import (
    estimate_audience,
    load_audience,
    save_audience,
    search_audience_interests,
    search_audience_locations,
    suggest_audience_interests,
)

from .promotion_audience_vm import AudienceInterestVM, AudiencePlaceVM, AudienceReachVM, reach_label
from .promotion_vm import PromotionDraftVM


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
    }


def audience_scope(tenant: str, piece: str, source: str, account: str) -> dict[str, UUID]:
    return {
        "tenant_id": UUID(tenant),
        "content_draft_id": UUID(piece),
        "publish_attempt_id": UUID(source),
        "ad_account_id": UUID(account),
    }


def find_places(scope: dict[str, UUID], query: str, kind: str) -> list[AudiencePlaceVM]:
    rows = asyncio.run(search_audience_locations(**scope, query=query, location_type=kind))
    return [
        AudiencePlaceVM(row.key, row.type, row.country_code, row.name, row.region) for row in rows
    ]


def find_interests(scope: dict[str, UUID], query: str) -> list[AudienceInterestVM]:
    rows = asyncio.run(search_audience_interests(**scope, query=query))
    return [AudienceInterestVM(row.id, row.name, row.status) for row in rows]


def suggest_interests(scope: dict[str, UUID], form: PromotionDraftVM) -> list[AudienceInterestVM]:
    rows = asyncio.run(
        suggest_audience_interests(**scope, interest_ids=tuple(row.id for row in form.interests))
    )
    return [AudienceInterestVM(row.id, row.name, row.status) for row in rows]


def read_reach(scope: dict[str, UUID], form: PromotionDraftVM) -> AudienceReachVM:
    estimate = asyncio.run(estimate_audience(**scope, audience=audience_from_form(form)))
    if not estimate.ready or estimate.lower is None or estimate.upper is None:
        return AudienceReachVM(
            label=estimate.message
            or "Meta aún no tiene una estimación disponible para este público."
        )
    return AudienceReachVM(label=reach_label(estimate.lower, estimate.upper), available=True)


def read_saved_audience(scope: dict[str, UUID]) -> tuple[dict[str, object], int] | None:
    saved = load_audience(**scope)
    return (form_audience_changes(saved.audience), saved.version) if saved else None


def store_audience(scope: dict[str, UUID], form: PromotionDraftVM, version: int) -> int:
    saved = save_audience(**scope, audience=audience_from_form(form), expected_version=version)
    return saved.version
