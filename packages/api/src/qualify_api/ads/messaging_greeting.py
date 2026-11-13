"""Owner-written greeting for ads that open a chat: versioned, tenant-scoped (m-24828980).

The greeting becomes the creative's `page_welcome_message`. Field name and type (a string)
come from facebook-python-business-sdk 26.0.0 `adobjects/adcreative.py`
(`AdCreative.Field.page_welcome_message`, `'page_welcome_message': 'string'`). The JSON inside
it follows Meta's click-to-WhatsApp / click-to-Instagram guides, «ice breakers» variant
(retrieved 2026-11-13): `type=VISUAL_EDITOR`, `version=2`, `landing_screen_type=welcome_message`,
`media_type=text`, `text_format.customer_action_type=ice_breakers`, `text_format.message`
with `text` and `ice_breakers[{title}]`. The optional automatic `response` of each question
is left out on purpose: replies stay assisted, never automatic.

Gap (docs/anuncios-conversaciones-atribucion.md): Meta's existing-post examples do not show
a `page_welcome_message`, so whether Meta accepts it on a `source_instagram_media_id`
creative is measured by the exact `validate_only` call before anything is created, and the
read-back must return the same structure before activation. Nothing is assumed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.tenancy.acting import current_acting_login, require_acting_member

PIPELINE_VERSION = "ad-message-greeting-v1"
# Instagram's Ice Breakers API allows a maximum of 4 questions (Meta corpus,
# reference/meta-instagram-platform/documentation/business-messaging/instagram-messaging/
# features/ice-breakers.md). shortcut: the text lengths are Qualify's own caps — Meta's
# limits for ad templates are not published; validate_only is the measured check.
MAX_QUESTIONS = 4
MAX_WELCOME = 300
MAX_QUESTION = 80


class GreetingUnavailable(ValueError):
    """A safe Spanish explanation for the owner."""


def clean(welcome_text: str, questions: list[str] | tuple[str, ...]) -> tuple[str, tuple[str, ...]]:
    if (
        not isinstance(welcome_text, str)
        or not isinstance(questions, (list, tuple))
        or any(not isinstance(q, str) for q in questions)
    ):
        raise GreetingUnavailable("Revisa el saludo y las preguntas.")
    welcome = welcome_text.strip()
    asked = tuple(q.strip() for q in questions if q.strip())  # Empty boxes are skipped.
    if not welcome or len(welcome) > MAX_WELCOME:
        raise GreetingUnavailable(
            f"Escribe un saludo de bienvenida de hasta {MAX_WELCOME} caracteres."
        )
    if not 1 <= len(asked) <= MAX_QUESTIONS:
        raise GreetingUnavailable(f"Escribe entre 1 y {MAX_QUESTIONS} preguntas sugeridas.")
    if any(len(q) > MAX_QUESTION for q in asked):
        raise GreetingUnavailable(f"Cada pregunta puede tener hasta {MAX_QUESTION} caracteres.")
    if len(set(asked)) != len(asked):
        raise GreetingUnavailable("Hay preguntas repetidas. Deja una sola de cada una.")
    return welcome, asked


@dataclass(frozen=True)
class MessageGreeting:
    greeting_id: UUID
    brand_id: UUID
    version: int
    welcome_text: str
    questions: tuple[str, ...]

    def snapshot(self) -> dict[str, Any]:
        if (
            not isinstance(self.greeting_id, UUID)
            or not isinstance(self.brand_id, UUID)
            or type(self.version) is not int
            or self.version < 1
            or clean(self.welcome_text, self.questions) != (self.welcome_text, self.questions)
        ):
            raise ValueError("invalid message greeting")
        return {
            "greeting_id": str(self.greeting_id),
            "brand_id": str(self.brand_id),
            "version": self.version,
            "welcome_text": self.welcome_text,
            "questions": list(self.questions),
        }

    @classmethod
    def from_snapshot(cls, value: dict[str, Any]) -> MessageGreeting:
        try:
            greeting = cls(
                UUID(value["greeting_id"]),
                UUID(value["brand_id"]),
                value["version"],
                value["welcome_text"],
                tuple(value["questions"]),
            )
            if greeting.snapshot() != value:
                raise ValueError("unexpected greeting fields")
            return greeting
        except (KeyError, TypeError, AttributeError, GreetingUnavailable) as exc:
            raise ValueError("invalid message greeting snapshot") from exc

    def page_welcome_message(self) -> str:
        """The creative string; key order is fixed so the approval hash is stable."""
        return json.dumps(
            {
                "type": "VISUAL_EDITOR",
                "version": 2,
                "landing_screen_type": "welcome_message",
                "media_type": "text",
                "text_format": {
                    "customer_action_type": "ice_breakers",
                    "message": {
                        "text": self.welcome_text,
                        "ice_breakers": [{"title": q} for q in self.questions],
                    },
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


def _member(tenant_id: UUID) -> UUID:
    login = current_acting_login()
    if login is None:
        raise GreetingUnavailable("Vuelve a iniciar sesión para revisar el saludo.")
    require_acting_member(tenant_id)
    return login


def _row(row: Any) -> MessageGreeting:
    return MessageGreeting(
        row["id"], row["brand_id"], row["version"], row["welcome_text"], tuple(row["questions"])
    )


def current_greeting(*, tenant_id: UUID, brand_id: UUID) -> MessageGreeting | None:
    """The brand's latest saved greeting, or None when the owner never wrote one."""
    _member(tenant_id)
    with tenant_session(tenant_id, independent=True) as session:
        row = (
            session.execute(
                text(
                    "SELECT id,brand_id,version,welcome_text,questions FROM ad_message_greetings "
                    "WHERE brand_id=:brand ORDER BY version DESC LIMIT 1"
                ),
                {"brand": brand_id},
            )
            .mappings()
            .first()
        )
    return _row(row) if row else None


