"""The WhatsApp Cloud API client seam (WA-06, QUA-206).

Same mould as `publishing/client.py` and `replies/client.py`: a `Protocol` the services
above depend on, one real HTTP implementation over an already-authenticated client, one
`_parse_*` function per endpoint marked with its evidence status, and an error type that
never carries a token, a response body or a user's text.

## Endpoints, as `docs/backlog-modulo-whatsapp.md` §2 WA-06 lists them

- `send_text`, `send_interactive_buttons`, `send_interactive_list`, `send_media`,
  `send_template` → `POST /{PHONE_NUMBER_ID}/messages`
- `mark_read` (+ typing indicator) → `POST /{PHONE_NUMBER_ID}/messages` (`status: read`)
- `upload_media` → `POST /{PHONE_NUMBER_ID}/media` (multipart)
- `media_url` → `GET /{MEDIA_ID}?phone_number_id=…`
- `download_media` → `GET <url>` (lookaside host, bearer header required)
- `get_phone_number` → `GET /{PHONE_NUMBER_ID}?fields=…`
- `get_business_profile`, `update_business_profile` →
  `GET/POST /{PHONE_NUMBER_ID}/whatsapp_business_profile`
- `get_conversational_automation` → `GET /{PHONE_NUMBER_ID}?fields=conversational_automation`
- `set_conversational_automation` → `POST /{PHONE_NUMBER_ID}/conversational_automation`
- `create_qr_code`, `list_qr_codes`, `delete_qr_code` →
  `POST/GET/DELETE /{PHONE_NUMBER_ID}/message_qrdls[/{code}]`

## Evidence status

Every request/response shape below is **doc-derived** (`[DOC]`), read on 2026-10-14 from
the pages cited on each `_parse_*` docstring. Nothing in this module has been exercised
against the test number yet — the smoke CLI (`qualify_api.whatsapp.smoke`) is the step
that promotes a parser to `[V]`, the same ritual `wa_shapes.FIELD_POLICIES` records for
the webhook half. When a live response disagrees with a parser, the parser is the one
place that moves.

## Limits are validated HERE, before a request costs anything

Meta rejects an over-long button title with an HTTP 400 after the round trip. Every
limit the docs publish (≤3 buttons, title ≤20, ≤10 rows, ice breakers ≤4/≤80 with no
emoji, commands ≤30 …) is checked in Python first and raised as `ValueError` with a
message that names the offending field — a validation failure is a programming error in
the caller, not a platform error, so it is deliberately NOT a `WhatsAppApiError`.

## What this module deliberately does NOT do

- **No token.** It receives an `AuthenticatedClient` from `CredentialResolver.client_for(
  connection_id, scheme="Bearer")` and never sees the credential (plan §6 rule: no
  WhatsApp module sees the system-user token).
- **No persistence, no window policy, no retries.** `whatsapp/outbox.py` (WA-08) owns
  retries/backoff and the 24-hour window; this module is a typed request builder plus a
  response parser, nothing more.
- **No degrade side effect.** A 401 / code 190 is reported through
  `WhatsAppApiError.is_auth_error`; the caller decides to invoke
  `connections.composition.degrade_connection_on_auth_error`, same posture as
  `publishing/service.py`.
- **No text in logs.** The exception's `str()` names the endpoint and numeric codes
  only; message bodies, captions and contact names never ride on it.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Protocol

import httpx

from qualify_api.connections.resolver import AuthenticatedClient

MESSAGING_PRODUCT: Final = "whatsapp"

# --- Meta-published limits, pinned with their source. ---------------------------------
# Interactive reply buttons (messages/interactive-reply-buttons-messages, 2026-10-14).
MAX_BUTTONS: Final = 3
MAX_BUTTON_TITLE_CHARS: Final = 20
MAX_BUTTON_ID_CHARS: Final = 256
MAX_BUTTONS_BODY_CHARS: Final = 1024
# Interactive list (messages/interactive-list-messages, 2026-10-14).
MAX_LIST_SECTIONS: Final = 10
MAX_LIST_ROWS_TOTAL: Final = 10
MAX_LIST_ROW_TITLE_CHARS: Final = 24
MAX_LIST_ROW_DESCRIPTION_CHARS: Final = 72
MAX_LIST_ROW_ID_CHARS: Final = 200
MAX_LIST_SECTION_TITLE_CHARS: Final = 24
MAX_LIST_BUTTON_LABEL_CHARS: Final = 20
MAX_LIST_BODY_CHARS: Final = 4096
# Shared by both interactive types.
MAX_INTERACTIVE_FOOTER_CHARS: Final = 60
MAX_INTERACTIVE_HEADER_CHARS: Final = 60
# Text messages: the public reference does not print a number on the page read on
# 2026-10-14; 4096 is the long-standing Cloud API limit and matches the list body cap.
MAX_TEXT_BODY_CHARS: Final = 4096
# Media captions (messages/image|video|document-messages, 2026-10-14).
MAX_MEDIA_CAPTION_CHARS: Final = 1024
# Conversational components (business-phone-numbers/conversational-components, 2026-10-14).
MAX_ICE_BREAKERS: Final = 4
MAX_ICE_BREAKER_CHARS: Final = 80
MAX_COMMANDS: Final = 30
MAX_COMMAND_NAME_CHARS: Final = 32
MAX_COMMAND_HINT_CHARS: Final = 256
# Business profile (cloud-api/reference/business-profiles, 2026-10-14).
MAX_PROFILE_ABOUT_CHARS: Final = 139
MAX_PROFILE_ADDRESS_CHARS: Final = 256
MAX_PROFILE_DESCRIPTION_CHARS: Final = 512
MAX_PROFILE_EMAIL_CHARS: Final = 128
MAX_PROFILE_WEBSITES: Final = 2
MAX_PROFILE_WEBSITE_CHARS: Final = 256
# QR codes (business-management-api/qr-codes, 2026-10-14).
MAX_QR_PREFILLED_MESSAGE_CHARS: Final = 140

MediaKind = Literal["image", "video", "document", "audio"]
QrImageFormat = Literal["PNG", "SVG"]

PHONE_NUMBER_FIELDS: Final = (
    "verified_name",
    "display_phone_number",
    "quality_rating",
    "messaging_limit_tier",
    "name_status",
    "status",
    "code_verification_status",
)
BUSINESS_PROFILE_FIELDS: Final = (
    "about",
    "address",
    "description",
    "email",
    "profile_picture_url",
    "websites",
    "vertical",
)


# ======================================================================================
# Errors
# ======================================================================================


class WhatsAppApiError(Exception):
    """A Cloud API call failed. Never carries the token, the response body or any text a
    user wrote — same discipline as `PublishError`/`CommentReplyError`.

    `status` is the HTTP status (`None` for a transport failure that never got a
    response); `code`/`subcode` are Meta's numeric `error.code`/`error.error_subcode`;
    `error_data_details` is Meta's own `error.error_data.details` string — Meta-authored
    diagnostic prose (e.g. the 24-hour-window refusal), NOT the message we tried to
    send. It is kept because it is the one field that tells a window refusal (131047)
    apart from a parameter error, and truncated so an unexpectedly chatty value cannot
    turn into a body dump.

    `is_transport` marks the ambiguous case `replies/client.py` names `is_ambiguous`: a
    timeout does not prove the message was not sent.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: int | None = None,
        subcode: int | None = None,
        error_data_details: str | None = None,
        is_transport: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.subcode = subcode
        self.error_data_details = error_data_details
        self.is_transport = is_transport

    @property
    def is_auth_error(self) -> bool:
        """HTTP 401 **or** code 190 — the same "or" `PublishError.http_status` exists to
        express (QUA-90): Meta's token rejection is not guaranteed to ride a 401."""
        return self.status == 401 or self.code == 190


