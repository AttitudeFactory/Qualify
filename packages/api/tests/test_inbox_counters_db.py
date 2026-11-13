"""Every «Por responder» number the owner sees against the unified list (m-25017859, BU-A3).

The test that proves a number in the menu can never disagree with the list it opens: on
one tenant seeded with every case of the rule (`inbox.awaiting`) on both channels, the
menu counters (`attention.counts`), Inicio (`home.summary.people_waiting`), the chips
(`inbox_counts`), `count_inbox`, the unified list's pages and the per-channel lists'
`awaiting_reply` column all agree. Then the fields the shared row needs, the
expired-without-an-answer flag and count (boundary, a later inbound, a closed chat, a
WhatsApp chat never flagged, the period), and RLS.

Seeding reuses `test_inbox_unified_db.py`'s helpers (fresh tenants per test).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from packages.api.tests.test_inbox_unified_db import (
    T0,
    _all_pages,
    _Biz,
    _business,
    _Chat,
    _statements,
)
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.attention import PostgresPendingCounts
from qualify_api.conversations.contracts import ChannelRegistry
from qualify_api.conversations.memory_source import (
    MemoryConversationSender,
    MemoryConversationSource,
)
from qualify_api.conversations.outbox import PostgresConversationOutboxRepository
from qualify_api.conversations.repository import PostgresConversationRepository
from qualify_api.conversations.service import ConversationService, ThreadNotFound
from qualify_api.home.summary import read_home_counts
from qualify_api.inbox.awaiting import awaits_reply, expired_unanswered
from qualify_api.inbox.unified import (
    EXPIRED_UNANSWERED_WITHIN,
    INBOX_FILTERS,
    NO_JIT_SQL,
    count_expired_unanswered,
    count_inbox,
    inbox_counts,
    list_inbox,
)
from qualify_api.whatsapp.chats import PostgresChatRepository
from qualify_api.whatsapp.window import WINDOW

pytestmark = pytest.mark.db


def _seed_every_case(biz: _Biz, now: datetime) -> dict[UUID, _Chat]:
    """The rule's cases on both channels, relative to `now` (the per-channel lists judge
    at the database's `now()`, so instants stay well away from every boundary)."""
    base = now - timedelta(minutes=30)
    after = base + timedelta(minutes=1)
    before = base - timedelta(minutes=1)
    chats: list[_Chat] = []

    def chat(channel: str, **kwargs: Any) -> _Chat:
        c = _Chat(biz, channel, **kwargs)
        chats.append(c)
        return c

    for channel in ("whatsapp", "dm"):
        chat(channel).inbound(base)  # unanswered
        chat(channel).inbound(base).reply(after)  # answered
        chat(channel, status="closed").inbound(base)  # closed
        chat(channel).inbound(base).reply(after, hidden=True)  # owner's reply hidden
        chat(channel).inbound(base, hidden=True)  # only a hidden inbound
        chat(channel).reply(before).inbound(base)  # outbound first, then the customer
        chat(channel).inbound(before).reply(base).inbound(after)  # wrote again
        chat(channel)  # no messages
    chat("dm").inbound(now - timedelta(days=3))  # window closed: expired, not waiting
    chat("dm").inbound(now - timedelta(days=30), text="¡gracias!")  # long expired
    chat("whatsapp").inbound(now - timedelta(days=30))  # WhatsApp: still waits
    chat("whatsapp").inbound(base).reply(after, menu=True)  # answered only by the menu
    chat("whatsapp").inbound(base).reply(after, menu=True).hand_off()  # handed to a person
    chat("whatsapp").inbound(base).menu_send("failed", after)  # failed automatic send
    chat("whatsapp").inbound(now - timedelta(minutes=1)).menu_send("pending", now)  # menu busy
    chat("whatsapp").inbound(base).menu_send("sending", after)  # stuck queue
    chat("whatsapp", status="closed").inbound(base).hand_off()  # closed though handed
    return {c.save(): c for c in chats}


