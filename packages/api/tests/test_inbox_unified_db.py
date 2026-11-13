"""The unified inbox and the «Por responder» rule against Postgres (m-25017843, BU-A1).

What only the database can prove: one statement per page across WhatsApp and Instagram,
newest first; the composite cursor never skips two chats with the same instant; the SQL
rule agrees with `awaits_reply` and with `attention.counts` on every case of the ticket;
RLS keeps another business's chats out; a 50-chat page stays under 300 ms (p95).

Seeding follows `test_attention_counts_db.py`: tenant/app/user via `admin_session`, the
rest through `tenant_session`. Fresh tenants per test, so exact numbers hold on re-runs.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import event
from sqlalchemy.engine import Engine

from qualify_api.attention import PostgresPendingCounts
from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.awaiting import ThreadReplyFacts, awaits_reply
from qualify_api.inbox.models import Message, Thread
from qualify_api.inbox.unified import InboxCursor, count_inbox, list_inbox
from qualify_api.tenancy.models import Brand, Tenant, User
from qualify_api.whatsapp.models import WhatsAppOutboxItem, WhatsAppThreadState

pytestmark = pytest.mark.db

# In the past: outbox rows get `created_at = now()`, which must not precede the inbound.
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
NOW = T0 + timedelta(hours=1)


@dataclass(frozen=True)
class _Biz:
    tenant_id: UUID
    instagram: UUID
    whatsapp: UUID
    user_id: UUID


def _connection(tenant_id: UUID, app_id: UUID, brand_id: UUID, user_id: UUID, platform: str):
    whatsapp = platform == "whatsapp"
    return SocialConnection(
        tenant_id=tenant_id,
        platform_app_id=app_id,
        brand_id=brand_id,
        platform=platform,
        account_type="waba_phone_number" if whatsapp else "business",
        external_account_id=f"{platform}-{uuid4().hex[:12]}",
        linked_page_id=None if whatsapp else "page-1",
        granted_scopes=(
            ["whatsapp_business_messaging"] if whatsapp else ["instagram_manage_messages"]
        ),
        status="active",
        access_posture="development",
        current_credential_version=0,
        connected_by_user_id=user_id,
    )


def _business() -> _Biz:
    tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name=f"t-bandeja-{tenant_id.hex[:8]}",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@bandeja.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id
    with tenant_session(tenant_id) as session:
        brand = Brand(tenant_id=tenant_id, name="Bianki")
        session.add(brand)
        session.flush()
        ig = _connection(tenant_id, app_id, brand.id, user_id, "instagram")
        wa = _connection(tenant_id, app_id, brand.id, user_id, "whatsapp")
        session.add_all([ig, wa])
        session.flush()
        return _Biz(tenant_id, ig.id, wa.id, user_id)


def _thread(
    biz: _Biz,
    channel: str,
    *,
    at: datetime = T0,
    status: str = "open",
    inbound: bool = True,
    name: str | None = None,
) -> UUID:
    """A chat whose customer wrote at `at` (when `inbound`)."""
    connection = biz.whatsapp if channel == "whatsapp" else biz.instagram
    with tenant_session(biz.tenant_id) as session:
        thread = Thread(
            tenant_id=biz.tenant_id,
            connection_id=connection,
            channel=channel,
            external_thread_id=f"ext-{uuid4().hex[:12]}",
            status=status,
            last_message_at=at,
            last_inbound_at=at if inbound else None,
            counterpart_name=name,
        )
        session.add(thread)
        session.flush()
        if inbound:
            session.add(
                Message(
                    tenant_id=biz.tenant_id,
                    thread_id=thread.id,
                    connection_id=connection,
                    external_message_id=f"in-{uuid4().hex[:12]}",
                    direction="inbound",
                    author_username="Cliente",
                    text="¿tienen domicilio?",
                    posted_at=at,
                    shape_version="test",
                )
            )
        return thread.id


def _outbound(
    biz: _Biz,
    thread_id: UUID,
    channel: str,
    *,
    at: datetime,
    kind: str | None = None,
    delivery_status: str | None = "sent",
) -> None:
    """An outbound message at `at`; on WhatsApp with its outbox row of `kind`."""
    connection = biz.whatsapp if channel == "whatsapp" else biz.instagram
    external = f"out-{uuid4().hex[:12]}"
    with tenant_session(biz.tenant_id) as session:
        if kind is not None:
            session.add(
                WhatsAppOutboxItem(
                    tenant_id=biz.tenant_id,
                    connection_id=connection,
                    thread_id=thread_id,
                    kind=kind,
                    payload={"to": "573000000000", "type": "text", "text": {"body": "Hola"}},
                    status="sent",
                    wamid=external,
                    sent_at=at,
                )
            )
        session.add(
            Message(
                tenant_id=biz.tenant_id,
                thread_id=thread_id,
                connection_id=connection,
                external_message_id=external,
                direction="outbound",
                text="Hola",
                posted_at=at,
                shape_version="test",
                delivery_status=delivery_status if channel == "whatsapp" else None,
            )
        )
        session.flush()


def _queued_automation(biz: _Biz, thread_id: UUID, status: str) -> None:
    with tenant_session(biz.tenant_id) as session:
        session.add(
            WhatsAppOutboxItem(
                tenant_id=biz.tenant_id,
                connection_id=biz.whatsapp,
                thread_id=thread_id,
                kind="automation",
                payload={"to": "573000000000", "type": "text", "text": {"body": "Menú"}},
                status=status,
                error_code="131000" if status in ("failed", "dead") else None,
            )
        )
        session.flush()


def _hand_to_person(biz: _Biz, thread_id: UUID) -> None:
    with tenant_session(biz.tenant_id) as session:
        session.add(
            WhatsAppThreadState(
                thread_id=thread_id,
                tenant_id=biz.tenant_id,
                context={"_payment": {"status": "review"}},
                automation_paused_at=T0 + timedelta(seconds=2),
            )
        )
        session.flush()


@contextmanager
def _statements() -> Iterator[list[str]]:
    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        if "set_config" not in statement:
            seen.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(Engine, "before_cursor_execute", record)


def _all_pages(tenant_id: UUID, **kwargs: object) -> list[UUID]:
    ids: list[UUID] = []
    cursor: InboxCursor | None = None
    while True:
        page = list_inbox(tenant_id, cursor=cursor, now=NOW, **kwargs)  # type: ignore[arg-type]
        ids.extend(r.thread_id for r in page.rows)
        if page.next_cursor is None:
            return ids
        cursor = page.next_cursor


# --------------------------------------------------------------------------------------


def test_one_statement_per_page_newest_first_across_channels() -> None:
    biz = _business()
    oldest = _thread(biz, "whatsapp", at=T0)
    middle = _thread(biz, "dm", at=T0 + timedelta(minutes=1), name="Ana")
    newest = _thread(biz, "whatsapp", at=T0 + timedelta(minutes=2))
    silent = _thread(biz, "whatsapp", at=None, inbound=False)  # type: ignore[arg-type]
    _hand_to_person(biz, newest)

    with _statements() as seen:
        page = list_inbox(biz.tenant_id, filter="todos", now=NOW)

    assert len(seen) == 1
    assert [r.thread_id for r in page.rows] == [newest, middle, oldest, silent]
    by_id = {r.thread_id: r for r in page.rows}
    ig, wa = by_id[middle], by_id[newest]
    assert (ig.channel, ig.counterpart_name, ig.counterpart_phone) == ("dm", "Ana", None)
    assert (ig.unread, ig.automation_paused, ig.payment_status) == (True, None, None)
    assert wa.channel == "whatsapp" and wa.counterpart_name == "Cliente"
    assert wa.counterpart_phone is not None and wa.unread is None
    assert (wa.automation_paused, wa.payment_status) == (True, "review")
    assert wa.last_message_text == "¿tienen domicilio?" and wa.last_message_direction == "inbound"
    assert wa.window_open and wa.window_closes_at == T0 + timedelta(minutes=2, hours=24)
    assert by_id[silent].window_open is False and by_id[silent].awaiting_reply is False


def test_two_chats_with_the_same_instant_both_appear_when_paging() -> None:
    biz = _business()
    same = [_thread(biz, channel, at=T0) for channel in ("whatsapp", "dm", "whatsapp")]
    earlier = _thread(biz, "dm", at=T0 - timedelta(minutes=1))

    ids = _all_pages(biz.tenant_id, filter="todos", limit=1)

    assert len(ids) == len(set(ids)) == 4
    assert set(ids[:3]) == set(same) and ids[3] == earlier
    assert ids[:3] == sorted(same, reverse=True)  # id DESC breaks the tie


def test_the_rule_the_list_and_the_counts_agree_on_every_case() -> None:
    biz = _business()
    after = T0 + timedelta(minutes=1)
    expected: dict[UUID, ThreadReplyFacts] = {}

    for channel in ("whatsapp", "dm"):
        # Entrante sin respuesta.
        t = _thread(biz, channel)
        expected[t] = ThreadReplyFacts(status="open", last_inbound_at=T0)
        # Respondido por el dueño.
        t = _thread(biz, channel)
        _outbound(biz, t, channel, at=after, kind="reply" if channel == "whatsapp" else None)
        expected[t] = ThreadReplyFacts(
            status="open", last_inbound_at=T0, last_person_outbound_at=after, last_outbound_at=after
        )
        # Chat cerrado.
        t = _thread(biz, channel, status="closed")
        expected[t] = ThreadReplyFacts(status="closed", last_inbound_at=T0)

    # Respondido sólo por el menú.
    t = _thread(biz, "whatsapp")
    _outbound(biz, t, "whatsapp", at=after, kind="automation")
    expected[t] = ThreadReplyFacts(status="open", last_inbound_at=T0, last_outbound_at=after)
    # El menú todavía está respondiendo (fila en cola).
    t = _thread(biz, "whatsapp")
    _queued_automation(biz, t, "pending")
    expected[t] = ThreadReplyFacts(
        status="open", last_inbound_at=T0, automation_queued_since_inbound=True
    )
    # Entregado a una persona: «Hablar con alguien» → el menú avisa y se pausa.
    t = _thread(biz, "whatsapp")
    _outbound(biz, t, "whatsapp", at=after, kind="automation")
    _hand_to_person(biz, t)
    expected[t] = ThreadReplyFacts(
        status="open", last_inbound_at=T0, last_outbound_at=after, handed_to_person=True
    )
    # Entregado a una persona y el dueño ya respondió.
    t = _thread(biz, "whatsapp")
    _hand_to_person(biz, t)
    _outbound(biz, t, "whatsapp", at=after, kind="reply")
    expected[t] = ThreadReplyFacts(
        status="open",
        last_inbound_at=T0,
        last_person_outbound_at=after,
        last_outbound_at=after,
        handed_to_person=True,
    )
    # Envío automático fallido (el sender lo marcó failed / dead).
    for status in ("failed", "dead"):
        t = _thread(biz, "whatsapp")
        _queued_automation(biz, t, status)
        expected[t] = ThreadReplyFacts(
            status="open", last_inbound_at=T0, automation_failed_since_inbound=True
        )
    # Envío automático aceptado y luego reportado fallido por Meta.
    t = _thread(biz, "whatsapp")
    _outbound(biz, t, "whatsapp", at=after, kind="automation", delivery_status="failed")
    expected[t] = ThreadReplyFacts(
        status="open",
        last_inbound_at=T0,
        last_outbound_at=after,
        automation_failed_since_inbound=True,
    )
    # Cerrado y entregado a una persona: no cuenta.
    t = _thread(biz, "whatsapp", status="closed")
    _hand_to_person(biz, t)
    expected[t] = ThreadReplyFacts(status="closed", last_inbound_at=T0, handed_to_person=True)

    rows = {r.thread_id: r for r in list_inbox(biz.tenant_id, filter="todos", limit=100).rows}
    rows |= {r.thread_id: r for r in list_inbox(biz.tenant_id, filter="cerrados", limit=100).rows}
    assert rows.keys() == expected.keys()
    for thread_id, facts in expected.items():
        assert rows[thread_id].awaiting_reply is awaits_reply(facts), facts

    waiting = {t for t, f in expected.items() if awaits_reply(f)}
    listed = set(_all_pages(biz.tenant_id, filter="por_responder", limit=3))
    assert listed == waiting
    counts = PostgresPendingCounts().read(biz.tenant_id)
    assert counts.whatsapp == count_inbox(biz.tenant_id, channel="whatsapp")
    assert counts.messages == count_inbox(biz.tenant_id, channel="dm")
    assert counts.messages + counts.whatsapp == count_inbox(biz.tenant_id) == len(waiting)
    # 1 dm + (1 unanswered + 1 handed + 2 failed + 1 failed delivery) whatsapp.
    assert (counts.messages, counts.whatsapp) == (1, 5)


def test_another_business_never_appears() -> None:
    mine, other = _business(), _business()
    my_thread = _thread(mine, "whatsapp")
    for channel in ("whatsapp", "dm", "dm"):
        _thread(other, channel)

    for filter in ("por_responder", "todos"):
        ids = _all_pages(mine.tenant_id, filter=filter)
        assert ids == [my_thread]
    assert count_inbox(mine.tenant_id) == 1
    assert count_inbox(other.tenant_id) == 3


def test_comment_threads_are_not_chats() -> None:
    biz = _business()
    chat = _thread(biz, "dm")
    _thread(biz, "comment")
    assert _all_pages(biz.tenant_id, filter="todos") == [chat]


def test_a_page_of_50_chats_has_p95_under_300_ms() -> None:
    biz = _business()
    for i in range(120):
        channel = "whatsapp" if i % 2 else "dm"
        t = _thread(biz, channel, at=T0 + timedelta(seconds=i))
        if i % 3 == 0:
            _outbound(
                biz,
                t,
                channel,
                at=T0 + timedelta(seconds=i, milliseconds=500),
                kind=("automation" if i % 6 == 0 else "reply") if channel == "whatsapp" else None,
            )
    list_inbox(biz.tenant_id, filter="todos", limit=50, now=NOW)  # warm the plan cache
    timings: list[float] = []
    for filter in ("todos", "por_responder") * 10:
        started = time.perf_counter()
        page = list_inbox(biz.tenant_id, filter=filter, limit=50, now=NOW)  # type: ignore[arg-type]
        timings.append(time.perf_counter() - started)
        assert len(page.rows) == 50
    p95 = statistics.quantiles(timings, n=20)[-1]
    print(f"inbox page of 50: p95 {p95 * 1000:.1f} ms")  # evidence for the PR
    assert p95 < 0.300, f"p95 {p95 * 1000:.1f} ms"
