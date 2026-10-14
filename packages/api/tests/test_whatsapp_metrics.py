"""WA-17 — conversation metrics over the in-memory repository (no database).

Table-driven: entry classification (command, ice breaker, QR prefix, keyword, «directo»),
orders/handoffs counting by range, and the first-human-response pairing — handed-off
threads, never-automated threads, automated threads without a handoff (no pair), and
waits nobody answered. `test_whatsapp_metrics_repository_db.py` covers the SQL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.whatsapp import handler
from qualify_api.whatsapp.menus.schema import Command, EntryConfig, IceBreaker
from qualify_api.whatsapp.metrics import (
    CTX_HANDOFF,
    NO_CURRENCY,
    ConnectionNotFound,
    ConversationMetricsService,
    EntryCount,
    EntryMatch,
    InvalidRange,
    MemoryMetricsRepository,
    MessageFact,
    MetricsRows,
    ThreadFact,
    aggregate,
    classify_entry,
    p90_nearest_rank,
    resolve_range,
)
from qualify_api.whatsapp.orders import order_record_from_handoff

TENANT = UUID("a1000000-0000-4000-8000-00000000000a")
OTHER = UUID("b1000000-0000-4000-8000-00000000000b")
CONN = UUID("a4000000-0000-4000-8000-00000000000a")
SINCE = datetime(2026, 10, 1, tzinfo=UTC)
UNTIL = datetime(2026, 10, 8, tzinfo=UTC)
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)

ENTRY = EntryConfig(
    keywords={"Menú": "home", "domicilio": "home"},
    ice_breakers=[IceBreaker(text="Quiero ver el menú", node="home")],
    commands=[Command(name="pedido", hint="Hacer un pedido", node="home")],
)
QR = {
    "mostrador": "Hola, vengo del mostrador",
    "empaque": "Hola, vengo del empaque",
    "empaque-promo": "Hola, vengo del empaque promo",
}


def at(day: int, hour: int = 12, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, second, tzinfo=UTC)


# ======================================================================================
# Entry classification
# ======================================================================================


@pytest.mark.parametrize(
    ("first_text", "expected"),
    [
        ("/pedido", EntryMatch("command", "pedido")),
        ("/PEDIDO dos hamburguesas", EntryMatch("command", "pedido")),
        ("/desconocido", EntryMatch("directo")),
        ("Quiero ver el menú", EntryMatch("ice_breaker", "Quiero ver el menú")),
        ("  quiero VER el menu ", EntryMatch("ice_breaker", "Quiero ver el menú")),
        ("Hola, vengo del mostrador", EntryMatch("qr", "mostrador")),
        ("hola, vengo del MOSTRADOR y quiero pedir", EntryMatch("qr", "mostrador")),
        # Longest matching prefix wins.
        ("Hola, vengo del empaque promo 2x1", EntryMatch("qr", "empaque-promo")),
        ("Hola, vengo del empaque", EntryMatch("qr", "empaque")),
        ("MENU", EntryMatch("keyword", "menu")),
        ("Domicilio", EntryMatch("keyword", "domicilio")),
        ("menú por favor", EntryMatch("directo")),
        ("Hola", EntryMatch("directo")),
        (None, EntryMatch("directo")),
        ("   ", EntryMatch("directo")),
    ],
)
def test_classify_entry(first_text: str | None, expected: EntryMatch) -> None:
    assert classify_entry(first_text, ENTRY, QR) == expected


def test_qr_wins_over_keyword_with_the_same_text() -> None:
    """The backlog maps each QR prefill to a keyword: the channel is the attribution."""
    entry = EntryConfig(keywords={"Hola, vengo del mostrador": "home"})
    assert classify_entry("Hola, vengo del mostrador", entry, QR) == EntryMatch("qr", "mostrador")
    assert classify_entry("Hola, vengo del mostrador", entry, {}) == EntryMatch(
        "keyword", "hola, vengo del mostrador"
    )


def test_without_a_menu_only_qr_or_directo() -> None:
    assert classify_entry("/pedido", None, QR) == EntryMatch("directo")
    assert classify_entry("Hola, vengo del mostrador", None, QR) == EntryMatch("qr", "mostrador")


def test_handoff_key_mirrors_the_handler() -> None:
    assert CTX_HANDOFF == handler.CTX_HANDOFF


# ======================================================================================
# Builders
# ======================================================================================


def handoff_ctx(when: datetime, reason: str = "human_requested") -> dict[str, Any]:
    return {CTX_HANDOFF: {"reason": reason, "summary": {}, "at": when.isoformat()}}


def order_ctx(when: datetime, total: str, currency: str | None = "COP") -> dict[str, Any]:
    record = order_record_from_handoff(
        {
            "order_confirmed": True,
            "order": [{"product_id": "p1", "name": "Combo", "qty": 1, "price": total}],
            "total": total,
            "currency": currency,
        },
        confirmed_at=when,
        source_message_id="wamid.x",
    )
    assert record is not None
    return {"_order": record}


class Thread:
    def __init__(
        self,
        first_text: str | None = "Hola",
        *,
        context: dict[str, Any] | None = None,
        automated: bool = False,
    ) -> None:
        self.id = uuid4()
        self.first_text = first_text
        self.context = context or {}
        self.automated = automated
        self.messages: list[MessageFact] = []

    def inbound(self, when: datetime) -> Thread:
        self.messages.append(MessageFact(self.id, "inbound", when))
        return self

    def out(self, when: datetime, kind: str | None, status: str | None = "delivered") -> Thread:
        self.messages.append(MessageFact(self.id, "outbound", when, kind, status))
        return self

    def fact(self) -> ThreadFact:
        firsts = sorted(m.at for m in self.messages if m.direction == "inbound")
        return ThreadFact(
            thread_id=self.id,
            first_inbound_at=firsts[0] if firsts else None,
            first_inbound_text=self.first_text if firsts else None,
            context=self.context,
            automated=self.automated,
        )


def rows(*threads: Thread, send_failed: int = 0, entry: EntryConfig | None = ENTRY) -> MetricsRows:
    return MetricsRows(
        threads=[t.fact() for t in threads],
        messages=[m for t in threads for m in t.messages],
        send_failed=send_failed,
        entry=entry,
    )


def run(*threads: Thread, **kwargs: Any) -> Any:
    return aggregate(rows(*threads, **kwargs), connection_id=CONN, since=SINCE, until=UNTIL)


# ======================================================================================
# Threads opened
# ======================================================================================


def test_threads_opened_counts_only_first_inbound_in_range_and_groups_by_entry() -> None:
    result = aggregate(
        rows(
            Thread("/pedido").inbound(at(2)),
            Thread("Hola, vengo del mostrador").inbound(at(3)),
            Thread("hola, vengo del mostrador!").inbound(at(4)),
            Thread("menu").inbound(at(5)),
            Thread("Hola").inbound(at(6)),
            Thread(None).inbound(at(6)),  # media first message
            # Started before the range: active now, but not opened now.
            Thread("menu").inbound(at(1) - timedelta(days=3)).inbound(at(2)),
            # Starts at `until` exactly: outside the half-open range.
            Thread("menu").inbound(UNTIL),
        ),
        connection_id=CONN,
        since=SINCE,
        until=UNTIL,
        qr_prefixes=QR,
    )
    assert result.threads_opened == 6
    assert result.threads_opened_by_entry == (
        EntryCount("directo", None, 2),
        EntryCount("qr", "mostrador", 2),
        EntryCount("command", "pedido", 1),
        EntryCount("keyword", "menu", 1),
    )


# ======================================================================================
# Orders and handoffs
# ======================================================================================


def test_orders_confirmed_and_totals_per_currency() -> None:
    result = run(
        Thread(context=order_ctx(at(2), "35000.00")).inbound(at(2)),
        Thread(context=order_ctx(at(3), "15000.50")).inbound(at(3)),
        Thread(context=order_ctx(at(3), "12.00", currency="USD")).inbound(at(3)),
        Thread(context=order_ctx(at(4), "1.00", currency=None)).inbound(at(4)),
        # Confirmed after the range (the thread is still active inside it).
        Thread(context=order_ctx(UNTIL + timedelta(hours=1), "99.00")).inbound(at(7)),
        Thread().inbound(at(2)),  # no order
    )
    assert result.orders_confirmed == 4
    assert result.orders_total == {
        "COP": Decimal("50000.50"),
        "USD": Decimal("12.00"),
        NO_CURRENCY: Decimal("1.00"),
    }


def test_handoffs_in_range_split_by_reason() -> None:
    result = run(
        Thread(context=handoff_ctx(at(2), "human_requested")).inbound(at(2)),
        Thread(context=handoff_ctx(at(3), "human_requested")).inbound(at(3)),
        Thread(context=handoff_ctx(at(4), "order_confirmed")).inbound(at(4)),
        Thread(context=handoff_ctx(SINCE - timedelta(seconds=1))).inbound(at(2)),
        Thread(context={CTX_HANDOFF: {"reason": "x", "at": "not-a-date"}}).inbound(at(2)),
        Thread(context={CTX_HANDOFF: {"at": at(5).isoformat()}}).inbound(at(5)),
    )
    assert result.handoffs == 4
    assert result.handoffs_by_reason == {
        "human_requested": 2,
        "order_confirmed": 1,
        "unknown": 1,
    }


# ======================================================================================
# First human response
# ======================================================================================


@pytest.mark.parametrize(
    ("thread", "expected_seconds", "awaiting"),
    [
        pytest.param(
            # Never automated: from the first inbound to the first person's reply.
            Thread().inbound(at(2, 10)).inbound(at(2, 10, 5)).out(at(2, 10, 20), "reply"),
            1200.0,
            0,
            id="never-automated",
        ),
        pytest.param(
            # Handed off: from the inbound that triggered the handoff (10:30:00, stamped
            # 10:30:02 by the handler), not from the thread's first message; the menu's
            # own answers do not count as a response.
            Thread(context=handoff_ctx(at(2, 10, 30, 2)), automated=True)
            .inbound(at(2, 10))
            .out(at(2, 10, 0, 1), "automation")
            .inbound(at(2, 10, 30))
            .out(at(2, 10, 30, 1), "automation")
            .out(at(2, 10, 35), "reply"),
            300.0,
            0,
            id="handoff-from-trigger-inbound",
        ),
        pytest.param(
            # Handoff whose triggering inbound is not loaded: the stamp itself.
            Thread(context=handoff_ctx(at(2, 10)), automated=True).out(at(2, 10, 1), "reply"),
            60.0,
            0,
            id="handoff-without-trigger-message",
        ),
        pytest.param(
            # The reply lands after `until` but inside the horizon: still answered.
            Thread().inbound(UNTIL - timedelta(minutes=5)).out(UNTIL + timedelta(hours=2), "reply"),
            7500.0,
            0,
            id="answered-after-until",
        ),
        pytest.param(
            Thread().inbound(at(2)).out(at(2, 13), "automation"),
            None,
            1,
            id="never-answered-by-a-person",
        ),
        pytest.param(
            # Automated, no handoff: a person stepping in is a takeover, not a response.
            Thread(automated=True).inbound(at(2)).out(at(2, 12, 5), "reply"),
            None,
            0,
            id="automated-without-handoff-no-pair",
        ),
        pytest.param(
            # A reply BEFORE the wait started does not answer it.
            Thread(context=handoff_ctx(at(3)), automated=True)
            .inbound(at(2))
            .out(at(2, 13), "reply")
            .inbound(at(3)),
            None,
            1,
            id="reply-before-handoff-ignored",
        ),
        pytest.param(
            # Never automated but opened before the range: no pair in this range.
            Thread().inbound(SINCE - timedelta(days=1)).inbound(at(2)).out(at(2, 13), "reply"),
            None,
            0,
            id="opened-before-range",
        ),
    ],
)
def test_first_human_response_pairing(
    thread: Thread, expected_seconds: float | None, awaiting: int
) -> None:
    result = run(thread)
    assert result.median_first_human_response_seconds == expected_seconds
    assert result.first_human_responses == (0 if expected_seconds is None else 1)
    assert result.awaiting_human_response == awaiting


def test_median_and_p90_over_several_threads() -> None:
    threads = [
        Thread().inbound(at(2, 10)).out(at(2, 10) + timedelta(seconds=s), "reply")
        for s in (60, 120, 180, 240, 600)
    ]
    result = run(*threads)
    assert result.first_human_responses == 5
    assert result.median_first_human_response_seconds == 180.0
    assert result.p90_first_human_response_seconds == 600.0


@pytest.mark.parametrize(
    ("values", "expected"),
    [([], None), ([5.0], 5.0), ([1.0, 2.0], 2.0), ([float(i) for i in range(1, 11)], 9.0)],
)
def test_p90_nearest_rank(values: list[float], expected: float | None) -> None:
    assert p90_nearest_rank(values) == expected


# ======================================================================================
# Message counters
# ======================================================================================


def test_message_counters_split_by_outbox_kind_and_range() -> None:
    t = (
        Thread()
        .inbound(at(2))
        .inbound(at(3))
        .out(at(2, 12, 1), "automation")
        .out(at(2, 12, 2), "automation", status="failed")
        .out(at(2, 13), "reply")
        .out(at(4), "campaign_send", status="read")
        .out(at(4, 13), None)  # no outbox row
        .inbound(UNTIL + timedelta(hours=1))  # horizon only: not counted
        .out(UNTIL + timedelta(hours=1), "reply", status="failed")
    )
    result = run(t, send_failed=3)
    assert result.messages_in == 2
    assert result.messages_out_automation == 2
    assert result.messages_out_human == 1
    assert result.messages_out_campaign == 1
    assert result.messages_out_other == 1
    assert result.delivery_failed == 1
    assert result.send_failed == 3


def test_empty_rows() -> None:
    result = run()
    assert result.threads_opened == 0
    assert result.threads_opened_by_entry == ()
    assert result.orders_total == {}
    assert result.median_first_human_response_seconds is None
    assert result.p90_first_human_response_seconds is None


# ======================================================================================
# Service + range
# ======================================================================================


def test_resolve_range_defaults_to_last_seven_days() -> None:
    assert resolve_range(None, None, NOW) == (NOW - timedelta(days=7), NOW)
    naive = datetime(2026, 10, 1)
    assert resolve_range(naive, None, NOW)[0] == datetime(2026, 10, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("since", "until"),
    [(UNTIL, UNTIL), (UNTIL, SINCE), (UNTIL - timedelta(days=400), UNTIL)],
)
def test_resolve_range_rejects(since: datetime, until: datetime) -> None:
    with pytest.raises(InvalidRange):
        resolve_range(since, until, NOW)


def test_service_scopes_by_tenant_and_filters_rows_to_the_window() -> None:
    repo = MemoryMetricsRepository()
    inside = Thread("menu").inbound(at(2)).out(at(2, 12, 30), "reply")
    outside = Thread("menu").inbound(SINCE - timedelta(days=30))
    repo.put(tenant_id=TENANT, connection_id=CONN, rows=rows(inside, outside))
    service = ConversationMetricsService(repo, clock=lambda: NOW)

    result = service.compute(TENANT, CONN, since=SINCE, until=UNTIL)
    assert result.threads_opened == 1
    assert result.median_first_human_response_seconds == 1800.0

    with pytest.raises(ConnectionNotFound):
        service.compute(OTHER, CONN, since=SINCE, until=UNTIL)
    with pytest.raises(InvalidRange):
        service.compute(TENANT, CONN, since=UNTIL, until=SINCE)
