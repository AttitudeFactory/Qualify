"""Safe, plain-language projections of Meta forms; no implicit advertising approval."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

FORM_STEPS = (
    "Elige la página de tu negocio",
    "¿Qué datos necesitas?",
    "Comparte tu política de privacidad",
    "¿Qué verán al terminar?",
    "Revisa tu formulario",
)
FORM_ROUTE = "/promotions/forms"
FORM_NOTICE = (
    "Crear este formulario en Meta no crea ni activa un anuncio y no autoriza gasto. "
    "Después de activar la recepción, las respuestas que Meta entregue aparecerán "
    "en Por responder, en Interesados."
)
WHATSAPP_NOTICE = (
    "Dejar un teléfono en este formulario no autoriza mensajes por WhatsApp. "
    "No registraremos ese permiso ni enviaremos mensajes."
)
FORM_UNCERTAIN = (
    "No pudimos confirmar si Meta creó el formulario. No vuelvas a crearlo: "
    "comprueba el resultado en Meta antes de continuar."
)


@dataclass(frozen=True)
class FormConnectionVM:
    id: str = ""
    label: str = ""
    available: bool = False
    reason: str = ""


@dataclass(frozen=True)
class AdFormDraftVM:
    connection_id: str = ""
    name: str = ""
    ask_name: bool = True
    ask_email: bool = True
    ask_phone: bool = False
    custom_questions: str = ""
    privacy_url: str = ""
    thank_you_title: str = "Gracias por dejarnos tus datos"
    thank_you_body: str = "Recibimos tu información."
    thank_you_url: str = ""


@dataclass(frozen=True)
class AdFormVM:
    id: str = ""
    connection_id: str = ""
    name: str = ""
    status: str = ""
    status_label: str = "Por comprobar"
    tone: str = "warn"
    editable: bool = False
    published: bool = False
    revision: int = 1
    page_label: str = ""
    draft: AdFormDraftVM = AdFormDraftVM()


def safe_https(value: str) -> bool:
    try:
        parsed = urlsplit(value.strip())
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not any(char.isspace() for char in value)
            and len(value) <= 2000
        )
    except ValueError:
        return False


def custom_questions(value: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in value.splitlines() if line.strip())


def custom_question_parts(value: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    parts = [tuple(part.strip() for part in line.split("|")) for line in custom_questions(value)]
    return tuple((row[0], row[1:]) for row in parts)


def question_summary(draft: AdFormDraftVM) -> str:
    questions = [
        label
        for enabled, label in (
            (draft.ask_name, "Nombre completo"),
            (draft.ask_email, "Correo electrónico"),
            (draft.ask_phone, "Teléfono"),
        )
        if enabled
    ]
    return " · ".join(questions + list(custom_questions(draft.custom_questions)))


def form_step_problem(draft: AdFormDraftVM, step: int) -> str:
    if step == 1:
        if not draft.connection_id:
            return "Elige la página de tu negocio."
        if not 1 <= len(draft.name.strip()) <= 100:
            return "Escribe un nombre de hasta 100 caracteres para reconocer el formulario."
    if step == 2:
        if not (draft.ask_email or draft.ask_phone):
            return "Pide al menos un correo electrónico o un teléfono de contacto."
        questions = custom_question_parts(draft.custom_questions)
        if len(questions) > 3 or any(not label or len(label) > 120 for label, _ in questions):
            return "Escribe hasta tres preguntas, de hasta 120 caracteres cada una."
        if len({label for label, _ in questions}) != len(questions):
            return "Quita las preguntas repetidas antes de continuar."
        for _, options in questions:
            if (
                len(options) > 10
                or any(not option or len(option) > 100 for option in options)
                or len(set(options)) != len(options)
            ):
                return "Usa hasta diez opciones diferentes por pregunta, de hasta 100 caracteres."
    if step == 3 and not safe_https(draft.privacy_url):
        return "Escribe el enlace completo de tu política de privacidad, con https://."
    if step == 4:
        if not 1 <= len(draft.thank_you_title.strip()) <= 60:
            return "Escribe un título de hasta 60 caracteres para el agradecimiento."
        if not 1 <= len(draft.thank_you_body.strip()) <= 200:
            return "Escribe un mensaje de hasta 200 caracteres para el agradecimiento."
        if not safe_https(draft.thank_you_url):
            return "Escribe el enlace que podrán abrir al terminar, con https://."
    return ""


def form_problem(draft: AdFormDraftVM) -> str:
    return next((reason for step in range(1, 5) if (reason := form_step_problem(draft, step))), "")


def form_status(status: str) -> tuple[str, str]:
    return {
        "draft": ("Borrador", "neutral"),
        "publishing": ("Creación en curso", "warn"),
        "pending": ("Creación en curso", "warn"),
        "published": ("Creado en Meta", "ok"),
        "unknown": ("Por comprobar en Meta", "warn"),
        "failed": ("Requiere revisión", "warn"),
    }.get(status, ("Por comprobar", "warn"))