def save_greeting(
    *,
    tenant_id: UUID,
    brand_id: UUID,
    welcome_text: str,
    questions: list[str] | tuple[str, ...],
    expected_version: int,
) -> MessageGreeting:
    """Append a new version (compare-and-swap on the version the owner edited).

    Saving the same text again returns the current version instead of a new one, so a
    double submit is harmless. Approved promotions keep the version they froze.
    """
    login = _member(tenant_id)
    welcome, asked = clean(welcome_text, questions)
    with tenant_session(tenant_id, independent=True) as session:
        if (
            session.execute(
                text("SELECT id FROM brands WHERE id=:id FOR SHARE"), {"id": brand_id}
            ).scalar_one_or_none()
            is None
        ):
            raise GreetingUnavailable("Esta marca ya no está disponible en este negocio.")
        latest = (
            session.execute(
                text(
                    "SELECT id,brand_id,version,welcome_text,questions FROM ad_message_greetings "
                    "WHERE brand_id=:brand ORDER BY version DESC LIMIT 1"
                ),
                {"brand": brand_id},
            )
            .mappings()
            .first()
        )
        current = _row(latest) if latest else None
        if current and (current.welcome_text, current.questions) == (welcome, asked):
            return current
        if (current.version if current else 0) != expected_version:
            raise GreetingUnavailable(
                "Alguien cambió el saludo mientras lo editabas. Revisa la versión actual."
            )
        row = (
            session.execute(
                text(
                    "INSERT INTO ad_message_greetings (tenant_id,brand_id,version,welcome_text,"
                    "questions,created_by,pipeline_version) VALUES (:tenant,:brand,:version,"
                    ":welcome,CAST(:questions AS jsonb),:login,:pipeline) "
                    "ON CONFLICT (tenant_id,brand_id,version) DO NOTHING "
                    "RETURNING id,brand_id,version,welcome_text,questions"
                ),
                {
                    "tenant": tenant_id,
                    "brand": brand_id,
                    "version": expected_version + 1,
                    "welcome": welcome,
                    "questions": json.dumps(list(asked), ensure_ascii=False),
                    "login": login,
                    "pipeline": PIPELINE_VERSION,
                },
            )
            .mappings()
            .first()
        )
    if row is None:
        raise GreetingUnavailable(
            "Alguien cambió el saludo mientras lo editabas. Revisa la versión actual."
        )
    return _row(row)
