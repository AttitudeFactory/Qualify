"""The unified inbox and the «Por responder» rule against Postgres (m-25017843, BU-A1).

What only the database can prove: one statement per page across WhatsApp and Instagram,
newest first; the composite cursor never skips two chats with the same instant; the SQL
rule (`awaiting_reply_sql`) agrees with its Python twin (`awaits_reply`) on every case —
each case is seeded once and read both ways — and `count_inbox` with the list; RLS keeps
another business's chats out. Instagram's reply-window bound (founder, 2026-11-13) is
`test_instagram_*_window*`; the open questions of `inbox.awaiting` are pinned
(`test_pinned_*`). The p95 benchmark is opt-in only (`QUALIFY_RUN_INBOX_BENCHMARK=1`,
plus `slow`): never in `just test`, `just test-db` or CI.

Seeding follows `test_attention_counts_db.py`: tenant/app/user via `admin_session`, the
rest through `tenant_session`. Fresh tenants per test, so exact numbers hold on re-runs.
"""

from __future__ import annotations

import os
import statistics
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import event, insert, text
from sqlalchemy.engine import Engine

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.awaiting import (
    AutomationSend,
    MessageFact,
    ThreadSnapshot,
    awaits_reply,
    count_awaiting_sql,
)
from qualify_api.inbox.models import Message, Thread
from qualify_api.inbox.unified import InboxCursor, count_inbox, list_inbox
from qualify_api.tenancy.models import Brand, Tenant, User
from qualify_api.whatsapp.models import WhatsAppOutboxItem, WhatsAppThreadState
from qualify_api.whatsapp.outbox import STALE_AFTER
from qualify_api.whatsapp.window import WINDOW

pytestmark = pytest.mark.db

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
NOW = T0 + timedelta(hours=1)
_PAYLOAD = {"to": "573000000000", "type": "text", "text": {"body": "Hola"}}


@dataclass(frozen=True)
class _Biz:
    tenant_id: UUID
    instagram: UUID
    whatsapp: UUID


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
        return _Biz(tenant_id, ig.id, wa.id)


