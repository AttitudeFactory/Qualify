"""Naming the person behind an Instagram thread (m-25017852), offline.

Production showed threads as «Persona sin nombre»: a thread created by the webhook stored
no handle, a profile lookup that came back without one (Meta's 403 code 230, or only
`profile_pic`) dropped the handle the conversations listing already carried, and the 24 h
stamp then blocked any retry. Pinned here, with the in-memory repository and channel (no
Postgres, no Meta):

- `parse_profile` / `fetch_profile` read Meta's answers (full, partial, 403 code 230) and
  log failures with codes only;
- the listing's handle reaches the thread whenever it has none — webhook-created thread,
  profile `None`, profile with only `profile_pic`, a stamp still inside the TTL;
- a lookup that leaves the thread nameless is retried after `NAMELESS_RETRY_AFTER`, not
  after `PROFILE_TTL`, and at most `MAX_NAMELESS_RETRIES_PER_SYNC` per round;
- a stored value is never overwritten with nothing; the message author's handle is
  backfilled; repeated rounds change nothing more.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    RemoteConversation,
    RemoteMessage,
    RemoteProfile,
    SourceConnection,
)
from qualify_api.conversations.instagram_source import InstagramDirectSource, parse_profile
from qualify_api.conversations.memory_source import (
    SHAPE_VERSION_MEMORY,
    MemoryConversationSource,
)
from qualify_api.conversations.repository import MemoryConversationRepository
from qualify_api.conversations.sync import (
    MAX_NAMELESS_RETRIES_PER_SYNC,
    NAMELESS_RETRY_AFTER,
    PROFILE_TTL,
    ConversationSyncService,
)

T0 = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
TENANT = uuid4()
CONNECTION = SourceConnection(
    tenant_id=TENANT, connection_id=uuid4(), external_account_id="ig-1", linked_page_id="p1"
)
GRAPH = "https://graph.facebook.com/v21.0"


def _msg(mid: str, *, author_username: str | None = None) -> RemoteMessage:
    return RemoteMessage(
        external_message_id=mid,
        direction="inbound",
        text="hola",
        posted_at=T0,
        shape_version=SHAPE_VERSION_MEMORY,
        author_external_id="igsid-ana",
        author_username=author_username,
    )


def _listed(igsid: str = "igsid-ana", username: str | None = "ana.cocina") -> RemoteConversation:
    return RemoteConversation(
        counterpart_external_id=igsid,
        external_conversation_id=f"t_{igsid}",
        counterpart_username=username,
    )


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class RaisingProfileSource(MemoryConversationSource):
    async def fetch_profile(self, connection: SourceConnection, counterpart_external_id: str):
        self.calls.append("fetch_profile")
        raise RuntimeError("boom")


@pytest.fixture
def world() -> tuple[MemoryConversationRepository, MemoryConversationSource, Clock, Any]:
    repo = MemoryConversationRepository()
    source = MemoryConversationSource()
    clock = Clock()
    service = ConversationSyncService(repository=repo, clock=clock)
    return repo, source, clock, service


def _thread(repo: MemoryConversationRepository, igsid: str = "igsid-ana"):
    return repo.find_thread(
        tenant_id=TENANT,
        connection_id=CONNECTION.connection_id,
        channel=CHANNEL_DM,
        counterpart_external_id=igsid,
    )


# --- parse_profile ------------------------------------------------------------------------


def test_parse_profile_full_partial_and_empty() -> None:
    full = parse_profile({"name": "Ana", "username": "ana.cocina", "profile_pic": "https://p"})
    assert full == RemoteProfile(name="Ana", username="ana.cocina", avatar_url="https://p")
    assert parse_profile({"profile_pic": "https://p", "id": "1"}) == RemoteProfile(
        avatar_url="https://p"
    )
    assert parse_profile({"name": "  ", "username": None, "id": "1"}) is None
    assert parse_profile({}) is None


# --- fetch_profile (the Graph adapter) ------------------------------------------------------


class FakeGraph:
    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.urls: list[str] = []

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.urls.append(url)
        if isinstance(self.answer, Exception):
            raise self.answer
        status, body = self.answer
        return httpx.Response(status, json=body, request=httpx.Request("GET", url))


def _source(graph: FakeGraph) -> InstagramDirectSource:
    async def factory(tenant_id: UUID, connection_id: UUID) -> FakeGraph:
        return graph

    return InstagramDirectSource(client_factory=factory, graph_url=GRAPH)  # type: ignore[arg-type]


async def test_fetch_profile_full_answer() -> None:
    graph = FakeGraph((200, {"name": "Ana", "username": "ana.cocina", "id": "igsid-ana"}))
    profile = await _source(graph).fetch_profile(CONNECTION, "igsid-ana")
    assert profile == RemoteProfile(name="Ana", username="ana.cocina")
    assert graph.urls == [f"{GRAPH}/igsid-ana"]


async def test_fetch_profile_partial_answer_keeps_what_came() -> None:
    graph = FakeGraph((200, {"profile_pic": "https://p", "id": "igsid-ana"}))
    assert await _source(graph).fetch_profile(CONNECTION, "igsid-ana") == RemoteProfile(
        avatar_url="https://p"
    )


async def test_fetch_profile_403_code_230_is_none_and_logged_with_codes_only(caplog) -> None:
    graph = FakeGraph((403, {"error": {"code": 230, "message": "consent"}}))
    with caplog.at_level(logging.WARNING, logger="qualify_api.conversations"):
        assert await _source(graph).fetch_profile(CONNECTION, "igsid-ana") is None
    lines = [r.getMessage() for r in caplog.records]
    assert any("http_403_code_230" in line for line in lines)
    assert not any("igsid-ana" in line or "consent" in line for line in lines)


async def test_fetch_profile_transport_error_is_none() -> None:
    graph = FakeGraph(httpx.ConnectError("down"))
    assert await _source(graph).fetch_profile(CONNECTION, "igsid-ana") is None


# --- refresh_profile through the sync -------------------------------------------------------


async def test_webhook_created_thread_gets_its_handle_on_the_next_sync(world) -> None:
    repo, source, clock, service = world
    # The webhook path: only the sender's id, no handle anywhere.
    service.ingest_message(
        CONNECTION,
        channel=CHANNEL_DM,
        conversation=RemoteConversation(counterpart_external_id="igsid-ana"),
        message=_msg("mid.1"),
    )
    assert _thread(repo).counterpart_username is None
    # Meta refuses the profile (no consent): `fetch_profile` answers None.
    source.add_message(_listed(), _msg("mid.1", author_username="ana.cocina"))
    clock.now = T0 + timedelta(minutes=5)
    await service.sync_connection(CONNECTION, source)

    thread = _thread(repo)
    assert thread.counterpart_username == "ana.cocina"
    assert thread.counterpart_profile_at == clock.now
    # The message the webhook stored without its author's handle is backfilled.
    (message,) = repo.list_messages(tenant_id=TENANT, thread_id=thread.id)
    assert message.author_username == "ana.cocina"


async def test_profile_with_only_picture_keeps_the_listing_handle(world) -> None:
    repo, source, clock, service = world
    source.add_message(_listed(), _msg("mid.1"))
    source.profiles["igsid-ana"] = RemoteProfile(avatar_url="https://p")
    await service.sync_connection(CONNECTION, source)

    thread = _thread(repo)
    assert (thread.counterpart_username, thread.counterpart_avatar_url) == (
        "ana.cocina",
        "https://p",
    )
    # Named, so the long TTL applies: no lookup on the next round.
    source.calls.clear()
    clock.now = T0 + timedelta(hours=2)
    await service.sync_connection(CONNECTION, source)
    assert "fetch_profile" not in source.calls


async def test_profile_none_with_listing_handle_stores_the_handle(world) -> None:
    repo, source, _clock, service = world
    source.add_message(_listed(), _msg("mid.1"))
    report = await service.sync_connection(CONNECTION, source)
    assert _thread(repo).counterpart_username == "ana.cocina"
    assert report.profile_lookups == 1 and report.profile_retries == 0


async def test_a_name_from_the_profile_wins_and_keeps_the_handle(world) -> None:
    repo, source, _clock, service = world
    source.add_message(_listed(), _msg("mid.1"))
    source.profiles["igsid-ana"] = RemoteProfile(name="Ana Pérez")
    await service.sync_connection(CONNECTION, source)
    thread = _thread(repo)
    assert (thread.counterpart_name, thread.counterpart_username) == ("Ana Pérez", "ana.cocina")


async def test_nothing_known_is_retried_after_the_short_backoff_not_the_ttl(world, caplog) -> None:
    repo, source, clock, service = world
    source.add_message(_listed(username=None), _msg("mid.1"))
    with caplog.at_level(logging.INFO, logger="qualify_api.conversations"):
        await service.sync_connection(CONNECTION, source)

    thread = _thread(repo)
    assert thread.counterpart_name is None and thread.counterpart_username is None
    assert thread.counterpart_profile_at == T0 - PROFILE_TTL + NAMELESS_RETRY_AFTER
    unnamed = [
        r for r in caplog.records if r.getMessage().startswith("conversations.profile.unnamed")
    ]
    assert len(unnamed) == 1 and unnamed[0].levelno == logging.WARNING
    assert "outcome=none" in unnamed[0].getMessage()
    assert "igsid-ana" not in unnamed[0].getMessage()

    # Inside the backoff: no new lookup.
    source.calls.clear()
    clock.now = T0 + NAMELESS_RETRY_AFTER - timedelta(minutes=1)
    await service.sync_connection(CONNECTION, source)
    assert source.calls.count("fetch_profile") == 0

    # After it: retried (long before 24 h), and this time Meta names them.
    source.profiles["igsid-ana"] = RemoteProfile(username="ana.cocina")
    clock.now = T0 + NAMELESS_RETRY_AFTER
    report = await service.sync_connection(CONNECTION, source)
    assert source.calls.count("fetch_profile") == 1 and report.profile_retries == 1
    thread = _thread(repo)
    assert thread.counterpart_username == "ana.cocina"
    assert thread.counterpart_profile_at == clock.now


async def test_a_failing_lookup_is_logged_by_class_and_does_not_block(world, caplog) -> None:
    repo = MemoryConversationRepository()
    source = RaisingProfileSource()
    service = ConversationSyncService(repository=repo, clock=lambda: T0)
    source.add_message(_listed(username=None), _msg("mid.1"))
    with caplog.at_level(logging.WARNING, logger="qualify_api.conversations"):
        report = await service.sync_connection(CONNECTION, source)
    assert report.status == "ok"
    assert any("outcome=error_RuntimeError" in r.getMessage() for r in caplog.records)
    assert _thread(repo).counterpart_profile_at == T0 - PROFILE_TTL + NAMELESS_RETRY_AFTER


async def test_nameless_retries_are_bounded_per_round(world) -> None:
    repo, source, clock, service = world
    count = MAX_NAMELESS_RETRIES_PER_SYNC + 3
    for i in range(count):
        source.add_message(_listed(f"igsid-{i}", username=None), _msg(f"mid.{i}"))
    first = await service.sync_connection(CONNECTION, source)
    # First lookups are not retries: every new thread is asked once.
    assert first.profile_lookups == count and first.profile_retries == 0

    clock.now = T0 + NAMELESS_RETRY_AFTER
    source.calls.clear()
    second = await service.sync_connection(CONNECTION, source)
    assert second.profile_retries == MAX_NAMELESS_RETRIES_PER_SYNC
    assert source.calls.count("fetch_profile") == MAX_NAMELESS_RETRIES_PER_SYNC

    # The ones left out are taken on the next round.
    source.calls.clear()
    third = await service.sync_connection(CONNECTION, source)
    assert third.profile_retries == count - MAX_NAMELESS_RETRIES_PER_SYNC


async def test_handle_fills_a_thread_stamped_inside_the_ttl_without_a_lookup(world) -> None:
    repo, source, clock, service = world
    # An earlier round stamped the thread with nothing (the production state).
    upsert = repo.upsert_thread(
        tenant_id=TENANT,
        connection_id=CONNECTION.connection_id,
        channel=CHANNEL_DM,
        counterpart_external_id="igsid-ana",
    )
    stamped = T0 - timedelta(hours=1)
    repo.save_profile(
        tenant_id=TENANT, thread_id=upsert.thread_id, profile=RemoteProfile(), now=stamped
    )
    source.add_message(_listed(), _msg("mid.1"))
    await service.sync_connection(CONNECTION, source)

    assert "fetch_profile" not in source.calls
    thread = _thread(repo)
    assert thread.counterpart_username == "ana.cocina"
    assert thread.counterpart_profile_at == stamped


async def test_a_later_lookup_never_erases_what_is_stored(world) -> None:
    repo, source, clock, service = world
    source.add_message(_listed(), _msg("mid.1"))
    source.profiles["igsid-ana"] = RemoteProfile(name="Ana", avatar_url="https://p")
    await service.sync_connection(CONNECTION, source)

    # A day later Meta answers nothing and the listing lost the handle.
    del source.profiles["igsid-ana"]
    source.conversations["igsid-ana"] = _listed(username=None)
    clock.now = T0 + PROFILE_TTL
    await service.sync_connection(CONNECTION, source)
    thread = _thread(repo)
    assert (thread.counterpart_name, thread.counterpart_username) == ("Ana", "ana.cocina")
    assert thread.counterpart_avatar_url == "https://p"
    # Already named: the plain TTL, not the nameless backoff.
    assert thread.counterpart_profile_at == clock.now


async def test_author_backfill_never_replaces_a_stored_handle(world) -> None:
    repo, source, _clock, service = world
    service.ingest_message(
        CONNECTION,
        channel=CHANNEL_DM,
        conversation=RemoteConversation(counterpart_external_id="igsid-ana"),
        message=_msg("mid.1", author_username="ana.cocina"),
    )
    source.add_message(_listed(), _msg("mid.1", author_username="otro"))
    await service.sync_connection(CONNECTION, source)
    (message,) = repo.list_messages(tenant_id=TENANT, thread_id=_thread(repo).id)
    assert message.author_username == "ana.cocina"


async def test_repeated_rounds_are_idempotent(world) -> None:
    repo, source, clock, service = world
    source.add_message(_listed(), _msg("mid.1"))
    await service.sync_connection(CONNECTION, source)
    before = _thread(repo)
    source.calls.clear()
    for minutes in (5, 10, 15):
        clock.now = T0 + timedelta(minutes=minutes)
        report = await service.sync_connection(CONNECTION, source)
        assert report.messages_created == 0 and report.profile_lookups == 0
    after = _thread(repo)
    assert after.counterpart_username == before.counterpart_username == "ana.cocina"
    assert after.counterpart_profile_at == before.counterpart_profile_at
    assert "fetch_profile" not in source.calls
    assert len(repo.list_messages(tenant_id=TENANT, thread_id=after.id)) == 1
