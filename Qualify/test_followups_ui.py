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
5. The public notice (PR 4) appears only on a card that offers it (`public_notice` on, a
   comment), with the default text, editable, approved with the message; unticked, the
   message goes alone.
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
from qualify_api.followups.notice import DEFAULT_NOTICE_TEXT
from qualify_api.followups.workspace import FollowupCard, IntentChip

from . import inbox_provider, inbox_state
from .followups_state import FollowupsState
from .followups_vm import (
    STEP_ASKED,
    STEP_REPLY,
    STEP_REVIEW,
    VIEW_MESSAGES,
    VIEW_QUERIES,
    FollowupCardVM,
    build_card_vm,
    done_title,
    notice_line,
    recipient_line,
    step_label,
    time_left,
)
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
    notice_available: bool = False,
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
        notice_available=notice_available,
    )


# --- card VMs ---------------------------------------------------------------------------


def test_a_card_says_who_where_why_and_how_it_goes_out() -> None:
    vm = build_card_vm(_card(), now=NOW, zone=ZONE)
    assert vm.author == "@ana" and vm.initial == "A"
    assert vm.where_label == "tu Reel"
    assert vm.permalink == "https://instagram.com/reel/x"
    assert len(vm.caption) <= 120 and vm.caption.endswith("…")
    assert vm.posted_label == "21 oct, 07:00"  # 12:00 UTC in Bogotá
    assert vm.trigger_label == "Quiere comprar"
    assert [(i.label, i.reliable) for i in vm.intents] == [("Precio", True), ("Variantes", False)]
    assert vm.intent_unsure is True  # «Variantes» is not backed: the card says so once
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
        "2 quieren comprar: te esperan en «Conversaciones»."
    )


def test_every_comment_offers_reply_by_dm() -> None:
    from .inbox_page import _comment_card

    rendered = str(_comment_card(inbox_state.InboxState.thread_comments[0]).render())
    assert "Escribirle en privado" in rendered
    assert "Responder por DM" not in rendered


# --- Conversaciones ------------------------------------------------------------------------


def test_conversations_loads_the_queries_on_entry_and_shows_the_toggle() -> None:
    # m-24842990: the queries are the «Quieren comprar» tab of /responder, whose entry
    # hands over to FollowupsState.enter_page; /conversations keeps the toggle.
    source = (Path(__file__).parent / "responder_state.py").read_text(encoding="utf-8")
    assert "FollowupsState.enter_page" in source
    from .conversations_page import conversations_index

    rendered = str(conversations_index().render())
    assert "Mensajes" in rendered
    assert "esperando para comprar" in rendered and "Ver comentarios" in rendered
    assert "/responder?tab=comentarios" in rendered


def test_the_state_accepts_only_known_views_and_known_cards() -> None:
    state = FollowupsState()
    assert FollowupsState.set_view.fn(state, "nope") is None  # type: ignore[attr-defined]
    assert state.view == VIEW_MESSAGES
    FollowupsState.set_view.fn(state, VIEW_QUERIES)  # type: ignore[attr-defined]
    assert state.view == VIEW_QUERIES
    FollowupsState.set_edit.fn(state, str(uuid4()), "texto")  # type: ignore[attr-defined]
    assert state.edits == {}


# --- the public notice (PR 4) ------------------------------------------------------------


def test_the_notice_is_offered_only_when_the_card_allows_it() -> None:
    off = build_card_vm(_card(), now=NOW, zone=ZONE)
    assert (off.notice_available, off.notice_default) == (False, "")
    on = build_card_vm(_card(notice_available=True), now=NOW, zone=ZONE)
    assert (on.notice_available, on.notice_default) == (True, DEFAULT_NOTICE_TEXT)


def test_the_card_renders_the_notice_block_behind_its_capability() -> None:
    from .followups_page import _notice

    rendered = str(_notice(FollowupsState.cards[0]).render())
    # The compiled JSX escapes non-ASCII («también» → `tambi\u00e9n`), escaped again by str().
    # m-24842991: the label says what is left on the comment, with its text.
    assert "Tambi\\\\u00e9n dejamos" in rendered and "en su comentario." in rendered
    assert "Texto del aviso en su comentario" in rendered
    assert "solo cuando el mensaje privado salga" in rendered
    # The whole block hangs from the card's `notice_available` (no capability, no box).
    assert "notice_available" in rendered