@dataclass
class _Chat:
    """One chat, written to Postgres AND kept as the `ThreadSnapshot` the twin reads."""

    biz: _Biz
    channel: str
    status: str = "open"
    name: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    sends: list[dict[str, Any]] = field(default_factory=list)
    paused: bool | None = None  # None = no thread state row
    snapshot_messages: list[MessageFact] = field(default_factory=list)
    snapshot_sends: list[AutomationSend] = field(default_factory=list)

    @property
    def connection(self) -> UUID:
        return self.biz.whatsapp if self.channel == "whatsapp" else self.biz.instagram

    def inbound(
        self, at: datetime, *, hidden: bool = False, text: str | None = "¿tienen domicilio?"
    ) -> _Chat:
        self.messages.append(
            {
                "direction": "inbound",
                "posted_at": at,
                "deleted_at": at if hidden else None,
                "text": text,
                "author_username": "Cliente",
                "media_type": None if text else "other",
            }
        )
        self.snapshot_messages.append(MessageFact("inbound", at, hidden=hidden))
        return self

    def reply(
        self,
        at: datetime,
        *,
        menu: bool = False,
        hidden: bool = False,
        delivery_status: str | None = "sent",
    ) -> _Chat:
        """An outbound message; on WhatsApp with its outbox row (`automation` or `reply`)."""
        external = f"out-{uuid4().hex[:12]}"
        self.messages.append(
            {
                "direction": "outbound",
                "posted_at": at,
                "deleted_at": at if hidden else None,
                "text": "Hola",
                "external_message_id": external,
                "delivery_status": delivery_status if self.channel == "whatsapp" else None,
            }
        )
        self.snapshot_messages.append(MessageFact("outbound", at, hidden=hidden, automatic=menu))
        if self.channel == "whatsapp":
            kind = "automation" if menu else "reply"
            self.sends.append({"kind": kind, "status": "sent", "wamid": external, "created_at": at})
            if menu:
                self.snapshot_sends.append(
                    AutomationSend("sent", at, delivery_failed=delivery_status == "failed")
                )
        return self

    def menu_send(self, status: str, created_at: datetime) -> _Chat:
        """An automatic reply that never became a message (queued or failed)."""
        self.sends.append(
            {"kind": "automation", "status": status, "wamid": None, "created_at": created_at}
        )
        self.snapshot_sends.append(AutomationSend(status, created_at))
        return self

    def hand_off(self, *, paused: bool = True) -> _Chat:
        self.paused = paused
        return self

    def snapshot(self) -> ThreadSnapshot:
        return ThreadSnapshot(
            status=self.status,
            channel=self.channel,
            messages=tuple(self.snapshot_messages),
            automation_sends=tuple(self.snapshot_sends),
            handed_to_person=bool(self.paused),
        )

    def save(self) -> UUID:
        tenant_id = self.biz.tenant_id
        inbound = [m["posted_at"] for m in self.messages if m["direction"] == "inbound"]
        every = [m["posted_at"] for m in self.messages]
        with tenant_session(tenant_id) as session:
            thread = Thread(
                tenant_id=tenant_id,
                connection_id=self.connection,
                channel=self.channel,
                external_thread_id=f"ext-{uuid4().hex[:12]}",
                status=self.status,
                last_message_at=max(every, default=None),
                last_inbound_at=max(inbound, default=None),
                counterpart_name=self.name,
            )
            session.add(thread)
            session.flush()
            for m in self.messages:
                session.add(
                    Message(
                        tenant_id=tenant_id,
                        thread_id=thread.id,
                        connection_id=self.connection,
                        external_message_id=m.get("external_message_id")
                        or f"in-{uuid4().hex[:12]}",
                        direction=m["direction"],
                        author_username=m.get("author_username"),
                        text=m["text"],
                        posted_at=m["posted_at"],
                        deleted_at=m["deleted_at"],
                        media_type=m.get("media_type"),
                        delivery_status=m.get("delivery_status"),
                        shape_version="test",
                    )
                )
            for s in self.sends:
                session.add(
                    WhatsAppOutboxItem(
                        tenant_id=tenant_id,
                        connection_id=self.connection,
                        thread_id=thread.id,
                        kind=s["kind"],
                        payload=_PAYLOAD,
                        status=s["status"],
                        wamid=s["wamid"],
                        created_at=s["created_at"],
                        error_code="131000" if s["status"] in ("failed", "dead") else None,
                    )
                )
            if self.paused is not None:
                session.add(
                    WhatsAppThreadState(
                        thread_id=thread.id,
                        tenant_id=tenant_id,
                        context={"_payment": {"status": "review"}},
                        automation_paused_at=T0 if self.paused else None,
                    )
                )
            session.flush()
            return thread.id


def _thread(biz: _Biz, channel: str, *, at: datetime = T0, **kwargs: Any) -> UUID:
    return _Chat(biz, channel, **kwargs).inbound(at).save()


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


def _all_pages(tenant_id: UUID, *, now: datetime = NOW, **kwargs: Any) -> list[UUID]:
    ids: list[UUID] = []
    cursor: InboxCursor | None = None
    while True:
        page = list_inbox(tenant_id, cursor=cursor, now=now, **kwargs)
        ids.extend(r.thread_id for r in page.rows)
        if page.next_cursor is None:
            return ids
        cursor = page.next_cursor


def _awaiting(biz: _Biz, now: datetime = NOW) -> dict[UUID, bool]:
    rows: dict[UUID, bool] = {}
    for filter in ("todos", "cerrados"):
        page = list_inbox(biz.tenant_id, filter=filter, limit=100, now=now)  # type: ignore[arg-type]
        for r in page.rows:
            rows[r.thread_id] = r.awaiting_reply
    return rows


def _counter(biz: _Biz, channel: str, now: datetime) -> int:
    """`count_awaiting_sql` as `attention.counts` will run it, with `now` bound."""
    with tenant_session(biz.tenant_id) as session:
        sql = text(f"SELECT {count_awaiting_sql(channel, now_param='now')}")
        return int(session.execute(sql, {"now": now}).scalar_one())