# ======================================================================================
# Shapes
# ======================================================================================


@dataclass(frozen=True)
class ButtonSpec:
    """One reply button. `id` is what comes back as `interactive.button_reply.id` in the
    webhook (`wa_shapes.WAInteractiveReply.id`) — the menu edge WA-14 follows."""

    id: str
    title: str


@dataclass(frozen=True)
class ListRow:
    id: str
    title: str
    description: str | None = None


@dataclass(frozen=True)
class ListSection:
    rows: Sequence[ListRow]
    title: str | None = None


@dataclass(frozen=True)
class MediaInfo:
    """`GET /{MEDIA_ID}` — the `url` expires after 5 minutes (reference/media)."""

    id: str
    url: str
    mime_type: str | None
    sha256: str | None
    file_size: int | None


@dataclass(frozen=True)
class PhoneNumberInfo:
    """`GET /{PHONE_NUMBER_ID}?fields=…`. Every field but `id` is optional on the wire
    (Meta omits fields it has no value for), so every field but `id` is nullable here."""

    id: str
    verified_name: str | None
    display_phone_number: str | None
    quality_rating: str | None
    messaging_limit_tier: str | None
    name_status: str | None
    status: str | None
    code_verification_status: str | None


@dataclass(frozen=True)
class BusinessProfile:
    about: str | None
    address: str | None
    description: str | None
    email: str | None
    profile_picture_url: str | None
    websites: tuple[str, ...]
    vertical: str | None


@dataclass(frozen=True)
class BusinessProfileUpdate:
    """Only the fields set (non-`None`) are sent; Meta leaves the others untouched.
    `profile_picture_handle` comes from the Resumable Upload API, not from
    `upload_media` — out of scope here, accepted as an opaque string."""

    about: str | None = None
    address: str | None = None
    description: str | None = None
    email: str | None = None
    vertical: str | None = None
    websites: Sequence[str] | None = None
    profile_picture_handle: str | None = None


@dataclass(frozen=True)
class Command:
    """A `/command` the user can pick from the composer. `name` without the slash."""

    name: str
    hint: str


@dataclass(frozen=True)
class ConversationalAutomation:
    ice_breakers: list[str] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)
    enable_welcome_message: bool = False


@dataclass(frozen=True)
class QrCode:
    """`qr_image_url` is returned by create only; list/get omit it (qr-codes page)."""

    code: str
    prefilled_message: str
    deep_link_url: str
    qr_image_url: str | None = None


# ======================================================================================
# Protocol
# ======================================================================================


