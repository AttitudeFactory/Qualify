"""Custom audience choices preserve tenant scope, Housing limits and approval integrity."""

from __future__ import annotations

from dataclasses import asdict, replace
from uuid import UUID

import pytest
from qualify_api.ads.audience import AudienceUnavailable
from qualify_api.ads.custom_audiences import CustomAudienceCatalog, CustomAudienceSummary
from qualify_api.tenancy.acting import current_acting_login

from . import ad_custom_audiences_provider as provider
from . import promotion_audience_provider as audience_provider
from . import promotion_state as state_module
from .ad_custom_audiences_ui import custom_audiences
from .ad_custom_audiences_vm import (
    CustomAudienceCatalogVM,
    CustomAudienceVM,
    creation_problem,
)
from .promotion_state import PromotionState
from .promotion_vm import step_problem
from .test_promotion_audience import AudienceContext
from .test_promotion_wizard import LOGIN, PIECE, SOURCE, TENANT

AUDIENCE = UUID("f0000000-0000-4000-8000-000000000001")
ENGAGEMENT = CustomAudienceVM(str(AUDIENCE), "123456", "Interacciones", "engagement", True)
LOOKALIKE = replace(ENGAGEMENT, local_id=str(PIECE), name="Personas parecidas", kind="lookalike")


class CustomContext(AudienceContext):
    _custom_audience_action = PromotionState._custom_audience_action

    def __init__(self) -> None:
        super().__init__()
        PromotionState._reset_custom_audiences(self)
        self.custom_catalog = CustomAudienceCatalogVM(
            loaded=True,
            terms_accepted=True,
            creation_available=True,
            notice="",
            audiences=[ENGAGEMENT, LOOKALIKE],
        )
        self.custom_name = "Personas que nos conocen"

    @property
    def custom_choices(self) -> list[CustomAudienceVM]:
        return PromotionState.custom_choices.fget(self)

    @property
    def custom_seed_choices(self) -> list[CustomAudienceVM]:
        return PromotionState.custom_seed_choices.fget(self)

    @property
    def custom_creation_enabled(self) -> bool:
        return PromotionState.custom_creation_enabled.fget(self)


def test_housing_hides_lookalikes_and_removes_selected_one_and_creation_consent() -> None:
    context = CustomContext()
    context.form = replace(context.form, custom_audiences=[LOOKALIKE])
    context.custom_kind = "lookalike"
    context.custom_seed = ENGAGEMENT.local_id
    context.custom_confirmed = context.confirm_charge = True
    PromotionState.option.fn(context, "housing", True)
    assert context.custom_choices == [ENGAGEMENT]
    assert not context.form.custom_audiences
    assert context.custom_kind == "engagement" and not context.custom_seed
    assert not context.custom_confirmed and not context.confirm_charge
    assert not context.review.review_id


def test_housing_cannot_select_forged_or_hidden_lookalike_or_creation_kind() -> None:
    context = CustomContext()
    context.form = replace(context.form, housing=True)
    assert PromotionState.choose_custom_audience.fn(context, LOOKALIKE.local_id) is None
    PromotionState.custom_edit.fn(context, "kind", "lookalike")
    assert context.custom_kind == "engagement" and not context.form.custom_audiences
    context.form = replace(context.form, custom_audiences=[LOOKALIKE])
    assert "vivienda" in step_problem(context.form, 3)


def test_selection_requires_available_server_result_and_observed_terms() -> None:
    context = CustomContext()
    before = context.form
    assert PromotionState.choose_custom_audience.fn(context, "forged") is None
    context.custom_catalog = replace(context.custom_catalog, terms_accepted=False)
    assert PromotionState.choose_custom_audience.fn(context, ENGAGEMENT.local_id) is None
    context.custom_catalog = replace(
        context.custom_catalog,
        terms_accepted=True,
        audiences=[replace(ENGAGEMENT, available=False)],
    )
    assert PromotionState.choose_custom_audience.fn(context, ENGAGEMENT.local_id) is None
    assert context.form == before


def test_selection_and_removal_invalidate_preview_and_spend_consent() -> None:
    context = CustomContext()
    context.confirm_charge = True
    PromotionState.choose_custom_audience.fn(context, ENGAGEMENT.local_id)
    assert context.form.custom_audiences == [ENGAGEMENT]
    assert not context.review.review_id and not context.confirm_charge
    result = audience_provider.audience_from_form(context.form)
    assert result.targeting()["custom_audiences"] == [{"id": ENGAGEMENT.meta_id}]
    context.confirm_charge = True
    PromotionState.remove_custom_audience.fn(context)
    assert not context.form.custom_audiences and not context.confirm_charge


def test_saved_custom_audience_must_be_rechecked_and_cannot_silently_broaden_targeting() -> None:
    context = CustomContext()
    audience = audience_provider.audience_from_form(
        replace(context.form, custom_audiences=[ENGAGEMENT])
    )
    restored = replace(context.form, **audience_provider.form_audience_changes(audience))
    assert restored.custom_audiences[0].local_id == ENGAGEMENT.local_id
    assert not restored.custom_audiences[0].available
    assert "Vuelve a consultar" in step_problem(restored, 3)


