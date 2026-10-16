"""The Meegle handlers of the webhook processor (plan §3: "un handler nuevo por evento,
mismo contrato `Outcome`").

Registered under `meegle:<event_type>` (`webhooks.processor.handler_key`), so they see
only what `qualify_api.meegle.receiver` recorded. Every handler runs the same prelude:

1. the recorded value must be `{"source": …, "data": {…}}` with the documented shape →
   otherwise `dead` (`contract_violation`);
2. `source == "openapi"` is Qualify's own write-back → settled `processed`
   (`ignored:openapi`), so the engine never reacts to itself;
3. an item of another work item type → `unsupported` (`other_work_item_type`): the plugin
   may be subscribed more widely than the engine; kept, never acted on;
4. no work item id in the event → `dead`.

Then, per event (plan §2):

- **2001 node completed** — the completed node is named through the item's workflow
  (`SchemaResolver.node_name`; the event carries the template node key, e.g. `state_0`).
  Only **Datos** triggers `OnboardingEngine.start_invitation`; any other node is
  `processed` (`ignored:node=<name>`). An invitation that could not be sent for a reason
  the person must fix (bad email, mail refused) is ALSO `processed`, with
  `invite_failed:<reason>` in `last_error`: the item itself shows the error and the node
  is rolled back — retrying the event would only repeat the same failure.
- **1005 terminated** — `expire_for_terminated`.
- **2004 rolled back** — nothing (`ignored:rollback`): the person will complete Datos
  again, which is a new 2001.

Anything else raised (Meegle unreachable, a schema name missing, the database) propagates:
the processor retries with backoff and settles `dead` after `MAX_ATTEMPTS`.

`production_meegle_handlers()` returns `{}` when the engine is off (`meegle_configured()`
false), so an unconfigured deployment leaves Meegle events `unsupported` in the queue —
replayable the day it is configured — instead of burning retries on
`MeegleNotConfigured`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, ValidationError

from qualify_api.meegle.envelope import (
    EVENT_NODE_COMPLETED,
    EVENT_NODE_ROLLED_BACK,
    EVENT_WORK_ITEM_TERMINATED,
    OBJECT_MEEGLE,
    SOURCE_OPENAPI,
)
from qualify_api.meegle.onboarding import OnboardingEngine, WorkItemNotFound
from qualify_api.meegle.settings import MeegleNames
from qualify_api.webhooks.processor import Handler, Outcome, handler_key
from qualify_api.webhooks.repository import (
    STATUS_DEAD,
    STATUS_PROCESSED,
    STATUS_UNSUPPORTED,
    ClaimedEvent,
)

logger = logging.getLogger("qualify_api.meegle.handlers")

NODE_COMPLETED_HANDLER_KEY = handler_key(OBJECT_MEEGLE, str(EVENT_NODE_COMPLETED))
WORK_ITEM_TERMINATED_HANDLER_KEY = handler_key(OBJECT_MEEGLE, str(EVENT_WORK_ITEM_TERMINATED))
NODE_ROLLED_BACK_HANDLER_KEY = handler_key(OBJECT_MEEGLE, str(EVENT_NODE_ROLLED_BACK))

IGNORED_OPENAPI = "ignored:openapi"
IGNORED_ROLLBACK = "ignored:rollback"
OTHER_WORK_ITEM_TYPE = "other_work_item_type"
CONTRACT_VIOLATION = "contract_violation"
WORK_ITEM_NOT_FOUND = "work_item_not_found"


class _WorkItemRef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    work_item_id: int
    work_item_name: str = ""
    work_item_type_key: str = ""


class _NodeInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    update_nodes: list[str] | None = None
    reason: str | None = None


class _EventData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event_type: int
    idempotent_key: str
    work_item_type_key: str = ""
    project_key: str = ""
    work_item_info: list[_WorkItemRef] = []
    node_info: _NodeInfo | None = None


class MeegleEvent(BaseModel):
    """The recorded value of one Meegle change (`envelope.parse_meegle_delivery`)."""

    model_config = ConfigDict(extra="ignore")
    source: str | None = None
    data: _EventData

    @property
    def work_item_id(self) -> int | None:
        return self.data.work_item_info[0].work_item_id if self.data.work_item_info else None


def _prelude(event: ClaimedEvent, *, work_item_type: str) -> tuple[MeegleEvent, int] | Outcome:
    try:
        parsed = MeegleEvent.model_validate(event.value or {})
    except ValidationError:
        logger.error("meegle event=%s field=%s value off-contract", event.id, event.field)
        return Outcome(STATUS_DEAD, CONTRACT_VIOLATION)
    if parsed.source == SOURCE_OPENAPI:
        return Outcome(STATUS_PROCESSED, IGNORED_OPENAPI)
    if parsed.data.work_item_type_key and parsed.data.work_item_type_key != work_item_type:
        return Outcome(STATUS_UNSUPPORTED, OTHER_WORK_ITEM_TYPE)
    work_item_id = parsed.work_item_id
    if work_item_id is None:
        logger.error("meegle event=%s carries no work item", event.id)
        return Outcome(STATUS_DEAD, CONTRACT_VIOLATION)
    return parsed, work_item_id


def meegle_handlers(
    engine: OnboardingEngine, *, work_item_type: str, names: MeegleNames | None = None
) -> Mapping[str, Handler]:
    names = names or MeegleNames()

    async def node_completed(event: ClaimedEvent) -> Outcome:
        prelude = _prelude(event, work_item_type=work_item_type)
        if isinstance(prelude, Outcome):
            return prelude
        parsed, work_item_id = prelude
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
        if not any(name.casefold() == names.node_data.casefold() for name in completed):
            label = ",".join(completed) or ",".join(keys) or "?"
            return Outcome(STATUS_PROCESSED, f"ignored:node={label}"[:200])
        try:
            result = await asyncio.to_thread(engine.start_invitation, work_item_id)
        except WorkItemNotFound:
            return Outcome(STATUS_DEAD, WORK_ITEM_NOT_FOUND)
        if result.ok:
            return Outcome(STATUS_PROCESSED)
        return Outcome(STATUS_PROCESSED, f"invite_failed:{result.reason}")

    async def work_item_terminated(event: ClaimedEvent) -> Outcome:
        prelude = _prelude(event, work_item_type=work_item_type)
        if isinstance(prelude, Outcome):
            return prelude
        _, work_item_id = prelude
        expired = await asyncio.to_thread(engine.expire_for_terminated, work_item_id)
        return Outcome(STATUS_PROCESSED, f"expired={expired}")

    async def node_rolled_back(event: ClaimedEvent) -> Outcome:
        prelude = _prelude(event, work_item_type=work_item_type)
        if isinstance(prelude, Outcome):
            return prelude
        return Outcome(STATUS_PROCESSED, IGNORED_ROLLBACK)

    return {
        NODE_COMPLETED_HANDLER_KEY: node_completed,
        WORK_ITEM_TERMINATED_HANDLER_KEY: work_item_terminated,
        NODE_ROLLED_BACK_HANDLER_KEY: node_rolled_back,
    }


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
    """What `webhooks.processor.production_processor` registers: the three handlers when
    the engine is configured, nothing otherwise (events stay `unsupported`, replayable)."""
    from qualify_api.meegle.settings import (  # noqa: PLC0415
        MeegleSettings,
        meegle_configured,
    )

    if not meegle_configured():
        logger.info("meegle engine off (QUALIFY_MEEGLE_* not set): events stay unsupported")
        return {}
    settings = MeegleSettings.from_env()
    return meegle_handlers(
        production_engine(),
        work_item_type=settings.work_item_type,
        names=MeegleNames.from_env(),
    )
