"""View-models for `/whatsapp` → Plantillas (WA-18, QUA-217) — the security boundary.

`WhatsAppTemplatesState` only holds the frozen dataclasses below: never a
`whatsapp_templates` ORM row, never a Graph client, never a token
(`test_whatsapp_templates_vm_has_no_credential_fields` pins it). Dates are pre-formatted
here, server-side.

**The owner never writes `{{…}}` (m-24842997).** The guided form has four steps (what to
announce → the message → buttons → «Así lo verá tu cliente»). The only variable it offers
is the customer's name: «Agregar el nombre del cliente» inserts `NAME_TOKEN` («[nombre]»)
into the text, and `build_components` turns it into `{{1}}` with its example filled in
(`NAME_EXAMPLE`), so Meta always receives the example it requires and the owner never
types one. `HttpWhatsAppClient.create_template` sends no `parameter_format`, so Meta reads
POSITIONAL parameters; `{{1}}` is also what the chat's approved-message drawer prefills
with the person's first name (`qualify_api.whatsapp.template_reply.prefill`). Meta's
internal name is chosen from the owner's words (`template_name`), never typed with an
underscore. Templates authored in WhatsApp Manager with named parameters come back
through «Ver si ya las aprobaron» untouched; `send_variables` reads both styles.

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
from collections.abc import Collection, Mapping, Sequence
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
    option_label: str  # «Promo octubre · Español» — the campaign select item
    display_name: str = ""  # «Promo octubre»: the internal name, readable (m-24842997)
    body_preview: str = ""  # the body with Meta's examples in place of `{{…}}`


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
        option_label=f"{display_name(name)} · {language_label(language)}",
        display_name=display_name(name),
        body_preview=readable_body(components),
    )


# --------------------------------------------------------------------------------------
# The guided form (m-24842997): ¿qué avisar? → mensaje → botones → así lo verá tu cliente
# --------------------------------------------------------------------------------------

#: What the owner sees (and the «Agregar el nombre del cliente» button inserts) where the
#: customer's name goes. Never `{{…}}`: `build_components` turns it into `{{1}}`.
NAME_TOKEN = "[nombre]"
#: The example Meta requires for that variable — filled in automatically, never typed.
NAME_EXAMPLE = "Ana"
ADD_NAME_LABEL = "Agregar el nombre del cliente"

# (key, label, one-line explanation): what the guided form offers. Authentication
# templates have Meta's fixed format and are not built here (see the module docstring).
GUIDED_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    (
        CATEGORY_MARKETING,
        "Una promoción",
        "Ofertas, novedades o descuentos. Solo les llega a los clientes que aceptaron "
        "recibir tus promociones.",
    ),
    (
        CATEGORY_UTILITY,
        "Un aviso de pedido",
        "Algo sobre lo que el cliente ya pidió: su pedido, su reserva o su pago.",
    ),
)
GUIDED_CATEGORY_KEYS: frozenset[str] = frozenset(key for key, _l, _h in GUIDED_CATEGORIES)

STEPS: tuple[str, ...] = ("Qué avisar", "Mensaje", "Botones", "Revisar")
STEP_KIND, STEP_MESSAGE, STEP_BUTTONS, STEP_REVIEW = range(4)
STEP_TITLES: tuple[str, ...] = (
    "¿Qué quieres avisar?",
    "Escribe el mensaje",
    "Botones (opcional)",
    "Así lo verá tu cliente",
)

FORM_TITLE = "Crear un mensaje"
SUBMIT_LABEL = "Enviar a aprobación"
MAX_LABEL_CHARS = 60
#: N3 — the exact notice once the message reached Meta, and the next step under it.
SUBMITTED_MESSAGE = "Te avisamos cuando esté aprobado (puede tardar hasta 24 h)."
NEXT_STEP_CONTACTS = "Ver clientes que aceptaron"

_MAX_AUTO_NAME_CHARS = 40
_NAME_CHARS = re.compile(r"[a-z0-9_]+")
_BRACES = re.compile(r"[{}]")


@dataclass(frozen=True)
class TemplateForm:
    """What the guided form holds — plain strings, as typed. `body` is in the owner's
    words, with `NAME_TOKEN` where the customer's name goes; `name` is Meta's internal
    name, chosen by the state (`template_name`), never typed with an underscore."""

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
)


def uses_name(body: str) -> bool:
    return NAME_TOKEN in body


def insert_name(body: str) -> str:
    """«Agregar el nombre del cliente»: an empty message starts with a greeting (a body
    cannot start with a variable); otherwise the name goes at the end, ready to keep
    writing after it."""
    if not body.strip():
        return f"Hola {NAME_TOKEN}, "
    return f"{body.rstrip()} {NAME_TOKEN} "


def suggest_name(text: str) -> str:
    """«Promo Octubre» → «promo_octubre»: Meta's alphabet (lowercase, digits, «_»)."""
    folded = text.lower().replace("ñ", "n")
    for accented, plain in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
        folded = folded.replace(accented, plain)
    return re.sub(r"[^a-z0-9_]+", "_", folded).lstrip("_")[:MAX_NAME_CHARS]


def auto_label(category: str, body: str) -> str:
    """What the owner will recognise the message by, until they write their own name in
    «Más opciones»: the kind plus the first words of the message (the name left out)."""
    kind = "Aviso" if category == CATEGORY_UTILITY else "Promoción"
    words = [w for w in body.replace(NAME_TOKEN, " ").split() if any(c.isalnum() for c in w)]
    return " ".join([kind, *words[:4]])