# --------------------------------------------------------------------------------------


def test_one_statement_per_page_newest_first_across_channels() -> None:
    biz = _business()
    oldest = _thread(biz, "whatsapp", at=T0)
    middle = _thread(biz, "dm", at=T0 + timedelta(minutes=1), name="Ana")
    newest = _Chat(biz, "whatsapp").inbound(T0 + timedelta(minutes=2)).hand_off().save()
    silent = _Chat(biz, "whatsapp").save()  # no message at all: undated, sorts last

    for filter in ("todos", "por_responder", "cerrados"):
        with _statements() as seen:
            list_inbox(biz.tenant_id, filter=filter, now=NOW)  # type: ignore[arg-type]
        assert len(seen) == 1, filter
    page = list_inbox(biz.tenant_id, filter="todos", now=NOW)

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
    undated = [_Chat(biz, "dm").save() for _ in range(2)]

    ids = _all_pages(biz.tenant_id, filter="todos", limit=1)

    assert len(ids) == len(set(ids)) == 6
    assert ids[:3] == sorted(same, reverse=True)  # id DESC breaks the tie
    assert ids[3] == earlier
    assert ids[4:] == sorted(undated, reverse=True)


def test_the_sql_rule_its_twin_and_count_inbox_agree_on_every_case() -> None:
    biz = _business()
    real_now = datetime.now(UTC)
    base = real_now - timedelta(minutes=30)
    after = base + timedelta(minutes=1)
    before = base - timedelta(minutes=1)
    fresh_in = real_now - timedelta(minutes=1)
    assert real_now - after > STALE_AFTER  # a queued row at `after` is stuck
    chats: list[_Chat] = []

    def chat(channel: str, **kwargs: Any) -> _Chat:
        c = _Chat(biz, channel, **kwargs)
        chats.append(c)
        return c

    for channel in ("whatsapp", "dm"):
        chat(channel).inbound(base)  # unanswered
        chat(channel).inbound(base).reply(after)  # answered by the owner
        chat(channel, status="closed").inbound(base)  # closed
        chat(channel).inbound(base).reply(after, hidden=True)  # owner's reply hidden
        chat(channel).inbound(base).reply(after).inbound(
            after + timedelta(seconds=1), hidden=True
        )  # hidden newest inbound
        chat(channel).inbound(base, hidden=True)  # only a hidden inbound
        chat(channel).reply(before)  # outbound-first, never answered back
        chat(channel).reply(before).inbound(base)  # outbound-first, then the customer
        chat(channel)  # no messages at all
        chat(channel).inbound(before).reply(base).inbound(after)  # wrote again after reply

    ig, wa = "dm", "whatsapp"
    # Instagram's reply window (founder, 2026-11-13).
    chat(ig).inbound(real_now - WINDOW + timedelta(minutes=1))  # window still open
    chat(ig).inbound(real_now - WINDOW)  # closed exactly at the boundary
    chat(ig).inbound(real_now - timedelta(days=30), text="¡gracias!")  # long closed
    chat(ig).inbound(real_now - timedelta(days=30)).reply(real_now - timedelta(days=29)).inbound(
        base
    )  # wrote again: the window reopened
    chat(ig).inbound(real_now - timedelta(days=2)).inbound(
        base, hidden=True
    )  # a hidden inbound still opened Meta's window; the visible one is unanswered
    chat(wa).inbound(real_now - timedelta(days=30))  # WhatsApp: not bounded

    chat(wa).inbound(base).reply(after, menu=True)  # answered only by the menu
    chat(wa).inbound(fresh_in).menu_send("pending", real_now)  # menu still answering
    chat(wa).inbound(base).menu_send("sending", after)  # stuck past STALE_AFTER
    chat(wa).inbound(base).reply(after, menu=True).hand_off()  # «Hablar con alguien»
    chat(wa).inbound(base).reply(after, menu=True).hand_off(paused=False)  # resumed
    chat(wa).inbound(base).hand_off().reply(after)  # handed over, owner answered
    chat(wa).inbound(base).menu_send("failed", after)  # failed automatic send
    chat(wa).inbound(base).menu_send("dead", after)
    chat(wa).inbound(base).reply(after, menu=True, delivery_status="failed")  # Meta: failed
    chat(wa, status="closed").inbound(base).hand_off()  # closed though handed over
    chat(wa).inbound(base).reply(after, menu=True).menu_send("failed", before)  # stale failed
    chat(wa).inbound(base).menu_send("pending", before)  # queued before the inbound

    ids = {c.save(): c for c in chats}
    now = real_now
    expected = {thread_id: awaits_reply(c.snapshot(), now) for thread_id, c in ids.items()}
    assert _awaiting(biz, now) == expected

    waiting = {t for t, w in expected.items() if w}
    pages = _all_pages(biz.tenant_id, filter="por_responder", limit=3, now=now)
    assert set(pages) == waiting
    assert count_inbox(biz.tenant_id, now=now) == len(waiting)
    per_channel = {c: count_inbox(biz.tenant_id, channel=c, now=now) for c in (ig, wa)}
    assert sum(per_channel.values()) == len(waiting)
    # Per channel, by hand from the cases above: dm 3 (unanswered, outbound-first then
    # customer, wrote again) + window open + window reopened + hidden-opened window = 6;
    # whatsapp those 3 + 30-day-old + stuck queue + handed + failed + dead + Meta-failed +
    # queued-before-inbound = 10.
    assert per_channel == {ig: 6, wa: 10}
    assert {c: _counter(biz, c, now) for c in (ig, wa)} == per_channel


