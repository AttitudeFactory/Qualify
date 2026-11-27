"""The investment profile's backend calls (m-25091387). Run inside `acting_login`."""

from __future__ import annotations

from uuid import UUID

from qualify_api.ads.investment_profile import (
    InvestmentProfile,
    default_currency,
    load_investment_profile,
    save_investment_profile,
)
from qualify_api.ads.live_wizard import production_currency_offset
from qualify_api.ads.results_service import list_promotion_results

from .creative_provider import default_brand_id
from .investment_profile_vm import ProfileAnswersVM, ProfileVM, save_values


def profile_vm(row: InvestmentProfile | None) -> ProfileVM:
    if row is None:
        return ProfileVM()
    return ProfileVM(
        exists=True,
        objective=row.objective,
        ticket=row.average_ticket_minor // 100,
        margin_points=row.margin_basis_points,
        estimated=row.margin_is_estimated,
        clients=row.weekly_new_clients,
        cap=row.monthly_cap_minor // 100,
        # rounded up: an exact answer re-read as percent gives back the same percent
        kept=-(-row.average_ticket_minor * row.margin_basis_points // 1_000_000),
        max_cost=row.max_cost_per_client_minor // 100,
        currency=row.currency,
    )


def brand_for(tenant_id: UUID, cached: str) -> UUID | None:
    """The brand the app is working on (Crear's), else the business's default one."""
    return UUID(cached) if cached else default_brand_id(tenant_id)


def load_profile(tenant_id: UUID, brand_id: UUID) -> tuple[ProfileVM, bool]:
    """(the profile, whether it can be saved in this brand's currency)."""
    row = load_investment_profile(tenant_id=tenant_id, brand_id=brand_id)
    if row is not None:
        return profile_vm(row), True
    currency = default_currency(tenant_id=tenant_id, brand_id=brand_id)
    return ProfileVM(currency=currency), production_currency_offset(currency) is not None


def should_offer(tenant_id: UUID, brand_id: UUID) -> bool:
    """Offer the questions before «Promocionar» only to a brand with no profile and no
    promotion yet: the first promotion ends the offer (no dismissal is stored)."""
    profile, supported = load_profile(tenant_id, brand_id)
    if profile.exists or not supported:
        return False
    return not list_promotion_results(tenant_id=tenant_id, brand_id=brand_id)


def save_profile(tenant_id: UUID, brand_id: UUID, answers: ProfileAnswersVM) -> ProfileVM:
    values = save_values(answers)
    return profile_vm(save_investment_profile(tenant_id=tenant_id, brand_id=brand_id, **values))