def template_name(label: str, category: str, body: str, taken: Collection[str]) -> str:
    """Meta's internal name from the owner's words: folded to Meta's alphabet, short, and
    never one already used on this number (Meta keeps a deleted name for 30 days, and
    the mirror still lists it) — «_2», «_3»… when it is."""
    base = suggest_name(label.strip() or auto_label(category, body))
    base = base[:_MAX_AUTO_NAME_CHARS].strip("_") or (
        "aviso" if category == CATEGORY_UTILITY else "promocion"
    )
    if base not in taken:
        return base
    suffix = 2
    while f"{base}_{suffix}" in taken:
        suffix += 1
    return f"{base}_{suffix}"


def display_name(name: str) -> str:
    """`promo_octubre` → «Promo octubre»: Meta's internal name, readable."""
    words = " ".join(part for part in (name or "").replace("-", "_").split("_") if part)
    return words[:1].upper() + words[1:] if words else "Mensaje sin nombre"


def _quick_replies(form: TemplateForm) -> list[str]:
    return [q.strip() for q in form.quick_replies if q.strip()]


def _meta_body(body: str) -> str:
    return body.strip().replace(NAME_TOKEN, "{{1}}")


def validate_kind(form: TemplateForm) -> str:
    if form.category == CATEGORY_AUTHENTICATION:
        return AUTHENTICATION_NOTICE
    if form.category not in GUIDED_CATEGORY_KEYS:
        return "Elige qué quieres avisar."
    return ""


def validate_message(form: TemplateForm) -> str:
    """Spanish copy for the first thing Meta would refuse in the message step."""
    body = form.body.strip()
    if not body:
        return "Escribe el mensaje."
    if _BRACES.search(body):
        return (
            "Quita las llaves del mensaje. Para poner el nombre del cliente, toca "
            f"«{ADD_NAME_LABEL}»."
        )
    if len(_meta_body(body)) > MAX_BODY_CHARS:
        return f"El mensaje admite hasta {MAX_BODY_CHARS} caracteres."
    if body.startswith(NAME_TOKEN):
        return "Empieza con un saludo antes del nombre del cliente, por ejemplo «Hola»."
    if body.endswith(NAME_TOKEN):
        return "Escribe algo después del nombre del cliente: el mensaje no puede terminar con él."
    header = form.header.strip()
    if len(header) > MAX_HEADER_CHARS:
        return f"El título admite hasta {MAX_HEADER_CHARS} caracteres."
    if _BRACES.search(header) or NAME_TOKEN in header:
        return "El título no puede llevar el nombre del cliente ni llaves."
    footer = form.footer.strip()
    if len(footer) > MAX_FOOTER_CHARS:
        return f"El texto pequeño del final admite hasta {MAX_FOOTER_CHARS} caracteres."
    if _BRACES.search(footer) or NAME_TOKEN in footer:
        return "El texto pequeño del final no puede llevar el nombre del cliente ni llaves."
    if form.language not in LANGUAGE_KEYS:
        return "Elige el idioma del mensaje en «Más opciones»."
    return ""


def validate_buttons(form: TemplateForm) -> str:
    if form.button_kind not in BUTTON_KIND_KEYS:
        return "Elige si el mensaje lleva botones."
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
        if _BRACES.search(url):
            return "El enlace del botón no puede llevar llaves."
    return ""


def validate_step(form: TemplateForm, step: int) -> str:
    """What still blocks «Siguiente» on `step` ("" = it can move on)."""
    if step == STEP_KIND:
        return validate_kind(form)
    if step == STEP_MESSAGE:
        return validate_message(form)
    if step == STEP_BUTTONS:
        return validate_buttons(form)
    return validate_template_form(form)


def validate_template_form(form: TemplateForm) -> str:
    """Spanish copy for the first thing Meta (or the client) would refuse; "" = sendable."""
    for check in (validate_kind, validate_message, validate_buttons):
        problem = check(form)
        if problem:
            return problem
    name = form.name.strip()
    if not name or len(name) > MAX_NAME_CHARS or not _NAME_CHARS.fullmatch(name):
        # The state chooses the name; a bad one is our bug, said in the owner's words.
        return "Escribe un nombre para reconocer el mensaje en «Más opciones»."
    return ""


def build_components(form: TemplateForm) -> list[dict[str, Any]]:
    """The `components` Meta reviews, POSITIONAL (see the module docstring): the name is
    `{{1}}` and its example is filled in here, so Meta always gets the field it requires.
    Assumes `validate_template_form(form) == ""`."""
    components: list[dict[str, Any]] = []
    if form.header.strip():
        components.append({"type": "HEADER", "format": "TEXT", "text": form.header.strip()})
    body: dict[str, Any] = {"type": "BODY", "text": _meta_body(form.body)}
    if uses_name(form.body):
        body["example"] = {"body_text": [[NAME_EXAMPLE]]}
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


def preview_body(body: str) -> str:
    """The body as the customer would read it: the name replaced by the example."""
    return body.strip().replace(NAME_TOKEN, NAME_EXAMPLE)


def readable_body(components: Sequence[Mapping[str, Any]]) -> str:
    """A stored body for the list: each `{{…}}` replaced by Meta's example (what the
    customer would read), or «…» when the template carries none."""
    body = _component(components, "BODY")
    text = _text_of(body)
    positional = _examples(body, "BODY")
    named = _named_examples(body, "BODY")

    def example(match: re.Match[str]) -> str:
        key = match.group(1)
        if key.isdigit() and 0 < int(key) <= len(positional):
            return positional[int(key) - 1] or "…"
        return named.get(key) or "…"

    return _ANY_PLACEHOLDER.sub(example, text)


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