def test_instagram_chat_counts_only_while_its_window_is_open() -> None:
    """Founder, 2026-11-13 («Ventana + cerrar chat»): Instagram has no «Cerrar chat» and
    refuses a normal reply after the window, so the chat stops counting when it closes —
    and stays in «todos», an open chat with its window shown closed."""
    biz = _business()
    thanks = _Chat(biz, "dm").inbound(T0, text="¡gracias!").save()

    def seen(now: datetime) -> tuple[list[UUID], int, int, bool]:
        return (
            _all_pages(biz.tenant_id, filter="por_responder", now=now),
            count_inbox(biz.tenant_id, now=now),
            _counter(biz, "dm", now),
            _awaiting(biz, now)[thanks],
        )

    assert seen(T0 + timedelta(hours=1)) == ([thanks], 1, 1, True)
    assert seen(T0 + WINDOW - timedelta(microseconds=1)) == ([thanks], 1, 1, True)
    assert seen(T0 + WINDOW) == ([], 0, 0, False)  # closed AT the boundary
    assert seen(T0 + timedelta(days=30)) == ([], 0, 0, False)

    (row,) = list_inbox(biz.tenant_id, filter="todos", now=T0 + WINDOW).rows
    assert (row.thread_id, row.awaiting_reply, row.window_open) == (thanks, False, False)


def test_instagram_a_new_message_after_a_closed_window_reopens_it_and_counts_again() -> None:
    biz = _business()
    again = T0 + timedelta(days=3)
    chat = _Chat(biz, "dm").inbound(T0).reply(T0 + timedelta(minutes=1)).inbound(again)
    thread_id = chat.save()
    for now, waits in ((again + timedelta(hours=1), True), (again + WINDOW, False)):
        assert _awaiting(biz, now) == {thread_id: waits}
        assert awaits_reply(chat.snapshot(), now) is waits
        assert count_inbox(biz.tenant_id, channel="dm", now=now) == int(waits)


def test_pinned_a_persons_reply_meta_reports_failed_still_answers() -> None:
    biz = _business()
    chat = (
        _Chat(biz, "whatsapp")
        .inbound(T0)
        .reply(T0 + timedelta(minutes=1), delivery_status="failed")
    )
    thread_id = chat.save()
    assert _awaiting(biz) == {thread_id: False}


