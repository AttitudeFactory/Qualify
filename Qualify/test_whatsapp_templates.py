"""Network-free tests for `/whatsapp` → Plantillas (WA-18, QUA-217).

They pin:
1. The VM boundary: frozen, no credential-bearing field, no raw datetime.
2. Meta status/quality/rejection → (label, tone) with design-system tones only.
3. The guided form's validation (name alphabet, variables, examples, start/end rule,
   buttons) and the named → POSITIONAL conversion Meta reviews.
4. Reading components back for a send (positional and named) and the wizard's blocks.
5. The provider over `MemoryTemplateRepository` + a fake client: Meta first, then the
   mirror; a duplicate refused before any Graph call; an auth error degrades.
"""

from __future__ import annotations

import dataclasses
import typing
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
import reflex as rx
from qualify_api.whatsapp.client import TemplateCreateResult, TemplateInfo, WhatsAppApiError
from qualify_api.whatsapp.templates import (
    MemoryTemplateRepository,
    TemplateAlreadyExists,
    TemplateService,
)

from . import whatsapp_tab_templates
from .whatsapp_templates_provider import (
    create_template,
    delete_template,
    list_templates,
    sync_templates,
)
from .whatsapp_templates_vm import (
    BUTTONS_QUICK,
    BUTTONS_URL,
    CATEGORY_AUTHENTICATION,
    EMPTY_FORM,
    ExampleFieldVM,
    SendVariable,
    TemplateForm,
    TemplateVM,
    body_variables,
    build_components,
    build_send_components,
    build_template_vm,
    example_fields,
    preview_body,
    quality_display,
    rejection_display,
    send_variables,
    status_display,
    suggest_name,
    validate_template_form,
    wizard_block,
)

_FORBIDDEN = ("token", "credential", "cipher", "secret", "key_id", "password", "plaintext")
_TONES = {"ok", "warn", "error", "info", "neutral"}
TENANT = UUID("00000000-0000-0000-0000-0000000000a1")
CONNECTION = UUID("00000000-0000-0000-0000-0000000000c1")


def _form(**overrides: Any) -> TemplateForm:
    base = dataclasses.replace(
        EMPTY_FORM,
        name="promo_octubre",
        body="Hola {{nombre}}, tu pedido {{pedido}} ya salió.",
        examples={"nombre": "Ana", "pedido": "A-12"},
    )
    return dataclasses.replace(base, **overrides)


# --- 1. VM boundary -------------------------------------------------------------------


def test_whatsapp_templates_vm_has_no_credential_fields() -> None:
    for vm in (TemplateVM, TemplateForm, ExampleFieldVM, SendVariable):
        assert dataclasses.is_dataclass(vm)
        assert vm.__dataclass_params__.frozen  # type: ignore[attr-defined]
        for f in dataclasses.fields(vm):
            assert not any(bad in f.name.lower() for bad in _FORBIDDEN), (vm, f.name)


def test_template_vm_carries_no_datetime() -> None:
    hints = typing.get_type_hints(TemplateVM)
    assert all(hint is not datetime for hint in hints.values())


# --- 2. enums -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "tone"),
    [
        ("APPROVED", "ok"),
        ("PENDING", "info"),
        ("REJECTED", "error"),
        ("DISABLED", "error"),
        ("PAUSED", "warn"),
        ("DELETED", "neutral"),
        ("SOMETHING_NEW", "neutral"),
    ],
)
def test_status_tones(status: str, tone: str) -> None:
    label, got = status_display(status)
    assert got == tone and got in _TONES
    if status == "SOMETHING_NEW":
        assert label == "SOMETHING_NEW"  # an unknown Meta enum surfaces as itself


def test_quality_and_rejection() -> None:
    assert quality_display("GREEN")[1] == "ok"
    assert quality_display(None)[1] == "neutral"
    assert rejection_display(None) == ""
    assert rejection_display("INVALID_FORMAT") == "Formato inválido"
    assert rejection_display("PROMOTIONAL: Contiene oferta").endswith("Contiene oferta")