class WhatsAppClient(Protocol):
    """Every `send_*` returns the `wamid` Meta assigned (the same string that later
    arrives as `statuses[].id` in the webhook). Every method raises `WhatsAppApiError`
    for a platform/transport failure and `ValueError` for a request that would violate a
    published limit."""

    async def send_text(self, to: str, body: str, preview_url: bool = False) -> str: ...

    async def send_interactive_buttons(
        self,
        to: str,
        body: str,
        buttons: Sequence[ButtonSpec],
        header: str | None = None,
        footer: str | None = None,
    ) -> str: ...

    async def send_interactive_list(
        self,
        to: str,
        body: str,
        button_label: str,
        sections: Sequence[ListSection],
        header: str | None = None,
        footer: str | None = None,
    ) -> str: ...

    async def send_media(
        self,
        to: str,
        kind: MediaKind,
        *,
        media_id: str | None = None,
        link: str | None = None,
        caption: str | None = None,
        filename: str | None = None,
    ) -> str: ...

    async def send_template(
        self,
        to: str,
        name: str,
        language: str,
        components: list[dict[str, Any]] | None = None,
    ) -> str: ...

    async def mark_read(self, message_id: str, typing: bool = False) -> None: ...

    async def upload_media(self, content: bytes, content_type: str, filename: str) -> str: ...

    async def media_url(self, media_id: str) -> MediaInfo: ...

    async def download_media(self, url: str) -> bytes: ...

    async def get_phone_number(self) -> PhoneNumberInfo: ...

    async def get_business_profile(self) -> BusinessProfile: ...

    async def update_business_profile(self, profile: BusinessProfileUpdate) -> None: ...

    async def get_conversational_automation(self) -> ConversationalAutomation: ...

    async def set_conversational_automation(self, automation: ConversationalAutomation) -> None: ...

    async def create_qr_code(
        self, prefilled_message: str, image_format: QrImageFormat = "PNG"
    ) -> QrCode: ...

    async def list_qr_codes(self) -> list[QrCode]: ...

    async def delete_qr_code(self, code: str) -> None: ...


# ======================================================================================
# Limit validation (pure, raises ValueError)
# ======================================================================================


def _require_len(value: str, *, name: str, max_chars: int, required: bool = True) -> None:
    if required and not value:
        raise ValueError(f"{name} must not be empty")
    if len(value) > max_chars:
        raise ValueError(f"{name} exceeds {max_chars} characters (got {len(value)})")


def _contains_emoji(text: str) -> bool:
    """Meta's "emojis are not supported" for ice breakers/commands. Conservative: any
    symbol in the Unicode `So` category (where every pictographic emoji lives), a
    variation selector-16 or a ZWJ sequence marker counts. Letters in any script pass."""
    for ch in text:
        if ch in ("️", "‍"):
            return True
        if unicodedata.category(ch) == "So":
            return True
    return False


def _validate_text(body: str) -> None:
    _require_len(body, name="text body", max_chars=MAX_TEXT_BODY_CHARS)


def _validate_header_footer(header: str | None, footer: str | None) -> None:
    if header is not None:
        _require_len(header, name="header", max_chars=MAX_INTERACTIVE_HEADER_CHARS)
    if footer is not None:
        _require_len(footer, name="footer", max_chars=MAX_INTERACTIVE_FOOTER_CHARS)


def _validate_buttons(body: str, buttons: Sequence[ButtonSpec]) -> None:
    _require_len(body, name="buttons body", max_chars=MAX_BUTTONS_BODY_CHARS)
    if not 1 <= len(buttons) <= MAX_BUTTONS:
        raise ValueError(f"interactive buttons need 1..{MAX_BUTTONS} buttons (got {len(buttons)})")
    ids = [b.id for b in buttons]
    titles = [b.title for b in buttons]
    if len(set(ids)) != len(ids):
        raise ValueError("button ids must be unique")
    if len(set(titles)) != len(titles):
        raise ValueError("button titles must be unique")
    for b in buttons:
        _require_len(b.id, name="button id", max_chars=MAX_BUTTON_ID_CHARS)
        _require_len(b.title, name="button title", max_chars=MAX_BUTTON_TITLE_CHARS)


def _validate_list(body: str, button_label: str, sections: Sequence[ListSection]) -> None:
    _require_len(body, name="list body", max_chars=MAX_LIST_BODY_CHARS)
    _require_len(button_label, name="list button label", max_chars=MAX_LIST_BUTTON_LABEL_CHARS)
    if not 1 <= len(sections) <= MAX_LIST_SECTIONS:
        raise ValueError(
            f"interactive list needs 1..{MAX_LIST_SECTIONS} sections (got {len(sections)})"
        )
    total_rows = sum(len(s.rows) for s in sections)
    if not 1 <= total_rows <= MAX_LIST_ROWS_TOTAL:
        raise ValueError(
            f"interactive list needs 1..{MAX_LIST_ROWS_TOTAL} rows in total (got {total_rows})"
        )
    row_ids: list[str] = []
    for section in sections:
        if not section.rows:
            raise ValueError("every list section needs at least one row")
        if section.title is not None:
            _require_len(
                section.title, name="section title", max_chars=MAX_LIST_SECTION_TITLE_CHARS
            )
        elif len(sections) > 1:
            raise ValueError("section title is required when a list has more than one section")
        for row in section.rows:
            _require_len(row.id, name="row id", max_chars=MAX_LIST_ROW_ID_CHARS)
            _require_len(row.title, name="row title", max_chars=MAX_LIST_ROW_TITLE_CHARS)
            if row.description is not None:
                _require_len(
                    row.description,
                    name="row description",
                    max_chars=MAX_LIST_ROW_DESCRIPTION_CHARS,
                    required=False,
                )
            row_ids.append(row.id)
    if len(set(row_ids)) != len(row_ids):
        raise ValueError("row ids must be unique across sections")


