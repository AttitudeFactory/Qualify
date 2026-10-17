"""The Instagram `messages` intake (QUA-226, E3), offline: the envelope maps
`entry[].messaging[]` to `instagram:messages` changes, and the handler turns one such
change into one `messages` row through the sync service's single-message door — the same
row the poll would write for the same `mid`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    RemoteConversation,
    RemoteMessage,
    SourceConnection,
)
from qualify_api.conversations.instagram_source import SHAPE_VERSION_IG_DM
from qualify_api.conversations.repository import MemoryConversationRepository
from qualify_api.conversations.sync import ConversationSyncService
from qualify_api.conversations.webhook import (
    CONTRACT_VIOLATION,
    INSTAGRAM_MESSAGES_HANDLER_KEY,
    MESSAGE_DELETED,
    NOT_A_MESSAGE,
    instagram_messages_handler,
    parse_messaging_item,
)
from qualify_api.mentions.resolve import ResolutionOutcome, TenantResolution
from qualify_api.webhooks.envelope import MESSAGING_FIELD, EnvelopeError, parse_delivery
from qualify_api.webhooks.processor import Processor, handler_key
from qualify_api.webhooks.repository import (
    STATUS_AMBIGUOUS,
    STATUS_DEAD,
    STATUS_ORPHAN,
    STATUS_PROCESSED,
    STATUS_UNSUPPORTED,
    ClaimedEvent,
)

IGID = "17841400000001"
TENANT = uuid4()
CONNECTION_ID = uuid4()

INBOUND = {
    "sender": {"id": "igsid-alice"},
    "recipient": {"id": IGID},
    "timestamp": 1760616000000,
    "message": {"mid": "mid.1", "text": "hola"},
}
ECHO = {
    "sender": {"id": IGID},
    "recipient": {"id": "igsid-alice"},
    "timestamp": 1760616060000,
    "message": {"mid": "mid.2", "text": "¡hola!", "is_echo": True},
}


def _event(value: object, *, entry_id: str = IGID) -> ClaimedEvent:
    return ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object="instagram",
        entry_id=entry_id,
        field=MESSAGING_FIELD,
        value=value,
        attempts=1,
        entry_time=1760616000,
    )


def _resolved(**kwargs):
    def resolve(*, platform: str, external_account_id: str) -> TenantResolution:
        return TenantResolution(
            outcome=ResolutionOutcome.RESOLVED, tenant_id=TENANT, connection_id=CONNECTION_ID
        )

    return resolve


# --- envelope -------------------------------------------------------------------------


def test_envelope_maps_messaging_items_to_messages_changes() -> None:
    body = json.dumps(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": IGID,
                    "time": 1760616000,
                    "messaging": [INBOUND, ECHO],
                }
            ],
        }
    ).encode()
    parsed = parse_delivery(body)
    assert parsed.object == "instagram"
    assert [c.field for c in parsed.changes] == [MESSAGING_FIELD, MESSAGING_FIELD]
    assert [c.change_index for c in parsed.changes] == [0, 1]
    assert parsed.changes[0].value == INBOUND
    assert parsed.changes[0].entry_id == IGID
    assert handler_key(parsed.object, parsed.changes[0].field) == INSTAGRAM_MESSAGES_HANDLER_KEY
    assert len({c.dedup_key for c in parsed.changes}) == 2


def test_envelope_keeps_changes_before_messaging_and_rejects_bad_items() -> None:
    body = json.dumps(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": IGID,
                    "changes": [{"field": "comments", "value": {}}],
                    "messaging": [INBOUND],
                }
            ],
        }
    ).encode()
    parsed = parse_delivery(body)
    assert [c.field for c in parsed.changes] == ["comments", MESSAGING_FIELD]
    with pytest.raises(EnvelopeError):
        parse_delivery(
            json.dumps({"object": "instagram", "entry": [{"id": IGID, "messaging": 3}]}).encode()
        )
    with pytest.raises(EnvelopeError):
        parse_delivery(
            json.dumps(
                {"object": "instagram", "entry": [{"id": IGID, "messaging": ["x"]}]}
            ).encode()
        )


# --- parsing --------------------------------------------------------------------------


def test_parse_inbound_item() -> None:
    conversation, message = parse_messaging_item(INBOUND, own_account_id=IGID)
    assert conversation.counterpart_external_id == "igsid-alice"
    assert message.direction == "inbound"
    assert message.external_message_id == "mid.1"
    assert message.text == "hola"
    assert message.author_external_id == "igsid-alice"
    assert message.posted_at == datetime.fromtimestamp(1760616000, UTC)
    assert message.shape_version == SHAPE_VERSION_IG_DM


def test_parse_echo_is_outbound_keyed_on_the_recipient() -> None:
    conversation, message = parse_messaging_item(ECHO, own_account_id=IGID)
    assert conversation.counterpart_external_id == "igsid-alice"
    assert message.direction == "outbound"
    # The account as sender is an echo even without the flag.
    _c, m = parse_messaging_item({**ECHO, "message": {"mid": "mid.3"}}, own_account_id=IGID)
    assert m.direction == "outbound" and m.text is None


def test_parse_non_messages_and_deleted_are_unsupported_reasons() -> None:
    reaction = {"sender": {"id": "a"}, "reaction": {"mid": "x", "action": "react"}}
    assert parse_messaging_item(reaction, own_account_id=IGID) == NOT_A_MESSAGE
    deleted = {**INBOUND, "message": {"mid": "mid.1", "is_deleted": True}}
    assert parse_messaging_item(deleted, own_account_id=IGID) == MESSAGE_DELETED


def test_parse_attachments_become_media_types() -> None:
    item = {
        **INBOUND,
        "message": {"mid": "mid.4", "attachments": [{"type": "image", "payload": {}}]},
    }
    _c, m = parse_messaging_item(item, own_account_id=IGID)
    assert m.media_type == "image" and m.text is None


@pytest.mark.parametrize(
    "value",
    ["not an object", {"message": {"text": "x"}}, {**INBOUND, "message": {"text": "no mid"}}],
)
def test_parse_off_contract_items_raise(value: object) -> None:
    with pytest.raises(ValueError):
        parse_messaging_item(value, own_account_id=IGID)


# --- the handler ----------------------------------------------------------------------


@pytest.fixture
def world():
    repo = MemoryConversationRepository()
    sync = ConversationSyncService(repository=repo)
    handler = instagram_messages_handler(resolve=_resolved(), sync=sync)
    return repo, sync, handler


async def test_inbound_change_lands_as_one_message_and_a_replay_is_a_no_op(world) -> None:
    repo, _sync, handler = world
    assert (await handler(_event(INBOUND))).status == STATUS_PROCESSED
    assert (await handler(_event(INBOUND))).status == STATUS_PROCESSED  # redelivered
    threads = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])
    assert len(threads) == 1
    thread = threads[0]
    assert thread.counterpart_external_id == "igsid-alice"
    assert thread.connection_id == CONNECTION_ID
    assert thread.last_inbound_at == datetime.fromtimestamp(1760616000, UTC)
    messages = repo.list_messages(tenant_id=TENANT, thread_id=thread.id)
    assert [m.external_message_id for m in messages] == ["mid.1"]


async def test_echo_lands_outbound_on_the_same_thread_without_moving_the_window(world) -> None:
    repo, _sync, handler = world
    await handler(_event(INBOUND))
    assert (await handler(_event(ECHO))).status == STATUS_PROCESSED
    thread = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])[0]
    directions = [m.direction for m in repo.list_messages(tenant_id=TENANT, thread_id=thread.id)]
    assert directions == ["inbound", "outbound"]
    assert thread.last_inbound_at == datetime.fromtimestamp(1760616000, UTC)
    assert thread.last_message_at == datetime.fromtimestamp(1760616060, UTC)


async def test_webhook_and_poll_converge_on_one_row_per_mid(world) -> None:
    repo, sync, handler = world
    await handler(_event(INBOUND))
    connection = SourceConnection(
        tenant_id=TENANT, connection_id=CONNECTION_ID, external_account_id=IGID
    )
    result = sync.ingest_message(
        connection,
        channel=CHANNEL_DM,
        conversation=RemoteConversation(
            counterpart_external_id="igsid-alice", external_conversation_id="t_1"
        ),
        message=RemoteMessage(
            external_message_id="mid.1",
            direction="inbound",
            text="hola",
            posted_at=datetime.fromtimestamp(1760616000, UTC),
            shape_version=SHAPE_VERSION_IG_DM,
        ),
    )
    assert result.thread_created is False and result.message_created is False
    thread = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])[0]
    assert thread.external_conversation_id == "t_1"  # the poll filled what the webhook lacked
    assert len(repo.list_messages(tenant_id=TENANT, thread_id=thread.id)) == 1


async def test_orphan_and_ambiguous_write_nothing() -> None:
    repo = MemoryConversationRepository()
    sync = ConversationSyncService(repository=repo)

    def orphan(**kwargs):
        return TenantResolution(outcome=ResolutionOutcome.ORPHAN)

    def ambiguous(**kwargs):
        return TenantResolution(outcome=ResolutionOutcome.AMBIGUOUS)

    assert (
        await instagram_messages_handler(resolve=orphan, sync=sync)(_event(INBOUND))
    ).status == STATUS_ORPHAN
    assert (
        await instagram_messages_handler(resolve=ambiguous, sync=sync)(_event(INBOUND))
    ).status == STATUS_AMBIGUOUS
    assert repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM]) == []


async def test_unsupported_and_dead_outcomes_never_resolve(world) -> None:
    _repo, sync, _handler = world
    calls: list[str] = []

    def resolve(**kwargs):
        calls.append(kwargs["external_account_id"])
        return TenantResolution(outcome=ResolutionOutcome.ORPHAN)

    handler = instagram_messages_handler(resolve=resolve, sync=sync)
    reaction = {"sender": {"id": "a"}, "reaction": {"mid": "x", "action": "react"}}
    read = await handler(_event(reaction))
    assert (read.status, read.error) == (STATUS_UNSUPPORTED, NOT_A_MESSAGE)
    dead = await handler(_event({"message": {"text": "no ids"}}))
    assert (dead.status, dead.error) == (STATUS_DEAD, CONTRACT_VIOLATION)
    assert calls == []


class _Queue:
    def __init__(self, events: list[ClaimedEvent]) -> None:
        self._events = events
        self.settled: list[tuple[str, str | None]] = []

    def claim(self, *, worker_id: str, now: datetime, limit: int) -> list[ClaimedEvent]:
        events, self._events = self._events[:limit], self._events[limit:]
        return events

    def settle(self, *, event_id, worker_id, now, status, error=None) -> bool:
        self.settled.append((status, error))
        return True

    def fail(self, *, event_id, worker_id, now, attempts, error) -> str | None:
        self.settled.append(("failed", error))
        return "pending"


async def test_processor_routes_instagram_messages_and_not_whatsapp_ones(world) -> None:
    _repo, _sync, handler = world
    whatsapp = ClaimedEvent(
        id=uuid4(),
        delivery_id=None,
        object="whatsapp_business_account",
        entry_id="waba",
        field="messages",
        value={"messages": []},
        attempts=1,
    )
    queue = _Queue([_event(INBOUND), whatsapp])
    processor = Processor(
        queue=queue, handlers={INSTAGRAM_MESSAGES_HANDLER_KEY: handler}, worker_id="t:1"
    )
    report = await processor.run_once()
    assert report.claimed == 2
    assert queue.settled == [(STATUS_PROCESSED, None), (STATUS_UNSUPPORTED, None)]
