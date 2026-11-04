"""Audience choices cannot survive a scope change or retain a stale spend consent."""

from __future__ import annotations

from dataclasses import asdict, replace

import pytest
from qualify_api.ads.audience import AudienceDraft, InterestOption, LocationOption, ReachEstimate
from qualify_api.tenancy.acting import current_acting_login

from . import promotion_audience_provider as provider
from . import promotion_state as state_module
from .promotion_audience_ui import promotion_audience
from .promotion_audience_vm import AudienceInterestVM, AudiencePlaceVM, AudienceReachVM
from .promotion_state import PromotionState
from .promotion_vm import step_problem
from .test_promotion_wizard import LOGIN, PIECE, SOURCE, TENANT, ActionContext, valid_form


class AudienceContext(ActionContext):
    _audience_scope = PromotionState._audience_scope
    _search_audience = PromotionState._search_audience
    _persist_audience = PromotionState._persist_audience

    def __init__(self) -> None:
        super().__init__()
        self.sources = [replace(self.sources[0], ad_account_id=str(PIECE))]
        self.place_query = "Cúcuta"
        self.interest_query = "café"
        self.place_results = []
        self.interest_results = []
        self.audience_reach = AudienceReachVM(label="old count", available=True)


def test_arbitrary_search_text_is_not_a_resolved_location_and_invalidates_consent() -> None:
    context = AudienceContext()
    context.confirm_charge = True
    event = PromotionState.audience_edit.fn(context, "place_query", "Otra ciudad")
    assert event
    assert not context.form.location_key and not context.form.city_name
    assert "resultados" in step_problem(context.form, 3)
    assert not context.review.review_id and not context.confirm_charge
    assert not context.audience_reach.available


def test_only_server_results_can_be_selected() -> None:
    context = AudienceContext()
    original = context.form
    assert PromotionState.choose_place.fn(context, "untrusted") is None
    assert context.form == original
    context.place_results = [AudiencePlaceVM("1234", "city", "CO", "Cúcuta", "Norte de Santander")]
    PromotionState.choose_place.fn(context, "1234")
    assert context.form.location_key == "1234"
    assert context.form.location_region == "Norte de Santander"
    assert not context.place_results


def test_manual_empty_is_not_silently_converted_to_automatic() -> None:
    form = replace(valid_form(), placement_mode="manual", placements=[])
    assert "al menos" in step_problem(form, 3)


def test_placements_invalidate_old_estimate_and_remote_consent() -> None:
    context = AudienceContext()
    context.form = replace(context.form, placement_mode="manual")
    context.confirm_charge = True
    PromotionState.placement.fn(context, "instagram_reels", True)
    assert context.form.placements == ["instagram_reels"]
    assert not context.review.review_id and not context.confirm_charge
    assert not context.audience_reach.available


def test_withdrawn_interest_needs_removal_and_housing_summary_hides_old_values() -> None:
    context = AudienceContext()
    context.form = replace(context.form, interests=[AudienceInterestVM("456", "Café", "retiring")])
    assert "Quita" in step_problem(context.form, 3)
    context.form = replace(context.form, housing=True)
    assert "Café" not in PromotionState.audience_interests_label.fget(context)


def test_housing_removes_hidden_choices_and_compiles_without_restricted_fields() -> None:
    context = AudienceContext()
    context.form = replace(
        context.form,
        age_min="30",
        gender="women",
        radius_km="20",
        interests=[AudienceInterestVM("456", "Café", "active")],
    )
    PromotionState.option.fn(context, "housing", True)
    assert context.form.age_min == "18" and context.form.gender == "all"
    assert not context.form.interests and not context.form.radius_km
    targeting = provider.audience_from_form(context.form).targeting()
    assert not {"age_min", "age_max", "genders", "flexible_spec", "exclusions"}.intersection(
        targeting
    )
    assert PromotionState.audience_people_label.fget(context).startswith("Todas")


