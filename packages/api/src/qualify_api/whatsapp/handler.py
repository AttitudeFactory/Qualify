"""The WhatsApp inbound handler of the intake processor (WA-07, QUA-207).

Registered in `webhooks.processor.production_processor` under
`WHATSAPP_MESSAGES_HANDLER_KEY` (`whatsapp_business_account:messages`), so an Instagram
DM change — also `field = "messages"` — never reaches it. One claimed change = one
`WAMessagesValue` (`qualify_shared.social.wa_shapes`), which carries `messages[]` (a
person wrote to the number), `statuses[]` (a receipt for something Qualify sent), or both.

What one change does, in order (plan §6.2):

1. Parse `event.value` against the contract → `dead(contract_violation)` if it does not
   fit (retrying cannot fix a shape).
2. Resolve `metadata.phone_number_id` → `(tenant_id, connection_id, phone_row_id)` through
   `whatsapp/resolve.py`. `ORPHAN` → settled `orphan`, **nothing written**: a number nobody
   connected can never become a row of any tenant.
3. For each inbound message: upsert the thread (`channel = 'whatsapp'`,
   `external_thread_id = wa_id`), insert the message by `wamid`. A duplicate insert (a
   replayed delivery, a reclaimed change) **skips the menu step** — the reply was already
   enqueued the first time. Otherwise, if the thread is not paused and `menu_loader`
   returns a published menu, run `menus.engine.step` and persist what it returns: the
   state to `whatsapp_thread_state`, the sends to `whatsapp_outbox` as already-built
   `POST /messages` bodies (`client.build_*_body`, `to = wa_id`, `kind = 'automation'`).
4. For each status: `apply_status` on the outbound row with that `wamid` (created by
   WA-08). A `wamid` with no row, or a status older than the stored one, is logged at
   debug and ignored — it is not an error of this change.
5. `processed`.

**Marketing hooks (WA-19/20), both optional and wired in production.** Between 3's insert
and the menu step, a text that is exactly `STOP`/`BAJA`/`CANCELAR`
(`optins.is_stop_keyword`) revokes the sender's opt-in through `opt_outs` and the menu is
skipped for it. In 4, every delivery status is also offered to `campaign_receipts` by
`wamid` (with Meta's `pricing.category`): a campaign send has no `messages` row.

**What is stored as `text`.** The body of a `text` message, the reply title of an
`interactive` reply, the caption of a media message that has one; `None` otherwise.
**What is stored about media (0061).** `media_type` for every non-text message (the
WhatsApp type, `other` for one outside 0061's CHECKed list), plus `media_id`/`media_mime`
for image/audio/video/document/sticker (`message_media`). Only the id is kept here — the
bytes are downloaded lazily, on the first request, by `whatsapp.media.
CapturingMediaLocator` (Meta's id lives ~30 days; nothing downloads at webhook time, so
the intake never waits on Meta's media host). `raw_payload_r2_key` stays `None`: the raw
change is in `meta_webhook_deliveries`/`meta_webhook_events`.

**Reserved context keys.** A `Handoff` leaves its reason and structured summary under
`CTX_HANDOFF` in `context` (no new `messages` row is invented for it). When that handoff
carries a confirmed order (`summary["order_confirmed"] is True`), WA-15 also stores the
order a person prepares under `orders.CTX_ORDER_RECORD` (`_order`, keyed on the inbound
`wamid` that confirmed it) and clears the engine's working `order`/`order_confirmed`, so
a conversation resumed later starts a new order. Both keys start with `_` so they never
collide with the engine's own `order`/`collected`/…. The engine's unknown-input counter
is NOT in `context`: it is the `whatsapp_thread_state.attempts` column 0058 added
(`StoredThreadState.attempts`).
`CTX_ATTEMPTS` survives only as a read-once shim for rows a pre-0058 build of this
handler wrote; nothing writes it any more.

**The menu.** `menu_loader(phone_row_id)` is `menus.load_published_menu_for_phone` in
production (`tuple[MenuDefinition, UUID] | None` — the live definition and the
`whatsapp_menu_versions.id` recorded on the thread; `None` when the number has no
published menu or it is paused). A test may also return a `PublishedMenu` directly, e.g.
around `examples.BIANKI_DEMO_MENU` with no version row.

**Menu version change.** When the stored `menu_version_id` differs from the loaded one,
`node_id` is reset (the conversation re-enters the new menu at its start on the next
unrecognized input) and `context` — the order being built — is kept.

**Ordering and crashes.** Each repository call is its own transaction. The message lands
before the menu runs; the state is saved before the outbox rows are inserted. A crash
between any two leaves the message persisted and the replay idempotent (duplicate →
skip), at the cost of at most one automated reply.

No `mark_read` here: the sender (WA-08) marks the inbound read when it answers.

Logging discipline is `wa_shapes.WAChangeSummary`'s: ids, types and enumerations only —
never a message body, never a contact name.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from uuid import UUID

from pydantic import ValidationError
from qualify_shared.social.wa_shapes import (
    FIELD_MESSAGES,
    OBJECT_WHATSAPP_BUSINESS_ACCOUNT,
    SHAPE_VERSION,
    WAMessage,
    WAMessagesValue,
    WAStatus,
)

from qualify_api.webhooks.processor import Handler, Outcome, handler_key
from qualify_api.webhooks.repository import (
    STATUS_DEAD,
    STATUS_ORPHAN,
    STATUS_PROCESSED,
    ClaimedEvent,
)
from qualify_api.whatsapp.client import (
    ButtonSpec,
    ListRow,
    ListSection,
    build_buttons_body,
    build_list_body,
    build_text_body,
)
from qualify_api.whatsapp.menus.engine import (
    CTX_ORDER,
    CTX_ORDER_CONFIRMED,
    CatalogItem,
    Handoff,
    OutboundAction,
    SendButtons,
    SendList,
    SendText,
    SetContext,
    ThreadMenuState,
    inbound_from_message,
    step,
)
from qualify_api.whatsapp.menus.schema import MenuDefinition
from qualify_api.whatsapp.models import DELIVERY_STATUSES, MEDIA_TYPE_OTHER, MEDIA_TYPES
from qualify_api.whatsapp.optins import (
    REVOKE_REASON_STOP,
    OptOutRepository,
    is_stop_keyword,
    phone_from_wa_id,
)
from qualify_api.whatsapp.orders import record_confirmed_order
from qualify_api.whatsapp.repository import (
    OUTBOX_KIND_AUTOMATION,
    StoredThreadState,
    WhatsAppInboxRepository,
)
from qualify_api.whatsapp.resolve import PhoneResolution, PhoneResolutionOutcome

logger = logging.getLogger("qualify_api.whatsapp.handler")

WHATSAPP_MESSAGES_HANDLER_KEY: Final = handler_key(OBJECT_WHATSAPP_BUSINESS_ACCOUNT, FIELD_MESSAGES)

# Reserved key inside `whatsapp_thread_state.context` (see the module docstring).
CTX_HANDOFF: Final = "_handoff"
# Pre-0058 shim: where this handler kept `attempts` before the column existed. Read once
# when the column is still 0, dropped on the next save, never written.
CTX_ATTEMPTS: Final = "_attempts"


@dataclass(frozen=True)
class PublishedMenu:
    """What `menu_loader` returns for a number that has a published menu: the validated
    definition and the `whatsapp_menu_versions.id` it came from (`None` only for a menu
    that lives nowhere, e.g. `examples.BIANKI_DEMO_MENU` in a test)."""

    definition: MenuDefinition
    version_id: UUID | None = None

    @classmethod
    def coerce(
        cls, loaded: tuple[MenuDefinition, UUID] | PublishedMenu | None
    ) -> PublishedMenu | None:
        """Accept what `menus.load_published_menu_for_phone` returns, or an instance."""
        if loaded is None or isinstance(loaded, PublishedMenu):
            return loaded
        definition, version_id = loaded
        return cls(definition=definition, version_id=version_id)


PhoneResolver = Callable[[str], PhoneResolution]
# By `phone_row_id`; the production implementation is `menus.load_published_menu_for_phone`.
MenuLoader = Callable[[UUID], "tuple[MenuDefinition, UUID] | PublishedMenu | None"]
CatalogLoader = Callable[[UUID], Sequence[CatalogItem]]  # by `phone_row_id`
Clock = Callable[[], datetime]


class CampaignReceiptSink(Protocol):
    """WA-20: `campaigns.PostgresCampaignReceiptRepository` in production."""

    def apply_receipt(
        self,
        *,
        tenant_id: UUID,
        wamid: str,
        status: str,
        error_code: str | None,
        price_category: str | None,
    ) -> bool: ...


def no_menu(phone_row_id: UUID) -> tuple[MenuDefinition, UUID] | PublishedMenu | None:
    """The offline default: no number has a menu (production passes
    `menus.load_published_menu_for_phone`)."""
    return None


def no_catalog(phone_row_id: UUID) -> Sequence[CatalogItem]:
    """The offline default: an empty catalog (production passes
    `whatsapp.catalog.load_catalog_for_phone`, WA-15)."""
    return ()


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --- engine state <-> stored row ----------------------------------------------------------


def menu_state_from_stored(stored: StoredThreadState | None) -> ThreadMenuState:
    """The engine's view of a stored row. `attempts` is the 0058 column; a row written
    by the pre-0058 shim (counter under `CTX_ATTEMPTS`, column still 0) is read once.
    The reserved keys stay in `context` — the engine ignores keys it does not own."""
    if stored is None:
        return ThreadMenuState()
    attempts = stored.attempts
    if attempts == 0:
        legacy = stored.context.get(CTX_ATTEMPTS, 0)
        attempts = legacy if isinstance(legacy, int) and legacy > 0 else 0
    return ThreadMenuState(
        node_id=stored.node_id,
        context=dict(stored.context),
        paused=stored.paused_at is not None,
        attempts=attempts,
    )


def stored_context(state: ThreadMenuState) -> dict[str, Any]:
    """`state.context` as it is persisted: the pre-0058 shim key is dropped (the counter
    lives in `StoredThreadState.attempts` now)."""
    context = dict(state.context)
    context.pop(CTX_ATTEMPTS, None)
    return context


# --- projections -----------------------------------------------------------------------


def message_text(message: WAMessage) -> str | None:
    """What goes in `messages.text`: the body of a text, the title of an interactive reply,
    the caption of a media message that has one; `None` for everything else (the type is
    in `media_type` — `message_media`)."""
    if message.type == "text" and message.text is not None:
        return message.text.body
    if message.type == "interactive" and message.interactive is not None:
        reply = message.interactive.reply
        if reply is not None:
            return reply.title
    media = message.media
    if media is not None and media.caption:
        return media.caption
    return None


@dataclass(frozen=True)
class InboundMedia:
    """What 0061 persists about a message's type and media. All `None` for a text."""

    media_type: str | None = None
    media_id: str | None = None
    media_mime: str | None = None


