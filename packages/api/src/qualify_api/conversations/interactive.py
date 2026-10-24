"""Quick replies and button templates for Instagram Direct (m-24789472, phase 3, B3).

Two ways a business message can offer the person something to tap instead of typing:

- **Quick replies** (`instagram-messaging/features/quick-replies.md`): up to
  `MAX_QUICK_REPLIES` (13) buttons under a TEXT message, each title at most 20 characters
  («each quick reply allows up to 20 characters before being truncated» — Qualify refuses
  instead of letting Instagram cut it). Wire shape, inside `message`:
  `"quick_replies": [{"content_type": "text", "title": …, "payload": …}]`. The corpus also
  documents `{"content_type": "user_phone_number"}` (no title, no payload: Instagram fills
  in the person's phone and shows nothing when the profile has none); `user_email` is not
  in the Instagram corpus and is NOT offered. Phone only («not available on desktop»), and
  they vanish once one is tapped. The tap comes back as a normal `message` with
  `quick_reply.payload` (`choices.CHOICE_QUICK_REPLY`, phase 1).
- **Button template** (`instagram-messaging/button-template.md`): a text of 1–640
  characters with 1–3 buttons, each a `postback` (sends `payload` back as a postback —
  Qualify's are always `QFB_…`, so `choices.postback_kind` reads the tap as `button`) or a
  `web_url` (opens a page in the in-app browser; Qualify accepts https only). Wire shape:
  `{"attachment": {"type": "template", "payload": {"template_type": "button", "text": …,
  "buttons": […]}}}`. Not available on the web version.

The **generic template** (carousel, ≤ 10 elements with image, subtitle and buttons,
`generic-template.md`) is out of scope: it needs an image per element, which means the
media-link machinery of a media reply, and no screen asks for it yet.

This module is PURE: validation, default payloads and the wire fragments. It imports no
outbox, no channel and no HTTP client, so the template library (`templates.py`, pinned
by a test to stay away from the send path) can validate its buttons with it. Errors carry
a stable `code` and the Spanish sentence to show the person (qualify-copy-es).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit

from qualify_api.conversations.choices import (
    MAX_CHOICE_PAYLOAD_CHARS,
    PREFIX_TEMPLATE_BUTTON,
)

MAX_QUICK_REPLIES: Final = 13
MAX_QUICK_REPLY_TITLE_CHARS: Final = 20
MAX_BUTTONS: Final = 3
MAX_BUTTON_TITLE_CHARS: Final = 20
MAX_BUTTON_TEMPLATE_TEXT_CHARS: Final = 640
#: Not a Meta limit (the corpus gives none for `web_url`): a sane ceiling for a link.
MAX_BUTTON_URL_CHARS: Final = 2000

#: The default payload of a text quick reply: `QR_` + the title's slug (`QR_SI`).
PREFIX_QUICK_REPLY: Final = "QR_"

QUICK_REPLY_TEXT: Final = "text"
QUICK_REPLY_PHONE: Final = "user_phone_number"
QUICK_REPLY_CONTENT_TYPES: Final = (QUICK_REPLY_TEXT, QUICK_REPLY_PHONE)

BUTTON_POSTBACK: Final = "postback"
BUTTON_WEB_URL: Final = "web_url"
BUTTON_TYPES: Final = (BUTTON_POSTBACK, BUTTON_WEB_URL)

TEMPLATE_TYPE_BUTTON: Final = "button"


# --- errors (shown to the client: Spanish, qualify-copy-es) -------------------------------

ERR_QUICK_REPLIES_TOO_MANY: Final = "quick_replies_too_many"
ERR_QUICK_REPLY_KIND_UNKNOWN: Final = "quick_reply_kind_unknown"
ERR_QUICK_REPLY_TITLE_EMPTY: Final = "quick_reply_title_empty"
ERR_QUICK_REPLY_TITLE_TOO_LONG: Final = "quick_reply_title_too_long"
ERR_QUICK_REPLY_TITLE_REPEATED: Final = "quick_reply_title_repeated"
ERR_QUICK_REPLY_PHONE_REPEATED: Final = "quick_reply_phone_repeated"
ERR_QUICK_REPLY_PAYLOAD_TOO_LONG: Final = "quick_reply_payload_too_long"
ERR_BUTTON_TEXT_EMPTY: Final = "button_text_empty"
ERR_BUTTON_TEXT_TOO_LONG: Final = "button_text_too_long"
ERR_BUTTONS_EMPTY: Final = "buttons_empty"
ERR_BUTTONS_TOO_MANY: Final = "buttons_too_many"
ERR_BUTTON_KIND_UNKNOWN: Final = "button_kind_unknown"
ERR_BUTTON_TITLE_EMPTY: Final = "button_title_empty"
ERR_BUTTON_TITLE_TOO_LONG: Final = "button_title_too_long"
ERR_BUTTON_TITLE_REPEATED: Final = "button_title_repeated"
ERR_BUTTON_URL_INVALID: Final = "button_url_invalid"
ERR_BUTTON_PAYLOAD_TOO_LONG: Final = "button_payload_too_long"

MESSAGES: Final[dict[str, str]] = {
    ERR_QUICK_REPLIES_TOO_MANY: (
        f"Un mensaje puede llevar hasta {MAX_QUICK_REPLIES} respuestas rápidas. Quita alguna."
    ),
    ERR_QUICK_REPLY_KIND_UNKNOWN: (
        "Esa respuesta rápida no existe en Instagram. Usa un texto o la de pedir el teléfono."
    ),
    ERR_QUICK_REPLY_TITLE_EMPTY: "Escribe el texto de cada respuesta rápida.",
    ERR_QUICK_REPLY_TITLE_TOO_LONG: (
        f"Cada respuesta rápida puede tener hasta {MAX_QUICK_REPLY_TITLE_CHARS} caracteres. "
        "Acórtala para que Instagram no la corte."
    ),
    ERR_QUICK_REPLY_TITLE_REPEATED: (
        "Hay dos respuestas rápidas con el mismo texto. Cambia o quita una."
    ),
    ERR_QUICK_REPLY_PHONE_REPEATED: (
        "La respuesta rápida para pedir el teléfono solo puede ir una vez por mensaje."
    ),
    ERR_QUICK_REPLY_PAYLOAD_TOO_LONG: (
        "Una de las respuestas rápidas es demasiado larga para Instagram. Acórtala."
    ),
    ERR_BUTTON_TEXT_EMPTY: "Escribe el mensaje que va encima de los botones.",
    ERR_BUTTON_TEXT_TOO_LONG: (
        f"Un mensaje con botones puede tener hasta {MAX_BUTTON_TEMPLATE_TEXT_CHARS} "
        "caracteres. Acórtalo o envíalo sin botones."
    ),
    ERR_BUTTONS_EMPTY: "Agrega al menos un botón.",
    ERR_BUTTONS_TOO_MANY: f"Un mensaje puede llevar hasta {MAX_BUTTONS} botones. Quita alguno.",
    ERR_BUTTON_KIND_UNKNOWN: (
        "Un botón puede abrir un enlace o enviar una respuesta. Elige una de las dos."
    ),
    ERR_BUTTON_TITLE_EMPTY: "Escribe el texto de cada botón.",
    ERR_BUTTON_TITLE_TOO_LONG: (
        f"El texto de cada botón puede tener hasta {MAX_BUTTON_TITLE_CHARS} caracteres."
    ),
    ERR_BUTTON_TITLE_REPEATED: "Hay dos botones con el mismo texto. Cambia o quita uno.",
    ERR_BUTTON_URL_INVALID: (
        "El enlace del botón debe ser una dirección web completa que empiece por https://."
    ),
    ERR_BUTTON_PAYLOAD_TOO_LONG: "Uno de los botones es demasiado largo para Instagram.",
}


class InteractiveMessageError(ValueError):
    """A quick reply or button the channel would refuse. `code` is stable (tests, the UI's
    logic); `message` — also `str(error)` — is the Spanish sentence to show the person;
    `index` points at the offending item (0-based) when there is one."""

    def __init__(self, code: str, *, index: int | None = None) -> None:
        self.code = code
        self.message = MESSAGES[code]
        self.index = index
        super().__init__(self.message)


# --- records -----------------------------------------------------------------------------


@dataclass(frozen=True)
class QuickReply:
    """One quick reply. `payload` defaults to `QR_<slug of the title>` when cleaned; a
    `user_phone_number` one has neither title nor payload."""

    title: str = ""
    payload: str | None = None
    content_type: str = QUICK_REPLY_TEXT

    @classmethod
    def phone(cls) -> QuickReply:
        return cls(content_type=QUICK_REPLY_PHONE)


@dataclass(frozen=True)
class TemplateButton:
    """One button of a button template: a `postback` (with a `QFB_` payload once cleaned)
    or a `web_url` (with an https `url`)."""

    type: str
    title: str
    payload: str | None = None
    url: str | None = None

    @classmethod
    def postback(cls, title: str, payload: str | None = None) -> TemplateButton:
        return cls(type=BUTTON_POSTBACK, title=title, payload=payload)

    @classmethod
    def web_url(cls, title: str, url: str) -> TemplateButton:
        return cls(type=BUTTON_WEB_URL, title=title, url=url)


# --- pure helpers ------------------------------------------------------------------------


def payload_slug(title: str) -> str:
    """`«¿Ver catálogo?»` → `VER_CATALOGO`: accents folded, anything else `_`, upper case.
    A title with no letter or digit at all slugs to `OPCION`."""
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", folded).strip("_").upper()
    return slug or "OPCION"


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _unique(base: str, taken: set[str]) -> str:
    """`base`, or `base_2`, `base_3`… — the first one not already taken."""
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}_{n}", n + 1
    return candidate


def _check_payload(payload: str, code: str, index: int) -> str:
    if len(payload) > MAX_CHOICE_PAYLOAD_CHARS:
        raise InteractiveMessageError(code, index=index)
    return payload


def clean_quick_replies(items: Iterable[QuickReply]) -> tuple[QuickReply, ...]:
    """Validate and normalize a message's quick replies (titles on one line, default
    payloads filled in, each payload unique). An empty iterable is `()`: no quick replies.
    Raises `InteractiveMessageError` naming the first problem."""
    replies = list(items)
    if len(replies) > MAX_QUICK_REPLIES:
        raise InteractiveMessageError(ERR_QUICK_REPLIES_TOO_MANY)
    titles: set[str] = set()
    payloads: set[str] = set()
    phone_seen = False
    cleaned: list[QuickReply] = []
    for index, reply in enumerate(replies):
        if not isinstance(reply, QuickReply) or reply.content_type not in (
            QUICK_REPLY_CONTENT_TYPES
        ):
            raise InteractiveMessageError(ERR_QUICK_REPLY_KIND_UNKNOWN, index=index)
        if reply.content_type == QUICK_REPLY_PHONE:
            if phone_seen:
                raise InteractiveMessageError(ERR_QUICK_REPLY_PHONE_REPEATED, index=index)
            phone_seen = True
            cleaned.append(QuickReply.phone())
            continue
        title = _one_line(reply.title or "")
        if not title:
            raise InteractiveMessageError(ERR_QUICK_REPLY_TITLE_EMPTY, index=index)
        if len(title) > MAX_QUICK_REPLY_TITLE_CHARS:
            raise InteractiveMessageError(ERR_QUICK_REPLY_TITLE_TOO_LONG, index=index)
        if title.casefold() in titles:
            raise InteractiveMessageError(ERR_QUICK_REPLY_TITLE_REPEATED, index=index)
        titles.add(title.casefold())
        given = (reply.payload or "").strip()
        payload = given or _unique(f"{PREFIX_QUICK_REPLY}{payload_slug(title)}", payloads)
        payload = _check_payload(payload, ERR_QUICK_REPLY_PAYLOAD_TOO_LONG, index)
        payloads.add(payload)
        cleaned.append(QuickReply(title=title, payload=payload))
    return tuple(cleaned)


def quick_replies_wire(replies: Sequence[QuickReply]) -> list[dict[str, str]]:
    """The `message.quick_replies` array for already-cleaned replies."""
    wire: list[dict[str, str]] = []
    for reply in replies:
        if reply.content_type == QUICK_REPLY_PHONE:
            wire.append({"content_type": QUICK_REPLY_PHONE})
        else:
            wire.append(
                {
                    "content_type": QUICK_REPLY_TEXT,
                    "title": reply.title,
                    "payload": reply.payload or "",
                }
            )
    return wire


def _valid_https_url(url: str) -> bool:
    if not url or len(url) > MAX_BUTTON_URL_CHARS or any(ch.isspace() for ch in url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = parts.hostname or ""
    return parts.scheme == "https" and "." in host and not host.startswith(".")


def clean_buttons(items: Iterable[TemplateButton]) -> tuple[TemplateButton, ...]:
    """Validate and normalize 1–3 template buttons: titles on one line and unique,
    postback payloads `QFB_`-prefixed (`QFB_<slug>` by default, the prefix added when a
    given payload lacks it) and unique, `web_url` links https. Raises
    `InteractiveMessageError` naming the first problem."""
    buttons = list(items)
    if not buttons:
        raise InteractiveMessageError(ERR_BUTTONS_EMPTY)
    if len(buttons) > MAX_BUTTONS:
        raise InteractiveMessageError(ERR_BUTTONS_TOO_MANY)
    titles: set[str] = set()
    payloads: set[str] = set()
    cleaned: list[TemplateButton] = []
    for index, button in enumerate(buttons):
        if not isinstance(button, TemplateButton) or button.type not in BUTTON_TYPES:
            raise InteractiveMessageError(ERR_BUTTON_KIND_UNKNOWN, index=index)
        title = _one_line(button.title or "")
        if not title:
            raise InteractiveMessageError(ERR_BUTTON_TITLE_EMPTY, index=index)
        if len(title) > MAX_BUTTON_TITLE_CHARS:
            raise InteractiveMessageError(ERR_BUTTON_TITLE_TOO_LONG, index=index)
        if title.casefold() in titles:
            raise InteractiveMessageError(ERR_BUTTON_TITLE_REPEATED, index=index)
        titles.add(title.casefold())
        if button.type == BUTTON_WEB_URL:
            url = (button.url or "").strip()
            if not _valid_https_url(url):
                raise InteractiveMessageError(ERR_BUTTON_URL_INVALID, index=index)
            cleaned.append(TemplateButton.web_url(title, url))
            continue
        given = (button.payload or "").strip()
        if given and not given.startswith(PREFIX_TEMPLATE_BUTTON):
            given = f"{PREFIX_TEMPLATE_BUTTON}{given}"
        payload = given or _unique(f"{PREFIX_TEMPLATE_BUTTON}{payload_slug(title)}", payloads)
        payload = _check_payload(payload, ERR_BUTTON_PAYLOAD_TOO_LONG, index)
        payloads.add(payload)
        cleaned.append(TemplateButton.postback(title, payload))
    return tuple(cleaned)


def clean_button_text(text: str) -> str:
    """The text above the buttons, trimmed: 1–640 characters. A button template is one
    message and is never split."""
    body = text.strip()
    if not body:
        raise InteractiveMessageError(ERR_BUTTON_TEXT_EMPTY)
    if len(body) > MAX_BUTTON_TEMPLATE_TEXT_CHARS:
        raise InteractiveMessageError(ERR_BUTTON_TEXT_TOO_LONG)
    return body


def buttons_wire(buttons: Sequence[TemplateButton]) -> list[dict[str, str]]:
    """The `payload.buttons` array (also the JSON a template stores) for cleaned buttons."""
    wire: list[dict[str, str]] = []
    for button in buttons:
        if button.type == BUTTON_WEB_URL:
            wire.append({"type": BUTTON_WEB_URL, "url": button.url or "", "title": button.title})
        else:
            wire.append(
                {"type": BUTTON_POSTBACK, "title": button.title, "payload": button.payload or ""}
            )
    return wire


def button_template_message(text: str, buttons: Sequence[TemplateButton]) -> dict[str, Any]:
    """The `message` object of a button template, validating text and buttons."""
    return {
        "attachment": {
            "type": "template",
            "payload": {
                "template_type": TEMPLATE_TYPE_BUTTON,
                "text": clean_button_text(text),
                "buttons": buttons_wire(clean_buttons(buttons)),
            },
        }
    }


def buttons_from_json(raw: Any) -> tuple[TemplateButton, ...]:
    """Stored buttons (`buttons_wire`'s shape) back into records. Lenient on purpose:
    an item that is not an object of a known type is skipped, never raised — rows were
    validated on write, and a later, stricter rule must not make a library unreadable."""
    if not isinstance(raw, list):
        return ()
    buttons: list[TemplateButton] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        kind, title = item.get("type"), item.get("title")
        if not isinstance(title, str):
            continue
        if kind == BUTTON_WEB_URL and isinstance(item.get("url"), str):
            buttons.append(TemplateButton.web_url(title, item["url"]))
        elif kind == BUTTON_POSTBACK:
            payload = item.get("payload")
            buttons.append(
                TemplateButton.postback(title, payload if isinstance(payload, str) else None)
            )
    return tuple(buttons)


# --- reading a built wire body -----------------------------------------------------------


def _message_of(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    message = payload.get("message")
    return message if isinstance(message, Mapping) else None


def has_quick_replies(payload: Mapping[str, Any]) -> bool:
    """Whether a stored wire body carries quick replies (needs `quick_replies`)."""
    message = _message_of(payload)
    return bool(message and message.get("quick_replies"))


def template_payload(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """`message.attachment.payload` of a stored body whose attachment is a template."""
    message = _message_of(payload)
    attachment = message.get("attachment") if message else None
    if not isinstance(attachment, Mapping) or attachment.get("type") != "template":
        return None
    inner = attachment.get("payload")
    return inner if isinstance(inner, Mapping) else None


def is_structured_template(payload: Mapping[str, Any]) -> bool:
    """Whether a stored wire body is a template (needs `structured_templates`)."""
    return template_payload(payload) is not None


__all__ = [
    "BUTTON_POSTBACK",
    "BUTTON_TYPES",
    "BUTTON_WEB_URL",
    "MAX_BUTTONS",
    "MAX_BUTTON_TEMPLATE_TEXT_CHARS",
    "MAX_BUTTON_TITLE_CHARS",
    "MAX_QUICK_REPLIES",
    "MAX_QUICK_REPLY_TITLE_CHARS",
    "MESSAGES",
    "PREFIX_QUICK_REPLY",
    "QUICK_REPLY_CONTENT_TYPES",
    "QUICK_REPLY_PHONE",
    "QUICK_REPLY_TEXT",
    "InteractiveMessageError",
    "QuickReply",
    "TemplateButton",
    "button_template_message",
    "buttons_from_json",
    "buttons_wire",
    "clean_button_text",
    "clean_buttons",
    "clean_quick_replies",
    "has_quick_replies",
    "is_structured_template",
    "payload_slug",
    "quick_replies_wire",
    "template_payload",
]