def _state_with(*cards: FollowupCardVM) -> FollowupsState:
    state = FollowupsState()
    state.cards = list(cards)
    return state


def test_the_notice_text_goes_only_when_offered_and_ticked() -> None:
    offered = build_card_vm(_card(notice_available=True), now=NOW, zone=ZONE)
    plain = build_card_vm(_card(), now=NOW, zone=ZONE)
    state = _state_with(offered, plain)
    # Defaults: ticked, with the default text.
    assert state._notice_for(offered) == DEFAULT_NOTICE_TEXT  # noqa: SLF001
    assert state._notice_for(plain) is None  # noqa: SLF001

    FollowupsState.set_notice_edit.fn(state, offered.followup_id, "Te escribimos 💬")  # type: ignore[attr-defined]
    assert state._notice_for(offered) == "Te escribimos 💬"  # noqa: SLF001
    FollowupsState.set_notice_on.fn(state, offered.followup_id, False)  # type: ignore[attr-defined]
    assert state._notice_for(offered) is None  # noqa: SLF001

    # A card that does not offer it, or an unknown id, cannot be given one.
    FollowupsState.set_notice_on.fn(state, plain.followup_id, True)  # type: ignore[attr-defined]
    FollowupsState.set_notice_edit.fn(state, str(uuid4()), "x")  # type: ignore[attr-defined]
    assert plain.followup_id not in state.notice_on
    assert set(state.notice_edits) == {offered.followup_id}


def test_the_gateway_hands_the_notice_to_the_workspace() -> None:
    from .followups_provider import FollowupsGateway

    seen: dict[str, object] = {}

    class Workspace:
        def approve(self, **kw: object) -> object:
            seen.update(kw)
            return type("Approved", (), {"send_route": SendRoute.PRIVATE_REPLY})()

    route = FollowupsGateway(Workspace()).approve(  # type: ignore[arg-type]
        TENANT, uuid4(), text="hola", user_id=uuid4(), draft_id=None, notice_text="aviso"
    )
    assert route == "private_reply"
    assert seen["notice_text"] == "aviso"


# --- replies to stories (PR 5) -------------------------------------------------------------


def test_a_story_reply_card_says_it_answered_a_story() -> None:
    from dataclasses import replace as _replace

    card = _card()
    story_origin = _replace(
        card.origin,
        channel="dm",
        story_reply_id="17900000000000001",
        story_reply_url="https://cdn/story",
    )
    vm = build_card_vm(_replace(card, origin=story_origin), now=NOW, zone=ZONE)
    assert vm.origin_label == "Respondió a tu historia por mensaje directo"
    assert (vm.permalink, vm.caption) == ("https://cdn/story", "")
    comment = build_card_vm(card, now=NOW, zone=ZONE)
    assert comment.origin_label == "Comentó en tu Reel"


# --- three steps and the confirmation (m-24842991, ATENDER-6) -----------------------------


def test_the_notice_proposes_the_owners_words_by_default() -> None:
    assert DEFAULT_NOTICE_TEXT == "Te escribimos al privado 💬"
    assert notice_line(DEFAULT_NOTICE_TEXT) == (
        "También dejamos “Te escribimos al privado 💬” en su comentario."
    )


def test_each_step_has_its_number_and_name() -> None:
    assert step_label(STEP_ASKED) == "Paso 1 de 3 · Qué preguntó"
    assert step_label(STEP_REPLY) == "Paso 2 de 3 · Qué le respondes"
    assert step_label(STEP_REVIEW) == "Paso 3 de 3 · Revisa y aprueba"
    assert step_label(9) == "Paso 1 de 3 · Qué preguntó"


def test_the_review_says_who_gets_it_in_words() -> None:
    vm = build_card_vm(_card(), now=NOW, zone=ZONE)
    assert vm.recipient_line == "Le llega a @ana por mensaje privado."
    assert recipient_line("Cliente") == "Le llega por mensaje privado."


def test_the_confirmation_names_the_person_and_the_next_step() -> None:
    assert done_title("@ana", more_left=True) == (
        "Listo. Le escribiste a @ana. ¿Seguimos con la siguiente?"
    )
    assert done_title("Cliente", more_left=False) == (
        "Listo. Le escribiste a tu cliente. No queda nadie más esperando."
    )


