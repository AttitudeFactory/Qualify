"""A person unsends an Instagram DM (m-25018661), offline: the handler erases the stored
copy and keeps it erased — redelivery, out-of-order arrival and the poll included — and
never touches an echo, an outbound row or another tenant's rows. The SQL side (redaction
columns, drafts, RLS, raw events) is `test_conversations_unsend_db.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    RemoteConversation,
    RemoteMessage,
    SourceConnection,
)
from qualify_api.conversations.instagram_source import SHAPE_VERSION_IG_DM
from qualify_api.conversations.memory_source import MemoryConversationSource
from qualify_api.conversations.repository import MemoryConversationRepository
from qualify_api.conversations.sync import ConversationSyncService
from qualify_api.conversations.webhook import (
    CONTRACT_VIOLATION,
    MESSAGE_DELETED_ECHO,
    MESSAGE_DELETED_OUTBOUND,
    MESSAGE_UNSENT,
    RemoteUnsend,
    instagram_messages_handler,
    parse_messaging_item,
)
from qualify_api.mentions.resolve import ResolutionOutcome, TenantResolution
from qualify_api.webhooks import worker
from qualify_api.webhooks.envelope import MESSAGING_FIELD
from qualify_api.webhooks.processor import Outcome, Processor
from qualify_api.webhooks.repository import (
    STATUS_DEAD,
    STATUS_PROCESSED,
    STATUS_UNSUPPORTED,
    ClaimedEvent,
)

IGID = "17841400000001"
TENANT = uuid4()
CONNECTION_ID = uuid4()
OTHER_TENANT = uuid4()
OTHER_CONNECTION = uuid4()
T0 = 1760616000000  # ms


def _item(mid: str, *, text: str | None = "hola", at: int = T0, **extra: Any) -> dict:
    message: dict[str, Any] = {"mid": mid, **extra}
    if text is not None:
        message["text"] = text
    return {
        "sender": {"id": "igsid-alice"},
        "recipient": {"id": IGID},
        "timestamp": at,
        "message": message,
    }


def _unsend(mid: str) -> dict:
    return {
        "sender": {"id": "igsid-alice"},
        "recipient": {"id": IGID},
        "timestamp": T0 + 90_000,
        "message": {"mid": mid, "is_deleted": True},
    }


def _echo(mid: str, **extra: Any) -> dict:
    return {
        "sender": {"id": IGID},
        "recipient": {"id": "igsid-alice"},
        "timestamp": T0 + 30_000,
        "message": {"mid": mid, "text": "¡hola!", "is_echo": True, **extra},
    }


def _event(value: object) -> ClaimedEvent:
    return ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object="instagram",
        entry_id=IGID,
        field=MESSAGING_FIELD,
        value=value,
        attempts=1,
        entry_time=1760616000,
    )


def _resolver(tenant: UUID = TENANT, connection: UUID = CONNECTION_ID):
    def resolve(*, platform: str, external_account_id: str) -> TenantResolution:
        return TenantResolution(
            outcome=ResolutionOutcome.RESOLVED, tenant_id=tenant, connection_id=connection
        )

    return resolve


class _Eraser:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *, entry_id: str, mid: str, keep_event_id: UUID) -> int:
        self.calls.append({"entry_id": entry_id, "mid": mid, "keep_event_id": keep_event_id})
        return 1


@pytest.fixture
def world():
    repo = MemoryConversationRepository()
    sync = ConversationSyncService(repository=repo)
    eraser = _Eraser()
    handler = instagram_messages_handler(resolve=_resolver(), sync=sync, erase_events=eraser)
    return repo, sync, handler, eraser


def _threads(repo: MemoryConversationRepository, tenant: UUID = TENANT):
    return repo.list_threads(tenant_id=tenant, channels=[CHANNEL_DM])


def _mids(repo: MemoryConversationRepository, thread_id: UUID) -> list[str]:
    return [
        m.external_message_id for m in repo.list_messages(tenant_id=TENANT, thread_id=thread_id)
    ]


# --- parsing ---------------------------------------------------------------------------


def test_parse_reads_an_unsend_and_keeps_echoes_and_bad_items_out() -> None:
    assert parse_messaging_item(_unsend("m.1"), own_account_id=IGID) == RemoteUnsend("m.1")
    echo = _echo("m.2", is_deleted=True)
    assert parse_messaging_item(echo, own_account_id=IGID) == MESSAGE_DELETED_ECHO
    # The sender is the account itself, even without `is_echo`: still the business's own.
    own = {**_unsend("m.3"), "sender": {"id": IGID}}
    assert parse_messaging_item(own, own_account_id=IGID) == MESSAGE_DELETED_ECHO
    with pytest.raises(ValueError):
        parse_messaging_item(
            {**_unsend("m.4"), "message": {"is_deleted": True}}, own_account_id=IGID
        )


async def test_an_unsend_without_mid_is_dead_and_resolves_nothing(world) -> None:
    _repo, _sync, handler, eraser = world
    outcome = await handler(_event({**_unsend("x"), "message": {"is_deleted": True}}))
    assert (outcome.status, outcome.error) == (STATUS_DEAD, CONTRACT_VIOLATION)
    assert eraser.calls == []


# --- the handler -------------------------------------------------------------------------


async def test_unsend_erases_the_message_recomputes_the_thread_and_erases_raw_events(
    world,
) -> None:
    repo, _sync, handler, eraser = world
    await handler(_event(_item("m.1", text="primero", at=T0)))
    await handler(_event(_echo("m.e")))
    await handler(_event(_item("m.2", text="me arrepentí", at=T0 + 60_000)))
    thread = _threads(repo)[0]
    assert thread.last_inbound_at == datetime.fromtimestamp((T0 + 60_000) / 1000, UTC)

    unsend = _event(_unsend("m.2"))
    outcome = await handler(unsend)

    assert outcome == Outcome(STATUS_PROCESSED)
    assert _mids(repo, thread.id) == ["m.1", "m.e"]
    thread = _threads(repo)[0]
    # The 24 h window and the «pendiente» state now rest on the earlier inbound.
    assert thread.last_inbound_at == datetime.fromtimestamp(T0 / 1000, UTC)
    assert thread.last_message_at == datetime.fromtimestamp((T0 + 30_000) / 1000, UTC)
    assert eraser.calls == [{"entry_id": IGID, "mid": "m.2", "keep_event_id": unsend.id}]


async def test_unsending_the_only_message_removes_the_thread_from_the_inbox(world) -> None:
    repo, _sync, handler, _eraser = world
    await handler(_event(_item("m.1")))
    assert len(_threads(repo)) == 1
    await handler(_event(_unsend("m.1")))
    assert _threads(repo) == []


async def test_redelivered_unsend_is_a_no_op(world) -> None:
    repo, sync, handler, _eraser = world
    await handler(_event(_item("m.1", at=T0)))
    await handler(_event(_item("m.2", at=T0 + 1000)))
    await handler(_event(_unsend("m.2")))
    connection = SourceConnection(
        tenant_id=TENANT, connection_id=CONNECTION_ID, external_account_id=IGID
    )
    again = sync.unsend_message(connection, external_message_id="m.2")
    assert (again.tombstone_created, again.message_redacted) == (False, False)
    assert (await handler(_event(_unsend("m.2")))).status == STATUS_PROCESSED
    assert _mids(repo, _threads(repo)[0].id) == ["m.1"]


async def test_unsend_before_its_message_blocks_the_late_webhook(world) -> None:
    repo, _sync, handler, eraser = world
    first = await handler(_event(_unsend("m.late")))
    assert first.status == STATUS_PROCESSED
    assert repo.unsends == {(CONNECTION_ID, "m.late"): TENANT}
    assert _threads(repo) == []  # a tombstone alone creates no thread

    late = await handler(_event(_item("m.late", text="esto no se guarda")))

    # Refused, and the change that still holds the text is deleted, not kept.
    assert late == Outcome(STATUS_PROCESSED, MESSAGE_UNSENT, erase=True)
    assert _threads(repo) == []
    assert len(eraser.calls) == 1


async def test_unsend_before_its_message_blocks_the_poll(world) -> None:
    repo, sync, handler, _eraser = world
    await handler(_event(_unsend("m.gone")))
    source = MemoryConversationSource()
    conversation = RemoteConversation(
        counterpart_external_id="igsid-alice", external_conversation_id="t_1"
    )
    source.add_message(
        conversation,
        RemoteMessage(
            external_message_id="m.kept",
            direction="inbound",
            text="sigue",
            posted_at=datetime.fromtimestamp(T0 / 1000, UTC),
            shape_version=SHAPE_VERSION_IG_DM,
        ),
    )
    source.add_message(
        conversation,
        RemoteMessage(
            external_message_id="m.gone",
            direction="inbound",
            text="borrado",
            posted_at=datetime.fromtimestamp((T0 + 5000) / 1000, UTC),
            shape_version=SHAPE_VERSION_IG_DM,
        ),
    )
    connection = SourceConnection(
        tenant_id=TENANT, connection_id=CONNECTION_ID, external_account_id=IGID
    )

    report = await sync.sync_connection(connection, source)

    assert report.unsent_skipped == 1 and report.messages_created == 1
    thread = _threads(repo)[0]
    assert _mids(repo, thread.id) == ["m.kept"]
    # The unsent message never moved the window.
    assert thread.last_inbound_at == datetime.fromtimestamp(T0 / 1000, UTC)


async def test_poll_after_unsend_does_not_resurrect_a_stored_message(world) -> None:
    repo, sync, handler, _eraser = world
    await handler(_event(_item("m.1", at=T0)))
    await handler(_event(_item("m.2", at=T0 + 1000)))
    await handler(_event(_unsend("m.2")))
    connection = SourceConnection(
        tenant_id=TENANT, connection_id=CONNECTION_ID, external_account_id=IGID
    )
    result = sync.ingest_message(
        connection,
        channel=CHANNEL_DM,
        conversation=RemoteConversation(counterpart_external_id="igsid-alice"),
        message=RemoteMessage(
            external_message_id="m.2",
            direction="inbound",
            text="otra vez",
            posted_at=datetime.fromtimestamp((T0 + 1000) / 1000, UTC),
            shape_version=SHAPE_VERSION_IG_DM,
        ),
    )
    assert result.unsent is True and result.thread_id is None
    assert _mids(repo, _threads(repo)[0].id) == ["m.1"]


async def test_echo_is_deleted_touches_nothing(world) -> None:
    repo, _sync, handler, eraser = world
    await handler(_event(_item("m.1")))
    await handler(_event(_echo("m.e")))
    outcome = await handler(_event(_echo("m.e", is_deleted=True)))
    assert (outcome.status, outcome.error) == (STATUS_UNSUPPORTED, MESSAGE_DELETED_ECHO)
    assert _mids(repo, _threads(repo)[0].id) == ["m.1", "m.e"]
    assert repo.unsends == {} and eraser.calls == []


async def test_unsend_naming_an_outbound_mid_touches_nothing(world) -> None:
    repo, _sync, handler, eraser = world
    await handler(_event(_item("m.1")))
    await handler(_event(_echo("m.e")))
    outcome = await handler(_event(_unsend("m.e")))  # not flagged echo, but stored outbound
    assert (outcome.status, outcome.error) == (STATUS_UNSUPPORTED, MESSAGE_DELETED_OUTBOUND)
    assert _mids(repo, _threads(repo)[0].id) == ["m.1", "m.e"]
    assert repo.unsends == {} and eraser.calls == []


async def test_unsend_never_touches_another_tenants_message() -> None:
    repo = MemoryConversationRepository()
    sync = ConversationSyncService(repository=repo)
    tenant_a = instagram_messages_handler(resolve=_resolver(), sync=sync)
    tenant_b = instagram_messages_handler(
        resolve=_resolver(OTHER_TENANT, OTHER_CONNECTION), sync=sync
    )
    await tenant_a(_event(_item("m.shared")))

    assert (await tenant_b(_event(_unsend("m.shared")))).status == STATUS_PROCESSED

    assert _mids(repo, _threads(repo)[0].id) == ["m.shared"]
    # B's tombstone is B's: A's poll or webhook keeps working for that id.
    assert repo.unsends == {(OTHER_CONNECTION, "m.shared"): OTHER_TENANT}


# --- the processor: settle by erasing ---------------------------------------------------


class _Queue:
    def __init__(self, events: list[ClaimedEvent]) -> None:
        self._events = events
        self.settled: list[tuple[str, str | None]] = []
        self.erased: list[UUID] = []

    def claim(self, *, worker_id: str, now: datetime, limit: int) -> list[ClaimedEvent]:
        events, self._events = self._events[:limit], self._events[limit:]
        return events

    def settle(self, *, event_id, worker_id, now, status, error=None) -> bool:
        self.settled.append((status, error))
        return True

    def fail(self, *, event_id, worker_id, now, attempts, error) -> str | None:
        self.settled.append(("failed", error))
        return "pending"

    def erase(self, *, event_id: UUID, worker_id: str) -> bool:
        self.erased.append(event_id)
        return True


async def test_processor_deletes_a_refused_original_instead_of_keeping_it(world) -> None:
    _repo, _sync, handler, _eraser = world
    unsend, late = _event(_unsend("m.x")), _event(_item("m.x", text="secreto"))
    queue = _Queue([unsend, late])
    processor = Processor(queue=queue, handlers={"instagram:messages": handler}, worker_id="t:1")
    report = await processor.run_once()
    assert queue.settled == [(STATUS_PROCESSED, None)]  # the unsend itself is kept
    assert queue.erased == [late.id]
    assert report.outcomes[STATUS_PROCESSED] == 2 and report.lost == 0


# --- the replay CLI ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["--requeue-deleted"],
        ["--requeue-deleted", "--account", IGID, "--all-accounts"],
        ["--requeue-postbacks", "--all-accounts"],
        ["--all-accounts"],
    ],
)
def test_requeue_deleted_demands_one_explicit_scope(argv: list[str], capsys) -> None:
    assert worker.main(argv) == 2


def test_requeue_deleted_dry_run_is_scoped_to_the_account(monkeypatch, capsys) -> None:
    calls: list[dict[str, Any]] = []

    class _FakeQueue:
        def requeue_unsupported_deleted(self, **kwargs: Any) -> int:
            calls.append(kwargs)
            return 3

    monkeypatch.setattr(worker, "WebhookQueue", _FakeQueue)
    monkeypatch.setattr(worker, "_load_dotenv", lambda: None)
    assert worker.main(["--requeue-deleted", "--account", IGID]) == 0
    assert calls[0]["entry_id"] == IGID and calls[0]["execute"] is False
    assert "would requeue (dry run) events=3" in capsys.readouterr().out


async def test_poll_of_a_conversation_whose_only_message_was_unsent_creates_no_thread(
    world,
) -> None:
    repo, sync, handler, _eraser = world
    await handler(_event(_unsend("m.only")))
    source = MemoryConversationSource()
    source.add_message(
        RemoteConversation(counterpart_external_id="igsid-alice"),
        RemoteMessage(
            external_message_id="m.only",
            direction="inbound",
            text="borrado",
            posted_at=datetime.fromtimestamp(T0 / 1000, UTC),
            shape_version=SHAPE_VERSION_IG_DM,
        ),
    )
    connection = SourceConnection(
        tenant_id=TENANT, connection_id=CONNECTION_ID, external_account_id=IGID
    )
    report = await sync.sync_connection(connection, source)
    assert (report.unsent_skipped, report.threads_created) == (1, 0)
    assert _threads(repo) == []
    assert "fetch_profile" not in source.calls
