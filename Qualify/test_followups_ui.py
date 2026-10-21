"""«Consultas desde comentarios» on the screens (m-24789646, PR 3) — network-free, no
database: the card VMs, the «Analizar intención» hook and its toast, «Responder por DM»
in Interacciones, the Conversaciones toggle and the state's guards.

Pins:
1. A card says who, where, why (intents, «no fiable»), the route it would go out on now
   and for how long — or, with no route, the reason for each one, the capability's
   included; the draft text and «requiere revisión» with the claims to confirm.
2. `_open_followups` is best effort: a failure is logged and counts 0, never undoing the
   analysis the person just saw. The toast names the new queries.
3. Interacciones has «Responder por DM» on every comment; Conversaciones has the
   «Mensajes | Consultas desde comentarios» toggle and runs `FollowupsState.enter_page`
   on load.
4. The state accepts only ids its cards hold and only known views.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from qualify_api.conversations.drafts import new_draft
from qualify_api.followups import (
    FollowupTrigger,
    OriginKind,
    OriginMessage,
    RouteOption,
    SendOptions,
    SendRoute,
    new_followup,
)
from qualify_api.followups.workspace import FollowupCard, IntentChip

from . import inbox_provider, inbox_state
from .followups_state import FollowupsState
from .followups_vm import VIEW_MESSAGES, VIEW_QUERIES, build_card_vm, time_left
from .inbox_vm import IntentAnalysisSummaryVM

NOW = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)
ZONE = ZoneInfo("America/Bogota")
TENANT = uuid4()


def _card(
    *,
    dm: RouteOption | None = None,
    private_reply: RouteOption | None = None,
    with_draft: bool = True,
    needs_review: bool = False,
) -> FollowupCard:
    origin = OriginMessage(
        id=uuid4(),
        tenant_id=TENANT,
        connection_id=uuid4(),
        thread_id=uuid4(),
        channel="comment",
        external_message_id="c1",
        direction="inbound",
        author_external_id="igsid-ana",
        author_username="ana",
        text="¿Cuánto cuesta?",
        posted_at=NOW - timedelta(hours=3),
        media_caption="Colección de otoño " * 20,
        media_permalink="https://instagram.com/reel/x",
        media_product_type="REELS",
    )
    followup = new_followup(
        tenant_id=TENANT,
        connection_id=origin.connection_id,
        origin_kind=OriginKind.COMMENT,
        origin_message_id=origin.id,
        trigger=FollowupTrigger.INTENT,
        intent_result_id=uuid4(),
        now=NOW,
    )
    draft = (
        new_draft(
            tenant_id=TENANT,
            thread_id=origin.thread_id,
            message_id=origin.id,
            generator_version="v",
            generated_text="Hola Ana, cuesta 50.000",
            gate_reason="commercial_comment",
            needs_review=needs_review,
            grounding={"unsupported_claims": ["Talla M disponible"] if needs_review else []},
        )
        if with_draft
        else None
    )
    options = SendOptions(
        dm=dm or RouteOption(SendRoute.DM, False, None, "No ha escrito en 24 h."),
        private_reply=private_reply
        or RouteOption(SendRoute.PRIVATE_REPLY, True, NOW + timedelta(days=6, hours=4), ""),
    )
    return FollowupCard(
        followup=followup,
        origin=origin,
        options=options,
        intents=(
            IntentChip("Precio", 0.9, commercial=True, reliable=True),
            IntentChip("Variantes", 0.6, commercial=True, reliable=False),
        ),
        draft=draft,
    )


# --- card VMs ---------------------------------------------------------------------------


def test_a_card_says_who_where_why_and_how_it_goes_out() -> None:
    vm = build_card_vm(_card(), now=NOW, zone=ZONE)
    assert vm.author == "@ana" and vm.initial == "A"
    assert vm.where_label == "tu Reel"
    assert vm.permalink == "https://instagram.com/reel/x"
    assert len(vm.caption) <= 120 and vm.caption.endswith("…")
    assert vm.posted_label == "21 oct, 07:00"  # 12:00 UTC in Bogotá
    assert vm.trigger_label == "Intención comercial"
    assert [(i.label, i.reliable) for i in vm.intents] == [("Precio", True), ("Variantes", False)]
    assert vm.route_available is True
    assert vm.route_label == "Respuesta privada al comentario"
    assert vm.route_deadline == "quedan 6 d 4 h"
    assert "Un solo mensaje" in vm.route_note
    assert vm.blocked_reasons == []
    assert (vm.has_draft, vm.draft_text) == (True, "Hola Ana, cuesta 50.000")


def test_with_no_route_a_card_gives_the_reason_for_each() -> None:
    blocked = RouteOption(
        SendRoute.PRIVATE_REPLY, False, None, "Por verificar (QUALIFY_COMMENT_PRIVATE_REPLY)."
    )
    vm = build_card_vm(_card(private_reply=blocked), now=NOW, zone=ZONE)
    assert vm.route_available is False
    assert vm.blocked_reasons == [
        "Mensaje directo: No ha escrito en 24 h.",
        "Respuesta privada al comentario: Por verificar (QUALIFY_COMMENT_PRIVATE_REPLY).",
    ]


def test_the_dm_route_shows_until_when_the_window_is_open() -> None:
    dm = RouteOption(SendRoute.DM, True, NOW + timedelta(hours=3, minutes=20), "")
    vm = build_card_vm(_card(dm=dm), now=NOW, zone=ZONE)
    # `SendOptions.chosen` prefers the DM when both are open.
    assert (vm.route_label, vm.route_deadline) == ("Mensaje directo", "quedan 3 h 20 min")


def test_a_draft_that_needs_review_lists_what_to_confirm() -> None:
    vm = build_card_vm(_card(needs_review=True), now=NOW, zone=ZONE)
    assert vm.needs_review is True
    assert vm.unsupported_claims == ["Talla M disponible"]
    empty = build_card_vm(_card(with_draft=False), now=NOW, zone=ZONE)
    assert (empty.has_draft, empty.draft_id, empty.draft_text) == (False, "", "")


def test_time_left_reads_in_days_hours_and_minutes() -> None:
    assert time_left(NOW + timedelta(minutes=12), NOW) == "quedan 12 min"
    assert time_left(NOW + timedelta(seconds=20), NOW) == "quedan 1 min"
    assert time_left(NOW, NOW) == "cerrada"


# --- Interacciones -------------------------------------------------------------------------


def test_opening_followups_is_best_effort(monkeypatch) -> None:  # noqa: ANN001
    class Broken:
        def open_from_intents(self, tenant_id: UUID, connection_id: UUID) -> object:
            raise RuntimeError("db down")

    from . import followups_provider

    monkeypatch.setattr(followups_provider, "gateway", lambda: Broken())
    assert asyncio.run(inbox_provider._open_followups(uuid4(), uuid4())) == 0  # noqa: SLF001


def test_the_analysis_toast_names_the_new_queries() -> None:
    summary = IntentAnalysisSummaryVM(
        comments_checked=3, new_results=3, skipped_empty=0, unclassified=0, followups_opened=2
    )
    assert inbox_state._intent_result_message(summary).endswith(  # noqa: SLF001
        "Consultas nuevas en Conversaciones: 2"
    )


def test_every_comment_offers_reply_by_dm() -> None:
    from .inbox_page import _comment_card

    rendered = str(_comment_card(inbox_state.InboxState.thread_comments[0]).render())
    assert "Responder por DM" in rendered


# --- Conversaciones ------------------------------------------------------------------------


def test_conversations_loads_the_queries_on_entry_and_shows_the_toggle() -> None:
    source = (Path(__file__).parent / "Qualify.py").read_text(encoding="utf-8")
    start = source.index("conversations_index,")
    block = source[start : source.index(")", start)]
    assert "FollowupsState.enter_page" in block
    from .conversations_page import conversations_index

    rendered = str(conversations_index().render())
    assert "Mensajes" in rendered
    assert "No hay consultas pendientes" in rendered


def test_the_state_accepts_only_known_views_and_known_cards() -> None:
    state = FollowupsState()
    assert FollowupsState.set_view.fn(state, "nope") is None  # type: ignore[attr-defined]
    assert state.view == VIEW_MESSAGES
    FollowupsState.set_view.fn(state, VIEW_QUERIES)  # type: ignore[attr-defined]
    assert state.view == VIEW_QUERIES
    FollowupsState.set_edit.fn(state, str(uuid4()), "texto")  # type: ignore[attr-defined]
    assert state.edits == {}