def _validate_media(
    kind: MediaKind,
    *,
    media_id: str | None,
    link: str | None,
    caption: str | None,
    filename: str | None,
) -> None:
    if kind not in ("image", "video", "document", "audio"):
        raise ValueError(f"unsupported media kind {kind!r}")
    if (media_id is None) == (link is None):
        raise ValueError("exactly one of media_id or link is required")
    if caption is not None:
        if kind == "audio":
            raise ValueError("audio messages do not support a caption")
        _require_len(caption, name="caption", max_chars=MAX_MEDIA_CAPTION_CHARS, required=False)
    if filename is not None and kind != "document":
        raise ValueError("filename is only valid for document messages")


def _validate_automation(automation: ConversationalAutomation) -> None:
    if len(automation.ice_breakers) > MAX_ICE_BREAKERS:
        raise ValueError(
            f"at most {MAX_ICE_BREAKERS} ice breakers (got {len(automation.ice_breakers)})"
        )
    for prompt in automation.ice_breakers:
        _require_len(prompt, name="ice breaker", max_chars=MAX_ICE_BREAKER_CHARS)
        if _contains_emoji(prompt):
            raise ValueError("ice breakers do not support emoji")
    if len(automation.commands) > MAX_COMMANDS:
        raise ValueError(f"at most {MAX_COMMANDS} commands (got {len(automation.commands)})")
    names = [c.name for c in automation.commands]
    if len(set(names)) != len(names):
        raise ValueError("command names must be unique")
    for command in automation.commands:
        _require_len(command.name, name="command name", max_chars=MAX_COMMAND_NAME_CHARS)
        if command.name.startswith("/"):
            raise ValueError("command name must not include the leading slash")
        if " " in command.name:
            raise ValueError("command name must not contain spaces")
        _require_len(command.hint, name="command hint", max_chars=MAX_COMMAND_HINT_CHARS)
        if _contains_emoji(command.name) or _contains_emoji(command.hint):
            raise ValueError("commands do not support emoji")


def _validate_profile_update(profile: BusinessProfileUpdate) -> None:
    if profile.about is not None:
        _require_len(profile.about, name="about", max_chars=MAX_PROFILE_ABOUT_CHARS)
    if profile.address is not None:
        _require_len(
            profile.address, name="address", max_chars=MAX_PROFILE_ADDRESS_CHARS, required=False
        )
    if profile.description is not None:
        _require_len(
            profile.description,
            name="description",
            max_chars=MAX_PROFILE_DESCRIPTION_CHARS,
            required=False,
        )
    if profile.email is not None:
        _require_len(profile.email, name="email", max_chars=MAX_PROFILE_EMAIL_CHARS, required=False)
    if profile.websites is not None:
        if len(profile.websites) > MAX_PROFILE_WEBSITES:
            raise ValueError(f"at most {MAX_PROFILE_WEBSITES} websites")
        for site in profile.websites:
            _require_len(site, name="website", max_chars=MAX_PROFILE_WEBSITE_CHARS)
            if not (site.startswith("http://") or site.startswith("https://")):
                raise ValueError("websites must start with http:// or https://")


# ======================================================================================
# Request builders (pure; tests assert these bodies byte-for-byte)
# ======================================================================================


def _envelope(to: str, type_: str) -> dict[str, Any]:
    return {
        "messaging_product": MESSAGING_PRODUCT,
        "recipient_type": "individual",
        "to": to,
        "type": type_,
    }


def build_text_body(to: str, body: str, preview_url: bool) -> dict[str, Any]:
    """[DOC] messages/send-messages: `text{preview_url, body}`."""
    _validate_text(body)
    return {**_envelope(to, "text"), "text": {"preview_url": preview_url, "body": body}}


def build_buttons_body(
    to: str,
    body: str,
    buttons: Sequence[ButtonSpec],
    header: str | None,
    footer: str | None,
) -> dict[str, Any]:
    """[DOC] messages/interactive-reply-buttons-messages: `interactive{type:'button',
    header?, body{text}, footer?{text}, action{buttons[{type:'reply', reply{id,title}}]}}`.
    Header restricted to `type:'text'` here — media headers are not in WA-06's scope."""
    _validate_buttons(body, buttons)
    _validate_header_footer(header, footer)
    interactive: dict[str, Any] = {
        "type": "button",
        "body": {"text": body},
        "action": {
            "buttons": [{"type": "reply", "reply": {"id": b.id, "title": b.title}} for b in buttons]
        },
    }
    if header is not None:
        interactive["header"] = {"type": "text", "text": header}
    if footer is not None:
        interactive["footer"] = {"text": footer}
    return {**_envelope(to, "interactive"), "interactive": interactive}


