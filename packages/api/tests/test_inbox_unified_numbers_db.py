"""One number of the unified list (m-25029799, BU-A11 second part), against Postgres.

WhatsApp's own chat list showed ONE number at a time; its «Abiertos» was that number's
open chats. The unified list of «Por responder» takes it over: `connection_id` narrows any
filter to one account, and `inbox_counts` counts every filter per account in its one
statement. Proven here on a business with two WhatsApp numbers and an Instagram account:

- every filter, per number: the list's pages, `count_inbox` and the chip all agree, and
  the numbers add up to the channel;
- «Todos» on one number IS what WhatsApp's «Abiertos» listed for it (the WhatsApp
  repository's own open chats of that number);
- another business's number lists and counts nothing (RLS, not a hand filter).

Seeding reuses `test_inbox_unified_db.py`'s helpers (fresh tenants per test).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from packages.api.tests.test_inbox_unified_db import (
    _all_pages,
    _Biz,
    _business,
    _Chat,
    _connection,
    _statements,
)
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.connections.models import SocialConnection
from qualify_api.inbox.unified import (
    INBOX_FILTERS,
    NO_JIT_SQL,
    count_inbox,
    inbox_counts,
)
from qualify_api.whatsapp.chats import PostgresChatRepository

pytestmark = pytest.mark.db


def _second_number(biz: _Biz) -> _Biz:
    """The same business with another WhatsApp number: chats made with the returned
    `_Biz` land on that number (`_Chat.connection`)."""
    with tenant_session(biz.tenant_id) as session:
        first = session.scalar(select(SocialConnection).where(SocialConnection.id == biz.whatsapp))
        assert first is not None
        other = _connection(
            biz.tenant_id,
            first.platform_app_id,
            first.brand_id,
            first.connected_by_user_id,
            "whatsapp",
        )
        session.add(other)
        session.flush()
        return _Biz(biz.tenant_id, biz.instagram, other.id)


def _seed(biz: _Biz, now: datetime) -> tuple[UUID, UUID]:
    """Chats on both numbers and Instagram; returns (first number, second number)."""
    base = now - timedelta(minutes=30)
    chats: list[_Chat] = []

    def chat(owner: _Biz, channel: str, **kwargs: object) -> _Chat:
        c = _Chat(owner, channel, **kwargs)  # type: ignore[arg-type]
        chats.append(c)
        return c

    second = _second_number(biz)
    for owner in (biz, second):
        chat(owner, "whatsapp").inbound(base)  # waits
        chat(owner, "whatsapp").inbound(base).reply(base + timedelta(minutes=1))  # answered
        chat(owner, "whatsapp", status="closed").inbound(base)  # closed
        chat(owner, "whatsapp")  # no messages yet: open, listed under «Todos»
    chat(second, "whatsapp").inbound(base - timedelta(days=3))  # a second one waiting there
    chat(biz, "dm").inbound(base)  # Instagram waits
    chat(biz, "dm").inbound(base).reply(base + timedelta(minutes=1))  # Instagram answered
    for c in chats:
        c.save()
    return biz.whatsapp, second.whatsapp


def test_every_filter_per_number_agrees_with_its_list_and_adds_up() -> None:
    biz = _business()
    now = datetime.now(UTC)
    first, second = _seed(biz, now)
    chips = inbox_counts(biz.tenant_id, now=now)
    for f in INBOX_FILTERS:
        per_number = 0
        for number in (first, second):
            listed = _all_pages(biz.tenant_id, filter=f, connection_id=number, now=now, limit=2)
            assert len(set(listed)) == len(listed), (f, number)  # no repeats across pages
            n = count_inbox(biz.tenant_id, filter=f, connection_id=number, now=now)  # type: ignore[arg-type]
            assert n == len(listed) == chips.count(f, connection_id=number), (f, number)  # type: ignore[arg-type]
            assert chips.count(f, "whatsapp", connection_id=number) == n  # type: ignore[arg-type]
            # A number is never an Instagram account: narrowed to Instagram, nothing.
            assert chips.count(f, "dm", connection_id=number) == 0  # type: ignore[arg-type]
            assert (
                count_inbox(
                    biz.tenant_id,
                    filter=f,  # type: ignore[arg-type]
                    channel="dm",
                    connection_id=number,
                    now=now,
                )
                == 0
            )
            per_number += n
        assert per_number == chips.count(f, "whatsapp"), f  # type: ignore[arg-type]
    # The figures this seed fixes: 2 + 1 waiting, 3 + 2 open, 1 + 1 closed.
    assert chips.count("por_responder", connection_id=first) == 1
    assert chips.count("por_responder", connection_id=second) == 2
    assert chips.count("todos", connection_id=first) == 3
    assert chips.count("todos", connection_id=second) == 4
    assert chips.count("cerrados", connection_id=second) == 1


def test_todos_on_a_number_is_what_whatsapps_abiertos_listed() -> None:
    """WhatsApp › Chats «Abiertos» (`whatsapp_chats_vm.filter_threads`): the chats of the
    selected number whose status is open — the repository read it from, narrowed to
    `status='open'`. The unified list's «Todos» on that number lists the same chats."""
    biz = _business()
    now = datetime.now(UTC)
    numbers = _seed(biz, now)
    repo = PostgresChatRepository()
    for number in numbers:
        abiertos = {
            r.id
            for r in repo.list_threads(
                tenant_id=biz.tenant_id,
                connection_id=number,
                status="open",
                limit=200,
                before=None,
            )
        }
        assert abiertos
        assert set(_all_pages(biz.tenant_id, filter="todos", connection_id=number, now=now)) == (
            abiertos
        )
        cerrados = {
            r.id
            for r in repo.list_threads(
                tenant_id=biz.tenant_id,
                connection_id=number,
                status="closed",
                limit=200,
                before=None,
            )
        }
        assert set(_all_pages(biz.tenant_id, filter="cerrados", connection_id=number, now=now)) == (
            cerrados
        )


def test_another_business_number_lists_and_counts_nothing() -> None:
    mine, theirs = _business(), _business()
    now = datetime.now(UTC)
    my_numbers = _seed(mine, now)
    their_number = _seed(theirs, now)[0]
    for f in INBOX_FILTERS:
        assert _all_pages(mine.tenant_id, filter=f, connection_id=their_number, now=now) == []
        assert count_inbox(mine.tenant_id, filter=f, connection_id=their_number, now=now) == 0  # type: ignore[arg-type]
    chips = inbox_counts(mine.tenant_id, now=now)
    assert str(their_number) not in chips.by_connection
    assert set(chips.by_connection) == {
        str(mine.instagram),
        *(str(n) for n in my_numbers),
    }


def test_the_chips_with_numbers_are_still_one_statement() -> None:
    biz = _business()
    now = datetime.now(UTC)
    numbers = _seed(biz, now)
    with _statements() as seen:
        chips = inbox_counts(biz.tenant_id, now=now)
    assert [s for s in seen if s != NO_JIT_SQL] == [seen[-1]] and len(seen) == 2
    assert chips.connection_channels[str(biz.instagram)] == "dm"
    for number in numbers:
        assert chips.connection_channels[str(number)] == "whatsapp"
