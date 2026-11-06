"""Saved brand permissions cannot be confused with current eligibility or paid consent."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.ads.enhancements import BrandEnhancementSettings
from qualify_api.tenancy.acting import current_acting_login

from . import ad_enhancements_provider as provider
from . import ad_enhancements_state as state_module
from .ad_enhancements_state import AdEnhancementsState as S
from .ad_enhancements_vm import (
    FEATURES,
    READ_FAILED,
    SAVE_FAILED,
    BrandEnhancementsVM,
    all_off,
    permission_summary,
)

TENANT, LOGIN, USER, BRAND = (str(uuid4()) for _ in range(4))
CONTEXT = (TENANT, LOGIN, USER, BRAND)


def policy(*, version: int = 0, enabled: bool = False) -> BrandEnhancementsVM:
    values = all_off()
    values["image_touchups"] = enabled
    return BrandEnhancementsVM(BRAND, version, values, True)


def test_unknown_permissions_are_not_presented_as_a_saved_all_off_policy() -> None:
    unknown = BrandEnhancementsVM()
    assert permission_summary(unknown) == "Permisos pendientes de consultar"
    assert permission_summary(policy()) == "Ninguno de estos cuatro cambios permitido"
    assert "retocar" in permission_summary(policy(enabled=True))
    assert all_off() == dict.fromkeys(FEATURES, False)
    assert policy().values == BrandEnhancementSettings(UUID(TENANT), UUID(BRAND)).values


@pytest.mark.parametrize("changed", ["tenant", "brand", "invalid_boolean", "extra_feature"])
def test_provider_rejects_another_scope_or_unrecognized_permissions(changed: str) -> None:
    values: dict[str, Any] = all_off()
    row = SimpleNamespace(tenant_id=UUID(TENANT), brand_id=UUID(BRAND), version=1, values=values)
    if changed == "tenant":
        row.tenant_id = uuid4()
    elif changed == "brand":
        row.brand_id = uuid4()
    elif changed == "invalid_boolean":
        row.values["image_touchups"] = 1
    else:
        row.values["invented_option"] = False
    with pytest.raises(ValueError):
        provider._view(row, UUID(TENANT), UUID(BRAND))


def test_provider_passes_exact_revision_and_values_to_the_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.ads import enhancements_service

    captured = {}
    values = {**all_off(), "enhance_cta": True}

    def save(**kwargs: Any) -> BrandEnhancementSettings:
        captured.update(kwargs)
        return BrandEnhancementSettings(UUID(TENANT), UUID(BRAND), 6, values)

    monkeypatch.setattr(enhancements_service, "save_brand_enhancements", save)
    result = provider.save_policy(UUID(TENANT), UUID(BRAND), values, 5)
    assert captured == {
        "tenant_id": UUID(TENANT),
        "brand_id": UUID(BRAND),
        "values": values,
        "expected_version": 5,
    }
    assert result.version == 6 and result.loaded and result.values == values


class _Context:
    def __init__(self) -> None:
        self.context = CONTEXT
        self._context = CONTEXT
        self._operation = "original"
        self.policy = policy(version=3)
        self.values = {**all_off(), "image_touchups": True}
        self.editing = True
        self.loading = self.saving = False
        self.error = self.notice = ""
        self.prepared_calls = []

    async def __aenter__(self) -> _Context:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def _session(self) -> tuple[str, str, str, str]:
        return self.context

    def _clear(self) -> None:
        S._clear(self)

    async def _invalidate_prepared(self, *args: Any) -> None:
        self.prepared_calls.append(args)

    @property
    def dirty(self) -> bool:
        return self.policy.loaded and self.values != self.policy.values


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["open", "save"])
@pytest.mark.parametrize("changed", [0, 1, 2, 3])
@pytest.mark.parametrize("fails", [False, True])
async def test_late_response_cannot_enter_a_different_business_brand_or_session(
    monkeypatch: pytest.MonkeyPatch, operation: str, changed: int, fails: bool
) -> None:
    context = _Context()

    async def delayed(*args: Any, **kwargs: Any) -> BrandEnhancementsVM:
        assert current_acting_login() == UUID(LOGIN)
        changed_scope = list(context.context)
        changed_scope[changed] = str(uuid4())
        context.context = tuple(changed_scope)
        if fails:
            raise RuntimeError("access_token=private")
        return policy(version=100, enabled=True)

    monkeypatch.setattr(state_module.asyncio, "to_thread", delayed)
    await getattr(S, operation).fn(context)
    assert context.policy.version != 100
    assert context.error == context.notice == ""
    assert "private" not in str(context.values)


@pytest.mark.asyncio
async def test_cancel_while_loading_discards_the_pending_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _Context()

    async def delayed(*args: Any) -> BrandEnhancementsVM:
        S.cancel.fn(context)
        return policy(version=10, enabled=True)

    monkeypatch.setattr(state_module.asyncio, "to_thread", delayed)
    await S.open.fn(context)
    assert not context.editing and not context.loading and not context.policy.loaded
    assert context.values == all_off()


@pytest.mark.asyncio
async def test_successful_save_replaces_the_revision_only_after_server_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _Context()
    seen = []

    async def saved(
        fn: Any, tenant: UUID, brand: UUID, values: dict[str, bool], version: int
    ) -> BrandEnhancementsVM:
        seen.append((tenant, brand, dict(values), version, current_acting_login()))
        assert context.policy.version == 3 and context.saving
        return policy(version=4, enabled=True)

    monkeypatch.setattr(state_module.asyncio, "to_thread", saved)
    await S.save.fn(context)
    assert seen == [(UUID(TENANT), UUID(BRAND), policy(enabled=True).values, 3, UUID(LOGIN))]
    assert context.policy.version == 4 and not context.dirty and not context.saving
    assert "guardados" in context.notice
    assert context.prepared_calls == [(CONTEXT, context.policy)]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,expected", [("open", READ_FAILED), ("save", SAVE_FAILED)])
async def test_read_or_compare_and_swap_failure_requires_reload_and_exposes_no_remote_data(
    monkeypatch: pytest.MonkeyPatch, operation: str, expected: str
) -> None:
    context = _Context()

    async def failed(*args: Any) -> None:
        raise RuntimeError("access_token=private remote SQL")

    monkeypatch.setattr(state_module.asyncio, "to_thread", failed)
    await getattr(S, operation).fn(context)
    assert context.error == expected
    assert not context.policy.loaded and not context.loading and not context.saving
    assert "private" not in context.error
    assert context.notice == ""


def test_cancel_restores_saved_values_and_ignores_unknown_controls() -> None:
    context = _Context()
    S.change.fn(context, "invented", True)
    assert set(context.values) == set(FEATURES)
    S.cancel.fn(context)
    assert context.values == context.policy.values and not context.dirty


def test_logout_registration_and_actual_brand_components_build_without_provider_html() -> None:
    from .ad_enhancements_ui import ad_enhancement_permissions
    from .auth_state import business_state_classes
    from .brand_kit_editor import brand_edit_index

    assert S in business_state_classes()
    rendered = str(ad_enhancement_permissions().render())
    assert "Guardar permisos" in rendered and "Revisar permisos" in rendered
    assert "dangerouslySetInnerHTML" not in rendered
    assert brand_edit_index().render()


def test_unknown_permissions_render_no_checkboxes_and_do_not_claim_a_negative_setting() -> None:
    from .ad_enhancements_ui import _permission_choices

    conditional = _permission_choices().render()["children"][0]
    assert "loaded" in conditional["cond_state"]
    assert "Checkbox" not in str(conditional["false_value"])
    assert "Vuelve a consultar" in str(conditional["false_value"])
    assert "Guardados: " in str(conditional["true_value"])
    assert str(conditional["true_value"]).count("RadixThemesCheckbox") == 4


def test_dirty_editor_marks_saved_summary_and_labels_the_destructive_reload() -> None:
    from .ad_enhancements_ui import ad_enhancement_permissions

    def contents(node: Any) -> list[str]:
        if isinstance(node, dict):
            found = [node["contents"]] if "contents" in node else []
            return found + [row for child in node.values() for row in contents(child)]
        if isinstance(node, list):
            return [row for child in node for row in contents(child)]
        return []

    tree = ad_enhancement_permissions().render()
    reload = [
        row for row in contents(tree) if "Descartar cambios y consultar" in row and ".dirty" in row
    ]
    assert len(reload) == 1
    assert "Volver a consultar" in reload[0]
    assert "Guardados: " in str(tree)


def test_promotion_switch_discards_old_brand_policy_and_paid_consent() -> None:
    from .promotion_state import PromotionState
    from .promotion_vm import PromotionReviewVM, PromotionSourceVM

    other = policy(version=2, enabled=True)
    state = PromotionState()
    state.sources = [
        PromotionSourceVM("one", "@uno", "Uno", enhancements=policy()),
        PromotionSourceVM("two", "@dos", "Dos", enhancements=replace(other, brand_id=str(uuid4()))),
    ]
    state.choose_source("one")
    state.review = PromotionReviewVM(review_id="prepared", preview_url="https://not.used")
    state.reviewed = state.confirm_charge = True
    state.choose_source("two")
    assert state.form.enhancements == state.sources[1].enhancements
    assert not state.review.review_id and not state.reviewed and not state.confirm_charge


def test_unknown_promotion_policy_blocks_preparation_instead_of_claiming_all_off() -> None:
    from .promotion_state import PromotionState
    from .promotion_vm import PromotionDraftVM, PromotionSourceVM

    state = PromotionState()
    state.sources = [PromotionSourceVM("one", "@uno", "Uno")]
    state.form = PromotionDraftVM(source_id="one")
    assert "consultar" in state.execution_reason
    assert "pendientes" in state.enhancement_summary


def test_source_projection_deduplicates_policy_reads_by_brand_and_does_not_read_on_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.ads.wizard import PromotionSource

    from . import promotion_provider

    first = PromotionSource(uuid4(), uuid4(), uuid4(), UUID(BRAND), "123", "456", "Uno", "@uno")
    second = replace(first, publish_attempt_id=uuid4())
    other = replace(first, publish_attempt_id=uuid4(), brand_id=uuid4())
    monkeypatch.setattr(
        promotion_provider, "list_promotion_sources", lambda **kwargs: [first, second, other]
    )
    monkeypatch.setattr(promotion_provider, "read_business_locale", lambda tenant: None)
    monkeypatch.setattr(promotion_provider, "messaging_destinations", lambda *args: [])
    calls = []

    def load(tenant: UUID, brand: UUID) -> BrandEnhancementsVM:
        calls.append((tenant, brand))
        return replace(policy(enabled=brand == UUID(BRAND)), brand_id=str(brand))

    monkeypatch.setattr(promotion_provider, "load_policy", load)
    entry, _ = promotion_provider.load_sources(UUID(TENANT), uuid4())
    assert calls == [] and all(not row.enhancements.loaded for row in entry)
    full, _ = promotion_provider.load_sources(UUID(TENANT), uuid4(), check_health=True)
    assert calls == [(UUID(TENANT), UUID(BRAND)), (UUID(TENANT), other.brand_id)]
    assert full[0].enhancements == full[1].enhancements
    assert full[0].enhancements.values["image_touchups"] is True
    assert full[2].enhancements.values["image_touchups"] is False


def test_prepare_passes_the_captured_policy_and_does_not_replace_it_with_a_later_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import promotion_provider
    from .promotion_vm import PromotionDraftVM

    captured = []

    async def prepare(**kwargs: Any) -> SimpleNamespace:
        captured.append(kwargs["form"].enhancements)
        return SimpleNamespace(
            preview_html='<iframe src="https://www.facebook.com/ads/api/preview_iframe.php?d=test">'
            "</iframe>",
            promotion_id=uuid4(),
            review_id=uuid4(),
            charge_notice="No enviado",
            expires_at=datetime(2027, 1, 1, tzinfo=UTC),
        )

    monkeypatch.setattr(promotion_provider, "prepare_promotion_preview", prepare)
    monkeypatch.setattr(
        promotion_provider, "load_policy", lambda *args: pytest.fail("Keep the accepted revision")
    )
    form = PromotionDraftVM(
        source_id=str(uuid4()),
        link_url="https://example.com/oferta",
        city_name="Cúcuta",
        location_key="123",
        location_country="CO",
        budget="25000",
        start_local="2027-01-10T09:00",
        end_local="2027-01-17T09:00",
        enhancements=policy(version=7, enabled=True),
    )
    promotion_provider.prepare_preview(
        UUID(TENANT), uuid4(), UUID(USER), form, "America/Bogota", "one-request"
    )
    assert captured == [
        BrandEnhancementSettings(UUID(TENANT), UUID(BRAND), 7, form.enhancements.values)
    ]
    with pytest.raises(ValueError, match="consultar"):
        promotion_provider.prepare_preview(
            UUID(TENANT),
            uuid4(),
            UUID(USER),
            replace(form, enhancements=BrandEnhancementsVM()),
            "America/Bogota",
            "unknown-permissions",
        )


class _PromotionContext:
    def __init__(self) -> None:
        from .promotion_vm import PromotionDraftVM, PromotionReviewVM, PromotionSourceVM

        self.context = CONTEXT[:3]
        self._loaded_context = self.context
        self._piece_id = str(uuid4())
        self.form = PromotionDraftVM(
            source_id=str(uuid4()),
            budget="25000",
            link_url="https://example.com",
            enhancements=policy(),
        )
        self.sources = [
            PromotionSourceVM(
                self.form.source_id,
                "@uno",
                "Uno",
                brand_id=BRAND,
                enhancements=self.form.enhancements,
            )
        ]
        self.step = 4
        self.review = PromotionReviewVM(review_id="old", preview_url="https://not.used")
        self.reviewed = self.confirm_charge = True
        self.success = ""
        self.busy = self.loading = self.enhancements_working = False
        self.enhancements_notice = self._enhancements_operation = ""

    @property
    def selected_source(self) -> Any:
        return self.sources[0]

    async def _session(self) -> tuple[str, str, str]:
        return self.context

    async def __aenter__(self) -> _PromotionContext:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def _invalidate_review(self) -> None:
        from .promotion_state import PromotionState

        PromotionState._invalidate_review(self)

    async def _enhancements_current(self, *args: Any) -> bool:
        from .promotion_state import PromotionState

        return await PromotionState._enhancements_current(self, *args)


@pytest.mark.asyncio
async def test_refresh_preserves_form_and_step_and_invalidates_old_paid_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import promotion_state

    context = _PromotionContext()
    before = context.form
    context.sources.append(replace(context.sources[0], id=str(uuid4())))
    context.sources.append(replace(context.sources[0], id=str(uuid4()), brand_id=str(uuid4())))
    captured = []

    def load(*args: Any) -> BrandEnhancementsVM:
        captured.append((*args, current_acting_login()))
        return policy(version=2, enabled=True)

    monkeypatch.setattr(promotion_state, "recheck_enhancement_permissions", load)
    await promotion_state.PromotionState.recheck_enhancements.fn(context)
    assert context.form == replace(before, enhancements=policy(version=2, enabled=True))
    assert context.step == 4 and not context.reviewed and not context.confirm_charge
    assert not context.review.review_id and not context.enhancements_working
    assert captured == [
        (UUID(TENANT), UUID(context._piece_id), UUID(before.source_id), UUID(BRAND), UUID(LOGIN))
    ]
    assert context.sources[0].enhancements == context.sources[1].enhancements
    assert context.sources[2].enhancements.version == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["session", "piece", "source", "brand"])
@pytest.mark.parametrize("fails", [False, True])
async def test_late_policy_refresh_cannot_change_another_promotion_context(
    monkeypatch: pytest.MonkeyPatch, changed: str, fails: bool
) -> None:
    from . import promotion_state

    context = _PromotionContext()

    async def delayed(*args: Any) -> BrandEnhancementsVM:
        if changed == "session":
            context.context = tuple(str(uuid4()) for _ in range(3))
        elif changed == "piece":
            context._piece_id = str(uuid4())
        elif changed == "source":
            context.form = replace(context.form, source_id=str(uuid4()))
        else:
            context.sources = [replace(context.sources[0], brand_id=str(uuid4()))]
        if fails:
            raise RuntimeError("private old response")
        return policy(version=100, enabled=True)

    monkeypatch.setattr(promotion_state.asyncio, "to_thread", delayed)
    await promotion_state.PromotionState.recheck_enhancements.fn(context)
    assert context.form.enhancements.version != 100 and context.enhancements_notice == ""


@pytest.mark.asyncio
async def test_failed_refresh_makes_permissions_unknown_instead_of_reusing_old_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import promotion_state

    context = _PromotionContext()

    async def failed(*args: Any) -> None:
        raise RuntimeError("token=private")

    monkeypatch.setattr(promotion_state.asyncio, "to_thread", failed)
    await promotion_state.PromotionState.recheck_enhancements.fn(context)
    assert not context.form.enhancements.loaded and not context.confirm_charge
    assert not context.sources[0].enhancements.loaded
    assert not context.enhancements_working and "private" not in context.enhancements_notice


@pytest.mark.parametrize("other", ["none", "tenant", "login", "user", "brand"])
def test_saved_policy_invalidates_only_same_brand_session_draft(other: str) -> None:
    from .ad_enhancements_state import apply_policy_to_current_draft
    from .promotion_state import PromotionState

    state = PromotionState()
    context = _PromotionContext()
    state.sources = context.sources
    state.form = context.form
    state._loaded_context = CONTEXT[:3]
    state.review = context.review
    state.confirm_charge = state.reviewed = True
    scope = list(CONTEXT)
    if other != "none":
        scope[["tenant", "login", "user", "brand"].index(other)] = str(uuid4())
    changed = apply_policy_to_current_draft(state, tuple(scope), policy(version=5, enabled=True))
    assert changed is (other == "none")
    if changed:
        assert not state.review.review_id and not state.reviewed and not state.confirm_charge
        assert state.form.enhancements.version == 5
    else:
        assert state.review.review_id == "old" and state.confirm_charge


@pytest.mark.asyncio
async def test_a_preference_change_during_preview_discards_only_the_stale_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import promotion_state
    from .promotion_vm import PromotionReviewVM
    from .test_promotion_wizard import ActionContext

    context = ActionContext()
    context.form = replace(context.form, enhancements=policy())
    context.review = PromotionReviewVM()

    def delayed(*args: Any) -> PromotionReviewVM:
        context.form = replace(context.form, enhancements=policy(version=4, enabled=True))
        context._invalidate_review()
        return PromotionReviewVM(review_id="stale-allowed-improvements", preview_url="https://old")

    monkeypatch.setattr(promotion_state, "prepare_preview", delayed)
    await context._remote(confirm=False)
    assert not context.review.review_id and not context.reviewed and not context.confirm_charge
    assert not context.busy
