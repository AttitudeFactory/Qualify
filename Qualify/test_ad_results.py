"""Results must preserve unknowns, tenant isolation and explicit pause consent."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
from qualify_api.ads.results import DailyInsight, PromotionResults, PromotionResultSummary
from qualify_api.tenancy.acting import current_acting_login

from . import ad_results_provider as provider
from . import ad_results_state as state_module
from .ad_results_page import _detail, ad_result_detail_index, ad_results_index
from .ad_results_state import AdResultsState
from .ad_results_vm import (
    LOAD_FAILED,
    NO_SESSION,
    PAUSE_FAILED,
    REFRESH_FAILED,
    URGENT_PAUSE,
    AdDetailVM,
    AdEditOutcomeVM,
    AdEditReviewVM,
    AdResultVM,
    AlertAccountVM,
    EditInputError,
    day_label,
    edit_budget,
    edit_end,
    money_label,
    number_label,
)
from .auth_state import AuthState, business_state_classes
from .ui.layout import NAV_ROUTES
from .ui.nav_vm import current_routes

TENANT, LOGIN, USER, PROMOTION = [
    UUID(f"{prefix}0000000-0000-4000-8000-000000000001") for prefix in "abcd"
]
CONTEXT = (str(TENANT), str(LOGIN), str(USER))


def summary(**changes: object) -> PromotionResultSummary:
    return replace(
        PromotionResultSummary(
            id=PROMOTION,
            brand_id=USER,
            status="ACTIVE",
            status_label="Activo",
            currency="USD",
            budget_minor=12345,
            budget_kind="lifetime",
            end_time=datetime(2027, 1, 20, tzinfo=UTC),
            checked_at=datetime(2027, 1, 15, tzinfo=UTC),
            caption="Una oferta",
            account_name="Mi negocio",
            timezone_name="America/Bogota",
            can_pause=True,
            stale=False,
        ),
        **changes,
    )


def detail() -> AdDetailVM:
    return AdDetailVM(promotion=provider.summary_vm(summary()))


def test_missing_results_do_not_become_zero_or_inherit_another_currency() -> None:
    result = PromotionResults(
        promotion=summary(),
        daily=(
            DailyInsight(
                day=date(2027, 1, 14),
                currency="USD",
                spend=Decimal("12.34"),
                reach=None,
                impressions=1234,
                clicks=0,
                ctr=None,
                cpc=None,
                cpm=Decimal("10"),
            ),
        ),
        updated_at=None,
    )
    vm = provider.detail_vm(result)
    assert vm.days[0].spend == "12,34 USD"
    assert vm.days[0].reach == vm.days[0].ctr == "Sin datos"
    assert vm.days[0].clicks == "0"
    assert vm.days[0].impressions == "1.234"
    assert vm.promotion.approved_budget == "123,45 USD"
    assert vm.promotion.currency == "USD"
    assert "COP" not in repr(vm)
    assert "UTC" not in vm.promotion.checked_label


@pytest.mark.parametrize("value", [None, True, Decimal("NaN"), Decimal("Infinity"), -1])
def test_invalid_or_missing_numeric_values_stay_unknown(value: object) -> None:
    assert number_label(value) == "Sin datos"


def test_unknown_money_currency_and_account_timezone_remain_explicit() -> None:
    assert money_label(Decimal("5"), "") == "Moneda por comprobar"
    assert money_label(Decimal("5"), "usd") == "Moneda por comprobar"
    now = datetime(2027, 1, 16, 2, tzinfo=UTC)
    assert day_label(date(2027, 1, 14), "America/Bogota", now) == "Ayer · 14/01/2027"
    assert day_label(date(2027, 1, 14), "", now) == "14/01/2027"
    assert day_label(date(2027, 1, 14), "invalid/zone", now) == "14/01/2027"


def test_old_active_observation_never_claims_current_delivery_or_enables_pause() -> None:
    vm = provider.summary_vm(summary(stale=True))
    assert vm.status_label == "Último estado: Activo"
    assert vm.tone == "warn" and not vm.can_pause
    failed = provider.summary_vm(summary(refresh_failed=True))
    assert failed.status_label == "Último estado: Activo" and not failed.can_pause


class Context:
    _session = AdResultsState._session
    _clear = AdResultsState._clear
    _clear_edit_review = AdResultsState._clear_edit_review
    _mark_uncertain = AdResultsState._mark_uncertain
    _edit_snapshot = AdResultsState._edit_snapshot
    _edit_allowed = AdResultsState._edit_allowed

    def __init__(self) -> None:
        self.auth = SimpleNamespace(
            session_tenant_id=str(TENANT), _auth_user_id=str(LOGIN), _session_user_id=str(USER)
        )
        self._context = CONTEXT
        self._selected_id = str(PROMOTION)
        self._operation = "initial"
        self._pause_request = ""
        self.detail = detail()
        self.ads = [self.detail.promotion]
        self.loading = False
        self.busy = False
        self.error = ""
        self.notice = ""
        self.pause_open = False
        self.edit_open = False
        self.edit_action = ""
        self.edit_budget_total = ""
        self.edit_end_local = ""
        self.edit_review = AdEditReviewVM()
        self.edit_consent = False
        self.edit_warning = ""
        self.change_pending = False
        self._edit_request = ""
        self._edit_token = ""
        self._edit_expires = ""
        self.promotion_id = str(PROMOTION)
        self.floor_label = ""
        self.floor_loading = False
        self._floor_input = ""
        self.alert_accounts = []
        self.alert_target = AlertAccountVM("", "")
        self.alerts_busy = False
        self.alerts_notice = ""
        self.alerts_error = ""

    async def __aenter__(self) -> Context:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def get_state(self, state_class: type) -> object:
        assert state_class is AuthState
        return self.auth


def editable_context() -> Context:
    context = Context()
    context.detail = replace(
        context.detail,
        promotion=replace(
            context.detail.promotion,
            currency="COP",
            can_manage=True,
            can_resume=True,
            current_budget_input="10000",
            current_end_input="2027-01-20T12:00",
        ),
    )
    return context


@pytest.mark.parametrize("value", ["10000", "9999", "10.001", "10001.5", "10,001", "١٠٠٠١", "-1"])
def test_edit_budget_rejects_non_increases_and_fractional_or_formatted_pesos(value: str) -> None:
    with pytest.raises(EditInputError):
        edit_budget(value, "10000")


def test_edit_inputs_preserve_exact_cop_and_account_timezone() -> None:
    assert edit_budget("10001", "10000") == 1000100
    assert edit_end("2027-01-20T12:00", "America/Bogota").hour == 12
    with pytest.raises(EditInputError):
        edit_end("2027-01-20T12:00+05:00", "America/Bogota")


@pytest.mark.asyncio
async def test_edit_requires_review_consent_and_blocks_retry_after_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = editable_context()
    calls = []

    def confirm(*args: object) -> AdEditOutcomeVM:
        assert current_acting_login() == LOGIN
        calls.append(args)
        return AdEditOutcomeVM(str(PROMOTION), "budget", "unknown", "No confirmado")

    monkeypatch.setattr(state_module, "confirm_edit", confirm)
    AdResultsState.open_edit.fn(context, "budget")
    context.edit_budget_total = "12000"
    await AdResultsState.confirm_change.fn(context)
    assert not calls
    context.edit_review = AdEditReviewVM(action="budget", ready=True)
    context._edit_token = "private-review"
    context._edit_expires = (datetime.now(UTC) + timedelta(minutes=2)).isoformat()
    await AdResultsState.confirm_change.fn(context)
    assert not calls
    AdResultsState.set_edit_consent.fn(context, True)
    await AdResultsState.confirm_change.fn(context)
    assert len(calls) == 1 and context.change_pending and not context.notice
    assert not context.detail.promotion.can_manage
    AdResultsState.set_edit_budget_total.fn(context, "14000")
    AdResultsState.open_edit.fn(context, "resume")
    await AdResultsState.confirm_change.fn(context)
    assert len(calls) == 1 and context.edit_budget_total == "12000"
    assert not context._edit_token
    AdResultsState.ask_pause.fn(context)
    assert not context.pause_open
    monkeypatch.setattr(state_module, "pause_ad", lambda *args: pytest.fail("pending pause wrote"))
    await AdResultsState.confirm_pause.fn(context)
    assert len(calls) == 1
    from .ad_results_page import _management

    assert URGENT_PAUSE in str(_management().render())


@pytest.mark.asyncio
async def test_expired_review_clears_consent_preserves_inputs_and_does_not_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = editable_context()
    AdResultsState.open_edit.fn(context, "budget")
    context.edit_budget_total = "12000"
    context.edit_review = AdEditReviewVM(action="budget", ready=True)
    context.edit_consent = True
    context._edit_token = "private-review"
    context._edit_expires = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    monkeypatch.setattr(
        state_module, "confirm_edit", lambda *args: pytest.fail("expired review wrote")
    )
    await AdResultsState.confirm_change.fn(context)
    assert context.edit_budget_total == "12000"
    assert not context.edit_consent and not context._edit_token and not context.edit_review.ready


def test_operational_values_never_fall_back_to_original_approval() -> None:
    vm = provider.summary_vm(summary())
    assert vm.approved_budget == "123,45 USD"
    assert vm.current_budget != vm.approved_budget


def test_review_approval_material_never_enters_reflex_frontend_vars() -> None:
    assert "_edit_token" not in AdResultsState.vars
    assert "_edit_expires" not in AdResultsState.vars
    assert "approval_token" not in AdEditReviewVM.__dataclass_fields__


@pytest.mark.parametrize(
    "ready,label,event",
    [
        (False, "Comprobar cambio", "prepare_change"),
        (True, "Confirmar cambio", "confirm_change"),
    ],
)
def test_actual_primary_action_render_has_one_button_for_each_review_phase(
    ready: bool,
    label: str,
    event: str,
) -> None:
    from .ad_results_page import _edit_primary_action

    conditional = _edit_primary_action(ready).render()["children"][0]
    assert conditional["cond_state"] == str(ready).lower()
    active = conditional["true_value" if ready else "false_value"]
    assert len(active["children"]) == 1
    button = active["children"][0]
    assert button["name"] == "RadixThemesButton"
    # The confirm label depends on the action («Guardar presupuesto» when lowering it).
    assert f'"{label}"' in str(button["children"])
    assert any(event in prop for prop in button["props"])
    assert not any(
        ("prepare_change" if ready else "confirm_change") in prop for prop in button["props"]
    )


def test_pending_backend_operation_disables_every_management_action() -> None:
    row = summary(currency="COP", operation_pending=True, can_manage=True, can_resume=True)
    vm = provider.summary_vm(row)
    assert not vm.can_pause and not vm.can_manage and not vm.can_resume


@pytest.mark.asyncio
async def test_preparation_does_not_restore_review_after_input_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = editable_context()
    AdResultsState.open_edit.fn(context, "budget")
    context.edit_budget_total = "12000"

    def prepare(*args: object, **kwargs: object) -> provider.PreparedAdEdit:
        assert current_acting_login() == LOGIN
        assert kwargs["budget_minor"] == 1200000
        AdResultsState.set_edit_budget_total.fn(context, "14000")
        return provider.PreparedAdEdit(
            AdEditReviewVM(action="budget", ready=True),
            "private-review",
            datetime.now(UTC) + timedelta(minutes=2),
        )

    monkeypatch.setattr(state_module, "prepare_edit", prepare)
    await AdResultsState.prepare_change.fn(context)
    assert context.edit_budget_total == "14000"
    assert not context.edit_review.ready and not context._edit_token
    assert not context.busy


@pytest.mark.asyncio
async def test_business_switch_before_confirmation_never_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = editable_context()
    AdResultsState.open_edit.fn(context, "resume")
    context.edit_review = AdEditReviewVM(action="resume", ready=True)
    context.edit_consent = True
    context._edit_token = "private-review"
    context._edit_expires = (datetime.now(UTC) + timedelta(minutes=2)).isoformat()
    context.auth.session_tenant_id = str(USER)
    monkeypatch.setattr(state_module, "confirm_edit", lambda *args: pytest.fail("foreign write"))
    await AdResultsState.confirm_change.fn(context)
    assert not context._edit_token and context.detail.promotion.id == ""
    assert context.error == NO_SESSION


@pytest.mark.asyncio
async def test_readonly_refresh_keeps_pending_latch_until_backend_reports_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = editable_context()
    context._mark_uncertain()
    pending = context.detail
    monkeypatch.setattr(state_module, "refresh_ad", lambda *args: pending)
    await AdResultsState.refresh.fn(context)
    assert context.change_pending and not context.notice
    resolved = replace(
        pending,
        promotion=replace(
            pending.promotion,
            operation_pending=False,
            stale=False,
            can_manage=True,
        ),
    )
    monkeypatch.setattr(state_module, "refresh_ad", lambda *args: resolved)
    await AdResultsState.refresh.fn(context)
    assert not context.change_pending and not context.edit_warning


@pytest.mark.asyncio
async def test_pause_requires_confirmation_and_auth_actor_is_forwarded_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Context()
    calls = []

    def pause(*args: object) -> AdDetailVM:
        assert current_acting_login() == LOGIN
        calls.append(args)
        return replace(detail(), promotion=replace(detail().promotion, can_pause=False))

    monkeypatch.setattr(state_module, "pause_ad", pause)
    await AdResultsState.confirm_pause.fn(context)
    assert calls == []
    AdResultsState.ask_pause.fn(context)
    request = context._pause_request
    assert request
    await AdResultsState.confirm_pause.fn(context)
    assert calls == [(TENANT, PROMOTION, request)]
    assert not context.pause_open and not context.busy and not context._pause_request
    await AdResultsState.confirm_pause.fn(context)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_business_switch_clears_old_detail_and_never_sends_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Context()
    calls = []
    AdResultsState.ask_pause.fn(context)
    context.auth.session_tenant_id = str(USER)
    monkeypatch.setattr(state_module, "pause_ad", lambda *args: calls.append(args))
    await AdResultsState.confirm_pause.fn(context)
    assert calls == []
    assert context.detail == AdDetailVM() and context.ads == []
    assert context.error == NO_SESSION and not context.pause_open


@pytest.mark.asyncio
async def test_unknown_pause_result_disables_retry_until_read_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Context()

    def fail(*args: object) -> None:
        raise RuntimeError("access_token=never-display-this")

    monkeypatch.setattr(state_module, "pause_ad", fail)
    AdResultsState.ask_pause.fn(context)
    await AdResultsState.confirm_pause.fn(context)
    assert context.error == PAUSE_FAILED
    assert not context.detail.promotion.can_pause
    assert context.detail.promotion.stale and context.detail.promotion.refresh_failed
    assert context.detail.promotion.tone == "warn"
    assert context.detail.promotion.status_label == "Último estado: Activo"
    assert not context._pause_request and not context.busy
    AdResultsState.ask_pause.fn(context)
    assert not context.pause_open


@pytest.mark.asyncio
async def test_late_refresh_cannot_repaint_a_new_business(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Context()

    def refresh(*args: object) -> AdDetailVM:
        assert current_acting_login() == LOGIN
        context.auth.session_tenant_id = str(USER)
        context._operation = "new-business-operation"
        context.detail = AdDetailVM()
        context.busy = True
        return detail()

    monkeypatch.setattr(state_module, "refresh_ad", refresh)
    await AdResultsState.refresh.fn(context)
    assert context.detail == AdDetailVM() and context.busy


@pytest.mark.asyncio
async def test_refresh_failure_keeps_cached_measurements_and_hides_raw_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Context()

    def fail(*args: object) -> None:
        raise RuntimeError("access_token=never-display-this")

    monkeypatch.setattr(state_module, "refresh_ad", fail)
    await AdResultsState.refresh.fn(context)
    assert context.detail.promotion.id == detail().promotion.id
    assert context.detail.promotion.stale and context.detail.promotion.refresh_failed
    assert not context.detail.promotion.can_pause
    assert context.detail.promotion.status_label.startswith("Último estado:")
    assert context.error == REFRESH_FAILED and not context.busy


@pytest.mark.asyncio
async def test_cached_reads_require_session_and_propagate_authenticated_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Context()
    calls = []

    def read(tenant_id: UUID) -> list[AdResultVM]:
        assert current_acting_login() == LOGIN
        calls.append(tenant_id)
        return [detail().promotion]

    monkeypatch.setattr(state_module, "load_ads", read)
    await AdResultsState.load_list.fn(context)
    assert calls == [TENANT] and context.ads == [detail().promotion]
    context.auth._auth_user_id = ""
    await AdResultsState.load_list.fn(context)
    assert calls == [TENANT] and context.ads == [] and context.error == NO_SESSION


@pytest.mark.asyncio
async def test_detail_read_error_never_exposes_remote_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Context()

    def read(*args: object) -> None:
        raise ValueError("secret remote response")

    monkeypatch.setattr(state_module, "load_ad", read)
    await AdResultsState.load_detail.fn(context)
    assert context.detail == AdDetailVM() and context.error == LOAD_FAILED


def test_results_state_resets_with_business_and_has_own_highlighted_route() -> None:
    assert AdResultsState in business_state_classes()
    assert current_routes(NAV_ROUTES, "/promotions") == ["/promotions"]
    assert current_routes(NAV_ROUTES, f"/promotions/{PROMOTION}") == ["/promotions"]
    assert not {"token", "ciphertext", "access_token"}.intersection(asdict(detail().promotion))


def test_actual_components_construct_with_dates_unknowns_and_confirmation() -> None:
    listing = repr(ad_results_index().render())
    detail_render = repr(ad_result_detail_index().render())
    assert "Anuncios" in listing and "Ver estado y resultados" in listing
    assert "Resultados por d" in detail_render and "Confirmar pausa" in detail_render
    assert "La falta de datos no significa" in detail_render
    # The app shell owns a trusted static SVG filter; provider content is text only.
    assert "dangerouslySetInnerHTML" not in repr(_detail().render())
