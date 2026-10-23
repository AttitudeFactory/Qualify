"""Taps in Conversaciones against the real database (m-24789472, PR 2: B4, B5, B6). What only
Postgres can prove:

- an Ice Breaker postback through the handler lands as ONE inbound `messages` row with
  `choice_kind` / `choice_payload` (0082); a replay is a no-op; the poll's copy of the same
  `mid` (no payload) neither duplicates nor erases it, and a webhook that reaches a row the
  poll stored first fills the pair — `ON CONFLICT … DO UPDATE … WHERE` in
  `_INSERT_MESSAGE`;
- 0082's CHECKs: the four kinds, payload ⇒ kind, ≤ 1000 characters, inbound only;
- B5: none of it writes a `conversation_outbox` row;
- B6 (RLS): another tenant reads neither the message nor its choice fields;
- `requeue_unsupported_postbacks` takes back only `postback` items settled `unsupported`
  as `not_a_message`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from qualify_api.conversations.choices import CHOICE_ICE_BREAKER, CHOICE_QUICK_REPLY
from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    RemoteConversation,
    RemoteMessage,
)
from qualify_api.conversations.instagram_source import SHAPE_VERSION_IG_DM
from qualify_api.conversations.repository import PostgresConversationRepository
from qualify_api.conversations.sync import ConversationSyncService
from qualify_api.conversations.webhook import instagram_messages_handler
from qualify_api.mentions.resolve import ResolutionOutcome, TenantResolution
from qualify_api.webhooks.repository import STATUS_PROCESSED, WebhookQueue

from .test_conversations_choices import AT, ICE_BREAKER, IGID, QUICK_REPLY
from .test_conversations_repository_db import OTHER, TENANT, _source_connection
from .test_conversations_repository_db import seeded as seeded  # noqa: F401 — fixture
from .test_conversations_webhook import _event
from .test_webhook_queue_db import NOW, _acct, _row
from .test_webhook_queue_db import owner as owner  # noqa: F401 — fixture

pytestmark = pytest.mark.db


@pytest.fixture
def intake(
    seeded,
) -> Iterator[tuple[PostgresConversationRepository, ConversationSyncService, object]]:  # noqa: F811
    def resolve(**kwargs: object) -> TenantResolution:
        return TenantResolution(
            outcome=ResolutionOutcome.RESOLVED,
            tenant_id=TENANT,
            connection_id=seeded["connection"],
        )

    repo = PostgresConversationRepository()
    sync = ConversationSyncService(repository=repo)
    yield repo, sync, instagram_messages_handler(resolve=resolve, sync=sync)


def _unique(value: dict, **postback: str) -> dict:
    """The fixture with a fresh sender and mid, so reruns never collide."""
    sender = f"igsid-{uuid4().hex[:10]}"
    item = {**value, "sender": {"id": sender}}
    for key in ("postback", "message"):
        if key in value:
            item[key] = {**value[key], "mid": f"mid.{uuid4().hex}", **postback}
    return item


def _thread_messages(repo: PostgresConversationRepository, seeded: dict, sender: str):  # noqa: F811
    thread = repo.find_thread(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        channel=CHANNEL_DM,
        counterpart_external_id=sender,
    )
    assert thread is not None
    return thread, repo.list_messages(tenant_id=TENANT, thread_id=thread.id)


def _outbox_rows(thread_id: UUID) -> int:
    with tenant_session(TENANT) as session:
        return int(
            session.execute(
                text("SELECT count(*) FROM conversation_outbox WHERE thread_id = :t"),
                {"t": thread_id},
            ).scalar_one()
        )


async def test_an_ice_breaker_lands_once_and_enqueues_nothing(intake, seeded) -> None:  # noqa: F811
    repo, _sync, handler = intake
    item = _unique(ICE_BREAKER)
    assert (await handler(_event(item))).status == STATUS_PROCESSED
    assert (await handler(_event(item))).status == STATUS_PROCESSED  # replayed
    thread, messages = _thread_messages(repo, seeded, item["sender"]["id"])
    assert len(messages) == 1
    [message] = messages
    assert (message.direction, message.text) == ("inbound", "¿Cuánto cuesta?")
    assert (message.choice_kind, message.choice_payload) == (CHOICE_ICE_BREAKER, "QF_PRECIO")
    assert message.choice_label == "Pregunta inicial: Precio"
    assert thread.last_inbound_at == AT
    assert _outbox_rows(thread.id) == 0  # B5: a tap is never answered on its own


async def test_poll_first_is_enriched_and_webhook_first_is_kept(intake, seeded) -> None:  # noqa: F811
    repo, sync, handler = intake
    connection = _source_connection(seeded)

    def poll(item: dict) -> bool:
        source = item.get("postback") or item["message"]
        return sync.ingest_message(
            connection,
            channel=CHANNEL_DM,
            conversation=RemoteConversation(counterpart_external_id=item["sender"]["id"]),
            message=RemoteMessage(
                external_message_id=source["mid"],
                direction="inbound",
                text=source.get("title") or source.get("text"),
                posted_at=AT,
                shape_version=SHAPE_VERSION_IG_DM,
            ),
        ).message_created

    # Poll first, then the webhook: the same row gains kind and payload.
    late = _unique(QUICK_REPLY)
    assert poll(late) is True
    _thread, [before] = _thread_messages(repo, seeded, late["sender"]["id"])
    assert before.choice_kind is None
    assert (await handler(_event(late))).status == STATUS_PROCESSED
    _thread, [after] = _thread_messages(repo, seeded, late["sender"]["id"])
    assert after.id == before.id
    assert (after.text, after.choice_kind, after.choice_payload) == (
        "Sí",
        CHOICE_QUICK_REPLY,
        "QFQ_CONFIRMA_SI",
    )

    # Webhook first, then the poll: nothing is erased, nothing duplicated.
    early = _unique(ICE_BREAKER)
    await handler(_event(early))
    assert poll(early) is False
    _thread, [kept] = _thread_messages(repo, seeded, early["sender"]["id"])
    assert (kept.choice_kind, kept.choice_payload) == (CHOICE_ICE_BREAKER, "QF_PRECIO")

    # A later webhook with another payload for the same mid never replaces the pair.
    other = {**early, "postback": {**early["postback"], "payload": "QFB_OTRO"}}
    await handler(_event(other))
    _thread, [still] = _thread_messages(repo, seeded, early["sender"]["id"])
    assert (still.choice_kind, still.choice_payload) == (CHOICE_ICE_BREAKER, "QF_PRECIO")


@pytest.mark.parametrize(
    ("direction", "kind", "payload"),
    [
        ("outbound", "quick_reply", "QFQ_SI"),  # a choice is the person's tap only
        ("inbound", "reaction", None),  # not one of the four kinds
        ("inbound", None, "QF_PRECIO"),  # a payload never exists without a kind
        ("inbound", "button", "x" * 1001),  # Meta's cap
    ],
)
def test_the_checks_refuse_an_impossible_choice(
    seeded,  # noqa: F811
    direction: str,
    kind: str | None,
    payload: str | None,
) -> None:
    repo = PostgresConversationRepository()
    upsert = repo.upsert_thread(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        channel=CHANNEL_DM,
        counterpart_external_id=f"igsid-{uuid4().hex[:10]}",
    )
    with pytest.raises(IntegrityError):
        repo.insert_message(
            tenant_id=TENANT,
            thread_id=upsert.thread_id,
            connection_id=seeded["connection"],
            message=RemoteMessage(
                external_message_id=f"mid.{uuid4().hex}",
                direction=direction,  # type: ignore[arg-type]
                text="x",
                posted_at=AT,
                shape_version=SHAPE_VERSION_IG_DM,
                choice_kind=kind,
                choice_payload=payload,
            ),
        )


async def test_another_tenant_reads_no_choice(intake, seeded) -> None:  # noqa: F811
    repo, _sync, handler = intake
    item = _unique(ICE_BREAKER)
    await handler(_event(item))
    thread, [message] = _thread_messages(repo, seeded, item["sender"]["id"])

    assert repo.get_thread(tenant_id=OTHER, thread_id=thread.id) is None
    assert repo.list_messages(tenant_id=OTHER, thread_id=thread.id) == []
    with tenant_session(OTHER) as session:
        leaked = session.execute(
            text("SELECT choice_kind, choice_payload FROM messages WHERE id = :id"),
            {"id": message.id},
        ).all()
        any_choice = session.execute(
            text("SELECT count(*) FROM messages WHERE choice_payload = 'QF_PRECIO'")
        ).scalar_one()
    assert leaked == [] and any_choice == 0
    with tenant_session(TENANT) as session:
        own = session.execute(
            text("SELECT choice_kind, choice_payload FROM messages WHERE id = :id"),
            {"id": message.id},
        ).one()
    assert tuple(own) == (CHOICE_ICE_BREAKER, "QF_PRECIO")


# --- replaying postbacks recorded before this handler ------------------------------------------


def _settled_item(
    owner: Engine,  # noqa: F811
    *,
    entry_id: str,
    value: dict,
    status: str = "unsupported",
    last_error: str | None = "not_a_message",
    field: str = "messages",
) -> UUID:
    event_id = uuid4()
    received = NOW - timedelta(days=2)
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO meta_webhook_events (id, change_index, received_at, object, "
                "entry_id, field, value, dedup_key, status, attempts, next_attempt_at, "
                "processed_at, last_error) VALUES (:id, 0, :at, 'instagram', :e, :f, "
                "CAST(:v AS jsonb), :k, :s, 1, :at, :at, :err)"
            ),
            {
                "id": event_id,
                "at": received,
                "e": entry_id,
                "f": field,
                "v": json.dumps(value),
                "k": f"t-{uuid4()}",
                "s": status,
                "err": last_error,
            },
        )
    return event_id


def test_requeue_takes_back_only_unsupported_postbacks(owner) -> None:  # noqa: F811
    queue = WebhookQueue()
    acct = _acct()
    postback = {**ICE_BREAKER, "recipient": {"id": IGID}}
    reaction = {"sender": {"id": "a"}, "reaction": {"mid": "x", "action": "react"}}
    old_postback = _settled_item(owner, entry_id=acct, value=postback)
    never_judged = _settled_item(owner, entry_id=acct, value=postback, last_error=None)
    a_reaction = _settled_item(owner, entry_id=acct, value=reaction)
    an_echo = _settled_item(owner, entry_id=acct, value=postback, last_error="postback_echo")
    processed = _settled_item(
        owner, entry_id=acct, value=postback, status="processed", last_error=None
    )
    a_comment = _settled_item(owner, entry_id=acct, value=postback, field="comments")
    other_account = _settled_item(owner, entry_id=_acct(), value=postback)

    assert queue.requeue_unsupported_postbacks(now=NOW, entry_id=acct) == 2  # dry run
    assert _row(owner, "meta_webhook_events", old_postback).status == "unsupported"
    assert queue.requeue_unsupported_postbacks(now=NOW, execute=True, entry_id=acct) == 2
    for requeued in (old_postback, never_judged):
        row = _row(owner, "meta_webhook_events", requeued)
        assert (row.status, row.attempts, row.last_error) == ("pending", 0, None)
        assert row.received_at == NOW - timedelta(days=2)  # retention clock untouched
    for untouched in (a_reaction, an_echo, a_comment, other_account):
        assert _row(owner, "meta_webhook_events", untouched).status == "unsupported"
    assert _row(owner, "meta_webhook_events", processed).status == "processed"
    assert queue.requeue_unsupported_postbacks(now=NOW, execute=True, entry_id=acct) == 0
