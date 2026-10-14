"""Typed shape contract for WhatsApp Cloud API **webhook notifications** (WA-03).

Same role `ig_shapes.py` plays for Instagram comments: the type the WhatsApp module
*imports* instead of re-deriving Meta's payload shape per call site. Strictly a
contract — parsing and validation only, no DB, no HTTP (this package's rule).

## What is `[V]` here, and against what

Unlike `ig_shapes.py`, which was fixed offline against a harvested corpus, the
`messages` half of this contract was fixed against a **live payload**: on
2026-10-14 the founder sent the panel's `Confirmación del pedido` test template from
the test number (`phone_number_id` `1393787420477981`, test WABA `2338576026889338`)
and Meta's own "Revisa los webhooks de prueba" panel displayed the resulting
`statuses` notification. That payload — phones redacted, nothing else touched — is
`packages/shared/tests/fixtures/whatsapp_status_read_live_2026-10-14.json`, and
`test_wa_shapes.py` parses it. Verified facts the live payload establishes:

- Envelope: `{"object": "whatsapp_business_account", "entry": [{"id": <WABA_ID>,
  "changes": [{"field": "messages", "value": {...}}]}]}`.
- `value.metadata.phone_number_id` is the routing key (which business number this
  is about); `value.metadata.display_phone_number` is digits only, no `+`.
- A `statuses[]` item carries `id` (the `wamid.` of the outbound message), `status`
  (`read` observed; `sent`/`delivered`/`failed` per the docs), `timestamp` as a
  **string** of epoch seconds, `recipient_id`, and — on billable messages — a
  `conversation{id, origin{type}}` and `pricing{billable, pricing_model, category,
  type}` block. `pricing_model` was `"PMP"` (per-message pricing, the model in force
  since 2025-07-01) and `category` `"utility"` for that template.
- Meta also ships an `internal_1p_only_data` object. Deliberately NOT modelled:
  undocumented, named as internal, and nothing here may come to depend on it.

The inbound `messages[]` half (a user writing to the business) is **not yet
observed live** — the test number cannot receive a real user message until a
recipient writes to it. Its shape below follows the official reference
(`messages` webhook, `text`/`interactive` message objects) and is marked
`provisional=True` in `FIELD_POLICIES`; the first live inbound payload promotes it,
same ritual `ig_shapes` followed for `GET /{media}/comments`.

## Non-`messages` fields

The app will also subscribe `message_template_status_update`,
`phone_number_quality_update`, `account_update`, `account_alerts`. Their `value`
objects have **different shapes** (no `metadata`, no `messages`). This contract keeps
`WAChange.value` as a raw mapping and exposes a typed view ONLY for
`field == "messages"` (`WAChange.messages_value()`); the other fields get their own
typed views when a consumer needs them and a live payload has been observed. A
notification carrying an unknown field must still parse — rejecting it would make
Meta retry for 7 days over nothing.

WA-18 added the first two such views, `WATemplateStatusUpdate` and
`WATemplateQualityUpdate` (`FIELD_TEMPLATE_STATUS` / `FIELD_TEMPLATE_QUALITY`). They
are **doc-derived and provisional** (no live capture yet): the fixtures
`whatsapp_template_status_*_doc.json` / `whatsapp_template_quality_doc.json` are the
reference page's own examples. The consumer validates `WAChange.value` against them.

NOT A TABLE SCHEMA. Nothing here names a column; migration `0046` (WA-04) decides
what persists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# Bumped when a field's name, type or nullability changes in a way that makes a
# consumer's assumptions wrong. Consumers record it alongside what they parsed
# (`messages.shape_version` already does this for the Instagram contract).
SHAPE_VERSION: Final = "wa-webhook-shapes-0.1.0"

OBJECT_WHATSAPP_BUSINESS_ACCOUNT: Final = "whatsapp_business_account"
FIELD_MESSAGES: Final = "messages"
FIELD_TEMPLATE_STATUS: Final = "message_template_status_update"
FIELD_TEMPLATE_QUALITY: Final = "message_template_quality_update"

# Which halves of this contract have been observed live. Data, not prose, so a test
# can assert the ritual was followed when a half is promoted.
FIELD_POLICIES: Final[dict[str, dict[str, Any]]] = {
    "statuses": {"provisional": False, "observed": "2026-10-14 live test template, status=read"},
    "messages": {"provisional": True, "observed": None},
    "contacts": {"provisional": False, "observed": "2026-10-14 (wa_id only; profile per docs)"},
    # WA-18: doc-derived from webhooks/reference/message_template_{status,quality}_update
    # (read 2026-10-14); the fixtures are the doc's own examples, not a capture.
    FIELD_TEMPLATE_STATUS: {"provisional": True, "observed": None},
    FIELD_TEMPLATE_QUALITY: {"provisional": True, "observed": None},
}


class _Shape(BaseModel):
    # Unknown keys are ignored, never rejected: Meta adds fields without a version
    # bump, and a stricter model would turn every such addition into 7 days of
    # retries. The raw body is what gets archived (R2, WA-07), not this projection.
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class WAMetadata(_Shape):
    display_phone_number: str
    phone_number_id: str


class WAContactProfile(_Shape):
    name: str | None = None


class WAContact(_Shape):
    wa_id: str
    profile: WAContactProfile | None = None


class WAText(_Shape):
    body: str


class WAInteractiveReply(_Shape):
    id: str
    title: str | None = None
    description: str | None = None


class WAInteractive(_Shape):
    """`interactive.type` is `button_reply` or `list_reply`; exactly one of the two
    reply objects is present. The `id` inside is the menu edge the WA-09 engine
    follows — it is the one field here that is load-bearing for routing."""

    type: str
    button_reply: WAInteractiveReply | None = None
    list_reply: WAInteractiveReply | None = None

    @property
    def reply(self) -> WAInteractiveReply | None:
        return self.button_reply or self.list_reply


class WAMessage(_Shape):
    """One inbound message. Provisional (see module docstring) — only `id`, `from`,
    `timestamp`, `type` are asserted required; everything type-specific is optional
    so an unmodelled type (`image`, `location`, `order`, `nfm_reply`…) still parses
    and reaches the sink with its `type` intact."""

    id: str
    from_: str = Field(alias="from")
    timestamp: str
    type: str
    text: WAText | None = None
    interactive: WAInteractive | None = None


class WAConversationOrigin(_Shape):
    type: str


class WAConversation(_Shape):
    id: str
    origin: WAConversationOrigin | None = None


class WAPricing(_Shape):
    billable: bool | None = None
    pricing_model: str | None = None
    category: str | None = None
    type: str | None = None


class WAError(_Shape):
    code: int | None = None
    title: str | None = None
    message: str | None = None


class WAStatus(_Shape):
    id: str
    status: str
    timestamp: str
    recipient_id: str
    conversation: WAConversation | None = None
    pricing: WAPricing | None = None
    errors: list[WAError] = Field(default_factory=list)


class WAMessagesValue(_Shape):
    """The `value` of a `field == "messages"` change. A single notification may carry
    `messages` OR `statuses` (the live one carried only `statuses`); both default to
    empty rather than `None` so consumers iterate without branching."""

    messaging_product: Literal["whatsapp"]
    metadata: WAMetadata
    contacts: list[WAContact] = Field(default_factory=list)
    messages: list[WAMessage] = Field(default_factory=list)
    statuses: list[WAStatus] = Field(default_factory=list)
    errors: list[WAError] = Field(default_factory=list)


def _id_as_str(value: Any) -> Any:
    """Meta sends `message_template_id` as a bare JSON integer in the webhook and as a
    numeric STRING in the Graph API; both become the same `str` here, so a template is
    matched by one spelling everywhere."""
    if isinstance(value, bool):  # bool is an int subclass — never a template id
        return value
    return str(value) if isinstance(value, int) else value


class WARejectionInfo(_Shape):
    reason: str | None = None
    recommendation: str | None = None


class WATemplateOtherInfo(_Shape):
    title: str | None = None
    description: str | None = None


class WATemplateStatusUpdate(_Shape):
    """The `value` of a `message_template_status_update` change (WA-18). Provisional,
    doc-derived (webhooks/reference/message_template_status_update, 2026-10-14).

    `event` is the template's new status (`APPROVED`, `REJECTED`, `PAUSED`, `DISABLED`,
    `PENDING_DELETION`, … — kept as a free string: Meta adds values). `reason` is the
    rejection enum (`NONE` when there is none; `null` when the template is scheduled for
    deletion). The template is keyed by `message_template_id` + the envelope's WABA id
    (`entry.id`) — this value carries no phone number."""

    event: str
    message_template_id: str
    message_template_name: str
    message_template_language: str
    reason: str | None = None
    message_template_category: str | None = None
    rejection_info: WARejectionInfo | None = None
    other_info: WATemplateOtherInfo | None = None
    disable_info: dict[str, Any] | None = None

    @field_validator("message_template_id", mode="before")
    @classmethod
    def _template_id(cls, value: Any) -> Any:
        return _id_as_str(value)


class WATemplateQualityUpdate(_Shape):
    """The `value` of a `message_template_quality_update` change (WA-18). Provisional,
    doc-derived. Scores: `GREEN`, `YELLOW`, `RED`, `UNKNOWN`."""

    previous_quality_score: str | None = None
    new_quality_score: str
    message_template_id: str
    message_template_name: str
    message_template_language: str

    @field_validator("message_template_id", mode="before")
    @classmethod
    def _template_id(cls, value: Any) -> Any:
        return _id_as_str(value)


class WAChange(_Shape):
    field: str
    value: dict[str, Any]

    def messages_value(self) -> WAMessagesValue | None:
        """Typed view of `value` iff this is a `messages` change; `None` for every
        other field. A `messages` change whose value does not fit the contract raises
        `ValidationError` — that is a contract break worth surfacing, not a soft `None`."""
        if self.field != FIELD_MESSAGES:
            return None
        return WAMessagesValue.model_validate(self.value)


class WAEntry(_Shape):
    id: str  # the WABA id
    changes: list[WAChange] = Field(default_factory=list)


class WANotification(_Shape):
    object: Literal["whatsapp_business_account"]
    entry: list[WAEntry] = Field(default_factory=list)


def parse_whatsapp_notification(payload: Any) -> WANotification:
    """Validate a decoded webhook body. Raises `pydantic.ValidationError` (a
    `ValueError` subclass) for anything that is not a WhatsApp Business Account
    notification — an Instagram or Page notification mistakenly routed here fails on
    `object`, which is the right place to fail."""
    return WANotification.model_validate(payload)


@dataclass(frozen=True)
class WAChangeSummary:
    """Log/metrics-safe projection of one change: identifiers and enumerations only,
    never message text, never a contact name. This is the ONLY shape the receiver may
    put in a log line (same discipline `CommentsReadError` set for Graph errors)."""

    waba_id: str
    field: str
    phone_number_id: str | None
    message_ids: tuple[str, ...]
    message_types: tuple[str, ...]
    status_ids: tuple[str, ...]
    statuses: tuple[str, ...]
    error_codes: tuple[int, ...]


def summarize_notification(notification: WANotification) -> tuple[WAChangeSummary, ...]:
    """One summary per change. Non-`messages` fields yield a summary with empty
    tuples and `phone_number_id=None`; a `messages` change whose value breaks the
    contract is reported with empty tuples too (and the `ValidationError` swallowed
    here) so one bad change never hides its siblings from the log."""
    out: list[WAChangeSummary] = []
    for entry in notification.entry:
        for change in entry.changes:
            try:
                value = change.messages_value()
            except ValidationError:
                value = None
            if value is None:
                out.append(
                    WAChangeSummary(
                        waba_id=entry.id,
                        field=change.field,
                        phone_number_id=None,
                        message_ids=(),
                        message_types=(),
                        status_ids=(),
                        statuses=(),
                        error_codes=(),
                    )
                )
                continue
            out.append(
                WAChangeSummary(
                    waba_id=entry.id,
                    field=change.field,
                    phone_number_id=value.metadata.phone_number_id,
                    message_ids=tuple(m.id for m in value.messages),
                    message_types=tuple(m.type for m in value.messages),
                    status_ids=tuple(s.id for s in value.statuses),
                    statuses=tuple(s.status for s in value.statuses),
                    error_codes=tuple(
                        e.code
                        for e in (*value.errors, *(err for s in value.statuses for err in s.errors))
                        if e.code is not None
                    ),
                )
            )
    return tuple(out)