def test_pinned_any_visible_inbound_row_counts_even_without_text_or_as_stop() -> None:
    """Pins the RULE's side only: any visible inbound `messages` row re-opens the wait —
    one with no text (how a WhatsApp reaction or other non-text type lands: inbound,
    `media_type='other'`) and one whose text is «STOP». Whether ingestion stores a given
    WhatsApp event as an inbound row is `whatsapp.handler`'s concern, not pinned here."""
    biz = _business()
    answered = T0 + timedelta(minutes=1)
    reaction = (
        _Chat(biz, "whatsapp")
        .inbound(T0)
        .reply(answered)
        .inbound(answered + timedelta(seconds=1), text=None)
        .save()
    )
    stop = (
        _Chat(biz, "whatsapp")
        .inbound(T0)
        .reply(answered)
        .inbound(answered + timedelta(seconds=1), text="STOP")
        .save()
    )
    assert _awaiting(biz) == {reaction: True, stop: True}


def test_hiding_one_of_several_customer_messages_keeps_the_chat_waiting() -> None:
    biz = _business()
    one_hidden = _Chat(biz, "whatsapp").inbound(T0).inbound(T0 + timedelta(seconds=1), hidden=True)
    all_hidden = (
        _Chat(biz, "dm").inbound(T0, hidden=True).inbound(T0 + timedelta(seconds=1), hidden=True)
    )
    ids = {one_hidden.save(): one_hidden, all_hidden.save(): all_hidden}
    awaiting = _awaiting(biz)
    assert awaiting == {t: awaits_reply(c.snapshot(), NOW) for t, c in ids.items()}
    assert sorted(awaiting.values()) == [False, True]
    assert awaiting[next(t for t, c in ids.items() if c is one_hidden)] is True


def test_another_business_never_appears() -> None:
    mine, other = _business(), _business()
    my_thread = _thread(mine, "whatsapp")
    for channel in ("whatsapp", "dm", "dm"):
        _thread(other, channel)

    for filter in ("por_responder", "todos"):
        assert _all_pages(mine.tenant_id, filter=filter) == [my_thread]
    assert count_inbox(mine.tenant_id, now=NOW) == 1
    assert count_inbox(other.tenant_id, now=NOW) == 3


def test_comment_threads_are_not_chats() -> None:
    biz = _business()
    chat = _thread(biz, "dm")
    _thread(biz, "comment")
    assert _all_pages(biz.tenant_id, filter="todos") == [chat]


# --------------------------------------------------------------------------------------
# Opt-in benchmark: gated by an environment variable, like
# `test_sentiment_scale_benchmark.py` — `@pytest.mark.slow` alone does not keep it out of
# `just test` / `just test-db`, whose explicit `-m` replaces addopts' `not slow`.
# --------------------------------------------------------------------------------------

_RUN_INBOX_BENCHMARK = os.environ.get("QUALIFY_RUN_INBOX_BENCHMARK") == "1"
_skip_unless_opted_in = pytest.mark.skipif(
    not _RUN_INBOX_BENCHMARK,
    reason=(
        "opt-in only — set QUALIFY_RUN_INBOX_BENCHMARK=1 to run "
        "(never in just test/test-db/CI; see test_sentiment_scale_benchmark.py's "
        "docstring for why -m alone cannot be trusted to keep this out of `just test`)"
    ),
)


