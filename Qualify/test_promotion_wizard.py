"""The promotion draft cannot silently become a paid advertising operation."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from qualify_api.ads.wizard import WizardUnavailable
from qualify_api.tenancy.acting import current_acting_login

from . import promotion_provider as provider
from . import promotion_state as state_module
from .ad_enhancements_vm import BrandEnhancementsVM
from .auth_state import AuthState, business_state_classes
from .promotion_page import _review, promotion_index
from .promotion_state import PromotionState
from .promotion_vm import (
    CONFIRM_FAILED,
    PREVIEW_FAILED,
    PromotionCheckVM,
    PromotionDraftVM,
    PromotionResultVM,
    PromotionReviewVM,
    PromotionSourceVM,
    cop_label,
    cop_minor,
    first_problem,
    local_datetime,
    promotion_checks,
    promotion_result,
    readable_date,
    step_problem,
)
from .ui.nav_vm import current_routes

TENANT = UUID("a0000000-0000-4000-8000-000000000001")
LOGIN = UUID("b0000000-0000-4000-8000-000000000001")
USER = UUID("c0000000-0000-4000-8000-000000000001")
PIECE = UUID("d0000000-0000-4000-8000-000000000001")
SOURCE = UUID("e0000000-0000-4000-8000-000000000001")
ZONE = "America/Bogota"


def valid_form() -> PromotionDraftVM:
    return PromotionDraftVM(
        source_id=str(SOURCE),
        link_url="https://negocio.example/oferta",
        city_name="Cúcuta",
        location_key="123",
        location_country="CO",
        budget="25000",
        start_local="2027-01-10T09:00",
        end_local="2027-01-17T09:00",
    )


def review() -> PromotionReviewVM:
    return PromotionReviewVM(
        promotion_id=str(PIECE),
        review_id=str(SOURCE),
        preview_url="https://www.facebook.com/ads/api/preview_iframe.php?d=test",
        charge_notice="Meta cobrará hasta $25.000 COP a tu método de pago.",
    )


@pytest.mark.parametrize("value", ["25.000", "25,000", "0", "-1", "25.5", "٢٥٠٠٠", "1e5"])
def test_budget_rejects_ambiguous_or_invalid_amounts(value: str) -> None:
    with pytest.raises(ValueError):
        cop_minor(value)


def test_money_is_exact_and_total_is_explicit() -> None:
    assert cop_minor("25000") == 2_500_000
    assert cop_label("25000") == "$25.000 COP"
    assert first_problem(valid_form(), ZONE) == ""
    assert "https" in step_problem(replace(valid_form(), link_url="http://example.com"), 2)
    assert "https" in step_problem(replace(valid_form(), link_url="https://user:secret@x.co"), 2)
    assert readable_date("2027-01-10T09:00") == "10/01/2027 · 09:00"
    assert readable_date("") == "Por definir"


@pytest.mark.parametrize("status", ["unknown", "success", None, {}, []])
def test_unrecognized_check_status_never_claims_meta_verification(status: object) -> None:
    checks = promotion_checks(
        ({"key": "currency", "status": status, "label": "Raw amount", "detail": "raw 100x"},)
    )
    assert len(checks) == 1 and checks[0].status == "unavailable"
    assert "raw" not in repr(checks).lower()


def test_check_projection_has_closed_labels_and_no_payment_guarantee() -> None:
    checks = promotion_checks(
        (
            {
                "key": "payment",
                "label": "Payment guaranteed",
                "status": "verified",
                "detail": "Payment guaranteed",
            },
            {"key": "new-secret-field", "status": "verified", "detail": "raw credentials"},
        )
    )
    assert checks[0].label == "Método de pago"
    assert "registrado" in checks[0].detail and "no garantiza" in checks[0].detail
    assert checks[1].status == "unavailable"
    assert "guaranteed" not in repr(checks) and "credentials" not in repr(checks)
    assert promotion_checks(()) == []
    assert isinstance(PromotionCheckVM().label, str)


@pytest.mark.parametrize("status", ["active", "unknown", "pending", "success", None, []])
def test_confirmation_provider_preserves_closed_status_and_discards_raw_message(
    monkeypatch: pytest.MonkeyPatch, status: object
) -> None:
    async def confirm(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(promotion_id=PIECE, status=status, message="RAW_INTERNAL_SUCCESS")

    monkeypatch.setattr(provider, "confirm_promotion", confirm)
    result = provider.confirm_review(TENANT, USER, review(), True)
    assert result.status == (status if status in ("active", "unknown", "pending") else "unknown")
    assert result.promotion_id == str(PIECE)
    assert "RAW_INTERNAL" not in result.message
    assert ("Activación solicitada" in result.message) is (status == "active")


@pytest.mark.parametrize(
    ("value", "zone"),
    [
        ("2027-01-10T09:00", ""),
        ("2027-01-10T09:00Z", ZONE),
        ("2026-03-08T02:30", "America/New_York"),
        ("2026-11-01T01:30", "America/New_York"),
    ],
)
def test_unknown_zone_dst_gap_or_ambiguous_hour_never_assumes_utc(value: str, zone: str) -> None:
    with pytest.raises(ValueError):
        local_datetime(value, zone)


@pytest.mark.parametrize(
    "html",
    [
        "<script>alert(1)</script>",
        '<iframe src="javascript:alert(1)"></iframe>',
        '<iframe src="https://facebook.com.evil.example/ads/api/preview_iframe.php"></iframe>',
        '<iframe src="https://www.facebook.com/elsewhere"></iframe>',
        '<iframe src="https://www.facebook.com/ads/api/preview_iframe.php?access_token=secret"></iframe>',
        '<iframe src="https://www.facebook.com:8443/ads/api/preview_iframe.php"></iframe>',
        '<iframe src="https://user:secret@www.facebook.com/ads/api/preview_iframe.php"></iframe>',
    ],
)
def test_provider_preview_html_cannot_inject_dom_or_credentials(html: str) -> None:
    assert provider.safe_preview_url(html) == ""


def test_preview_url_projection_discards_all_raw_html() -> None:
    html = (
        '<script>never execute</script><iframe onclick="never execute" '
        'src="https://www.facebook.com/ads/api/preview_iframe.php?d=test&amp;format=mobile"></iframe>'
    )
    result = provider.safe_preview_url(html)
    assert result.endswith("?d=test&format=mobile")
    assert "script" not in result and "onclick" not in result


def test_actual_preview_provider_projects_backend_checks_without_raw_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    form = replace(valid_form(), enhancements=BrandEnhancementsVM(str(TENANT), loaded=True))

    async def prepare(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            promotion_id=PIECE,
            review_id=SOURCE,
            preview_html=(
                '<iframe src="https://www.facebook.com/ads/api/preview_iframe.php?d=test"></iframe>'
            ),
            charge_notice="Meta cobrará hasta el importe que autorices.",
            expires_at=datetime(2027, 1, 1, tzinfo=UTC),
            checks=(
                {
                    "key": "validation",
                    "label": "Raw internal configuration",
                    "status": "verified",
                    "detail": "Meta comprobó esta elección.",
                },
            ),
        )

    monkeypatch.setattr(provider, "prepare_promotion_preview", prepare)
    result = provider.prepare_preview(TENANT, PIECE, USER, form, ZONE, "same-approved-choice")
    assert result.preview_url == review().preview_url
    assert result.checks[0].status == "verified"
    assert result.checks[0].label == "Configuración del anuncio"
    assert "Raw internal" not in repr(result)


class ActionContext:
    _session = PromotionState._session
    _remote = PromotionState._remote
    _invalidate_review = PromotionState._invalidate_review
    _step_completeness = PromotionState._step_completeness
    _invalidate_audience = PromotionState._invalidate_audience
    _invalidate_destinations = PromotionState._invalidate_destinations
    _invalidate_enhancements = PromotionState._invalidate_enhancements

    def __init__(self) -> None:
        self.auth = SimpleNamespace(
            session_tenant_id=str(TENANT), _auth_user_id=str(LOGIN), _session_user_id=str(USER)
        )
        self.sources = [
            PromotionSourceVM(str(SOURCE), "@negocio", "Una oferta", unavailable_reason="")
        ]
        self.form = valid_form()
        self.review = review()
        self.result = PromotionResultVM()
        self.checks = []
        self.timezone_name = ZONE
        self._tenant_timezone = ZONE
        self._loaded_context = (str(TENANT), str(LOGIN), str(USER))
        self._piece_id = str(PIECE)
        self._request_key = "one-approved-draft"
        self._return_params = {}
        self._operation = ""
        self.reviewed = True
        self.confirm_charge = False
        self.busy = False
        self.loading = False
        self.enhancements_working = False
        self.error = ""
        self.success = ""
        self.step = 4
        self.direction = "next"
        self._audience_revision = "initial-audience"
        self._audience_search = ""
        self._audience_version = 0
        self.audience_notice = ""
        self.audience_error = ""
        self.audience_working = ""
        self.reach_loading = False

    @property
    def has_remote_review(self) -> bool:
        return bool(self.review.review_id and self.review.preview_url)

    @property
    def execution_reason(self) -> str:
        return self.sources[0].unavailable_reason

    @property
    def preparation_blocked(self) -> bool:
        return self.sources[0].health.blocks_preparation

    async def __aenter__(self) -> ActionContext:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def get_state(self, state_class: type) -> object:
        assert state_class is AuthState
        return self.auth


@pytest.mark.asyncio
async def test_confirmation_without_checkbox_never_calls_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()
    calls = []
    monkeypatch.setattr(state_module, "confirm_review", lambda *args: calls.append(args))
    await context._remote(confirm=True)
    assert not calls
    assert "acepta" in context.error


@pytest.mark.asyncio
async def test_preflight_failure_preserves_form_and_step_and_shows_completed_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()
    before = context.form
    context.confirm_charge = True

    def fail(*args: object) -> None:
        raise WizardUnavailable(
            "Falta comprobar el importe antes de continuar.",
            diagnostics=(
                {"key": "permissions", "status": "verified", "detail": "Permiso comprobado."},
                {"key": "currency", "status": "unavailable", "detail": "Vuelve a consultar."},
            ),
        )

    monkeypatch.setattr(state_module, "prepare_preview", fail)
    await context._remote(confirm=False)
    assert context.form == before and context.step == 4 and context.reviewed
    assert [check.status for check in context.checks] == ["verified", "unavailable"]
    assert "importe" in context.error
    assert not context.confirm_charge and not context.busy


@pytest.mark.asyncio
async def test_incomplete_checks_reject_paid_confirmation_even_with_checked_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()
    context.checks = [PromotionCheckVM()]
    context.confirm_charge = True
    calls = []
    monkeypatch.setattr(state_module, "confirm_review", lambda *args: calls.append(args))
    await context._remote(confirm=True)
    assert not calls and not context.confirm_charge
    assert "comprobaciones pendientes" in context.error
    PromotionState.accept_charge.fn(context, True)
    assert not context.confirm_charge


@pytest.mark.asyncio
async def test_verified_preview_checks_still_require_separate_explicit_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()
    prepared = replace(
        review(),
        checks=[PromotionCheckVM("validation", "Configuración del anuncio", "verified", "Lista.")],
    )
    calls = []
    monkeypatch.setattr(state_module, "prepare_preview", lambda *args: prepared)
    monkeypatch.setattr(
        state_module,
        "confirm_review",
        lambda *args: (
            calls.append(args)
            or promotion_result(SimpleNamespace(status="active", promotion_id=PIECE), str(PIECE))
        ),
    )
    await context._remote(confirm=False)
    assert context.review == prepared and context.checks == prepared.checks
    assert not context.confirm_charge
    await context._remote(confirm=True)
    assert not calls
    PromotionState.accept_charge.fn(context, True)
    await context._remote(confirm=True)
    assert len(calls) == 1 and "Activación solicitada" in context.success
    assert not context.confirm_charge


@pytest.mark.parametrize("change", ["budget", "source", "brand"])
def test_changed_choice_discards_checks_preview_and_paid_consent(change: str) -> None:
    context = ActionContext()
    context.checks = [PromotionCheckVM("media", "Publicación", "verified", "Lista.")]
    context.confirm_charge = True
    if change == "budget":
        PromotionState.edit.fn(context, "budget", "30000")
    else:
        source = replace(context.sources[0], id=str(USER), brand_id=str(TENANT))
        if change == "brand":
            source = replace(source, id=context.form.source_id, brand_id=str(PIECE))
        context.sources = [source]
        PromotionState.choose_source.fn(context, source.id)
    assert not context.checks and not context.review.review_id and not context.confirm_charge


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["budget", "source", "brand", "business"])
@pytest.mark.parametrize("failed", [False, True])
async def test_late_preflight_cannot_repaint_checks_for_changed_choice(
    monkeypatch: pytest.MonkeyPatch, change: str, failed: bool
) -> None:
    context = ActionContext()

    def delayed(*args: object) -> PromotionReviewVM:
        if change == "budget":
            context.form = replace(context.form, budget="30000")
        elif change == "source":
            context.form = replace(context.form, source_id=str(USER))
        elif change == "brand":
            context.sources = [replace(context.sources[0], brand_id=str(PIECE))]
        else:
            context.auth.session_tenant_id = str(PIECE)
        if failed:
            raise WizardUnavailable(
                "Resultado anterior.",
                diagnostics=({"key": "media", "status": "verified", "detail": "Anterior."},),
            )
        return replace(review(), checks=[PromotionCheckVM("media", "Publicación", "verified")])

    monkeypatch.setattr(state_module, "prepare_preview", delayed)
    await context._remote(confirm=False)
    assert not context.checks
    assert "anterior" not in context.error.lower()


@pytest.mark.asyncio
async def test_explicit_confirmation_passes_authenticated_actor_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()
    context.confirm_charge = True
    calls = []

    def confirm(*args: object) -> PromotionResultVM:
        assert current_acting_login() == LOGIN
        calls.append(args)
        return promotion_result(SimpleNamespace(status="active", promotion_id=PIECE), str(PIECE))

    monkeypatch.setattr(state_module, "confirm_review", confirm)
    await context._remote(confirm=True)
    assert calls == [(TENANT, USER, review(), True)]
    assert "Activación solicitada a Meta" in context.success
    assert not context.confirm_charge and not context.busy
    await context._remote(confirm=True)
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["unknown", "pending"])
async def test_uncertain_activation_stays_readonly_after_budget_edit(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    context = ActionContext()
    context.confirm_charge = True
    calls = []

    def confirm(*args: object) -> PromotionResultVM:
        calls.append("confirm")
        return promotion_result(SimpleNamespace(status=status, promotion_id=PIECE), str(PIECE))

    monkeypatch.setattr(state_module, "confirm_review", confirm)
    monkeypatch.setattr(state_module, "prepare_preview", lambda *args: calls.append("create"))
    await context._remote(confirm=True)
    assert context.result.status == status and not context.success
    assert PromotionState.paid_operation_locked.fget(context)
    assert PromotionState.promotion_status_href.fget(context) == f"/promotions/{PIECE}"
    original_request = context._request_key
    PromotionState.edit.fn(context, "budget", "30000")
    assert context.form.budget == "30000"
    assert context._request_key == original_request
    assert context.result.status == status and not context.success
    PromotionState.accept_charge.fn(context, True)
    context.reviewed = True
    await context._remote(confirm=False)
    await context._remote(confirm=True)
    assert calls == ["confirm"] and not context.confirm_charge


@pytest.mark.asyncio
async def test_configuration_gate_still_allows_local_review_without_remote_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()
    context.sources = [
        replace(context.sources[0], unavailable_reason="Falta comprobar el acceso con Meta.")
    ]
    context.reviewed = False
    context.review = PromotionReviewVM()
    calls = []
    monkeypatch.setattr(state_module, "prepare_preview", lambda *args: calls.append(args))
    PromotionState.next_step.fn(context)
    assert context.reviewed
    await context._remote(confirm=False)
    assert not calls
    assert "Falta comprobar" in context.error


@pytest.mark.asyncio
async def test_late_result_cannot_repaint_or_clear_new_business_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()

    def prepare(*args: object) -> PromotionReviewVM:
        assert current_acting_login() == LOGIN
        context.auth.session_tenant_id = str(SOURCE)
        context._operation = "operation-of-new-business"
        context.review = PromotionReviewVM()
        context.busy = True
        return review()

    monkeypatch.setattr(state_module, "prepare_preview", prepare)
    await context._remote(confirm=False)
    assert not context.review.review_id
    assert context.busy


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
async def test_command_errors_never_echo_raw_details(
    monkeypatch: pytest.MonkeyPatch, confirm: bool
) -> None:
    context = ActionContext()
    context.confirm_charge = True

    def fail(*args: object) -> None:
        raise ValueError("token=never-expose-me")

    monkeypatch.setattr(state_module, "confirm_review" if confirm else "prepare_preview", fail)
    await context._remote(confirm=confirm)
    assert context.error == (CONFIRM_FAILED if confirm else PREVIEW_FAILED)
    assert not context.busy
    assert "never-expose" not in context.error


def test_any_edit_invalidates_remote_review_and_spend_consent() -> None:
    context = ActionContext()
    context.confirm_charge = True
    PromotionState.edit.fn(context, "budget", "30000")
    assert context.form.budget == "30000"
    assert not context.review.review_id
    assert not context.confirm_charge and not context.reviewed
    assert context._request_key != "one-approved-draft"


def test_actual_component_tree_constructs_and_uses_sandboxed_preview() -> None:
    tree = promotion_index()
    rendered = repr(tree.render())
    assert "sandbox" in rendered
    # The app shell has a trusted, static SVG filter; only the external preview matters here.
    assert "dangerouslySetInnerHTML" not in repr(_review().render())
    assert "Crear en pausa" in rendered
    assert "confirm_charge" in rendered


def test_preview_and_source_display_models_have_no_credential_field() -> None:
    assert not {"token", "ciphertext", "access_token", "preview_html"}.intersection(
        asdict(review())
    )
    assert not {"token", "ciphertext", "access_token"}.intersection(
        asdict(ActionContext().sources[0])
    )


def test_business_reset_and_origin_navigation_cover_new_route() -> None:
    assert PromotionState in business_state_classes()
    routes = ("/", "/drafts", "/planner")
    assert current_routes(routes, f"/drafts/{PIECE}/promote") == ["/drafts"]
    assert current_routes(routes, f"/drafts/{PIECE}/promote", {"desde": "semana"}) == ["/planner"]


@pytest.mark.asyncio
async def test_multiple_sources_are_not_silently_selected_and_missing_ads_keeps_business_zone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()
    context._loaded_context = ("", "", "")
    context.result = PromotionResultVM(str(PIECE), "unknown", "Operación anterior.")
    context.draft_id = str(PIECE)
    context.router = SimpleNamespace(url=SimpleNamespace(query_parameters={"paso": "4"}))
    context.read_step = lambda: PromotionState.read_step.fn(context)
    context.choose_source = lambda value: PromotionState.choose_source.fn(context, value)
    sources = [
        PromotionSourceVM(str(SOURCE), "@primera", "Primera publicación"),
        PromotionSourceVM(str(USER), "@segunda", "Segunda publicación"),
    ]

    def load(*args: object) -> tuple[list[PromotionSourceVM], str]:
        assert current_acting_login() == LOGIN
        return sources, ZONE

    monkeypatch.setattr(state_module, "load_sources", load)
    events = [event async for event in PromotionState.load.fn(context)]
    assert events
    assert len(context.sources) == 2 and not context.form.source_id
    assert context.timezone_name == ZONE
    assert context.form.start_local and context.form.end_local
    assert context.step == 1  # A deep link cannot skip the explicit publication choice.
    assert not context.loading
    assert not context.result.status  # A fresh scoped load resets the former operation's latch.


def test_history_back_from_review_revokes_confirmation_without_losing_form() -> None:
    context = ActionContext()
    context.router = SimpleNamespace(url=SimpleNamespace(query_parameters={"paso": "4"}))
    context.confirm_charge = True
    before = context.form
    PromotionState.read_step.fn(context)
    assert context.form == before
    assert not context.reviewed and not context.confirm_charge
