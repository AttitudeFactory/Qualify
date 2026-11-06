"""The promotion draft cannot silently become a paid advertising operation."""

from __future__ import annotations

from dataclasses import asdict, replace
from types import SimpleNamespace
from uuid import UUID

import pytest
from qualify_api.tenancy.acting import current_acting_login

from . import promotion_provider as provider
from . import promotion_state as state_module
from .auth_state import AuthState, business_state_classes
from .promotion_page import _review, promotion_index
from .promotion_state import PromotionState
from .promotion_vm import (
    CONFIRM_FAILED,
    PREVIEW_FAILED,
    PromotionDraftVM,
    PromotionReviewVM,
    PromotionSourceVM,
    cop_label,
    cop_minor,
    first_problem,
    local_datetime,
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
async def test_explicit_confirmation_passes_authenticated_actor_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ActionContext()
    context.confirm_charge = True
    calls = []

    def confirm(*args: object) -> str:
        assert current_acting_login() == LOGIN
        calls.append(args)
        return "Anuncio confirmado."

    monkeypatch.setattr(state_module, "confirm_review", confirm)
    await context._remote(confirm=True)
    assert calls == [(TENANT, USER, review(), True)]
    assert context.success == "Anuncio confirmado."
    assert not context.confirm_charge and not context.busy
    await context._remote(confirm=True)
    assert len(calls) == 1


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


def test_history_back_from_review_revokes_confirmation_without_losing_form() -> None:
    context = ActionContext()
    context.router = SimpleNamespace(url=SimpleNamespace(query_parameters={"paso": "4"}))
    context.confirm_charge = True
    before = context.form
    PromotionState.read_step.fn(context)
    assert context.form == before
    assert not context.reviewed and not context.confirm_charge
