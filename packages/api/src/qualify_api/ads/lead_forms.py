"""Typed, bounded lead form drafts and CRM projections (m-24828981)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID


class LeadFormUnavailable(ValueError):
    """A client-safe explanation, never provider response text."""


def safe_text(value: str, *, maximum: int = 500, required: bool = True) -> str:
    if not isinstance(value, str):
        raise LeadFormUnavailable("Revisa los textos del formulario.")
    result = value.strip()
    if (
        (required and not result)
        or len(result) > maximum
        or any(ord(char) < 32 and char not in "\n\t" for char in result)
    ):
        raise LeadFormUnavailable("Revisa los textos del formulario.")
    return result


def https_url(value: str) -> str:
    result = safe_text(value, maximum=2000)
    try:
        url = urlsplit(result)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or any(char.isspace() for char in result)
        ):
            raise ValueError
    except ValueError:
        raise LeadFormUnavailable("Escribe un enlace completo que empiece por https://.") from None
    return result


@dataclass(frozen=True)
class LeadFormQuestion:
    kind: str
    key: str = ""
    label: str = ""
    options: tuple[str, ...] = ()

    def payload(self) -> dict:
        if self.kind not in {"FULL_NAME", "EMAIL", "PHONE", "CUSTOM"}:
            raise LeadFormUnavailable("Elige una pregunta disponible.")
        if self.kind != "CUSTOM":
            if self.key or self.options:
                raise LeadFormUnavailable("Revisa las preguntas de contacto.")
            return {"type": self.kind}
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", self.key):
            raise LeadFormUnavailable("Revisa el identificador de la pregunta personalizada.")
        result = {"type": "CUSTOM", "key": self.key, "label": safe_text(self.label, maximum=120)}
        if self.options:
            if len(self.options) > 10 or len(set(self.options)) != len(self.options):
                raise LeadFormUnavailable("Usa hasta diez opciones diferentes por pregunta.")
            result["options"] = [
                {"key": str(index), "value": safe_text(option, maximum=100)}
                for index, option in enumerate(self.options)
            ]
        return result


@dataclass(frozen=True)
class LeadFormDraft:
    name: str
    privacy_policy_url: str
    thank_you_title: str
    thank_you_body: str
    thank_you_url: str
    questions: tuple[LeadFormQuestion, ...]
    locale: str = "ES_LA"

    def payload(self) -> dict:
        if self.locale not in {"ES_LA", "ES_ES"}:
            raise LeadFormUnavailable("Elige español para el formulario.")
        if not 1 <= len(self.questions) <= 10:
            raise LeadFormUnavailable("Añade entre una y diez preguntas.")
        keys = [question.key or question.kind for question in self.questions]
        if len(keys) != len(set(keys)):
            raise LeadFormUnavailable("Evita repetir una pregunta.")
        if not any(question.kind in {"EMAIL", "PHONE"} for question in self.questions):
            raise LeadFormUnavailable("Añade correo o teléfono para poder contactar a la persona.")
        return {
            "name": safe_text(self.name, maximum=120),
            "locale": self.locale,
            "privacy_policy": {"url": https_url(self.privacy_policy_url)},
            "questions": [question.payload() for question in self.questions],
            "thank_you_page": {
                "title": safe_text(self.thank_you_title, maximum=60),
                "body": safe_text(self.thank_you_body, maximum=500),
                "button_type": "VIEW_WEBSITE",
                "button_text": "Ver sitio web",
                "website_url": https_url(self.thank_you_url),
            },
        }


@dataclass(frozen=True)
class LeadFormConnection:
    id: UUID
    label: str
    page_id: str
    available: bool
    reason: str


@dataclass(frozen=True)
class LeadFormSummary:
    id: UUID
    connection_id: UUID
    name: str
    page_id: str
    status: str
    meta_form_id: str
    draft: LeadFormDraft
    message: str = ""
    revision: int = 1


@dataclass(frozen=True)
class MetaLeadSummary:
    id: UUID
    full_name: str
    phone: str | None
    email: str | None
    form_name: str
    meta_form_id: str
    meta_ad_id: str | None
    promotion_id: UUID | None
    created_at: datetime
    contacted_at: datetime | None
    answers: dict[str, str] = field(default_factory=dict)
    whatsapp_opt_in: bool = False


def draft_from_json(value: dict) -> LeadFormDraft:
    return LeadFormDraft(
        **{
            key: value[key]
            for key in (
                "name",
                "privacy_policy_url",
                "thank_you_title",
                "thank_you_body",
                "thank_you_url",
            )
        },
        questions=tuple(LeadFormQuestion(**question) for question in value["questions"]),
        locale=value.get("locale", "ES_LA"),
    )