def test_vm_from_components() -> None:
    vm = build_template_vm(
        template_id="t1",
        name="promo",
        language="es",
        category="marketing",
        status="REJECTED",
        quality="YELLOW",
        rejected_reason="INVALID_FORMAT",
        components=[
            {"type": "HEADER", "format": "TEXT", "text": "Hola"},
            {"type": "BODY", "text": "Cuerpo {{1}} final"},
            {"type": "FOOTER", "text": "Pie"},
            {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Sí"}]},
        ],
        updated_at=datetime(2026, 10, 14, 10, 0, tzinfo=UTC),
    )
    assert (vm.header_text, vm.body_text, vm.footer_text) == ("Hola", "Cuerpo {{1}} final", "Pie")
    assert vm.buttons_label == "Sí"
    assert vm.status_tone == "error" and vm.rejected_reason == "Formato inválido"
    assert vm.updated_at == "14 Oct 2026, 10:00"
    assert not vm.sendable and vm.can_delete


# --- 3. the form ----------------------------------------------------------------------


def test_a_valid_form_passes() -> None:
    assert validate_template_form(_form()) == ""


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"name": ""}, "nombre"),
        ({"name": "Promo Octubre"}, "minúsculas"),
        ({"language": "xx"}, "idioma"),
        ({"body": ""}, "mensaje"),
        ({"body": "{{nombre}} hola"}, "empiece o termine"),
        ({"body": "Hola {{nombre}}"}, "empiece o termine"),
        ({"body": "Hola {{ Nombre }} ya"}, "dobles llaves"),
        ({"examples": {"nombre": "Ana"}}, "{{pedido}}"),
        ({"header": "Hola {{nombre}}"}, "encabezado"),
        ({"footer": "x" * 61}, "pie"),
        ({"button_kind": BUTTONS_QUICK}, "respuesta rápida"),
        ({"button_kind": BUTTONS_QUICK, "quick_replies": ("Sí", "Sí", "")}, "repetirse"),
        ({"button_kind": BUTTONS_URL, "url_text": "Ver", "url": "http://x.co"}, "https://"),
    ],
)
def test_form_validation(overrides: dict[str, Any], fragment: str) -> None:
    problem = validate_template_form(_form(**overrides))
    assert fragment.lower() in problem.lower()


def test_authentication_is_explained_not_built() -> None:
    problem = validate_template_form(_form(category=CATEGORY_AUTHENTICATION))
    assert "cuenta de WhatsApp Business en Meta" in problem


def test_named_variables_become_positional_with_examples_in_order() -> None:
    form = _form(
        body="Hola {{nombre}}, tu pedido {{pedido}} para {{nombre}} ya salió.",
        header="Novedades",
        footer="Responde BAJA",
        button_kind=BUTTONS_URL,
        url_text="Ver",
        url="https://qualify.la/menu",
    )
    assert validate_template_form(form) == ""
    components = build_components(form)
    assert components[0] == {"type": "HEADER", "format": "TEXT", "text": "Novedades"}
    assert components[1] == {
        "type": "BODY",
        "text": "Hola {{1}}, tu pedido {{2}} para {{1}} ya salió.",
        "example": {"body_text": [["Ana", "A-12"]]},
    }
    assert components[2] == {"type": "FOOTER", "text": "Responde BAJA"}
    assert components[3]["buttons"] == [
        {"type": "URL", "text": "Ver", "url": "https://qualify.la/menu"}
    ]


def test_body_without_variables_has_no_example() -> None:
    components = build_components(_form(body="Hola, hay promo hoy.", examples={}))
    assert components == [{"type": "BODY", "text": "Hola, hay promo hoy."}]


def test_preview_and_examples() -> None:
    form = _form(examples={"nombre": "Ana"})
    assert body_variables(form.body) == ["nombre", "pedido"]
    assert preview_body(form.body, form.examples) == "Hola Ana, tu pedido [pedido] ya salió."
    assert [f.placeholder for f in example_fields(form)] == ["{{nombre}}", "{{pedido}}"]
    assert suggest_name("Promo Octubre") == "promo_octubre"
    assert suggest_name("_Promo ") == "promo_"  # the space just typed survives
    assert suggest_name("Pastelería Ñ") == "pasteleria_n"


# --- 4. reading components for a send -------------------------------------------------


def test_send_variables_positional_and_components() -> None:
    components = [
        {
            "type": "HEADER",
            "format": "TEXT",
            "text": "Hola {{1}}",
            "example": {"header_text": ["Ana"]},
        },
        {"type": "BODY", "text": "Tu {{2}} y {{1}}", "example": {"body_text": [["x", "y"]]}},
    ]
    variables = send_variables(components)
    assert [(v.component, v.key, v.example) for v in variables] == [
        ("header", "1", "Ana"),
        ("body", "1", "x"),
        ("body", "2", "y"),
    ]
    sent = build_send_components(variables, {"header:1": "Ana", "body:1": "A", "body:2": "B"})
    assert sent == [
        {"type": "header", "parameters": [{"type": "text", "text": "Ana"}]},
        {
            "type": "body",
            "parameters": [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}],
        },
    ]


def test_send_variables_named() -> None:
    components = [
        {
            "type": "BODY",
            "text": "Hola {{first_name}}",
            "example": {"body_text_named_params": [{"param_name": "first_name", "example": "Ana"}]},
        }
    ]
    variables = send_variables(components)
    assert variables == [SendVariable("body", "first_name", True, "Ana")]
    assert build_send_components(variables, {"body:first_name": "Ana"}) == [
        {
            "type": "body",
            "parameters": [{"type": "text", "text": "Ana", "parameter_name": "first_name"}],
        }
    ]