def build_list_body(
    to: str,
    body: str,
    button_label: str,
    sections: Sequence[ListSection],
    header: str | None,
    footer: str | None,
) -> dict[str, Any]:
    """[DOC] messages/interactive-list-messages: `interactive{type:'list', header?{type:
    'text', text}, body{text}, footer?{text}, action{button, sections[{title?, rows[{id,
    title, description?}]}]}}`."""
    _validate_list(body, button_label, sections)
    _validate_header_footer(header, footer)
    wire_sections: list[dict[str, Any]] = []
    for section in sections:
        rows: list[dict[str, Any]] = []
        for row in section.rows:
            wire_row: dict[str, Any] = {"id": row.id, "title": row.title}
            if row.description is not None:
                wire_row["description"] = row.description
            rows.append(wire_row)
        wire_section: dict[str, Any] = {"rows": rows}
        if section.title is not None:
            wire_section["title"] = section.title
        wire_sections.append(wire_section)
    interactive: dict[str, Any] = {
        "type": "list",
        "body": {"text": body},
        "action": {"button": button_label, "sections": wire_sections},
    }
    if header is not None:
        interactive["header"] = {"type": "text", "text": header}
    if footer is not None:
        interactive["footer"] = {"text": footer}
    return {**_envelope(to, "interactive"), "interactive": interactive}


def build_media_body(
    to: str,
    kind: MediaKind,
    *,
    media_id: str | None,
    link: str | None,
    caption: str | None,
    filename: str | None,
) -> dict[str, Any]:
    """[DOC] messages/image|video|document|audio-messages: `<kind>{id | link, caption?,
    filename? (document only)}`; audio takes no caption. Meta recommends `id` over
    `link` — both are accepted, exactly one is required."""
    _validate_media(kind, media_id=media_id, link=link, caption=caption, filename=filename)
    media: dict[str, Any] = {}
    if media_id is not None:
        media["id"] = media_id
    if link is not None:
        media["link"] = link
    if caption is not None:
        media["caption"] = caption
    if filename is not None:
        media["filename"] = filename
    return {**_envelope(to, kind), kind: media}


