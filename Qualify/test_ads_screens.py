"""m-25026344: lead-ad step, lowering a budget, Meta rejection and Meta notices."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from qualify_api.ads.results import ResultsUnavailable
from qualify_api.tenancy.acting import current_acting_login

from . import ad_results_provider as results_provider
from . import ad_results_state as results_state
from . import promotion_provider
from .ad_enhancements_vm import BrandEnhancementsVM
from .ad_results_page import _detail, _edit_confirmation, ad_results_index
from .ad_results_state import AdResultsState
from .ad_results_vm import (
    ALERTS_ALREADY_ON,
    ALERTS_ON,
    FLOOR_FAILED,
    NO_REJECTION_REASON,
    AlertAccountVM,
    EditInputError,
    budget_down_summary,
    edit_budget_down,
    floor_label,
    rejection_text,
)
from .promotion_page import _destination, _review
from .promotion_state import PromotionState
from .promotion_vm import LeadFormChoiceVM, PromotionSourceVM, step_problem
from .test_ad_results import LOGIN, PROMOTION, TENANT, editable_context, summary
from .test_promotion_wizard import PIECE, SOURCE, USER, ZONE, valid_form

FORM_A = "f0000000-0000-4000-8000-00000000000a"
FORM_B = "f0000000-0000-4000-8000-00000000000b"
ACCOUNT = "90000000-0000-4000-8000-000000000001"


# --- 1. «¿Qué quieres que haga la gente?» -------------------------------------------


def test_lead_goal_needs_a_form_and_a_known_button_but_no_link() -> None:
    draft = replace(valid_form(), goal="lead", link_url="")
    assert "formulario" in step_problem(draft, 2)
    assert step_problem(replace(draft, lead_form_id=FORM_A), 2) == ""
    assert "botón" in step_problem(replace(draft, lead_form_id=FORM_A, lead_cta="BUY_NOW"), 2)
    assert "https://" in step_problem(replace(draft, goal="visit"), 2)


def test_ready_forms_only_published_and_last_used_first(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        SimpleNamespace(id=UUID(FORM_B), name="Cotización", status="published", meta_form_id="7"),
        SimpleNamespace(id=UUID(FORM_A), name="Registro", status="published", meta_form_id="8"),
        SimpleNamespace(id=UUID(int=3), name="Borrador", status="draft", meta_form_id=""),
    ]
    monkeypatch.setattr(promotion_provider, "list_lead_forms", lambda **kwargs: rows)
    monkeypatch.setattr(promotion_provider, "last_used_lead_form", lambda tenant: FORM_A)
    forms, error = promotion_provider.ready_lead_forms(TENANT, PIECE)
    assert [row.id for row in forms] == [FORM_A, FORM_B] and error == ""


def test_failed_form_read_is_not_shown_as_no_forms(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**kwargs: object) -> list:
        raise RuntimeError("db down")

    monkeypatch.setattr(promotion_provider, "list_lead_forms", boom)
    forms, error = promotion_provider.ready_lead_forms(TENANT, PIECE)
    assert forms == [] and error == promotion_provider.LEAD_FORMS_FAILED


def test_preview_sends_the_published_form_and_button_instead_of_a_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    target = object()
    monkeypatch.setattr(
        promotion_provider,
        "published_lead_form",
        lambda tenant, form: seen.update(f=form) or target,
    )

    async def prepare(**kwargs: object) -> SimpleNamespace:
        seen["form"] = kwargs["form"]
        return SimpleNamespace(
            promotion_id=PIECE,
            review_id=SOURCE,
            preview_html='<iframe src="https://www.facebook.com/ads/api/preview_iframe.php?d=1">'
            "</iframe>",
            charge_notice="Meta cobrará hasta el importe que autorices.",
            expires_at=datetime(2027, 1, 1, tzinfo=UTC),
            checks=(),
        )

    monkeypatch.setattr(promotion_provider, "prepare_promotion_preview", prepare)
    draft = replace(
        valid_form(),
        goal="lead",
        lead_form_id=FORM_A,
        lead_cta="SIGN_UP",
        enhancements=BrandEnhancementsVM(str(TENANT), loaded=True),
    )
    promotion_provider.prepare_preview(TENANT, PIECE, USER, draft, ZONE, "lead-choice")
    form = seen["form"]
    assert seen["f"] == UUID(FORM_A)
    assert form.lead_form is target and form.lead_cta == "SIGN_UP" and form.link_url == ""


class GoalContext:
    _invalidate_review = PromotionState._invalidate_review

    def __init__(self) -> None:
        self.form = replace(valid_form(), lead_form_id=FORM_A)
        self.selected_source = PromotionSourceVM(
            str(SOURCE),
            "@negocio",
            "Una oferta",
            lead_forms=[LeadFormChoiceVM(FORM_A, "Registro"), LeadFormChoiceVM(FORM_B, "Otro")],
        )
        self.busy = False
        self.error = "old"
        self.review = SimpleNamespace(review_id="r")
        self.checks = ["x"]
        self.reviewed = True
        self.confirm_charge = True
        self.success = ""
        self._request_key = "k"


def test_goal_form_and_button_choices_invalidate_the_review() -> None:
    context = GoalContext()
    PromotionState.choose_goal.fn(context, "lead")
    assert context.form.goal == "lead" and not context.reviewed and not context.confirm_charge
    PromotionState.choose_lead_form.fn(context, "not-a-form-of-this-account")
    assert context.form.lead_form_id == FORM_A
    PromotionState.choose_lead_form.fn(context, FORM_B)
    PromotionState.choose_lead_cta.fn(context, "BUY_NOW")
    PromotionState.choose_lead_cta.fn(context, "LEARN_MORE")
    assert context.form.lead_form_id == FORM_B and context.form.lead_cta == "LEARN_MORE"


def test_lead_step_and_review_render_spanish_choices() -> None:
    step = str(_destination().render())
    for text in (  # accents may render escaped
        "Que te deje sus datos para contactarla",
        "Pedir cotizaci",
        "Registrarme",
        "informaci",
        "Crear formulario",
        "/promotions/forms",
    ):
        assert text in step
    assert "Formulario" in str(_review().render())


# --- 2. «Bajar presupuesto» ---------------------------------------------------------


@pytest.mark.parametrize("value", ["10000", "12000", "0", "5.000", "abc", ""])
def test_budget_down_must_be_a_lower_whole_amount(value: str) -> None:
    with pytest.raises(EditInputError):
        edit_budget_down(value, "10000", "")


def test_budget_down_below_known_floor_shows_the_minimum() -> None:
    with pytest.raises(EditInputError, match=r"Puedes bajarlo hasta \$6\.000"):
        edit_budget_down("5000", "10000", "6000")
    assert edit_budget_down("6000", "10000", "6000") == 600_000
    assert edit_budget_down("5000", "10000", "") == 500_000  # Meta still checks at prepare


def test_floor_and_summary_are_plain_pesos() -> None:
    assert floor_label(12_000_000, 8_000_000) == "Mínimo: $120.000 (ya gastaste $80.000)"
    assert budget_down_summary(20_000_000, 15_000_000) == (
        "Tu anuncio podrá gastar hasta $150.000 en total, en vez de $200.000."
    )


@pytest.mark.asyncio
async def test_lowering_reads_the_floor_and_never_prepares_below_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = editable_context()
    assert AdResultsState.open_edit.fn(context, "budget_down") is AdResultsState.load_floor
    assert context.edit_budget_total == "10000"

    def floor(tenant: UUID, promotion: UUID) -> tuple[str, str]:
        assert current_acting_login() == LOGIN and promotion == PROMOTION
        return floor_label(600_000, 200_000), "6000"

    monkeypatch.setattr(results_state, "read_floor", floor)
    await AdResultsState.load_floor.fn(context)
    assert context.floor_label == "Mínimo: $6.000 (ya gastaste $2.000)"
    monkeypatch.setattr(results_state, "prepare_edit", lambda *a, **k: pytest.fail("prepared"))
    context.edit_budget_total = "5000"
    await AdResultsState.prepare_change.fn(context)
    assert "$6.000" in context.error
    calls = []

    def prepare(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        raise ResultsUnavailable("Puedes bajarlo hasta $7.000.")

    monkeypatch.setattr(results_state, "prepare_edit", prepare)
    context.edit_budget_total = "6500"
    await AdResultsState.prepare_change.fn(context)
    assert calls[0][0][3] == "budget_down" and calls[0][1]["budget_minor"] == 650_000
    assert context.error == "Puedes bajarlo hasta $7.000."


@pytest.mark.asyncio
async def test_failed_floor_read_says_so_and_keeps_the_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = editable_context()
    AdResultsState.open_edit.fn(context, "budget_down")

    def boom(*args: object) -> tuple[str, str]:
        raise RuntimeError("meta down")

    monkeypatch.setattr(results_state, "read_floor", boom)
    await AdResultsState.load_floor.fn(context)
    assert context.floor_label == FLOOR_FAILED and context._floor_input == ""


def test_prepare_maps_budget_down_to_backend_budget_with_plain_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.ads import results_service

    now = datetime.now(UTC)

    async def prepare(**kwargs: object) -> SimpleNamespace:
        assert kwargs["action"] == "budget"
        return SimpleNamespace(
            action="budget",
            summary="Cambiar el presupuesto total a 150.000 COP.",
            expires_at=now + timedelta(minutes=4),
            current_budget_minor=20_000_000,
            new_budget_minor=kwargs["budget_minor"],
            current_end_time=now + timedelta(days=3),
            new_end_time=now + timedelta(days=3),
            approval_token="sealed",
        )

    monkeypatch.setattr(results_service, "prepare_promotion_edit", prepare)
    prepared = results_provider.prepare_edit(
        TENANT, PROMOTION, "k", "budget_down", ZONE, budget_minor=15_000_000
    )
    assert prepared.review.title == "Bajar presupuesto"
    assert prepared.review.summary.startswith("Tu anuncio podrá gastar hasta $150.000")
    with pytest.raises(ResultsUnavailable):  # a "decrease" that Meta reports as an increase
        results_provider.prepare_edit(
            TENANT, PROMOTION, "k", "budget_down", ZONE, budget_minor=30_000_000
        )


def test_budget_down_dialog_has_floor_and_save_button() -> None:
    rendered = str(_edit_confirmation().render())
    assert "Guardar presupuesto" in rendered and "ad-edit-floor" in rendered


# --- 3. «Rechazado por Meta» --------------------------------------------------------


def test_rejection_without_reason_tells_what_to_check() -> None:
    generic = "Meta rechazó este anuncio. Consulta el motivo detallado en el Administrador."
    assert rejection_text("DISAPPROVED", generic) == NO_REJECTION_REASON
    assert rejection_text("DISAPPROVED", "") == NO_REJECTION_REASON
    reason = "Motivo informado por Meta: El texto promete resultados."
    assert rejection_text("DISAPPROVED", reason) == reason
    assert rejection_text("WITH_ISSUES", "") == ""


def test_rejected_ad_has_label_reason_and_route_back_to_the_piece() -> None:
    vm = results_provider.summary_vm(
        summary(
            status="DISAPPROVED",
            status_label="Rechazado por Meta",
            rejection_reason="",
            content_draft_id=PIECE,
        )
    )
    assert vm.rejected and vm.status_label == "Rechazado por Meta" and vm.tone == "error"
    assert vm.rejection_reason == NO_REJECTION_REASON and vm.fix_href == f"/drafts/{PIECE}"
    assert results_provider.summary_vm(summary()).fix_href == "/drafts"
    assert "Cambiar imagen o texto" in str(_detail().render())


# --- 4. «Activar avisos» ------------------------------------------------------------


@pytest.mark.asyncio
async def test_alerts_need_confirmation_and_show_the_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = editable_context()
    context.alert_accounts = [AlertAccountVM(ACCOUNT, "Mi cuenta")]
    calls = []

    def activate(tenant: UUID, account: UUID) -> str:
        assert current_acting_login() == LOGIN
        calls.append((tenant, account))
        return ALERTS_ON

    monkeypatch.setattr(results_state, "activate_alerts", activate)
    await AdResultsState.confirm_alerts.fn(context)
    assert not calls  # nothing without the owner's confirmation dialog
    AdResultsState.ask_alerts.fn(context, "another-account")
    assert context.alert_target.id == ""
    AdResultsState.ask_alerts.fn(context, ACCOUNT)
    await AdResultsState.confirm_alerts.fn(context)
    assert calls == [(TENANT, UUID(ACCOUNT))]
    assert context.alerts_notice == ALERTS_ON and context.alert_target.id == ""

    def refused(tenant: UUID, account: UUID) -> str:
        raise ResultsUnavailable("Autoriza los anuncios de nuevo para activar los avisos.")

    monkeypatch.setattr(results_state, "activate_alerts", refused)
    AdResultsState.ask_alerts.fn(context, ACCOUNT)
    await AdResultsState.confirm_alerts.fn(context)
    assert context.alerts_error.startswith("Autoriza") and context.alerts_notice == ""


def test_activate_alerts_reports_already_active(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.ads import status_webhook

    async def subscribe(**kwargs: object) -> bool:
        assert kwargs["confirmed"] is True
        return False

    monkeypatch.setattr(status_webhook, "subscribe_ad_account_webhooks", subscribe)
    assert results_provider.activate_alerts(TENANT, UUID(ACCOUNT)) == ALERTS_ALREADY_ON


def test_alerts_card_uses_the_backend_offer() -> None:
    from qualify_api.ads.status_webhook import SUBSCRIBE_OFFER

    rendered = str(ad_results_index().render())
    tail = SUBSCRIBE_OFFER.split("aquí ")[1]  # accents render escaped
    assert tail in rendered and "Activar avisos" in rendered
