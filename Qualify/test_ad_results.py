"""Results must preserve unknowns, tenant isolation and explicit pause consent."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
from qualify_api.ads.results import (
    DailyInsight,
    PromotionResults,
    PromotionResultSummary,
    ResultsUnavailable,
)
from qualify_api.tenancy.acting import current_acting_login

from . import ad_results_provider as provider
from . import ad_results_state as state_module
from .ad_results_page import _detail, ad_result_detail_index, ad_results_index
from .ad_results_state import AdResultsState
from .ad_results_vm import (
    LOAD_FAILED,
    NO_SESSION,
    PAUSE_FAILED,
    PAUSE_HERE,
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
    assert vm.days[0].spend == "$12,34 USD"
    assert vm.days[0].reach == vm.days[0].ctr == "Sin datos"
    assert vm.days[0].clicks == "0"
    assert vm.days[0].impressions == "1.234"
    assert vm.promotion.approved_budget == "$123,45 USD"
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
    _open_edit = AdResultsState._open_edit

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
        self._advised = False
        self.promotion_id = str(PROMOTION)
        self.floor_label = ""
        self.floor_loading = False
        self._floor_input = ""
        self.alert_accounts = []
        self.alert_target = AlertAccountVM("", "")
        self.alerts_busy = False
        self.alerts_on = []
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
        edit_budget(value, "10000", "COP")


def test_edit_inputs_preserve_exact_cop_and_account_timezone() -> None:
    assert edit_budget("10001", "10000", "COP") == 1000100
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

    rendered = str(_management().render())
    # The rendered tree escapes accents; the plain part of the sentence is enough.
    assert URGENT_PAUSE in rendered and PAUSE_HERE.split(",")[1].split(" aqu")[0] in rendered


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
    assert vm.approved_budget == "$123,45 USD"
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


def test_pending_backend_operation_disables_edits_but_never_the_pause() -> None:
    # m-25072681: an unresolved edit keeps edits blocked; the backend's can_pause decides.
    row = summary(currency="COP", operation_pending=True, can_manage=True, can_resume=True)
    vm = provider.summary_vm(row)
    assert vm.can_pause and not vm.can_manage and not vm.can_resume
    assert not provider.summary_vm(replace(row, can_pause=False)).can_pause


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


# --- The traffic light (m-25091390) ---


def _advice(**changes: object):
    from qualify_api.ads.traffic_light import Advice

    return replace(
        Advice(
            "raise",
            "cheap",
            datetime(2027, 1, 15, tzinfo=UTC).isoformat(),
            raise_percent=20,
            cost_per_result_minor=700_000,
            max_cost_minor=2_000_000,
            unspent_minor=10_000_000,
        ),
        **changes,
    )


def _with_advice(advice: object, **changes: object) -> PromotionResults:
    row = summary(currency="COP", current_budget_minor=10_000_000, can_manage=True)
    # (status ACTIVE, ends 2027-01-20: from `summary`)
    return PromotionResults(
        promotion=row,
        daily=(),
        updated_at=datetime(2027, 1, 15, tzinfo=UTC),
        advice=advice,
        **({"insights_stale": False} | changes),
    )


def test_advice_shows_one_light_one_message_and_the_raise_amount() -> None:
    vm = provider.advice_vm(_with_advice(_advice()))
    assert (vm.shown, vm.tone, vm.label) == (True, "ok", "Va bien")
    assert vm.message.startswith(
        "Súbele 20 % a lo que te queda por invertir. Cada persona interesada te cuesta $7.000 COP"
    )
    assert (vm.raise_label, vm.raise_input) == ("Subir a $120.000 COP", "120000")
    assert not vm.new_piece and not vm.profile_link


def test_advice_is_hidden_without_a_current_one() -> None:
    assert not provider.advice_vm(_with_advice(None)).shown
    assert not provider.advice_vm(_with_advice(_advice(), insights_stale=True)).shown
    assert not provider.advice_vm(_with_advice(_advice(), insights_refresh_failed=True)).shown


def test_fatigue_and_meta_creative_fatigue_lead_to_a_new_piece_never_a_raise() -> None:
    fatigue = provider.advice_vm(_with_advice(_advice(action="fatigue", reason="fatigue")))
    assert fatigue.tone == "error" and fatigue.new_piece and not fatigue.can_raise
    meta = provider.advice_vm(
        _with_advice(_advice(action="keep", reason="close", meta=("CREATIVE_FATIGUE",)))
    )
    assert meta.new_piece and not meta.can_raise
    assert meta.meta[0].startswith("Meta sugiere una pieza nueva")
    profile = provider.advice_vm(_with_advice(_advice(action="keep", reason="no_profile")))
    assert profile.profile_link and profile.tone == "warn"


@pytest.mark.asyncio
async def test_advised_raise_opens_the_usual_review_and_prepares_from_the_advice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = editable_context()
    context.detail = replace(context.detail, advice=provider.advice_vm(_with_advice(_advice())))
    calls = []

    def prepare(*args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        raise ResultsUnavailable("stop")

    monkeypatch.setattr(state_module, "prepare_edit", prepare)
    monkeypatch.setattr(
        state_module, "confirm_edit", lambda *a: pytest.fail("never confirmed for the owner")
    )
    AdResultsState.open_advised_raise.fn(context)
    assert context.edit_open and context.edit_action == "budget"
    assert context.edit_budget_total == "120000" and context._advised
    await AdResultsState.prepare_change.fn(context)
    assert calls[-1]["advised"] is True and calls[-1]["budget_minor"] == 12_000_000
    # The owner types another amount: an ordinary edit, not the advice's.
    AdResultsState.set_edit_budget_total.fn(context, "130000")
    await AdResultsState.prepare_change.fn(context)
    assert calls[-1]["advised"] is False and not context._advised


def test_advice_card_renders_with_its_buttons() -> None:
    rendered = repr(_detail().render())
    assert "te recomendamos" in rendered
    # repr() escapes the accent («publicaci\u00f3n»), so match the prefix.
    assert "Crear publicaci" in rendered and "/promotions/perfil" in rendered


@pytest.mark.parametrize("new_budget", [12_000_000, 12_100_000])
def test_provider_prepares_the_advised_raise_and_refuses_another_amount(
    monkeypatch: pytest.MonkeyPatch, new_budget: int
) -> None:
    from qualify_api.ads import traffic_light

    async def advised(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            action="budget",
            summary="Cambiar el presupuesto total.",
            approval_token="sealed",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            current_budget_minor=10_000_000,
            new_budget_minor=new_budget,
            current_end_time=datetime(2027, 1, 20, tzinfo=UTC),
            new_end_time=datetime(2027, 1, 20, tzinfo=UTC),
        )

    monkeypatch.setattr(traffic_light, "prepare_advised_raise", advised)
    call = lambda: provider.prepare_edit(  # noqa: E731
        TENANT, PROMOTION, "key", "budget", "America/Bogota",
        currency="COP", budget_minor=12_000_000, advised=True,
    )  # fmt: skip
    if new_budget == 12_000_000:
        assert call().review.new_budget == "$120.000 COP"
    else:
        with pytest.raises(ResultsUnavailable):
            call()
