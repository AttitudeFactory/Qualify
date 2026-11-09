"""Review boundaries, unknown writes and generic Meta contacts stay safe offline."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from qualify_api.ads.lead_forms import (
    LeadFormSummary,
    MetaLeadSummary,
)
from qualify_api.tenancy.acting import current_acting_login

from . import ad_forms_provider as provider
from . import ad_forms_state as state_module
from .ad_forms_page import _editor, ad_forms_index
from .ad_forms_state import AdFormsState
from .ad_forms_vm import (
    FORM_UNCERTAIN,
    AdFormDraftVM,
    AdFormVM,
    form_problem,
    form_step_problem,
)
from .auth_state import AuthState, business_state_classes
from .leads_page import _lead_card
from .leads_provider import meta_lead_vm
from .leads_state import with_contacted
from .leads_vm import pending_summary
from .ui.nav_vm import current_routes

TENANT = UUID("a0000000-0000-4000-8000-000000000001")
LOGIN = UUID("b0000000-0000-4000-8000-000000000001")
USER = UUID("c0000000-0000-4000-8000-000000000001")
FORM = UUID("d0000000-0000-4000-8000-000000000001")
CONNECTION = UUID("e0000000-0000-4000-8000-000000000001")
CONTEXT = str(TENANT), str(LOGIN), str(USER)


def draft() -> AdFormDraftVM:
    return AdFormDraftVM(
        connection_id=str(CONNECTION),
        name="Consulta de viajes",
        privacy_url="https://negocio.example/privacidad",
        thank_you_url="https://negocio.example/gracias",
        custom_questions="¿Qué destino te interesa? | Playa | Montaña",
    )


def summary() -> LeadFormSummary:
    return LeadFormSummary(
        id=FORM,
        connection_id=CONNECTION,
        name="Consulta de viajes",
        page_id="123456",
        status="draft",
        meta_form_id="",
        draft=provider.backend_draft(draft()),
        revision=3,
    )


def test_privacy_is_required_and_plain_contacts_do_not_establish_whatsapp_consent() -> None:
    assert form_problem(draft()) == ""
    assert "privacidad" in form_step_problem(replace(draft(), privacy_url=""), 3)
    for url in ("http://x.example", "https://user:secret@x.example", "javascript:alert(1)"):
        assert form_step_problem(replace(draft(), privacy_url=url), 3)
    assert "correo" in form_step_problem(replace(draft(), ask_email=False, ask_phone=False), 2)
    payload = provider.backend_draft(draft()).payload()
    assert payload["locale"] == "ES_LA"
    assert payload["privacy_policy"]["url"] == draft().privacy_url
    assert not any("whatsapp" in key.lower() for key in payload)
    assert payload["questions"][-1]["options"][0]["value"] == "Playa"


def test_saved_question_options_round_trip_and_review_revision_are_preserved() -> None:
    row = provider.form_vm(summary())
    assert row.revision == 3 and row.editable and not row.published
    assert provider.backend_draft(row.draft).questions == summary().draft.questions
    assert "meta_form_id" not in AdFormVM.__dataclass_fields__
    assert "page_id" not in AdFormVM.__dataclass_fields__


def test_custom_question_guidance_rejects_empty_duplicate_or_excessive_options() -> None:
    for value in ("Destino | Playa | Playa", "Destino | ", "x" * 121, "a\nb\nc\nd"):
        assert form_step_problem(replace(draft(), custom_questions=value), 2)


class Context:
    _session = AdFormsState._session
    _current = AdFormsState._current

    def __init__(self) -> None:
        self.auth = SimpleNamespace(
            session_tenant_id=str(TENANT), _auth_user_id=str(LOGIN), _session_user_id=str(USER)
        )
        self._context = CONTEXT
        self._operation = "initial"
        self.selected = provider.form_vm(summary())
        self.draft = self.selected.draft
        self.forms = [self.selected]
        self.busy = False
        self.loading = False
        self.editing = True
        self.step = 5
        self.publish_consent = False
        self.receive_consent = False
        self.discard_open = False
        self._pending_form_id = ""
        self.error = self.notice = ""

    @property
    def saved_current(self) -> bool:
        return bool(self.selected.id and self.selected.draft == self.draft)

    @property
    def can_publish(self) -> bool:
        return (
            self.saved_current
            and self.selected.editable
            and self.publish_consent
            and self.step == 5
            and not self.busy
            and not self.loading
        )

    @property
    def page_label(self) -> str:
        return "Página de prueba"

    @property
    def has_unfinished(self) -> bool:
        return (
            not self.editing
            and (not self.selected.id or self.selected.editable)
            and self.draft != AdFormDraftVM()
        )

    async def __aenter__(self) -> Context:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def get_state(self, state_class: type) -> object:
        assert state_class is AuthState
        return self.auth


@pytest.mark.asyncio
async def test_publish_requires_exact_saved_review_consent_and_locks_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Context()
    calls = []

    def publish(*args: object) -> AdFormVM:
        assert current_acting_login() == LOGIN
        calls.append(args)
        raise RuntimeError("raw upstream secret")

    monkeypatch.setattr(state_module, "publish_form", publish)
    await AdFormsState.publish.fn(context)
    assert not calls
    context.publish_consent = True
    context.draft = replace(context.draft, name="Otro formulario")
    await AdFormsState.publish.fn(context)
    assert not calls
    context.draft = context.selected.draft
    await AdFormsState.publish.fn(context)
    assert calls == [(TENANT, FORM, 3)]
    assert context.error == FORM_UNCERTAIN
    assert not context.selected.editable and not context.publish_consent
    context.publish_consent = True
    await AdFormsState.publish.fn(context)
    assert len(calls) == 1
    assert "secret" not in context.error


@pytest.mark.asyncio
async def test_logout_racing_publish_cannot_restore_previous_business_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Context()
    context.publish_consent = True

    def publish(*args: object) -> AdFormVM:
        context.auth._session_user_id = ""
        context.forms = []
        context.selected = AdFormVM()
        return replace(provider.form_vm(summary()), status="published", published=True)

    monkeypatch.setattr(state_module, "publish_form", publish)
    await AdFormsState.publish.fn(context)
    assert context.forms == [] and context.selected.id == ""


@pytest.mark.asyncio
async def test_receiving_answers_needs_its_own_consent_and_published_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Context()
    calls = []

    def receive(*args: object) -> None:
        assert current_acting_login() == LOGIN
        calls.append(args)

    monkeypatch.setattr(state_module, "receive_form", receive)
    context.publish_consent = True
    await AdFormsState.receive_answers.fn(context)
    assert not calls
    context.receive_consent = True
    await AdFormsState.receive_answers.fn(context)
    assert not calls
    context.selected = replace(context.selected, status="published", published=True, editable=False)
    await AdFormsState.receive_answers.fn(context)
    assert calls == [(TENANT, FORM)]
    assert not context.receive_consent
    await AdFormsState.receive_answers.fn(context)
    assert len(calls) == 1


def test_leaving_editor_keeps_draft_and_switching_forms_needs_explicit_discard() -> None:
    context = Context()
    original = replace(context.draft, name="Cambios sin guardar")
    context.draft = original
    AdFormsState.close_editor.fn(context)
    assert context.draft == original and context.has_unfinished
    AdFormsState.resume_editor.fn(context)
    assert context.editing and context.draft == original
    AdFormsState.close_editor.fn(context)
    other = replace(context.selected, id=str(USER), name="Otro formulario")
    context.forms.append(other)
    assert AdFormsState.open_form.fn(context, str(USER)) is None
    assert context.discard_open and context.draft == original
    AdFormsState.keep_draft.fn(context)
    assert not context.discard_open and context.draft == original
    AdFormsState.open_form.fn(context, str(USER))
    AdFormsState.discard_draft.fn(context)
    assert context.editing and context.selected.id == str(USER)


def test_meta_contact_never_gets_a_whatsapp_link_even_if_projection_claims_optin() -> None:
    row = MetaLeadSummary(
        id=FORM,
        full_name="Ana",
        phone="+573001112233",
        email="ana@example.test",
        form_name="Consulta de viajes",
        meta_form_id="111",
        meta_ad_id="222",
        promotion_id=None,
        created_at=datetime(2026, 11, 9, tzinfo=UTC),
        contacted_at=None,
        answers={"Destino": "Playa"},
        whatsapp_opt_in=True,
    )
    vm = meta_lead_vm(row, "America/Bogota")
    assert vm.id == "meta:" + str(FORM) and vm.kind == "meta"
    assert vm.wa_href == "" and vm.email == "ana@example.test"
    assert vm.origin_label == "Formulario de Meta"
    assert with_contacted([vm], vm.id, contacted=True)[0].status_label == "Atendida"
    rendered = str(_lead_card(vm).render())
    assert "https://wa.me/" not in rendered
    assert pending_summary(1, includes_meta=True) == "Te falta 1 consulta por atender"
    assert "atendidas" in pending_summary(0, includes_meta=True)


def test_actual_components_render_with_review_no_spend_and_matching_navigation() -> None:
    rendered = str(ad_forms_index().render())
    assert "RadixThemesTable" not in rendered
    assert "44px" in rendered
    assert "privacidad" in rendered
    assert "no crea ni activa un anuncio" in rendered
    assert "autorizo crear este formulario" in rendered
    assert "Crear formulario en Meta" in str(_editor().render())
    assert current_routes(("/promotions", "/responder"), "/promotions/forms") == ["/promotions"]
    assert AdFormsState in business_state_classes()