def test_every_owner_visible_count_equals_the_unified_list_on_every_case() -> None:
    biz = _business()
    now = datetime.now(UTC)
    chats = _seed_every_case(biz, now)
    expected = {t: awaits_reply(c.snapshot(), now) for t, c in chats.items()}
    by_channel = {
        ch: {t for t, w in expected.items() if w and chats[t].channel == ch}
        for ch in ("dm", "whatsapp")
    }
    # dm: unanswered, outbound-first, wrote again = 3. whatsapp: those 3 + 30-day-old +
    # handed + failed + stuck = 7 (menu-only, menu busy and closed do not count).
    assert {ch: len(ids) for ch, ids in by_channel.items()} == {"dm": 3, "whatsapp": 7}

    listed = set(_all_pages(biz.tenant_id, filter="por_responder", now=now, limit=2))
    assert listed == by_channel["dm"] | by_channel["whatsapp"]

    menu = PostgresPendingCounts(clock=lambda: now).read(biz.tenant_id)
    chips = inbox_counts(biz.tenant_id, now=now)
    for ch, attr in (("dm", "messages"), ("whatsapp", "whatsapp")):
        n = count_inbox(biz.tenant_id, channel=ch, now=now)
        assert n == len(by_channel[ch]) == getattr(menu, attr), ch
        assert chips.count("por_responder", ch) == n, ch
    assert read_home_counts(biz.tenant_id, now=now).people_waiting == menu.messages
    assert chips.por_responder == count_inbox(biz.tenant_id, now=now) == len(listed)
    for f in INBOX_FILTERS:
        for ch in (None, "dm", "whatsapp"):
            assert chips.count(f, ch) == count_inbox(
                biz.tenant_id,
                filter=f,
                channel=ch,
                now=now,  # type: ignore[arg-type]
            ), (f, ch)

    # The per-channel lists carry the same verdict, from the same fragment.
    wa_rows = PostgresChatRepository().list_threads(
        tenant_id=biz.tenant_id, connection_id=None, status=None, limit=200, before=None
    )
    assert {r.id for r in wa_rows if r.awaiting_reply} == by_channel["whatsapp"]
    ig_rows = PostgresConversationRepository().list_threads(
        tenant_id=biz.tenant_id, channels=["dm"], limit=200
    )
    assert {r.id for r in ig_rows if r.awaiting_reply} == by_channel["dm"]
    assert all(r.awaiting_reply is not None for r in ig_rows)
    single = PostgresConversationRepository().get_thread(
        tenant_id=biz.tenant_id, thread_id=ig_rows[0].id
    )
    assert single is not None and single.awaiting_reply is None  # not computed there


def test_the_chips_are_one_statement() -> None:
    biz = _business()
    _Chat(biz, "dm").inbound(T0).save()
    with _statements() as seen:
        inbox_counts(biz.tenant_id, now=T0 + timedelta(hours=1))
    # One read, plus the transaction-local `SET LOCAL jit = off` (no round trip of data).
    assert [s for s in seen if s != NO_JIT_SQL] == [seen[-1]] and len(seen) == 2


def test_the_row_carries_what_the_shared_row_draws() -> None:
    biz = _business()
    now = T0 + timedelta(hours=1)
    wa_id = _Chat(biz, "whatsapp").inbound(T0).hand_off().save()  # payment «review»
    ig_id = _Chat(biz, "dm", name="Ana").inbound(T0).reply(T0 + timedelta(minutes=1)).save()
    closed_review = _Chat(biz, "whatsapp", status="closed").inbound(T0).hand_off().save()
    with tenant_session(biz.tenant_id) as session:
        user_id = session.execute(text("SELECT id FROM users LIMIT 1")).scalar_one()
        session.execute(
            text(
                "UPDATE threads SET assigned_agent_id = :u, counterpart_username = 'ana.co', "
                "counterpart_avatar_url = 'https://cdn.example/a.jpg' WHERE id = :ig"
            ),
            {"u": user_id, "ig": ig_id},
        )

    by_id = {r.thread_id: r for r in list_inbox(biz.tenant_id, filter="todos", now=now).rows}
    wa, ig = by_id[wa_id], by_id[ig_id]
    assert (wa.payment_review, wa.payment_awaiting, wa.automation_paused) == (True, False, True)
    assert wa.counterpart_phone is not None and wa.assigned_agent_id is None
    assert (ig.counterpart_name, ig.counterpart_username) == ("Ana", "ana.co")
    assert ig.counterpart_avatar_url == "https://cdn.example/a.jpg"
    assert ig.assigned_agent_id == user_id and ig.last_message_direction == "outbound"
    assert ig.window_closes_at == T0 + WINDOW and ig.payment_status is None

    # «Pago por revisar» = the WhatsApp screen's own chip: open OR closed — closing a chat
    # does not settle its payment.
    review = list_inbox(biz.tenant_id, filter="pago_por_revisar", now=now).rows
    assert {r.thread_id for r in review} == {wa_id, closed_review}
    assert {r.thread_id: r.is_closed for r in review}[closed_review] is True
    assert inbox_counts(biz.tenant_id, now=now).payment_review == 2
    assert count_inbox(biz.tenant_id, filter="pago_por_revisar", now=now) == 2