def test_back_and_forth_keeps_what_was_written() -> None:
    first = build_card_vm(_card(), now=NOW, zone=ZONE)
    state = _state_with(first)
    fid = first.followup_id
    state.edits = {fid: first.draft_text}
    state.steps = {fid: STEP_ASKED}
    FollowupsState.go_step.fn(state, fid, STEP_REPLY)  # type: ignore[attr-defined]
    FollowupsState.set_edit.fn(state, fid, "Hola Ana, lo tenemos en rojo")  # type: ignore[attr-defined]
    FollowupsState.go_step.fn(state, fid, STEP_REVIEW)  # type: ignore[attr-defined]
    assert state.steps[fid] == STEP_REVIEW
    FollowupsState.go_step.fn(state, fid, STEP_REPLY)  # type: ignore[attr-defined]
    FollowupsState.go_step.fn(state, fid, STEP_ASKED)  # type: ignore[attr-defined]
    assert state.steps[fid] == STEP_ASKED
    assert state.edits[fid] == "Hola Ana, lo tenemos en rojo"  # «Atrás» erased nothing


def test_the_review_needs_a_message_and_only_known_steps_and_cards() -> None:
    first = build_card_vm(_card(), now=NOW, zone=ZONE)
    state = _state_with(first)
    fid = first.followup_id
    state.edits = {fid: "   "}
    state.steps = {fid: STEP_REPLY}
    assert FollowupsState.go_step.fn(state, fid, STEP_REVIEW) is not None  # type: ignore[attr-defined]
    assert state.steps[fid] == STEP_REPLY
    assert FollowupsState.go_step.fn(state, fid, 7) is None  # type: ignore[attr-defined]
    assert FollowupsState.go_step.fn(state, str(uuid4()), STEP_REPLY) is None  # type: ignore[attr-defined]
    assert state.steps == {fid: STEP_REPLY}


def test_after_approving_the_confirmation_leads_to_the_next_one() -> None:
    first = build_card_vm(_card(), now=NOW, zone=ZONE)
    state = _state_with(first)
    state.done_author = "@bea"
    state.done_note = "Tu mensaje privado a @bea sale en unos segundos."
    assert state.showing_done is True
    assert state.done_text == "Listo. Le escribiste a @bea. ¿Seguimos con la siguiente?"
    FollowupsState.next_query.fn(state)  # type: ignore[attr-defined]
    assert (state.showing_done, state.done_author) == (False, "")
    assert state.highlight_id == first.followup_id
    assert state.steps[first.followup_id] == STEP_ASKED
    nobody = _state_with()
    nobody.done_author = "@bea"
    assert nobody.done_text.endswith("No queda nadie más esperando.")


def test_the_panel_has_the_steps_the_confirmation_and_no_tooltip() -> None:
    import inspect

    from . import followups_page

    assert "rx.tooltip" not in inspect.getsource(followups_page)  # nothing hover-only
    rendered = str(followups_page.followups_panel().render())
    for text in ("Siguiente", "Atr\\\\u00e1s", "Volver a comentarios", "Aprobar y enviar"):
        assert text in rendered, text
    assert "Otra idea" in rendered and "/responder?tab=comentarios" in rendered
    assert "44px" in rendered


def test_the_ux_review_fixes_are_on_the_card() -> None:
    """m-24842991 UX review: blocked route said on step 1 with a way out, step 2's
    «Siguiente» off while the box is empty (and why), a titled preview with «Cambiar
    mensaje», and a notice label that does not echo the box."""
    from .followups_page import _notice, _step_asked, _step_reply, _step_review

    c = FollowupsState.cards[0]
    asked = str(_step_asked(c).render())
    assert "No disponible todav" in asked and "Volver a comentarios" in asked
    assert "route_available" in asked
    reply = str(_step_reply(c).render())
    assert "para seguir." in reply and "pyStrip" in reply
    review = str(_step_review(c).render())
    assert "Tu mensaje:" in review and "Cambiar mensaje" in review
    label = str(_notice(c).render())
    assert "notice_default" in label


def test_the_notice_messages_use_the_same_words_as_the_card() -> None:
    from . import followups_state as fs

    for text in (fs._NOTICE_EMPTY, fs._NOTICE_TOO_LONG, fs._NOTICE_QUEUED):
        assert "aviso público" not in text and "en su comentario" in text