def test_restore_projection_round_trips_every_audience_choice() -> None:
    audience = AudienceDraft(
        location=LocationOption("123", "Cúcuta", "city", "CO", "Norte de Santander"),
        radius_km=20,
        age_min=25,
        age_max=55,
        gender="men",
        interests=(InterestOption("456", "Café", "retiring"),),
        advantage_audience=True,
        placements=("instagram_reels", "facebook_feed"),
    )
    form = replace(valid_form(), **provider.form_audience_changes(audience))
    assert provider.audience_from_form(form) == audience


@pytest.mark.asyncio
async def test_location_search_uses_authenticated_context_and_discards_late_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = AudienceContext()

    def search(scope: dict, query: str, kind: str) -> list[AudiencePlaceVM]:
        assert current_acting_login() == LOGIN
        assert scope == {
            "tenant_id": TENANT,
            "content_draft_id": PIECE,
            "publish_attempt_id": SOURCE,
            "ad_account_id": PIECE,
        }
        PromotionState.audience_edit.fn(context, "place_query", "Nueva búsqueda")
        return [AudiencePlaceVM("123", "city", "CO", "Resultado anterior")]

    monkeypatch.setattr(state_module, "find_places", search)
    await context._search_audience("places")
    assert not context.place_results


@pytest.mark.asyncio
async def test_late_estimate_does_not_replace_new_audience_or_its_loading_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = AudienceContext()

    def estimate(scope: dict, form: object) -> AudienceReachVM:
        assert current_acting_login() == LOGIN
        context._audience_revision = "new-audience"
        context.audience_reach = AudienceReachVM(label="new count")
        context.reach_loading = True
        return AudienceReachVM(label="old count", available=True)

    monkeypatch.setattr(state_module, "read_reach", estimate)
    await PromotionState.refresh_reach.fn(context)
    assert context.audience_reach.label == "new count" and context.reach_loading


@pytest.mark.asyncio
async def test_saved_audience_restores_then_refreshes_estimate_without_stuck_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = AudienceContext()
    changes = provider.form_audience_changes(
        AudienceDraft(location=LocationOption("789", "Colombia", "country", "CO"))
    )
    monkeypatch.setattr(state_module, "read_saved_audience", lambda scope: (changes, 3))
    monkeypatch.setattr(
        state_module, "read_reach", lambda scope, form: AudienceReachVM(label="ready")
    )
    await context._persist_audience(save=False)
    assert context._audience_version == 3 and context.form.location_key == "789"
    assert context.form.location_kind == "country"
    assert context.audience_reach.label == "ready"
    assert not context.busy and not context.audience_working
    assert not context.review.review_id


def test_no_ready_bounds_means_unavailable_not_fake_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unready(**kwargs: object) -> ReachEstimate:
        return ReachEstimate(ready=False, lower=0, upper=0)

    monkeypatch.setattr(provider, "estimate_audience", unready)
    result = provider.read_reach({}, valid_form())
    assert not result.available
    assert "0 personas" not in result.label


@pytest.mark.asyncio
async def test_business_switch_discards_saved_result_and_preserves_new_busy_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = AudienceContext()

    def store(*args: object) -> int:
        context.auth.session_tenant_id = str(SOURCE)
        context._audience_revision = "new-business"
        context.busy = True
        return 2

    monkeypatch.setattr(state_module, "store_audience", store)
    await context._persist_audience(save=True)
    assert context._audience_version == 0 and not context.audience_notice
    assert context.busy


@pytest.mark.asyncio
async def test_restore_empty_explains_next_step_without_overwriting_current_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = AudienceContext()
    before = context.form
    monkeypatch.setattr(state_module, "read_saved_audience", lambda scope: None)
    monkeypatch.setattr(state_module, "read_reach", lambda scope, form: AudienceReachVM())
    await context._persist_audience(save=False)
    assert context.form == before and "Todavía no guardaste" in context.audience_notice
    assert not context.busy


def test_audience_component_constructs_and_display_dto_contains_no_credentials() -> None:
    rendered = repr(promotion_audience().render())
    assert "Guardar p" in rendered and "Buscar lugares" in rendered
    assert "Dónde aparece" not in rendered  # Summary stays separate from geography.
    assert not {"token", "ciphertext", "access_token"}.intersection(asdict(AudiencePlaceVM()))