def test_expired_unanswered_flag_and_count() -> None:
    biz = _business()
    now = T0 + timedelta(days=10)
    at_boundary = _Chat(biz, "dm").inbound(now - WINDOW)  # closed exactly now
    almost = _Chat(biz, "dm").inbound(now - WINDOW + timedelta(seconds=1))  # still open
    answered = (
        _Chat(biz, "dm")
        .inbound(now - timedelta(days=2))
        .reply(now - timedelta(days=2) + timedelta(minutes=5))
    )
    again = (  # expired once, then the customer wrote again: waiting, not expired
        _Chat(biz, "dm").inbound(now - timedelta(days=5)).inbound(now - timedelta(hours=1))
    )
    closed = _Chat(biz, "dm", status="closed").inbound(now - timedelta(days=2))
    whatsapp = _Chat(biz, "whatsapp").inbound(now - timedelta(days=2))  # never flagged
    recent = _Chat(biz, "dm").inbound(now - timedelta(days=3))  # closed 2 days ago
    old = _Chat(biz, "dm").inbound(  # window closed 7 days + 1 s ago: outside the period
        now - WINDOW - EXPIRED_UNANSWERED_WITHIN - timedelta(seconds=1)
    )
    chats = {
        name: (c.save(), c)
        for name, c in {
            "at_boundary": at_boundary,
            "almost": almost,
            "answered": answered,
            "again": again,
            "closed": closed,
            "whatsapp": whatsapp,
            "recent": recent,
            "old": old,
        }.items()
    }
    rows = {
        r.thread_id: r
        for f in ("todos", "cerrados")
        for r in list_inbox(biz.tenant_id, filter=f, now=now, limit=100).rows  # type: ignore[arg-type]
    }
    flagged = {name for name, (t, _) in chats.items() if rows[t].window_expired_unanswered}
    assert flagged == {"at_boundary", "recent", "old"}
    for name, (thread_id, chat) in chats.items():
        row = rows[thread_id]
        assert row.window_expired_unanswered is expired_unanswered(chat.snapshot(), now), name
        assert not (row.window_expired_unanswered and row.awaiting_reply), name
        if row.window_expired_unanswered:
            assert row.window_expired_at == chat.last_inbound_at + WINDOW, name
        else:
            assert row.window_expired_at is None, name
    assert rows[chats["almost"][0]].awaiting_reply and rows[chats["again"][0]].awaiting_reply

    in_period = {chats["at_boundary"][0], chats["recent"][0]}
    assert set(_all_pages(biz.tenant_id, filter="ventana_vencida", now=now, limit=1)) == in_period
    assert count_expired_unanswered(biz.tenant_id, now=now) == 2
    assert inbox_counts(biz.tenant_id, now=now).expired_unanswered == 2
    assert count_expired_unanswered(biz.tenant_id, now=now, within=timedelta(days=30)) == 3
    assert count_expired_unanswered(biz.tenant_id, now=now, within=timedelta(hours=1)) == 1


