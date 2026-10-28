"""The Meegle handlers of the webhook processor (plan §3: "un handler nuevo por evento,
mismo contrato `Outcome`").

Registered under `meegle:<event_type>` (`webhooks.processor.handler_key`), so they see
only what `qualify_api.meegle.receiver` recorded. One recorded event is routed by the
WORK ITEM TYPE it names, after a prelude every route shares:

1. the recorded value must be `{"source": …, "data": {…}}` with the documented shape →
   otherwise `dead` (`contract_violation`);
2. `source == "openapi"` is Qualify's own write-back → settled `processed`
   (`ignored:openapi`), so the engine never reacts to itself — including to the writes the
   ticket notifier may one day make;
3. no work item id in the event → `dead`;
4. the configured "Alta de cliente" type → the onboarding handlers below; a ticket type
   (`TicketSettings.ticket_types`: Features / Issues / Tasks) → the ticket notifier, when
   one is configured; anything else → `unsupported` (`other_work_item_type`): the plugin
   may be subscribed more widely than the engine; kept, never acted on, replayable.

Onboarding, per event (plan §2):

- **2001 node completed** — the completed node is named through the item's workflow
  (`SchemaResolver.node_name`; the event carries the template node key, e.g. `state_0`).
  Only **Datos** triggers `OnboardingEngine.start_invitation`; any other node is
  `processed` (`ignored:node=<name>`). An invitation that could not be sent for a reason
  the person must fix (bad email, mail refused) is ALSO `processed`, with
  `invite_failed:<reason>` in `last_error`: the item itself shows the error and the node
  is rolled back — retrying the event would only repeat the same failure.
  After a SENT invitation, and only then, the Brand Kit prefill is scheduled
  (`prefill.AltaPrefillScheduler.schedule`, PB-4 m-24852198): a reserved draft and one
  queued job, run later by the same worker. Whatever it does or raises never changes the
  event's outcome into a retry — a retry would send the invitation again — so it is
  swallowed and logged; with the prefill on, its label rides in `last_error`
  (`prefill=<label>`) of the `processed` event.
  **Plan ampliado** (m-24852131) triggers `OnboardingEngine.apply_plan_update` with the
  event's `idempotent_key` (the idempotency of the plan and the pack) and who completed
  it: `processed` with `plan=applied` / `plan=pending_registration`, or `processed` with
  `plan_failed:<reason>` when the item shows the error and the node was rolled back.
- **1005 terminated** — `expire_for_terminated`.
- **2004 rolled back** — nothing (`ignored:rollback`).
- **1001 / 1009 / 3001** on the onboarding type — nothing to do (`processed`,
  `ignored:event`): the plugin subscribes to them for the ticket types, Meegle sends them
  per type, but a wider subscription must not burn retries.

Tickets (plan §3bis), every event the plugin delivers for a ticket type — `1001` created,
`1009` field modified, `3001` status changed, `2001` / `2004` node completed / rolled
back, `1005` terminated: `TicketNotifier.notify` re-reads the item, formats who · what ·
item · link and posts it to the Lark group. `processed` (`sent`), or `processed` with
`lark_rejected:<code>` when Lark refused the message for good; a vanished item is `dead`.

Anything else raised (Meegle unreachable, a schema name missing, Lark down, the database)
propagates: the processor retries with backoff and settles `dead` after `MAX_ATTEMPTS`.

`production_meegle_handlers()` returns `{}` when the engine is off (`meegle_configured()`
false), so an unconfigured deployment leaves Meegle events `unsupported` in the queue —
replayable the day it is configured — instead of burning retries on
`MeegleNotConfigured`. With the engine on and `QUALIFY_MEEGLE_NOTIFY_WEBHOOK_URL` unset,
ticket events stay `unsupported` the same way.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from functools import partial
from typing import TYPE_CHECKING, Protocol

from pydantic import ValidationError

from qualify_api.meegle.envelope import (
    EVENT_FIELD_MODIFIED,
    EVENT_NODE_COMPLETED,
    EVENT_NODE_ROLLED_BACK,
    EVENT_STATUS_CHANGED,
    EVENT_WORK_ITEM_CREATED,
    EVENT_WORK_ITEM_TERMINATED,
    OBJECT_MEEGLE,
)
from qualify_api.meegle.events import MeegleEvent
from qualify_api.meegle.onboarding import InvitationResult, OnboardingEngine, WorkItemNotFound
from qualify_api.meegle.settings import MeegleNames
from qualify_api.webhooks.processor import Handler, Outcome, handler_key
from qualify_api.webhooks.repository import (
    STATUS_DEAD,
    STATUS_PROCESSED,
    STATUS_UNSUPPORTED,
    ClaimedEvent,
)

if TYPE_CHECKING:
    from qualify_api.meegle.client import MeegleClient
    from qualify_api.meegle.prefill import AltaPrefillRunner

logger = logging.getLogger("qualify_api.meegle.handlers")

WORK_ITEM_CREATED_HANDLER_KEY = handler_key(OBJECT_MEEGLE, str(EVENT_WORK_ITEM_CREATED))
WORK_ITEM_TERMINATED_HANDLER_KEY = handler_key(OBJECT_MEEGLE, str(EVENT_WORK_ITEM_TERMINATED))
FIELD_MODIFIED_HANDLER_KEY = handler_key(OBJECT_MEEGLE, str(EVENT_FIELD_MODIFIED))
NODE_COMPLETED_HANDLER_KEY = handler_key(OBJECT_MEEGLE, str(EVENT_NODE_COMPLETED))
NODE_ROLLED_BACK_HANDLER_KEY = handler_key(OBJECT_MEEGLE, str(EVENT_NODE_ROLLED_BACK))
STATUS_CHANGED_HANDLER_KEY = handler_key(OBJECT_MEEGLE, str(EVENT_STATUS_CHANGED))

TICKET_EVENT_CODES: frozenset[int] = frozenset(
    {
        EVENT_WORK_ITEM_CREATED,
        EVENT_FIELD_MODIFIED,
        EVENT_STATUS_CHANGED,
        EVENT_NODE_COMPLETED,
        EVENT_NODE_ROLLED_BACK,
        EVENT_WORK_ITEM_TERMINATED,
    }
)

IGNORED_OPENAPI = "ignored:openapi"
IGNORED_ROLLBACK = "ignored:rollback"
IGNORED_EVENT = "ignored:event"
OTHER_WORK_ITEM_TYPE = "other_work_item_type"
CONTRACT_VIOLATION = "contract_violation"
WORK_ITEM_NOT_FOUND = "work_item_not_found"

TypedHandler = Callable[[MeegleEvent, int], Awaitable[Outcome]]


class PrefillScheduler(Protocol):
    """`prefill.AltaPrefillScheduler`, or a fake: a short label, "" when off."""

    def schedule(self, work_item_id: int, *, email: str, handle: str | None) -> str: ...


PREFILL_ERROR = "error"


def _schedule_quietly(
    prefill: PrefillScheduler, work_item_id: int, result: InvitationResult
) -> str:
    """The prefill never touches the invitation: anything it raises is logged here."""
    try:
        return prefill.schedule(work_item_id, email=result.email, handle=result.instagram_handle)
    except Exception:  # noqa: BLE001 — a retry of the event would email the invite again
        logger.exception("meegle onboarding: work_item=%s prefill not scheduled", work_item_id)
        return PREFILL_ERROR


class TicketHandler(Protocol):
    """`tickets.TicketNotifier`, or a fake: returns the settle reason, raises
    `WorkItemNotFound` for an item that is not in the space."""

    def notify(self, event: MeegleEvent) -> str: ...


def _parse(event: ClaimedEvent) -> tuple[MeegleEvent, int] | Outcome:
    """The shared prelude: contract, own writes, the work item id."""
    try:
        parsed = MeegleEvent.model_validate(event.value or {})
    except ValidationError:
        logger.error("meegle event=%s field=%s value off-contract", event.id, event.field)
        return Outcome(STATUS_DEAD, CONTRACT_VIOLATION)
    if parsed.is_own_write:
        return Outcome(STATUS_PROCESSED, IGNORED_OPENAPI)
    work_item_id = parsed.work_item_id
    if work_item_id is None:
        logger.error("meegle event=%s carries no work item", event.id)
        return Outcome(STATUS_DEAD, CONTRACT_VIOLATION)
    return parsed, work_item_id


def _requested_by(parsed: MeegleEvent) -> str:
    """Who completed the node, for the provenance of a plan or pack (m-24852131)."""
    user = parsed.data.user_info
    who = (user.email or user.display_name()) if user is not None else ""
    return f"meegle:{who or parsed.actor}"


def _sync_consumption(work_item_id: int) -> str:
    """m-24823681: post the consumption summary to the «Alta de cliente» item.
    Guarded so a ledger/Meegle failure never turns the node event into a retry."""
    try:
        from qualify_api.consumption import sync_consumption_to_meegle  # noqa: PLC0415

        return sync_consumption_to_meegle(work_item_id)
    except Exception:  # noqa: BLE001 — the node is done; the ledger is not load-bearing
        logger.warning("consumption sync for work_item=%s failed", work_item_id, exc_info=True)
        return "failed"


def post_consumption_comment(work_item_id: int, markdown: str) -> str:
    """m-24823681: post a consumption summary comment to a Meegle work item.

    The meegle package owns the client (the plugin secret lives here); the
    consumption package owns the ledger read and the summary text. This is the
    one door between them so the consumption module never imports the raw
    client (the `meegle.client` sanctity guard). Returns `synced` on success,
    `meegle_off` when the engine is not configured, and `meegle_failed` on any
    refusal or transport failure (never raises — the ledger rows are the record).
    """
    from qualify_api.meegle.client import MeegleClient  # noqa: PLC0415
    from qualify_api.meegle.settings import (  # noqa: PLC0415
        MeegleSettings,
        meegle_configured,
    )

    if not meegle_configured():
        return "meegle_off"
    settings = MeegleSettings.from_env()
    client = MeegleClient(settings)
    try:
        client.comment(work_item_id, markdown)
    finally:
        client.close()
    return "synced"


async def _plan_update(
    engine: OnboardingEngine, work_item_id: int, event_key: str, actor: str
) -> Outcome:
    """**Plan ampliado** completed. A refused value is settled (`plan_failed:<reason>`):
    the item shows it and the node is rolled back; retrying would only repeat it."""
    try:
        result = await asyncio.to_thread(
            partial(engine.apply_plan_update, event_key=event_key, actor=actor), work_item_id
        )
    except WorkItemNotFound:
        return Outcome(STATUS_DEAD, WORK_ITEM_NOT_FOUND)
    if not result.ok:
        return Outcome(STATUS_PROCESSED, f"plan_failed:{result.reason}")
    return Outcome(STATUS_PROCESSED, f"plan={result.reason}")


def _onboarding_handlers(
    engine: OnboardingEngine, names: MeegleNames, prefill: PrefillScheduler | None = None
) -> Mapping[int, TypedHandler]:
    async def node_completed(parsed: MeegleEvent, work_item_id: int) -> Outcome:
        keys = (parsed.data.node_info.update_nodes if parsed.data.node_info else None) or []
        try:
            completed = [
                name
                for name in await asyncio.gather(
                    *(asyncio.to_thread(engine.node_name, work_item_id, key) for key in keys)
                )
                if name
            ]
        except WorkItemNotFound:
            return Outcome(STATUS_DEAD, WORK_ITEM_NOT_FOUND)
        event_key = parsed.data.idempotent_key
        actor = _requested_by(parsed)
        folded = {name.casefold() for name in completed}
        if names.node_data.casefold() not in folded:
            if names.node_plan.casefold() in folded:
                return await _plan_update(engine, work_item_id, event_key, actor)
            # m-24823681: «Kit de marca listo» → post the consumption summary.
            # Best-effort (a `processed` outcome with `consumption=<label>`); a
            # retry of the event is safe — Meegle accepts a repeated comment, and
            # the ledger rows are the record, so `empty` just means "nothing yet".
            if names.node_brand_kit_ready.casefold() in folded:
                label = await asyncio.to_thread(_sync_consumption, work_item_id)
                return Outcome(STATUS_PROCESSED, f"consumption={label}")
            label = ",".join(completed) or ",".join(keys) or "?"
            return Outcome(STATUS_PROCESSED, f"ignored:node={label}"[:200])
        try:
            result = await asyncio.to_thread(
                partial(engine.start_invitation, event_key=event_key, actor=actor), work_item_id
            )
        except WorkItemNotFound:
            return Outcome(STATUS_DEAD, WORK_ITEM_NOT_FOUND)
        if not result.ok:
            return Outcome(STATUS_PROCESSED, f"invite_failed:{result.reason}")
        if prefill is not None:
            label = await asyncio.to_thread(_schedule_quietly, prefill, work_item_id, result)
            if label:
                return Outcome(STATUS_PROCESSED, f"prefill={label}")
        return Outcome(STATUS_PROCESSED)

    async def work_item_terminated(parsed: MeegleEvent, work_item_id: int) -> Outcome:
        expired = await asyncio.to_thread(engine.expire_for_terminated, work_item_id)
        return Outcome(STATUS_PROCESSED, f"expired={expired}")

    async def node_rolled_back(parsed: MeegleEvent, work_item_id: int) -> Outcome:
        return Outcome(STATUS_PROCESSED, IGNORED_ROLLBACK)

    async def nothing(parsed: MeegleEvent, work_item_id: int) -> Outcome:
        return Outcome(STATUS_PROCESSED, IGNORED_EVENT)

    return {
        EVENT_NODE_COMPLETED: node_completed,
        EVENT_WORK_ITEM_TERMINATED: work_item_terminated,
        EVENT_NODE_ROLLED_BACK: node_rolled_back,
        EVENT_WORK_ITEM_CREATED: nothing,
        EVENT_FIELD_MODIFIED: nothing,
        EVENT_STATUS_CHANGED: nothing,
    }


def _ticket_handler(notifier: TicketHandler) -> TypedHandler:
    async def notify(parsed: MeegleEvent, work_item_id: int) -> Outcome:
        try:
            reason = await asyncio.to_thread(notifier.notify, parsed)
        except WorkItemNotFound:
            return Outcome(STATUS_DEAD, WORK_ITEM_NOT_FOUND)
        return Outcome(STATUS_PROCESSED, reason)

    return notify


def meegle_handlers(
    engine: OnboardingEngine,
    *,
    work_item_type: str,
    names: MeegleNames | None = None,
    tickets: TicketHandler | None = None,
    ticket_types: frozenset[str] = frozenset(),
    prefill: PrefillScheduler | None = None,
) -> Mapping[str, Handler]:
    """One handler per event code, routing by work item type: `work_item_type` → the
    onboarding engine (and, after a sent invitation, `prefill`); `ticket_types` →
    `tickets` (when given); the rest → unsupported."""
    onboarding = _onboarding_handlers(engine, names or MeegleNames(), prefill)
    ticket = _ticket_handler(tickets) if tickets is not None else None
    codes = set(onboarding) | (TICKET_EVENT_CODES if ticket is not None else set())

    def route(code: int) -> Handler:
        async def handler(event: ClaimedEvent) -> Outcome:
            prelude = _parse(event)
            if isinstance(prelude, Outcome):
                return prelude
            parsed, work_item_id = prelude
            item_type = parsed.data.work_item_type_key
            if item_type in ("", work_item_type):
                # An event without a type key is taken for the onboarding type, as before
                # the ticket notifier existed (the plugin was subscribed to that type only).
                typed = onboarding.get(code)
                if typed is not None:
                    return await typed(parsed, work_item_id)
            elif ticket is not None and item_type in ticket_types:
                return await ticket(parsed, work_item_id)
            return Outcome(STATUS_UNSUPPORTED, OTHER_WORK_ITEM_TYPE)

        return handler

    return {handler_key(OBJECT_MEEGLE, str(code)): route(code) for code in sorted(codes)}


def production_engine() -> OnboardingEngine:
    """The real client, resolver and mailer. Raises `MeegleNotConfigured` when off."""
    from qualify_api.meegle.client import MeegleClient  # noqa: PLC0415
    from qualify_api.meegle.schema import SchemaResolver  # noqa: PLC0415
    from qualify_api.meegle.settings import MeegleSettings  # noqa: PLC0415

    settings = MeegleSettings.from_env()
    names = MeegleNames.from_env()
    client = MeegleClient(settings)
    return OnboardingEngine(
        client,
        SchemaResolver(client, names),
        names=names,
        signer=os.environ.get("QUALIFY_INVITE_SIGNER", "").strip(),
    )


def production_meegle_handlers() -> Mapping[str, Handler]:
    """What `webhooks.processor.production_processor` registers: the onboarding handlers
    when the engine is configured (plus the ticket notifier when its webhook is set),
    nothing otherwise (events stay `unsupported`, replayable)."""
    from qualify_api.meegle.client import MeegleClient  # noqa: PLC0415
    from qualify_api.meegle.settings import (  # noqa: PLC0415
        MeegleSettings,
        TicketSettings,
        meegle_configured,
    )
    from qualify_api.meegle.tickets import LarkWebhookPoster, TicketNotifier  # noqa: PLC0415

    if not meegle_configured():
        logger.info("meegle engine off (QUALIFY_MEEGLE_* not set): events stay unsupported")
        return {}
    settings = MeegleSettings.from_env()
    ticket_settings = TicketSettings.from_env()
    tickets: TicketNotifier | None = None
    if ticket_settings.enabled:
        tickets = TicketNotifier(
            MeegleClient(settings),
            LarkWebhookPoster(ticket_settings.webhook_url),
            web_url=ticket_settings.web_url,
        )
        logger.info(
            "meegle ticket notices on for types=%s", ",".join(sorted(ticket_settings.ticket_types))
        )
    else:
        logger.info("meegle ticket notices off (QUALIFY_MEEGLE_NOTIFY_WEBHOOK_URL not set)")
    return meegle_handlers(
        production_engine(),
        work_item_type=settings.work_item_type,
        names=MeegleNames.from_env(),
        tickets=tickets,
        ticket_types=ticket_settings.ticket_types,
        # PB-4: always wired; it reads QUALIFY_ALTA_PREFILL_* on every «Datos» and does
        # nothing at all while the prefill is off (the default).
        prefill=production_prefill_scheduler(MeegleClient(settings)),
    )


def production_prefill_scheduler(client: MeegleClient) -> PrefillScheduler:
    """The real scheduler: Postgres jobs, the Meegle comment through `client`."""
    from qualify_api.meegle.prefill import AltaPrefillScheduler  # noqa: PLC0415
    from qualify_api.meegle.prefill_jobs import PostgresPrefillJobs  # noqa: PLC0415

    return AltaPrefillScheduler(PostgresPrefillJobs(), client.comment)


def production_prefill_runner(*, worker_id: str) -> AltaPrefillRunner | None:
    """What the webhook-worker drains Alta prefill jobs with; None while the Meegle
    engine is off (no job can exist without it, and the comment needs the client)."""
    from qualify_api.meegle.client import MeegleClient  # noqa: PLC0415
    from qualify_api.meegle.prefill import AltaPrefillRunner  # noqa: PLC0415
    from qualify_api.meegle.prefill_jobs import PostgresPrefillJobs  # noqa: PLC0415
    from qualify_api.meegle.settings import MeegleSettings, meegle_configured  # noqa: PLC0415

    if not meegle_configured():
        return None
    client = MeegleClient(MeegleSettings.from_env())
    return AltaPrefillRunner(PostgresPrefillJobs(), client.comment, worker_id=worker_id)