def seed_volume(biz: _Biz, chats: int, messages_per_chat: int, waiting_percent: int) -> None:
    """`chats` chats with a message history, bulk-inserted: alternating channels, every
    tenth closed, every sixth WhatsApp one answered by the menu, and the newest message
    from the customer in `waiting_percent` % of the chats (the rest end on a reply)."""
    thread_rows: list[dict[str, Any]] = []
    message_rows: list[dict[str, Any]] = []
    outbox_rows: list[dict[str, Any]] = []
    for i in range(chats):
        channel = "whatsapp" if i % 2 else "dm"
        connection = biz.whatsapp if channel == "whatsapp" else biz.instagram
        thread_id = uuid4()
        start = T0 + timedelta(minutes=i)
        last = start
        last_in: datetime | None = None
        for j in range(messages_per_chat):
            at = start + timedelta(seconds=j)
            # Alternating history; the newest message decides whether the chat waits.
            ends_inbound = i % 100 < waiting_percent
            outbound = j % 2 == 1 if j < messages_per_chat - 1 else not ends_inbound
            external = f"m-{uuid4().hex}"
            message_rows.append(
                {
                    "tenant_id": biz.tenant_id,
                    "thread_id": thread_id,
                    "connection_id": connection,
                    "external_message_id": external,
                    "direction": "outbound" if outbound else "inbound",
                    "text": "Hola",
                    "posted_at": at,
                    "shape_version": "test",
                }
            )
            if outbound and channel == "whatsapp":
                outbox_rows.append(
                    {
                        "tenant_id": biz.tenant_id,
                        "connection_id": connection,
                        "thread_id": thread_id,
                        "kind": "automation" if i % 6 == 1 else "reply",
                        "payload": _PAYLOAD,
                        "status": "sent",
                        "wamid": external,
                        "created_at": at,
                    }
                )
            if not outbound:
                last_in = at
            last = at
        thread_rows.append(
            {
                "id": thread_id,
                "tenant_id": biz.tenant_id,
                "connection_id": connection,
                "channel": channel,
                "external_thread_id": f"ext-{thread_id.hex[:16]}",
                "status": "closed" if i % 10 == 0 else "open",
                "last_message_at": last,
                "last_inbound_at": last_in,
            }
        )
    with tenant_session(biz.tenant_id) as session:
        session.execute(insert(Thread), thread_rows)
        session.execute(insert(Message), message_rows)
        if outbox_rows:
            session.execute(insert(WhatsAppOutboxItem), outbox_rows)


@pytest.mark.slow
@_skip_unless_opted_in
@pytest.mark.parametrize("waiting_percent", [67, 2])
def test_a_page_of_50_chats_has_p95_under_300_ms(waiting_percent: int) -> None:
    """Opt-in only — `QUALIFY_RUN_INBOX_BENCHMARK=1 pytest -m slow -k inbox`.

    3,000 chats x 12 messages. Two shares of waiting chats, because `por_responder` cost
    depends on it: the page is scanned in `ix_thread_inbox_order` order and the rule is
    evaluated chat by chat until 50 waiting chats are found. With most chats waiting
    (67 %, the best case) that stops after ~80 chats; with few waiting — the normal case,
    2 % here — it evaluates the rule over nearly every open chat, and `count_inbox` always
    does so over all of them. The remedy, if it is ever too slow, is the denormalised
    `threads.last_person_reply_at` proposed in `inbox.awaiting`, not another store."""
    biz = _business()
    seed_volume(biz, chats=3000, messages_per_chat=12, waiting_percent=waiting_percent)
    # Fresh bulk rows have no planner statistics yet (autovacuum would add them in
    # production); refresh them as the owner when its DSN is set, as `just test-db` has.
    owner_dsn = os.environ.get("QUALIFY_MIGRATION_DSN")
    if owner_dsn:
        import psycopg

        with psycopg.connect(owner_dsn.replace("+psycopg", ""), autocommit=True) as conn:
            conn.execute("ANALYZE threads, messages, whatsapp_outbox")
    waiting = count_inbox(biz.tenant_id)
    timings: dict[str, list[float]] = {"todos": [], "por_responder": [], "count": []}
    for _ in range(11):
        for filter in ("todos", "por_responder"):
            started = time.perf_counter()
            page = list_inbox(biz.tenant_id, filter=filter, limit=50, now=NOW)  # type: ignore[arg-type]
            timings[filter].append(time.perf_counter() - started)
            assert len(page.rows) == (50 if filter == "todos" else min(50, waiting))
        started = time.perf_counter()
        count_inbox(biz.tenant_id)
        timings["count"].append(time.perf_counter() - started)
    # The first round is the warm-up.
    p95 = {k: statistics.quantiles(v[1:], n=20)[-1] for k, v in timings.items()}
    print(
        f"inbox, 3000 chats, {waiting_percent} % waiting ({waiting}): "
        + ", ".join(f"{k} p95 {v * 1000:.1f} ms" for k, v in p95.items())
    )
    assert max(p95["todos"], p95["por_responder"]) < 0.300, p95