def test_another_business_never_appears_in_any_count() -> None:
    mine, other = _business(), _business()
    now = T0 + timedelta(days=3)
    _Chat(mine, "dm").inbound(now - timedelta(days=2)).save()  # expired
    _Chat(mine, "whatsapp").inbound(now - timedelta(hours=1)).save()  # waiting
    for _ in range(2):
        _Chat(other, "dm").inbound(now - timedelta(days=2)).save()
        _Chat(other, "dm").inbound(now - timedelta(hours=1)).save()
        _Chat(other, "whatsapp").inbound(now - timedelta(hours=1)).hand_off().save()

    def seen(biz: _Biz) -> tuple[int, ...]:
        menu = PostgresPendingCounts(clock=lambda: now).read(biz.tenant_id)
        chips = inbox_counts(biz.tenant_id, now=now)
        return (
            menu.messages,
            menu.whatsapp,
            read_home_counts(biz.tenant_id, now=now).people_waiting,
            chips.por_responder,
            chips.count("todos"),
            chips.payment_review,
            count_expired_unanswered(biz.tenant_id, now=now),
        )

    assert seen(mine) == (0, 1, 0, 1, 2, 0, 1)
    assert seen(other) == (2, 2, 2, 4, 6, 2, 2)


def test_a_chat_whose_every_message_was_unsent_is_never_listed_nor_counted() -> None:
    """m-25018661 hides it from the Instagram list; the unified list and every count hide
    it with the SAME predicate, so no number counts a chat nobody can open."""
    biz = _business()
    now = datetime.now(UTC)
    gone = _Chat(biz, "dm").inbound(now - timedelta(minutes=5), unsent=True).save()
    gone_closed = (
        _Chat(biz, "dm", status="closed").inbound(now - timedelta(minutes=5), unsent=True).save()
    )
    kept = (  # one unsent, one still there: listed, like on the Instagram screen
        _Chat(biz, "dm")
        .inbound(now - timedelta(minutes=6))
        .inbound(now - timedelta(minutes=5), unsent=True)
        .save()
    )
    ig_list = PostgresConversationRepository().list_threads(
        tenant_id=biz.tenant_id, channels=["dm"], limit=200
    )
    assert {r.id for r in ig_list} == {kept}

    listed = {
        r.thread_id
        for f in INBOX_FILTERS
        for r in list_inbox(biz.tenant_id, filter=f, now=now, limit=100).rows  # type: ignore[arg-type]
    }
    assert listed == {kept} and not listed & {gone, gone_closed}
    chips = inbox_counts(biz.tenant_id, now=now)
    for f in INBOX_FILTERS:
        assert chips.count(f) == count_inbox(biz.tenant_id, filter=f, now=now), f  # type: ignore[arg-type]
    assert (chips.count("todos"), chips.count("cerrados"), chips.por_responder) == (1, 0, 1)
    menu = PostgresPendingCounts(clock=lambda: now).read(biz.tenant_id)
    assert menu.messages == 1 == read_home_counts(biz.tenant_id, now=now).people_waiting
    with pytest.raises(ThreadNotFound):
        _service().get_dm_thread(tenant_id=biz.tenant_id, thread_id=gone)


def _service() -> ConversationService:
    registry = ChannelRegistry()
    registry.register(source=MemoryConversationSource(), sender=MemoryConversationSender())
    return ConversationService(
        repository=PostgresConversationRepository(),
        outbox=PostgresConversationOutboxRepository(),
        registry=registry,
    )


def test_a_chat_beyond_the_screens_newest_200_opens_by_id() -> None:
    biz, other = _business(), _business()
    now = datetime.now(UTC)
    oldest = _Chat(biz, "dm").inbound(now - timedelta(hours=5)).save()
    for i in range(200):
        _Chat(biz, "dm").inbound(now - timedelta(minutes=200 - i)).reply(
            now - timedelta(minutes=199 - i, seconds=30)
        ).save()
    loaded = PostgresConversationRepository().list_threads(
        tenant_id=biz.tenant_id, channels=["dm"], limit=200
    )
    assert oldest not in {r.id for r in loaded}  # what the Instagram pane has in memory

    view = _service().get_dm_thread(tenant_id=biz.tenant_id, thread_id=oldest)
    (row,) = [
        r
        for r in list_inbox(biz.tenant_id, filter="por_responder", now=now, limit=100).rows
        if r.thread_id == oldest
    ]
    assert view.thread.id == oldest and view.thread.connection_id == biz.instagram
    assert view.awaiting_reply is True is row.awaiting_reply
    wa = _Chat(biz, "whatsapp").inbound(now).save()
    for tenant, thread in ((other.tenant_id, oldest), (biz.tenant_id, wa)):
        with pytest.raises(ThreadNotFound):
            _service().get_dm_thread(tenant_id=tenant, thread_id=thread)