def message_media(message: WAMessage) -> InboundMedia:
    """`messages.media_type` / `media_id` / `media_mime` for one inbound message.

    `media_type` is set for EVERY non-text message — a type outside 0061's CHECKed list
    (`reaction`, `system`, `unsupported`, whatever Meta adds next) becomes `other`, never
    an INSERT failure that Meta would retry for 7 days. `media_id`/`media_mime` only for
    the five downloadable types, and only when Meta sent the object."""
    if message.type == "text":
        return InboundMedia()
    media_type = message.type if message.type in MEDIA_TYPES else MEDIA_TYPE_OTHER
    media = message.media
    if media is None:
        return InboundMedia(media_type=media_type)
    return InboundMedia(media_type=media_type, media_id=media.id, media_mime=media.mime_type)


def epoch_to_datetime(timestamp: str) -> datetime | None:
    """Meta's `timestamp` is a string of epoch seconds; anything else yields `None`
    rather than failing the whole change."""
    try:
        return datetime.fromtimestamp(int(timestamp), UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def outbox_payload(action: OutboundAction, *, to: str) -> dict[str, Any] | None:
    """The `POST /messages` body for a send action; `None` for the non-send ones
    (`Handoff`, `SetContext`). Raises `ValueError` if the body breaks a Cloud API limit —
    a published menu cannot (the schema validates them), so that is a bug worth a retry
    trail, not a silent skip."""
    if isinstance(action, SendText):
        return build_text_body(to, action.body, False)
    if isinstance(action, SendButtons):
        return build_buttons_body(
            to,
            action.body,
            [ButtonSpec(b.id, b.title) for b in action.buttons],
            action.header,
            action.footer,
        )
    if isinstance(action, SendList):
        return build_list_body(
            to,
            action.body,
            action.button_label,
            [
                ListSection(
                    rows=[ListRow(r.id, r.title, r.description) for r in s.rows], title=s.title
                )
                for s in action.sections
            ],
            action.header,
            action.footer,
        )
    return None


# --- the handler -----------------------------------------------------------------------


class _ChangeContext:
    """Per-change scratch: the resolution plus the menu and catalog, loaded at most once."""

    def __init__(
        self,
        *,
        resolution: PhoneResolution,
        menu_loader: MenuLoader,
        catalog_loader: CatalogLoader,
    ) -> None:
        assert resolution.tenant_id is not None
        assert resolution.connection_id is not None
        assert resolution.phone_row_id is not None
        self.tenant_id: UUID = resolution.tenant_id
        self.connection_id: UUID = resolution.connection_id
        self.phone_row_id: UUID = resolution.phone_row_id
        self._menu_loader = menu_loader
        self._catalog_loader = catalog_loader
        self._menu: PublishedMenu | None = None
        self._menu_loaded = False
        self._catalog: Sequence[CatalogItem] | None = None

    def menu(self) -> PublishedMenu | None:
        if not self._menu_loaded:
            self._menu = PublishedMenu.coerce(self._menu_loader(self.phone_row_id))
            self._menu_loaded = True
        return self._menu

    def catalog(self) -> Sequence[CatalogItem]:
        if self._catalog is None:
            self._catalog = tuple(self._catalog_loader(self.phone_row_id))
        return self._catalog


def whatsapp_messages_handler(
    *,
    resolve: PhoneResolver,
    repo: WhatsAppInboxRepository,
    menu_loader: MenuLoader = no_menu,
    catalog_loader: CatalogLoader = no_catalog,
    clock: Clock = _utcnow,
    opt_outs: OptOutRepository | None = None,
    campaign_receipts: CampaignReceiptSink | None = None,
) -> Handler:
    """Build the handler. Everything that touches the database runs in a worker thread
    (`asyncio.to_thread`), as `mentions_handler` does for its sync reads.

    `opt_outs` (WA-19): when given, an inbound text that `optins.is_stop_keyword` matches
    revokes that phone's opt-in and the menu is NOT stepped for it (an opt-out is not a
    menu input). `campaign_receipts` (WA-20): when given, every delivery status is also
    offered to it, keyed by `wamid` — campaign sends have no `messages` row, so
    `apply_status` alone never sees them. Both default to off (production wires both)."""

    def _automate(ctx: _ChangeContext, *, thread_id: UUID, message: WAMessage, first: bool) -> None:
        stored = repo.get_thread_state(thread_id)
        if stored is not None and stored.paused_at is not None:
            return
        menu = ctx.menu()
        if menu is None:
            return
        state = menu_state_from_stored(stored)
        if stored is not None and stored.menu_version_id != menu.version_id:
            state = replace(state, node_id=None, attempts=0)
        inbound = inbound_from_message(message, first_message=first)
        result = step(menu.definition, state, inbound, catalog=ctx.catalog())

        context = stored_context(result.state)
        payloads: list[dict[str, Any]] = []
        for action in result.actions:
            if isinstance(action, Handoff):
                at = clock()
                context[CTX_HANDOFF] = {
                    "reason": action.reason,
                    "summary": action.summary,
                    "at": at.isoformat(),
                }
                if action.summary.get("order_confirmed") is True:
                    # WA-15: the confirmed order becomes the record a person reads; the
                    # engine's working order is closed so a resumed chat starts anew.
                    record_confirmed_order(
                        context, action.summary, confirmed_at=at, source_message_id=message.id
                    )
                    context.pop(CTX_ORDER, None)
                    context.pop(CTX_ORDER_CONFIRMED, None)
                continue
            if isinstance(action, SetContext):
                continue
            payload = outbox_payload(action, to=message.from_)
            if payload is not None:
                payloads.append(payload)

        repo.save_thread_state(
            thread_id=thread_id,
            tenant_id=ctx.tenant_id,
            state=StoredThreadState(
                menu_version_id=menu.version_id,
                node_id=result.state.node_id,
                context=context,
                paused_at=clock() if result.state.paused else None,
                attempts=result.state.attempts,
            ),
        )
        for payload in payloads:
            repo.enqueue_outbox(
                tenant_id=ctx.tenant_id,
                connection_id=ctx.connection_id,
                thread_id=thread_id,
                kind=OUTBOX_KIND_AUTOMATION,
                payload=payload,
            )
        logger.info(
            "whatsapp webhook: tenant=%s thread=%s message_type=%s menu node=%s sends=%d "
            "handed_off=%s",
            ctx.tenant_id,
            thread_id,
            message.type,
            result.state.node_id,
            len(payloads),
            result.handed_off,
        )

    def _is_opt_out(message: WAMessage) -> bool:
        return message.type == "text" and is_stop_keyword(message_text(message))

    def _revoke(ctx: _ChangeContext, message: WAMessage) -> None:
        assert opt_outs is not None
        try:
            phone = phone_from_wa_id(message.from_)
        except ValueError:
            logger.warning(
                "whatsapp webhook: tenant=%s wamid=%s opt-out from a non-E.164 sender ignored",
                ctx.tenant_id,
                message.id,
            )
            return
        revoked = opt_outs.revoke(
            tenant_id=ctx.tenant_id,
            phone_e164=phone,
            at=epoch_to_datetime(message.timestamp) or clock(),
            reason=REVOKE_REASON_STOP,
        )
        logger.info(
            "whatsapp webhook: tenant=%s wamid=%s stop keyword — opt-in revoked=%s, menu skipped",
            ctx.tenant_id,
            message.id,
            revoked,
        )

    def _inbound(ctx: _ChangeContext, value: WAMessagesValue) -> None:
        names = {
            c.wa_id: c.profile.name
            for c in value.contacts
            if c.profile is not None and c.profile.name
        }
        for message in value.messages:
            posted_at = epoch_to_datetime(message.timestamp)
            media = message_media(message)
            upsert = repo.upsert_thread(
                tenant_id=ctx.tenant_id,
                connection_id=ctx.connection_id,
                wa_id=message.from_,
                inbound_at=posted_at or clock(),
            )
            inserted = repo.insert_inbound_message(
                tenant_id=ctx.tenant_id,
                thread_id=upsert.thread_id,
                connection_id=ctx.connection_id,
                external_message_id=message.id,
                author_external_id=message.from_,
                author_username=names.get(message.from_),
                text=message_text(message),
                posted_at=posted_at,
                shape_version=SHAPE_VERSION,
                media_type=media.media_type,
                media_id=media.media_id,
                media_mime=media.media_mime,
            )
            if not inserted:
                logger.debug(
                    "whatsapp webhook: tenant=%s thread=%s wamid=%s already stored — menu skipped",
                    ctx.tenant_id,
                    upsert.thread_id,
                    message.id,
                )
                continue
            if opt_outs is not None and _is_opt_out(message):
                _revoke(ctx, message)
                continue
            _automate(ctx, thread_id=upsert.thread_id, message=message, first=upsert.created)

    def _receipts(ctx: _ChangeContext, statuses: Sequence[WAStatus]) -> None:
        for status in statuses:
            if status.status not in DELIVERY_STATUSES:
                logger.debug(
                    "whatsapp webhook: tenant=%s wamid=%s status=%s is not a delivery status",
                    ctx.tenant_id,
                    status.id,
                    status.status,
                )
                continue
            error_code = next((str(e.code) for e in status.errors if e.code is not None), None)
            if campaign_receipts is not None:
                campaign_receipts.apply_receipt(
                    tenant_id=ctx.tenant_id,
                    wamid=status.id,
                    status=status.status,
                    error_code=error_code,
                    price_category=status.pricing.category if status.pricing else None,
                )
            applied = repo.apply_status(
                connection_id=ctx.connection_id,
                external_message_id=status.id,
                status=status.status,
                error_code=error_code,
            )
            if not applied:
                logger.debug(
                    "whatsapp webhook: tenant=%s wamid=%s status=%s not applied "
                    "(no outbound row yet, or an older receipt)",
                    ctx.tenant_id,
                    status.id,
                    status.status,
                )

    def _process(event: ClaimedEvent, value: WAMessagesValue) -> Outcome:
        resolution = resolve(value.metadata.phone_number_id)
        if resolution.outcome is not PhoneResolutionOutcome.RESOLVED:
            logger.warning(
                "whatsapp webhook: event=%s orphan change, no connected number for "
                "phone_number_id=%s — not persisted",
                event.id,
                value.metadata.phone_number_id,
            )
            return Outcome(STATUS_ORPHAN)
        ctx = _ChangeContext(
            resolution=resolution, menu_loader=menu_loader, catalog_loader=catalog_loader
        )
        _inbound(ctx, value)
        _receipts(ctx, value.statuses)
        return Outcome(STATUS_PROCESSED)

    async def handle(event: ClaimedEvent) -> Outcome:
        try:
            value = WAMessagesValue.model_validate(event.value or {})
        except ValidationError:
            logger.error("whatsapp webhook: event=%s messages value off-contract", event.id)
            return Outcome(STATUS_DEAD, "contract_violation")
        return await asyncio.to_thread(_process, event, value)

    return handle


__all__ = [
    "CTX_ATTEMPTS",
    "CampaignReceiptSink",
    "CTX_HANDOFF",
    "WHATSAPP_MESSAGES_HANDLER_KEY",
    "CatalogLoader",
    "Clock",
    "MenuLoader",
    "PhoneResolver",
    "PublishedMenu",
    "InboundMedia",
    "epoch_to_datetime",
    "menu_state_from_stored",
    "message_media",
    "message_text",
    "no_catalog",
    "no_menu",
    "outbox_payload",
    "stored_context",
    "whatsapp_messages_handler",
]