def test_wizard_blocks() -> None:
    body = {"type": "BODY", "text": "Hola"}
    assert wizard_block("marketing", [body]) == ""
    assert "autenticación" in wizard_block("authentication", [body])
    assert "imagen" in wizard_block("marketing", [{"type": "HEADER", "format": "IMAGE"}, body])
    dynamic = {
        "type": "BUTTONS",
        "buttons": [{"type": "URL", "text": "Ver", "url": "https://x/{{1}}"}],
    }
    assert "variable" in wizard_block("marketing", [body, dynamic])


# --- 5. provider ----------------------------------------------------------------------


class FakeClient:
    def __init__(self, *, fail: WhatsAppApiError | None = None) -> None:
        self.created: list[tuple[str, str, str, str, list[dict[str, Any]]]] = []
        self.deleted: list[tuple[str, str]] = []
        self.listed: list[TemplateInfo] = []
        self.fail = fail

    async def create_template(
        self, waba_id: str, name: str, language: str, category: str, components: Any
    ) -> TemplateCreateResult:
        if self.fail:
            raise self.fail
        self.created.append((waba_id, name, language, category, components))
        return TemplateCreateResult(id="meta-1", status="PENDING", category="marketing")

    async def list_templates(self, waba_id: str) -> list[TemplateInfo]:
        if self.fail:
            raise self.fail
        return self.listed

    async def delete_template(self, waba_id: str, name: str) -> None:
        self.deleted.append((waba_id, name))


def _service(client: FakeClient) -> tuple[TemplateService, MemoryTemplateRepository]:
    repo = MemoryTemplateRepository()
    repo.add_number(
        tenant_id=TENANT, connection_id=CONNECTION, waba_id="waba-1", phone_row_id=uuid4()
    )

    async def factory(*, tenant_id: UUID, connection_id: UUID) -> FakeClient:
        return client

    return TemplateService(repo, factory), repo  # type: ignore[arg-type]


async def test_create_goes_to_meta_then_mirrors() -> None:
    client = FakeClient()
    service, _repo = _service(client)
    vm = await create_template(TENANT, CONNECTION, _form(), service=service)
    assert client.created[0][:4] == ("waba-1", "promo_octubre", "es", "marketing")
    assert client.created[0][4][0]["text"] == "Hola {{1}}, tu pedido {{2}} ya salió."
    assert vm.status_label == "En revisión" and vm.status_tone == "info"
    listed = await list_templates(TENANT, CONNECTION, service=service)
    assert [t.name for t in listed] == ["promo_octubre"]


async def test_duplicate_is_refused_before_meta() -> None:
    client = FakeClient()
    service, _repo = _service(client)
    await create_template(TENANT, CONNECTION, _form(), service=service)
    with pytest.raises(TemplateAlreadyExists):
        await create_template(TENANT, CONNECTION, _form(), service=service)
    assert len(client.created) == 1


async def test_auth_error_degrades_the_connection() -> None:
    client = FakeClient(fail=WhatsAppApiError("rejected", status=401, code=190))
    service, _repo = _service(client)
    degraded: list[dict[str, UUID]] = []
    with pytest.raises(WhatsAppApiError):
        await create_template(
            TENANT, CONNECTION, _form(), service=service, degrader=lambda **kw: degraded.append(kw)
        )
    assert degraded == [{"tenant_id": TENANT, "connection_id": CONNECTION}]


async def test_non_auth_error_does_not_degrade() -> None:
    client = FakeClient(fail=WhatsAppApiError("bad", status=400, code=100))
    service, _repo = _service(client)
    degraded: list[object] = []
    with pytest.raises(WhatsAppApiError):
        await sync_templates(TENANT, CONNECTION, service=service, degrader=degraded.append)
    assert degraded == []


async def test_sync_and_delete() -> None:
    client = FakeClient()
    client.listed = [
        TemplateInfo(
            id="m-2",
            name="aviso",
            language="es",
            status="APPROVED",
            category="utility",
            components=[{"type": "BODY", "text": "Tu pedido salió"}],
        )
    ]
    service, repo = _service(client)
    report = await sync_templates(TENANT, CONNECTION, service=service)
    assert (report.listed, report.created) == (1, 1)
    [vm] = await list_templates(TENANT, CONNECTION, service=service)
    assert vm.sendable and vm.status_tone == "ok"
    marked = await delete_template(TENANT, CONNECTION, UUID(vm.template_id), service=service)
    assert marked == 1 and client.deleted == [("waba-1", "aviso")]
    [gone] = await list_templates(TENANT, CONNECTION, service=service)
    assert gone.status_label == "Eliminada" and not gone.can_delete


def test_tab_renders() -> None:
    component = whatsapp_tab_templates.templates_tab()
    assert isinstance(component, rx.Component)
    rendered = str(component.render())
    for text in ("Ver si ya las aprobaron", "Nueva plantilla", "Enviar a revisi"):
        assert text in rendered, text
