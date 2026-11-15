"""m-25017846 (BU-B1): one inbound WhatsApp message advances the menu in ONE transaction,
one conversation at a time — against a real Postgres, through the real
`qualify_webhook_worker` door and the real phone resolver.

- **Crash between the engine step and the outbox.** A failure injected in the middle of
  the outbox writes leaves nothing behind (no message, no cursor, no row), and the
  webhook's retry produces the menu's reply exactly once.
- **Two messages of one customer at once.** Two changes of the same conversation handled
  concurrently end with the second applied over the first (the unknown-input counter
  counts both), instead of the second overwriting the first.
- **The lock is the conversation's own row.** A conversation held by one transaction
  blocks only that conversation: another business's conversation (and another customer
  of the same business) goes through meanwhile.
- **Retry after success.** Replaying a change that committed sends nothing twice and
  never advances the menu twice.

Seeding mirrors `test_whatsapp_inbox_repository_db.py` (tenant/user/app via
`admin_session`, connection and phone row via `tenant_session`). The menu is
`examples.BIANKI_DEMO_MENU`, handed to the handler directly (no version row needed).
Nothing here calls Meta: the outbox rows are only written, never sent.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Message, Thread
from qualify_api.tenancy.models import Tenant, User
from qualify_api.webhooks.repository import ClaimedEvent
from qualify_api.whatsapp.handler import PublishedMenu, whatsapp_messages_handler
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
from qualify_api.whatsapp.models import (
    WhatsAppOutboxItem,
    WhatsAppPhoneNumber,
    WhatsAppThreadState,
)
from qualify_api.whatsapp.repository import PostgresWhatsAppInboxRepository
from qualify_api.whatsapp.resolve import resolve_phone_number

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-000025017846")
OTHER_TENANT = UUID("b0000000-0000-4000-8000-000025017846")
MENU = PublishedMenu(BIANKI_DEMO_MENU)


class InjectedCrash(RuntimeError):
    """The process «dies» here: the exception the processor turns into a retry."""


def _seed(tenant_id: UUID) -> dict[str, Any]:
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=f"t-{tenant_id}",
                    country="VE",
                    timezone="America/Caracas",
                    currency="USD",
                )
            )
            session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@bub1.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id
    phone_number_id = f"pn-{uuid4()}"
    with tenant_session(tenant_id) as session:
        conn = SocialConnection(
            tenant_id=tenant_id,
            platform_app_id=app_id,
            platform="whatsapp",
            account_type="waba_phone_number",
            external_account_id=phone_number_id,
            linked_page_id=None,
            granted_scopes=["whatsapp_business_messaging"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        session.add(
            WhatsAppPhoneNumber(
                tenant_id=tenant_id,
                connection_id=conn.id,
                waba_id="waba-1",
                phone_number_id=phone_number_id,
                display_phone_number="15556336018",
            )
        )
        session.flush()
        return {"tenant": tenant_id, "connection": conn.id, "phone_number_id": phone_number_id}


@pytest.fixture
def business() -> dict[str, Any]:
    return _seed(TENANT)


@pytest.fixture
def other_business() -> dict[str, Any]:
    return _seed(OTHER_TENANT)


def _wa_id() -> str:
    return f"58424{uuid4().int % 10_000_000:07d}"


def _event(business: dict[str, Any], wa_id: str, body: str, *, wamid: str | None = None):
    value = {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": "15556336018",
            "phone_number_id": business["phone_number_id"],
        },
        "contacts": [{"profile": {"name": "Cliente"}, "wa_id": wa_id}],
        "messages": [
            {
                "from": wa_id,
                "id": wamid or f"wamid.{uuid4().hex}",
                "timestamp": str(int(time.time())),
                "type": "text",
                "text": {"body": body},
            }
        ],
    }
    return ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object="whatsapp_business_account",
        entry_id="waba-1",
        field="messages",
        value=value,
        attempts=1,
    )


def _handler(repo: Any, menu_loader: Any = None) -> Any:
    return whatsapp_messages_handler(
        resolve=resolve_phone_number,
        repo=repo,
        menu_loader=menu_loader or (lambda phone_row_id: MENU),
    )


def _thread_id(business: dict[str, Any], wa_id: str) -> UUID | None:
    with tenant_session(business["tenant"]) as session:
        return session.scalar(
            select(Thread.id).where(
                Thread.connection_id == business["connection"],
                Thread.external_thread_id == wa_id,
            )
        )


def _state(business: dict[str, Any], thread_id: UUID) -> WhatsAppThreadState | None:
    with tenant_session(business["tenant"]) as session:
        row = session.get(WhatsAppThreadState, thread_id)
        if row is not None:
            session.expunge(row)
        return row


def _outbox(business: dict[str, Any], thread_id: UUID) -> list[dict[str, Any]]:
    with tenant_session(business["tenant"]) as session:
        rows = session.scalars(
            select(WhatsAppOutboxItem).where(WhatsAppOutboxItem.thread_id == thread_id)
        ).all()
        return [dict(row.payload) for row in rows]


def _messages(business: dict[str, Any], thread_id: UUID) -> list[str]:
    with tenant_session(business["tenant"]) as session:
        return list(
            session.scalars(
                select(Message.external_message_id).where(Message.thread_id == thread_id)
            ).all()
        )


class _CrashingCalls:
    """Delegates every call to `inner`; the second `enqueue_outbox` of the armed run
    raises — after the engine stepped, the state was saved and one reply row written."""

    def __init__(self, inner: Any, owner: CrashOnSecondOutboxRow) -> None:
        self._inner = inner
        self._owner = owner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def enqueue_outbox(self, **kwargs: Any) -> UUID:
        self._owner.calls += 1
        if self._owner.armed and self._owner.calls == 2:
            self._owner.armed = False
            raise InjectedCrash("process died between the menu step and its outbox rows")
        return self._inner.enqueue_outbox(**kwargs)

    def transaction(self) -> Any:
        inner_cm = self._inner.transaction()
        owner = self._owner

        class _Cm:
            def __enter__(self) -> _CrashingCalls:
                return _CrashingCalls(inner_cm.__enter__(), owner)

            def __exit__(self, *exc: Any) -> Any:
                return inner_cm.__exit__(*exc)

        return _Cm()


class CrashOnSecondOutboxRow(_CrashingCalls):
    """Fault injection on the real repository, whether the handler calls it directly
    (one transaction per call) or through `transaction()`."""

    def __init__(self) -> None:
        self.armed = True
        self.calls = 0
        super().__init__(PostgresWhatsAppInboxRepository(), self)


async def test_a_crash_between_the_step_and_the_outbox_leaves_the_cursor_and_replies_once(
    business,
) -> None:
    # The reference: what one clean run of this first message writes.
    clean_wa = _wa_id()
    await _handler(PostgresWhatsAppInboxRepository())(_event(business, clean_wa, "Hola"))
    clean_thread = _thread_id(business, clean_wa)
    assert clean_thread is not None
    expected = _outbox(business, clean_thread)
    assert len(expected) >= 2  # welcome + the menu: the crash below hits between them
    clean_state = _state(business, clean_thread)
    assert clean_state is not None

    wa_id = _wa_id()
    repo = CrashOnSecondOutboxRow()
    handle = _handler(repo)
    event = _event(business, wa_id, "Hola", wamid=f"wamid.crash-{uuid4().hex}")

    with pytest.raises(InjectedCrash):
        await handle(event)

    # Nothing of the failed run is visible: no cursor, no half-written reply, and the
    # message itself is not stored either (not even the thread, upserted in the same
    # transaction) — so the retry is a first delivery.
    assert _thread_id(business, wa_id) is None

    # The processor retries the same change (`Processor.run_once` → `fail` → reclaim).
    outcome = await handle(event)
    assert outcome.status == "processed"

    thread_id = _thread_id(business, wa_id)
    assert thread_id is not None
    sent = _outbox(business, thread_id)
    assert len(sent) == len(expected)
    assert [p.get("type") for p in sent] == [p.get("type") for p in expected]
    state = _state(business, thread_id)
    assert state is not None
    assert (state.node_id, state.attempts) == (clean_state.node_id, clean_state.attempts)

    # A further retry of a change that committed writes nothing more.
    assert (await handle(event)).status == "processed"
    assert len(_outbox(business, thread_id)) == len(expected)
    assert _messages(business, thread_id) == [event.value["messages"][0]["id"]]


async def test_two_messages_of_one_customer_at_once_apply_the_second_over_the_first(
    business,
) -> None:
    wa_id = _wa_id()
    repo = PostgresWhatsAppInboxRepository()
    # The conversation is at the menu (attempts 0) before the race.
    await _handler(repo)(_event(business, wa_id, "Hola"))
    thread_id = _thread_id(business, wa_id)
    assert thread_id is not None
    before = _state(business, thread_id)
    assert before is not None and before.attempts == 0

    # Both handlers wait for each other right after reading the state (the menu loader
    # runs after `get_thread_state`) — the interleaving two workers would hit. With a
    # per-conversation lock the second never reaches it while the first holds the
    # conversation, so the wait times out and the two run one after the other.
    barrier = threading.Barrier(2, timeout=3)

    def racing_loader(phone_row_id: UUID) -> PublishedMenu:
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return MENU

    handle = _handler(repo, menu_loader=racing_loader)
    first, second = await asyncio.gather(
        handle(_event(business, wa_id, "zzz uno")),
        handle(_event(business, wa_id, "zzz dos")),
    )
    assert (first.status, second.status) == ("processed", "processed")

    after = _state(business, thread_id)
    assert after is not None
    # Two unknown inputs in a row: the counter counts both (MAX_UNKNOWN_ATTEMPTS = 2,
    # so no handoff yet). A lost update leaves 1.
    assert after.attempts == 2
    assert after.automation_paused_at is None


async def test_a_held_conversation_blocks_only_itself(business, other_business) -> None:
    repo = PostgresWhatsAppInboxRepository()
    handle = _handler(repo)
    held_wa = _wa_id()
    await handle(_event(business, held_wa, "Hola"))
    held_thread = _thread_id(business, held_wa)
    assert held_thread is not None

    locked = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with repo.transaction() as tx:
            tx.lock_thread(held_thread)
            locked.set()
            release.wait(15)

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert locked.wait(5)
        # Another business, and another customer of the same business: not blocked.
        other_wa, neighbour_wa = _wa_id(), _wa_id()
        done = await asyncio.wait_for(handle(_event(other_business, other_wa, "Hola")), 5)
        assert done.status == "processed"
        done = await asyncio.wait_for(handle(_event(business, neighbour_wa, "Hola")), 5)
        assert done.status == "processed"
        assert _outbox(other_business, _thread_id(other_business, other_wa))  # type: ignore[arg-type]
        assert _outbox(business, _thread_id(business, neighbour_wa))  # type: ignore[arg-type]

        # The held conversation itself waits.
        wamid = f"wamid.held-{uuid4().hex}"
        waiting = asyncio.ensure_future(handle(_event(business, held_wa, "zzz", wamid=wamid)))
        finished, _ = await asyncio.wait({waiting}, timeout=1.0)
        assert not finished
        assert wamid not in _messages(business, held_thread)
    finally:
        release.set()
        holder.join(10)
    assert (await asyncio.wait_for(waiting, 10)).status == "processed"
    assert wamid in _messages(business, held_thread)
    state = _state(business, held_thread)
    assert state is not None and state.attempts == 1


async def test_a_retry_after_a_committed_message_sends_nothing_and_never_steps_twice(
    business,
) -> None:
    repo = PostgresWhatsAppInboxRepository()
    calls: list[UUID] = []

    def counting_loader(phone_row_id: UUID) -> PublishedMenu:
        calls.append(phone_row_id)
        return MENU

    handle = _handler(repo, menu_loader=counting_loader)
    wa_id = _wa_id()
    event = _event(business, wa_id, "Hola")
    await handle(event)
    thread_id = _thread_id(business, wa_id)
    assert thread_id is not None
    rows, state = _outbox(business, thread_id), _state(business, thread_id)
    assert rows and state is not None
    assert len(calls) == 1

    for _ in range(2):
        assert (await handle(event)).status == "processed"

    assert _outbox(business, thread_id) == rows
    again = _state(business, thread_id)
    assert again is not None
    assert (again.node_id, again.attempts, again.context) == (
        state.node_id,
        state.attempts,
        state.context,
    )
    assert len(calls) == 1  # the menu was never stepped again