def test_input_changes_reset_creation_consent_and_idempotency_key() -> None:
    context = CustomContext()
    context.custom_confirmed = True
    key = context._custom_request_key
    PromotionState.custom_edit.fn(context, "name", "Otro público")
    assert context._custom_request_key != key and not context.custom_confirmed
    context.custom_kind = "lookalike"
    context.custom_seed = ENGAGEMENT.local_id
    PromotionState.custom_edit.fn(context, "kind", "messages")
    assert not context.custom_seed


@pytest.mark.asyncio
async def test_creation_without_separate_confirmation_never_calls_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = CustomContext()
    calls = []
    monkeypatch.setattr(
        state_module, "request_custom_audience", lambda *args, **kwargs: calls.append(args)
    )
    await context._custom_audience_action(create=True)
    assert not calls and "confirma" in context.custom_error


@pytest.mark.asyncio
async def test_creation_retry_preserves_key_and_authenticated_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = CustomContext()
    context.custom_confirmed = True
    keys = []

    def create(scope: dict, **kwargs: object) -> CustomAudienceVM:
        assert current_acting_login() == LOGIN
        assert scope == {
            "tenant_id": TENANT,
            "content_draft_id": PIECE,
            "publish_attempt_id": SOURCE,
            "ad_account_id": PIECE,
        }
        keys.append(kwargs["request_key"])
        raise AudienceUnavailable("Consulta el público antes de repetir la creación.")

    monkeypatch.setattr(state_module, "request_custom_audience", create)
    await context._custom_audience_action(create=True)
    context.custom_catalog = replace(
        context.custom_catalog, terms_accepted=True, creation_available=True
    )
    await context._custom_audience_action(create=True)
    assert len(keys) == 2 and keys[0] == keys[1]
    assert not context.custom_working and "Consulta" in context.custom_error


@pytest.mark.asyncio
async def test_late_read_after_business_switch_cannot_replace_new_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = CustomContext()

    def read(scope: dict) -> CustomAudienceCatalogVM:
        assert current_acting_login() == LOGIN
        context.auth.session_tenant_id = str(SOURCE)
        context.custom_catalog = CustomAudienceCatalogVM(notice="Otro negocio")
        context.custom_working = True
        return CustomAudienceCatalogVM(loaded=True, terms_accepted=True, audiences=[ENGAGEMENT])

    monkeypatch.setattr(state_module, "read_custom_audiences", read)
    await context._custom_audience_action(create=False)
    assert context.custom_catalog.notice == "Otro negocio" and context.custom_working


@pytest.mark.asyncio
async def test_late_read_after_account_change_is_discarded(monkeypatch: pytest.MonkeyPatch) -> None:
    context = CustomContext()

    def read(scope: dict) -> CustomAudienceCatalogVM:
        context.sources = [replace(context.sources[0], ad_account_id=str(AUDIENCE))]
        context.custom_catalog = CustomAudienceCatalogVM(notice="Otra cuenta")
        return CustomAudienceCatalogVM(loaded=True, terms_accepted=True, audiences=[ENGAGEMENT])

    monkeypatch.setattr(state_module, "read_custom_audiences", read)
    await context._custom_audience_action(create=False)
    assert context.custom_catalog.notice == "Otra cuenta"


@pytest.mark.asyncio
async def test_unavailable_selected_audience_remains_visible_and_blocks_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = CustomContext()
    context.form = replace(context.form, custom_audiences=[ENGAGEMENT])
    context.confirm_charge = True
    monkeypatch.setattr(
        state_module,
        "read_custom_audiences",
        lambda scope: CustomAudienceCatalogVM(loaded=True, terms_accepted=True),
    )
    await context._custom_audience_action(create=False)
    assert context.form.custom_audiences[0].name == ENGAGEMENT.name
    assert not context.form.custom_audiences[0].available
    assert "Vuelve a consultar" in step_problem(context.form, 3)
    assert not context.confirm_charge and not context.review.review_id


def test_provider_preserves_unknown_terms_and_never_treats_truthy_values_as_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def read(**kwargs: object) -> CustomAudienceCatalog:
        return CustomAudienceCatalog(
            None,
            False,
            "Vuelve a consultar los términos.",
            (CustomAudienceSummary(AUDIENCE, "Interacciones", "engagement", "unknown"),),
        )

    monkeypatch.setattr(provider, "list_custom_audiences", read)
    catalog = provider.read_custom_audiences({})
    assert catalog.loaded and not catalog.terms_accepted and not catalog.creation_available
    assert not catalog.audiences[0].available
    assert not {"access_token", "credential", "ciphertext"}.intersection(asdict(catalog))


def test_creation_local_guidance_rejects_housing_lookalike_and_invalid_retention() -> None:
    values = dict(
        name="Mi público",
        kind="engagement",
        retention="365",
        seed_id="",
        country="CO",
        housing=False,
    )
    assert creation_problem(**values) == ""
    assert creation_problem(**{**values, "retention": "731"})
    assert creation_problem(**{**values, "kind": "lookalike", "housing": True})


def test_optional_audience_components_construct_with_labels_and_next_actions() -> None:
    rendered = repr(custom_audiences().render())
    assert "Consultar p" in rendered and "Crear p" in rendered
    assert "https://adsmanager.facebook.com/" in rendered
    assert "custom-audience-name" in rendered and "custom-audience-seed" in rendered
