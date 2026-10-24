"""View-models for `/whatsapp` → Plantillas (WA-18, QUA-217) — the security boundary.

`WhatsAppTemplatesState` only holds the frozen dataclasses below: never a
`whatsapp_templates` ORM row, never a Graph client, never a token
(`test_whatsapp_templates_vm_has_no_credential_fields` pins it). Dates are pre-formatted
here, server-side.

**Named variables on screen, positional on the wire.** The operator writes the body with
named variables (`Hola {{nombre}}, tu pedido {{pedido}} está listo`) because a name says
what goes there. `HttpWhatsAppClient.create_template` sends no `parameter_format`, so Meta
applies its default — POSITIONAL (`{{1}}`, `{{2}}`) — and would reject a named body. So
`build_components` numbers the names in order of first appearance (a repeated name reuses
its number) and sends `example.body_text` in that order: what Meta reviews is exactly
what the preview showed. Templates authored in WhatsApp Manager with named parameters
come back through «Ver si ya las aprobaron» untouched; `send_variables` reads both styles.

Meta's rules surfaced here (template-management, read 2026-10-14): name = lowercase
letters, digits and `_`; header ≤ 60 chars, body ≤ 1024, footer ≤ 60; a body cannot start
or end with a variable; every variable needs an example; up to 3 quick replies or one URL
button (≤ 25 chars of text); review "can take up to 24 h". Authentication templates have a
fixed one-time-code format the guided form does not build — they are created in WhatsApp
Manager and synced.

Pure module: no Reflex, network or database import (plain unit tests).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .whatsapp_vm import format_timestamp

# --------------------------------------------------------------------------------------
# Categories, languages
# --------------------------------------------------------------------------------------

CATEGORY_MARKETING = "marketing"
CATEGORY_UTILITY = "utility"
CATEGORY_AUTHENTICATION = "authentication"

# (key, label, one-line explanation). Order = the picker's.
CATEGORIES: tuple[tuple[str, str, str], ...] = (
    (
        CATEGORY_MARKETING,
        "Promociones",
        "Promociones, novedades y ofertas. Solo a contactos que aceptaron recibir tus "
        "mensajes; Meta limita cuántas recibe cada persona.",
    ),
    (
        CATEGORY_UTILITY,
        "Avisos de pedidos",
        "Avisos sobre algo que el cliente ya pidió: su pedido, su reserva, su pago.",
    ),
    (
        CATEGORY_AUTHENTICATION,
        "Autenticación",
        "Códigos de verificación de un solo uso, con el formato fijo de Meta.",
    ),
)
CATEGORY_KEYS: frozenset[str] = frozenset(key for key, _l, _h in CATEGORIES)
_CATEGORY_LABEL: dict[str, str] = {key: label for key, label, _h in CATEGORIES}

LANGUAGES: tuple[tuple[str, str], ...] = (
    ("es", "Español"),
    ("es_MX", "Español (México)"),
    ("es_AR", "Español (Argentina)"),
    ("es_ES", "Español (España)"),
    ("en_US", "Inglés (EE. UU.)"),
    ("pt_BR", "Portugués (Brasil)"),
)
LANGUAGE_KEYS: frozenset[str] = frozenset(key for key, _ in LANGUAGES)
DEFAULT_LANGUAGE = "es"
_LANGUAGE_LABEL: dict[str, str] = dict(LANGUAGES)

# Meta-published limits.
MAX_NAME_CHARS = 512
MAX_HEADER_CHARS = 60
MAX_BODY_CHARS = 1024
MAX_FOOTER_CHARS = 60
MAX_BUTTON_CHARS = 25
MAX_URL_CHARS = 2000
MAX_QUICK_REPLIES = 3

BUTTONS_NONE = "none"
BUTTONS_QUICK = "quick"
BUTTONS_URL = "url"
BUTTON_KINDS: tuple[tuple[str, str], ...] = (
    (BUTTONS_NONE, "Sin botones"),
    (BUTTONS_QUICK, "Respuestas rápidas"),
    (BUTTONS_URL, "Botón con enlace"),
)
BUTTON_KIND_KEYS: frozenset[str] = frozenset(key for key, _ in BUTTON_KINDS)

REVIEW_NOTICE = (
    "Meta revisa cada plantilla antes de que puedas usarla; la revisión puede tardar "
    "hasta 24 h. El estado se actualiza solo, o con «Ver si ya las aprobaron»."
)
AUTHENTICATION_NOTICE = (
    "Las plantillas de autenticación usan el formato fijo de Meta (un código de un solo "
    "uso). Créalas desde tu cuenta de WhatsApp Business en Meta y luego pulsa «Ver si ya "
    "las aprobaron»."
)

# --------------------------------------------------------------------------------------
# Meta enums → (label, tone)
# --------------------------------------------------------------------------------------

_STATUS: dict[str, tuple[str, str]] = {
    "APPROVED": ("Aprobada", "ok"),
    "PENDING": ("En revisión", "info"),
    "IN_APPEAL": ("En apelación", "info"),
    "REJECTED": ("Rechazada", "error"),
    "DISABLED": ("Desactivada", "error"),
    "PAUSED": ("Pausada", "warn"),
    "LIMIT_EXCEEDED": ("Límite alcanzado", "warn"),
    "FLAGGED": ("Marcada por Meta", "warn"),
    "PENDING_DELETION": ("Eliminándose", "neutral"),
    "DELETED": ("Eliminada", "neutral"),
    "ARCHIVED": ("Archivada", "neutral"),
    "LOCKED": ("Bloqueada", "warn"),
    "REINSTATED": ("Restablecida", "info"),
    "UNARCHIVED": ("Desarchivada", "info"),
}

_QUALITY: dict[str, tuple[str, str]] = {
    "GREEN": ("Calidad alta", "ok"),
    "YELLOW": ("Calidad media", "warn"),
    "RED": ("Calidad baja", "error"),
    "UNKNOWN": ("Sin datos de calidad", "neutral"),
}

# `rejected_reason` enum (template-management «Rejection reasons»).
_REJECTION: dict[str, str] = {
    "INVALID_FORMAT": "Formato inválido",
    "PROMOTIONAL": "Contenido promocional en un tipo que no es Promociones",
    "INCORRECT_CATEGORY": "La categoría no corresponde al contenido",
    "TAG_CONTENT_MISMATCH": "La categoría no corresponde al contenido",
    "ABUSIVE_CONTENT": "Contenido que infringe las políticas de WhatsApp",
    "SCAM": "Posible fraude",
}

_GONE_STATUSES = frozenset({"DELETED", "PENDING_DELETION"})


def status_display(status: str | None) -> tuple[str, str]:
    if not status:
        return "Sin dato", "neutral"
    return _STATUS.get(status.upper(), (status, "neutral"))


def quality_display(quality: str | None) -> tuple[str, str]:
    if not quality:
        return _QUALITY["UNKNOWN"]
    return _QUALITY.get(quality.upper(), (quality, "neutral"))


def rejection_display(reason: str | None) -> str:
    """`ENUM` or `ENUM: Meta's explanation` → Spanish label (+ Meta's detail)."""
    if not reason:
        return ""
    code, _, detail = reason.partition(":")
    label = _REJECTION.get(code.strip().upper(), code.strip())
    detail = detail.strip()
    return f"{label}. {detail}" if detail else label


def category_label(category: str) -> str:
    return _CATEGORY_LABEL.get(category, category or "Sin categoría")


def language_label(language: str) -> str:
    return _LANGUAGE_LABEL.get(language, language)


# --------------------------------------------------------------------------------------
# Reading Meta components (synced or created here)
# --------------------------------------------------------------------------------------

_ANY_PLACEHOLDER = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")


def _component(components: Sequence[Mapping[str, Any]], kind: str) -> Mapping[str, Any] | None:
    for component in components:
        if str(component.get("type", "")).upper() == kind:
            return component
    return None


def _text_of(component: Mapping[str, Any] | None) -> str:
    if component is None:
        return ""
    text = component.get("text")
    return text if isinstance(text, str) else ""


def _buttons(components: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    block = _component(components, "BUTTONS")
    raw = block.get("buttons") if block else None
    return [b for b in raw if isinstance(b, Mapping)] if isinstance(raw, list) else []


def button_labels(components: Sequence[Mapping[str, Any]]) -> list[str]:
    labels = []
    for button in _buttons(components):
        text = button.get("text")
        labels.append(text if isinstance(text, str) and text else str(button.get("type", "")))
    return labels


@dataclass(frozen=True)
class SendVariable:
    """One parameter a send must fill. `component` is `header`/`body`; `key` is the
    positional number (`"1"`) or the parameter name; `example` is Meta's example value."""

    component: str
    key: str
    named: bool
    example: str


def _examples(component: Mapping[str, Any] | None, kind: str) -> list[str]:
    """`example.header_text: [..]` / `example.body_text: [[..]]` (positional), or the
    `*_text_named_params: [{param_name, example}]` of a named template."""
    if component is None:
        return []
    example = component.get("example")
    if not isinstance(example, Mapping):
        return []
    if kind == "HEADER":
        values = example.get("header_text")
        return [str(v) for v in values] if isinstance(values, list) else []
    values = example.get("body_text")
    if isinstance(values, list) and values and isinstance(values[0], list):
        return [str(v) for v in values[0]]
    return []


def _named_examples(component: Mapping[str, Any] | None, kind: str) -> dict[str, str]:
    if component is None or not isinstance(component.get("example"), Mapping):
        return {}
    key = "header_text_named_params" if kind == "HEADER" else "body_text_named_params"
    params = component["example"].get(key)
    if not isinstance(params, list):
        return {}
    return {
        str(p.get("param_name")): str(p.get("example", ""))
        for p in params
        if isinstance(p, Mapping) and p.get("param_name")
    }


def send_variables(components: Sequence[Mapping[str, Any]]) -> list[SendVariable]:
    """Every parameter of the header (TEXT) and the body, in send order: positional ones
    by number, named ones by first appearance."""
    out: list[SendVariable] = []
    for kind in ("HEADER", "BODY"):
        component = _component(components, kind)
        if component is None:
            continue
        if kind == "HEADER" and str(component.get("format", "TEXT")).upper() != "TEXT":
            continue
        keys: list[str] = []
        for match in _ANY_PLACEHOLDER.finditer(_text_of(component)):
            if match.group(1) not in keys:
                keys.append(match.group(1))
        positional = [k for k in keys if k.isdigit()]
        if positional and len(positional) == len(keys):
            examples = _examples(component, kind)
            for key in sorted(keys, key=int):
                index = int(key) - 1
                example = examples[index] if 0 <= index < len(examples) else ""
                out.append(SendVariable(kind.lower(), key, False, example))
        else:
            named = _named_examples(component, kind)
            for key in keys:
                out.append(SendVariable(kind.lower(), key, True, named.get(key, "")))
    return out


_SENDABLE_BUTTONS = frozenset({"QUICK_REPLY", "URL", "PHONE_NUMBER"})


def wizard_block(category: str, components: Sequence[Mapping[str, Any]]) -> str:
    """Why the campaign wizard cannot fill this template's send ("" when it can)."""
    if category == CATEGORY_AUTHENTICATION:
        return "Las plantillas de autenticación no se usan en campañas."
    header = _component(components, "HEADER")
    if header is not None and str(header.get("format", "TEXT")).upper() != "TEXT":
        return "Lleva un encabezado con imagen, video o documento; el asistente aún no lo admite."
    for button in _buttons(components):
        kind = str(button.get("type", "")).upper()
        if kind not in _SENDABLE_BUTTONS:
            return f"Lleva un botón de tipo {kind or 'desconocido'}; el asistente aún no lo admite."
        url = button.get("url")
        if kind == "URL" and isinstance(url, str) and "{{" in url:
            return "Lleva un botón con enlace variable; el asistente aún no lo admite."
    return ""


def build_send_components(
    variables: Sequence[SendVariable], values: Mapping[str, str]
) -> list[dict[str, Any]]:
    """`values` keyed by `"<component>:<key>"` → the `template.components` of the send
    (`client.build_template_body` passes it through verbatim)."""
    out: list[dict[str, Any]] = []
    for component in ("header", "body"):
        params: list[dict[str, Any]] = []
        for variable in variables:
            if variable.component != component:
                continue
            param: dict[str, Any] = {
                "type": "text",
                "text": values.get(variable_id(variable), "").strip(),
            }
            if variable.named:
                param["parameter_name"] = variable.key
            params.append(param)
        if params:
            out.append({"type": component, "parameters": params})
    return out


def variable_id(variable: SendVariable) -> str:
    return f"{variable.component}:{variable.key}"


def variable_label(variable: SendVariable) -> str:
    where = "Encabezado" if variable.component == "header" else "Mensaje"
    name = f"{{{{{variable.key}}}}}"
    return f"{where} · {name}"


# --------------------------------------------------------------------------------------
# The list
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TemplateVM:
    template_id: str
    name: str
    language: str
    language_label: str
    category: str
    category_label: str
    status: str
    status_label: str
    status_tone: str
    quality_label: str
    quality_tone: str
    rejected_reason: str  # "" when none — Spanish label + Meta's detail
    header_text: str
    body_text: str
    footer_text: str
    buttons_label: str  # «Sí · No · Ver menú», "" without buttons
    updated_at: str  # PRE-FORMATTED
    can_delete: bool
    sendable: bool  # APPROVED and fillable by the campaign wizard
    wizard_block: str  # why not (for an approved template the wizard cannot fill)
    option_label: str  # «promo_octubre · Español» — the campaign select item


def build_template_vm(
    *,
    template_id: str,
    name: str,
    language: str,
    category: str,
    status: str,
    quality: str | None,
    rejected_reason: str | None,
    components: Sequence[Mapping[str, Any]],
    updated_at: datetime | None,
) -> TemplateVM:
    status_label, status_tone = status_display(status)
    quality_label, quality_tone = quality_display(quality)
    header = _component(components, "HEADER")
    header_text = _text_of(header)
    if header is not None and not header_text:
        header_text = f"[{str(header.get('format', '')).capitalize() or 'Encabezado'}]"
    block = wizard_block(category, components)
    return TemplateVM(
        template_id=template_id,
        name=name,
        language=language,
        language_label=language_label(language),
        category=category,
        category_label=category_label(category),
        status=status,
        status_label=status_label,
        status_tone=status_tone,
        quality_label=quality_label,
        quality_tone=quality_tone,
        rejected_reason=rejection_display(rejected_reason),
        header_text=header_text,
        body_text=_text_of(_component(components, "BODY")),
        footer_text=_text_of(_component(components, "FOOTER")),
        buttons_label=" · ".join(button_labels(components)),
        updated_at=format_timestamp(updated_at, "Sin fecha"),
        can_delete=status.upper() not in _GONE_STATUSES,
        sendable=status.upper() == "APPROVED" and not block,
        wizard_block=block,
        option_label=f"{name} · {language_label(language)}",
    )


# --------------------------------------------------------------------------------------
# The guided form
# --------------------------------------------------------------------------------------

_NAME_CHARS = re.compile(r"[a-z0-9_]+")
_VARIABLE = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


@dataclass(frozen=True)
class TemplateForm:
    """What the «Nueva plantilla» form holds — plain strings, as typed."""

    category: str
    name: str
    language: str
    header: str
    body: str
    footer: str
    button_kind: str
    quick_replies: tuple[str, str, str]
    url_text: str
    url: str
    examples: Mapping[str, str]


EMPTY_FORM = TemplateForm(
    category=CATEGORY_MARKETING,
    name="",
    language=DEFAULT_LANGUAGE,
    header="",
    body="",
    footer="",
    button_kind=BUTTONS_NONE,
    quick_replies=("", "", ""),
    url_text="",
    url="",
    examples={},
)


def body_variables(body: str) -> list[str]:
    """Named variables in order of first appearance (`{{nombre}}`, case-sensitive)."""
    names: list[str] = []
    for match in _VARIABLE.finditer(body):
        if match.group(1) not in names:
            names.append(match.group(1))
    return names


def suggest_name(text: str) -> str:
    """«Promo Octubre» → «promo_octubre»: what the name field becomes as it is typed. Only a
    LEADING «_» is dropped: a trailing one is the space just typed, and stripping it would
    glue the next word on («promo» + «n» → «promon»)."""
    folded = text.lower().replace("ñ", "n")
    for accented, plain in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
        folded = folded.replace(accented, plain)
    return re.sub(r"[^a-z0-9_]+", "_", folded).lstrip("_")[:MAX_NAME_CHARS]


def _quick_replies(form: TemplateForm) -> list[str]:
    return [q.strip() for q in form.quick_replies if q.strip()]


def validate_template_form(form: TemplateForm) -> str:
    """Spanish copy for the first thing Meta (or the client) would refuse; "" = sendable."""
    if form.category not in CATEGORY_KEYS:
        return "Elige una categoría."
    if form.category == CATEGORY_AUTHENTICATION:
        return AUTHENTICATION_NOTICE
    name = form.name.strip()
    if not name:
        return "Escribe un nombre para la plantilla."
    if len(name) > MAX_NAME_CHARS or not _NAME_CHARS.fullmatch(name):
        return "El nombre solo admite minúsculas, números y guion bajo (ej.: promo_octubre)."
    if form.language not in LANGUAGE_KEYS:
        return "Elige el idioma de la plantilla."
    header = form.header.strip()
    if len(header) > MAX_HEADER_CHARS:
        return f"El encabezado admite hasta {MAX_HEADER_CHARS} caracteres."
    if "{{" in header or "}}" in header:
        return "El encabezado no admite variables en este formulario."
    body = form.body.strip()
    if not body:
        return "Escribe el mensaje."
    if len(body) > MAX_BODY_CHARS:
        return f"El mensaje admite hasta {MAX_BODY_CHARS} caracteres."
    stripped = _VARIABLE.sub("", body)
    if "{{" in stripped or "}}" in stripped:
        return (
            "Revisa las variables: escríbelas entre dobles llaves, en minúsculas y sin "
            "espacios, como {{nombre}}."
        )
    if _VARIABLE.match(body) or re.search(r"\{\{\s*[a-z_][a-z0-9_]*\s*\}\}$", body):
        return "Meta no acepta un mensaje que empiece o termine con una variable."
    for variable in body_variables(body):
        if not form.examples.get(variable, "").strip():
            return f"Escribe un ejemplo para {{{{{variable}}}}}: Meta lo exige para revisarla."
    footer = form.footer.strip()
    if len(footer) > MAX_FOOTER_CHARS:
        return f"El pie admite hasta {MAX_FOOTER_CHARS} caracteres."
    if "{{" in footer:
        return "El pie no admite variables."
    if form.button_kind not in BUTTON_KIND_KEYS:
        return "Elige el tipo de botones."
    if form.button_kind == BUTTONS_QUICK:
        replies = _quick_replies(form)
        if not replies:
            return "Escribe al menos una respuesta rápida, o elige «Sin botones»."
        if any(len(r) > MAX_BUTTON_CHARS for r in replies):
            return f"Cada botón admite hasta {MAX_BUTTON_CHARS} caracteres."
        if len(set(replies)) != len(replies):
            return "Las respuestas rápidas no pueden repetirse."
    if form.button_kind == BUTTONS_URL:
        text, url = form.url_text.strip(), form.url.strip()
        if not text:
            return "Escribe el texto del botón con enlace."
        if len(text) > MAX_BUTTON_CHARS:
            return f"El texto del botón admite hasta {MAX_BUTTON_CHARS} caracteres."
        if not url.startswith("https://") or len(url) > MAX_URL_CHARS or " " in url:
            return "El enlace del botón debe empezar por https:// y no llevar espacios."
        if "{{" in url:
            return "El enlace del botón no admite variables en este formulario."
    return ""


def build_components(form: TemplateForm) -> list[dict[str, Any]]:
    """The `components` Meta reviews, POSITIONAL (see the module docstring). Assumes
    `validate_template_form(form) == ""`."""
    names = body_variables(form.body.strip())
    numbers = {name: str(index + 1) for index, name in enumerate(names)}
    body_text = _VARIABLE.sub(lambda m: f"{{{{{numbers[m.group(1)]}}}}}", form.body.strip())
    components: list[dict[str, Any]] = []
    if form.header.strip():
        components.append({"type": "HEADER", "format": "TEXT", "text": form.header.strip()})
    body: dict[str, Any] = {"type": "BODY", "text": body_text}
    if names:
        body["example"] = {"body_text": [[form.examples[name].strip() for name in names]]}
    components.append(body)
    if form.footer.strip():
        components.append({"type": "FOOTER", "text": form.footer.strip()})
    if form.button_kind == BUTTONS_QUICK:
        components.append(
            {
                "type": "BUTTONS",
                "buttons": [{"type": "QUICK_REPLY", "text": r} for r in _quick_replies(form)],
            }
        )
    elif form.button_kind == BUTTONS_URL:
        components.append(
            {
                "type": "BUTTONS",
                "buttons": [
                    {"type": "URL", "text": form.url_text.strip(), "url": form.url.strip()}
                ],
            }
        )
    return components


@dataclass(frozen=True)
class ExampleFieldVM:
    """One «ejemplo» input of the form: the variable's name and what was typed."""

    name: str
    placeholder: str  # «{{nombre}}»
    value: str


def example_fields(form: TemplateForm) -> list[ExampleFieldVM]:
    return [
        ExampleFieldVM(name=n, placeholder=f"{{{{{n}}}}}", value=form.examples.get(n, ""))
        for n in body_variables(form.body)
    ]


def preview_body(body: str, examples: Mapping[str, str]) -> str:
    """The body as the customer would read it: each variable replaced by its example,
    or by «[nombre]» while the example is still empty."""
    return _VARIABLE.sub(
        lambda m: examples.get(m.group(1), "").strip() or f"[{m.group(1)}]", body.strip()
    )


def preview_buttons(form: TemplateForm) -> list[str]:
    if form.button_kind == BUTTONS_QUICK:
        return _quick_replies(form)
    if form.button_kind == BUTTONS_URL and form.url_text.strip():
        return [form.url_text.strip()]
    return []


def sync_report_message(listed: int, created: int, updated: int) -> str:
    if listed == 0:
        return "Meta no tiene plantillas para este número todavía."
    return f"Revisamos con Meta: {listed} plantillas ({created} nuevas, {updated} actualizadas)."