def build_template_body(
    to: str, name: str, language: str, components: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """[DOC] templates: `template{name, language{code}, components?[]}`. `components` is
    passed through verbatim — template parameter shapes vary per template category and
    are WA-18's concern; this client does not interpret them."""
    if not name:
        raise ValueError("template name must not be empty")
    if not language:
        raise ValueError("template language code must not be empty")
    template: dict[str, Any] = {"name": name, "language": {"code": language}}
    if components:
        template["components"] = components
    return {**_envelope(to, "template"), "template": template}


def build_mark_read_body(message_id: str, typing: bool) -> dict[str, Any]:
    """[DOC] guides/mark-message-as-read + typing-indicators: `{messaging_product,
    status:'read', message_id, typing_indicator?{type:'text'}}`. The indicator is
    dismissed when we reply or after 25 s, whichever comes first."""
    if not message_id:
        raise ValueError("message_id must not be empty")
    payload: dict[str, Any] = {
        "messaging_product": MESSAGING_PRODUCT,
        "status": "read",
        "message_id": message_id,
    }
    if typing:
        payload["typing_indicator"] = {"type": "text"}
    return payload


def build_profile_update_body(profile: BusinessProfileUpdate) -> dict[str, Any]:
    """[DOC] reference/business-profiles POST: `messaging_product` plus only the fields
    being changed."""
    _validate_profile_update(profile)
    payload: dict[str, Any] = {"messaging_product": MESSAGING_PRODUCT}
    for key in ("about", "address", "description", "email", "vertical", "profile_picture_handle"):
        value = getattr(profile, key)
        if value is not None:
            payload[key] = value
    if profile.websites is not None:
        payload["websites"] = list(profile.websites)
    if len(payload) == 1:
        raise ValueError("business profile update carries no field to change")
    return payload


def build_automation_body(automation: ConversationalAutomation) -> dict[str, Any]:
    """[DOC] business-phone-numbers/conversational-components + the reference page:
    `{enable_welcome_message, prompts[], commands[{command_name, command_description}]}`.
    All three are always sent so a `set` is a full replacement, never a merge — the
    panel in WA-15 edits the whole set at once."""
    _validate_automation(automation)
    return {
        "enable_welcome_message": automation.enable_welcome_message,
        "prompts": list(automation.ice_breakers),
        "commands": [
            {"command_name": c.name, "command_description": c.hint} for c in automation.commands
        ],
    }


def build_qr_create_body(prefilled_message: str, image_format: QrImageFormat) -> dict[str, Any]:
    """[DOC] business-management-api/qr-codes: `{prefilled_message, generate_qr_image}`."""
    _require_len(
        prefilled_message, name="prefilled_message", max_chars=MAX_QR_PREFILLED_MESSAGE_CHARS
    )
    if image_format not in ("PNG", "SVG"):
        raise ValueError("image_format must be PNG or SVG")
    return {"prefilled_message": prefilled_message, "generate_qr_image": image_format}


# ======================================================================================
# [DOC] response parsing. One function per endpoint; the only place reality lands.
# ======================================================================================


def _error_fields(response: httpx.Response) -> tuple[int | None, int | None, str | None]:
    """Meta's numeric `error.code`/`error.error_subcode` and `error.error_data.details`
    from a failed response. Integers extracted defensively; `details` truncated. The
    `message`, `fbtrace_id` and anything else stay in the body, which is never kept."""
    try:
        error = dict(response.json()).get("error")
    except ValueError:
        return None, None, None
    if not isinstance(error, dict):
        return None, None, None
    code = error.get("code")
    subcode = error.get("error_subcode")
    details: str | None = None
    error_data = error.get("error_data")
    if isinstance(error_data, dict) and isinstance(error_data.get("details"), str):
        details = error_data["details"][:300]
    return (
        code if isinstance(code, int) else None,
        subcode if isinstance(subcode, int) else None,
        details,
    )


def _raise_for_status(response: httpx.Response, what: str) -> None:
    if response.status_code == 200:
        return
    code, subcode, details = _error_fields(response)
    raise WhatsAppApiError(
        f"{what} failed with HTTP {response.status_code} (code={code}, subcode={subcode})",
        status=response.status_code,
        code=code,
        subcode=subcode,
        error_data_details=details,
    )


def _parse_send_response(payload: dict[str, Any]) -> str:
    """[DOC] messages/send-messages: `{messaging_product, contacts[{input, wa_id}],
    messages[{id, message_status?}]}`. Returns `messages[0].id` — the `wamid`. The
    response means "accepted", not "delivered"; delivery arrives via `statuses[]`."""
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise WhatsAppApiError("send response carried no messages[]")
    first = messages[0]
    wamid = first.get("id") if isinstance(first, dict) else None
    if not isinstance(wamid, str) or not wamid:
        raise WhatsAppApiError("send response carried no message id")
    return wamid


def _parse_success(payload: dict[str, Any], what: str) -> None:
    """[DOC] `{"success": true}` — mark-read, business profile POST, conversational
    automation POST, media/QR DELETE all share it."""
    if payload.get("success") is not True:
        raise WhatsAppApiError(f"{what} did not report success=true")


def _parse_media_upload(payload: dict[str, Any]) -> str:
    """[DOC] reference/media POST: `{"id": "<MEDIA_ID>"}`; the id lives 30 days."""
    media_id = payload.get("id")
    if not isinstance(media_id, str) or not media_id:
        raise WhatsAppApiError("media upload response carried no id")
    return media_id


def _parse_media_info(payload: dict[str, Any]) -> MediaInfo:
    """[DOC] reference/media GET: `{messaging_product, url, mime_type, sha256,
    file_size, id}`; `url` expires after 5 minutes."""
    media_id = payload.get("id")
    url = payload.get("url")
    if not isinstance(media_id, str) or not isinstance(url, str) or not url:
        raise WhatsAppApiError("media info response carried no id/url")
    size = payload.get("file_size")
    if isinstance(size, str) and size.isdigit():
        size = int(size)
    return MediaInfo(
        id=media_id,
        url=url,
        mime_type=_opt_str(payload.get("mime_type")),
        sha256=_opt_str(payload.get("sha256")),
        file_size=size if isinstance(size, int) else None,
    )


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _parse_phone_number(payload: dict[str, Any]) -> PhoneNumberInfo:
    """[DOC] business-phone-numbers/phone-numbers: flat object keyed by the requested
    fields plus `id`. Enumerations (`GREEN`/`YELLOW`/`RED`/`NA`/`UNKNOWN`,
    `APPROVED`/`AVAILABLE_WITHOUT_REVIEW`/…, `CONNECTED`/…) are kept as strings — the
    page itself does not print a closed list for every one of them."""
    phone_id = payload.get("id")
    if not isinstance(phone_id, str) or not phone_id:
        raise WhatsAppApiError("phone number response carried no id")
    return PhoneNumberInfo(
        id=phone_id,
        verified_name=_opt_str(payload.get("verified_name")),
        display_phone_number=_opt_str(payload.get("display_phone_number")),
        quality_rating=_opt_str(payload.get("quality_rating")),
        messaging_limit_tier=_opt_str(payload.get("messaging_limit_tier")),
        name_status=_opt_str(payload.get("name_status")),
        status=_opt_str(payload.get("status")),
        code_verification_status=_opt_str(payload.get("code_verification_status")),
    )


def _parse_business_profile(payload: dict[str, Any]) -> BusinessProfile:
    """[DOC] reference/business-profiles GET: `{"data": [{about, address, description,
    email, messaging_product, profile_picture_url, websites[], vertical}]}` — one
    element, wrapped in a list."""
    data = payload.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise WhatsAppApiError("business profile response carried no data[0]")
    item = data[0]
    websites = item.get("websites")
    return BusinessProfile(
        about=_opt_str(item.get("about")),
        address=_opt_str(item.get("address")),
        description=_opt_str(item.get("description")),
        email=_opt_str(item.get("email")),
        profile_picture_url=_opt_str(item.get("profile_picture_url")),
        websites=tuple(w for w in websites if isinstance(w, str))
        if isinstance(websites, list)
        else (),
        vertical=_opt_str(item.get("vertical")),
    )


def _parse_conversational_automation(payload: dict[str, Any]) -> ConversationalAutomation:
    """[DOC] `GET /{PHONE_NUMBER_ID}?fields=conversational_automation`:
    `{conversational_automation{prompts[], commands[{command_name, command_description}],
    enable_welcome_message?}, id}`. A number with nothing configured answers without the
    nested object — that reads as an empty configuration, not as an error."""
    block = payload.get("conversational_automation")
    if not isinstance(block, dict):
        return ConversationalAutomation()
    prompts = block.get("prompts")
    commands_raw = block.get("commands")
    commands: list[Command] = []
    if isinstance(commands_raw, list):
        for item in commands_raw:
            if not isinstance(item, dict):
                continue
            name = item.get("command_name")
            hint = item.get("command_description")
            if isinstance(name, str):
                commands.append(Command(name=name, hint=hint if isinstance(hint, str) else ""))
    ice_breakers = [p for p in prompts if isinstance(p, str)] if isinstance(prompts, list) else []
    return ConversationalAutomation(
        ice_breakers=ice_breakers,
        commands=commands,
        enable_welcome_message=block.get("enable_welcome_message") is True,
    )


def _parse_qr_code(item: dict[str, Any]) -> QrCode:
    """[DOC] business-management-api/qr-codes: `{code, prefilled_message, deep_link_url,
    qr_image_url?}` — `qr_image_url` present on create only."""
    code = item.get("code")
    if not isinstance(code, str) or not code:
        raise WhatsAppApiError("QR code response carried no code")
    return QrCode(
        code=code,
        prefilled_message=_opt_str(item.get("prefilled_message")) or "",
        deep_link_url=_opt_str(item.get("deep_link_url")) or "",
        qr_image_url=_opt_str(item.get("qr_image_url")),
    )


def _parse_qr_list(payload: dict[str, Any]) -> list[QrCode]:
    """[DOC] `GET /{PHONE_NUMBER_ID}/message_qrdls`: `{"data": [ {code, …}, … ]}`."""
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [_parse_qr_code(item) for item in data if isinstance(item, dict)]


# ======================================================================================
# HTTP implementation
# ======================================================================================


class HttpWhatsAppClient:
    """Real client over one already-authenticated Graph client (`scheme="Bearer"` — the
    Cloud API is `graph.facebook.com` throughout; media downloads hit a `lookaside`
    host with the same bearer header, per reference/media).

    `phone_number_id` is bound at construction: every method in the table above is
    about one business number, and a client that took it per call would let a caller
    send from a number another tenant owns by passing the wrong id. `waba_id` is
    accepted for the WABA-level calls later stories add (templates, WA-18) and unused
    here."""

    def __init__(
        self,
        graph_client: AuthenticatedClient,
        graph_url: str,
        phone_number_id: str,
        waba_id: str | None = None,
    ) -> None:
        if not phone_number_id:
            raise ValueError("phone_number_id must not be empty")
        self._graph = graph_client
        self._graph_url = graph_url.rstrip("/")
        self._phone_number_id = phone_number_id
        self._waba_id = waba_id

    @property
    def phone_number_id(self) -> str:
        return self._phone_number_id

    # -- transport helpers ---------------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self._graph_url}/{path}"

    def _messages_url(self) -> str:
        return self._url(f"{self._phone_number_id}/messages")

    async def _post_json(self, url: str, payload: dict[str, Any], what: str) -> dict[str, Any]:
        try:
            response = await self._graph.post(url, json=payload)
        except httpx.TransportError as exc:
            raise WhatsAppApiError(f"transport failure during {what}", is_transport=True) from exc
        _raise_for_status(response, what)
        return _json_object(response, what)

    async def _get_json(
        self, url: str, what: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        try:
            response = await self._graph.get(url, params=params)
        except httpx.TransportError as exc:
            raise WhatsAppApiError(f"transport failure during {what}", is_transport=True) from exc
        _raise_for_status(response, what)
        return _json_object(response, what)

    async def _send(self, payload: dict[str, Any], what: str) -> str:
        return _parse_send_response(await self._post_json(self._messages_url(), payload, what))

    # -- messages ------------------------------------------------------------------------

    async def send_text(self, to: str, body: str, preview_url: bool = False) -> str:
        return await self._send(build_text_body(to, body, preview_url), "send_text")

    async def send_interactive_buttons(
        self,
        to: str,
        body: str,
        buttons: Sequence[ButtonSpec],
        header: str | None = None,
        footer: str | None = None,
    ) -> str:
        return await self._send(
            build_buttons_body(to, body, buttons, header, footer), "send_interactive_buttons"
        )

    async def send_interactive_list(
        self,
        to: str,
        body: str,
        button_label: str,
        sections: Sequence[ListSection],
        header: str | None = None,
        footer: str | None = None,
    ) -> str:
        return await self._send(
            build_list_body(to, body, button_label, sections, header, footer),
            "send_interactive_list",
        )

    async def send_media(
        self,
        to: str,
        kind: MediaKind,
        *,
        media_id: str | None = None,
        link: str | None = None,
        caption: str | None = None,
        filename: str | None = None,
    ) -> str:
        return await self._send(
            build_media_body(
                to, kind, media_id=media_id, link=link, caption=caption, filename=filename
            ),
            f"send_media[{kind}]",
        )

    async def send_template(
        self,
        to: str,
        name: str,
        language: str,
        components: list[dict[str, Any]] | None = None,
    ) -> str:
        return await self._send(
            build_template_body(to, name, language, components), "send_template"
        )

    async def mark_read(self, message_id: str, typing: bool = False) -> None:
        payload = await self._post_json(
            self._messages_url(), build_mark_read_body(message_id, typing), "mark_read"
        )
        _parse_success(payload, "mark_read")

    # -- media ---------------------------------------------------------------------------

    async def upload_media(self, content: bytes, content_type: str, filename: str) -> str:
        """Multipart `file` + `type` + `messaging_product` (reference/media). A MIME
        mismatch between `content_type` and the bytes is Meta error 131053 — the
        caller owns the declared type, this client does not sniff."""
        if not content:
            raise ValueError("media content must not be empty")
        if not content_type or "/" not in content_type:
            raise ValueError("content_type must be a MIME type like image/jpeg")
        try:
            response = await self._graph.post(
                self._url(f"{self._phone_number_id}/media"),
                data={"messaging_product": MESSAGING_PRODUCT, "type": content_type},
                files={"file": (filename, content, content_type)},
            )
        except httpx.TransportError as exc:
            raise WhatsAppApiError(
                "transport failure during upload_media", is_transport=True
            ) from exc
        _raise_for_status(response, "upload_media")
        return _parse_media_upload(_json_object(response, "upload_media"))

    async def media_url(self, media_id: str) -> MediaInfo:
        """`phone_number_id` is passed so Meta refuses a media id that was uploaded on
        another number — a free cross-tenant guard the reference documents."""
        if not media_id:
            raise ValueError("media_id must not be empty")
        payload = await self._get_json(
            self._url(media_id), "media_url", params={"phone_number_id": self._phone_number_id}
        )
        return _parse_media_info(payload)

    async def download_media(self, url: str) -> bytes:
        """`GET <url>` with the bearer header (the download fails without it). A 404
        usually means the 5-minute URL expired — the caller re-fetches `media_url`."""
        try:
            response = await self._graph.get(url)
        except httpx.TransportError as exc:
            raise WhatsAppApiError(
                "transport failure during download_media", is_transport=True
            ) from exc
        _raise_for_status(response, "download_media")
        return response.content

    # -- phone number --------------------------------------------------------------------

    async def get_phone_number(self) -> PhoneNumberInfo:
        payload = await self._get_json(
            self._url(self._phone_number_id),
            "get_phone_number",
            params={"fields": ",".join(PHONE_NUMBER_FIELDS)},
        )
        return _parse_phone_number(payload)

    # -- business profile ----------------------------------------------------------------

    async def get_business_profile(self) -> BusinessProfile:
        payload = await self._get_json(
            self._url(f"{self._phone_number_id}/whatsapp_business_profile"),
            "get_business_profile",
            params={"fields": ",".join(BUSINESS_PROFILE_FIELDS)},
        )
        return _parse_business_profile(payload)

    async def update_business_profile(self, profile: BusinessProfileUpdate) -> None:
        payload = await self._post_json(
            self._url(f"{self._phone_number_id}/whatsapp_business_profile"),
            build_profile_update_body(profile),
            "update_business_profile",
        )
        _parse_success(payload, "update_business_profile")

    # -- conversational automation -------------------------------------------------------

    async def get_conversational_automation(self) -> ConversationalAutomation:
        payload = await self._get_json(
            self._url(self._phone_number_id),
            "get_conversational_automation",
            params={"fields": "conversational_automation"},
        )
        return _parse_conversational_automation(payload)

    async def set_conversational_automation(self, automation: ConversationalAutomation) -> None:
        payload = await self._post_json(
            self._url(f"{self._phone_number_id}/conversational_automation"),
            build_automation_body(automation),
            "set_conversational_automation",
        )
        _parse_success(payload, "set_conversational_automation")

    # -- QR codes ------------------------------------------------------------------------

    async def create_qr_code(
        self, prefilled_message: str, image_format: QrImageFormat = "PNG"
    ) -> QrCode:
        payload = await self._post_json(
            self._url(f"{self._phone_number_id}/message_qrdls"),
            build_qr_create_body(prefilled_message, image_format),
            "create_qr_code",
        )
        return _parse_qr_code(payload)

    async def list_qr_codes(self) -> list[QrCode]:
        payload = await self._get_json(
            self._url(f"{self._phone_number_id}/message_qrdls"), "list_qr_codes"
        )
        return _parse_qr_list(payload)

    async def delete_qr_code(self, code: str) -> None:
        if not code:
            raise ValueError("code must not be empty")
        try:
            response = await self._graph.delete(
                self._url(f"{self._phone_number_id}/message_qrdls/{code}")
            )
        except httpx.TransportError as exc:
            raise WhatsAppApiError(
                "transport failure during delete_qr_code", is_transport=True
            ) from exc
        _raise_for_status(response, "delete_qr_code")
        _parse_success(_json_object(response, "delete_qr_code"), "delete_qr_code")


def _json_object(response: httpx.Response, what: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise WhatsAppApiError(f"{what} returned a non-JSON 200 body", status=200) from exc
    if not isinstance(payload, dict):
        raise WhatsAppApiError(f"{what} returned a non-object JSON body", status=200)
    return payload
