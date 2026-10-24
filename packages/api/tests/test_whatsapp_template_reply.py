"""m-24848535 (WHATSAPP-2) — an approved message from an expired chat, offline.

Pins the founder's rule (§2b-4): a person who wrote before may receive follow-ups only;
promotions need an explicit, active opt-in — and the SERVER refuses a promotion without
it whatever the screen offered. Also: only approved templates of the thread's account
are listed, the «Pedirle que acepte» template is found only when it exists, variables are
filled server-side, a repeated `request_key` never queues twice, and the sender drains a
`template_reply` with the window closed and re-checks a promotion's opt-in at send time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.whatsapp.chats import ChatService, MemoryChatRepository, ThreadNotFound
from qualify_api.whatsapp.optins import MemoryOptInRepository, OptInService
from qualify_api.whatsapp.outbox import (
    ERROR_OPTED_OUT,
    ClaimedOutboxItem,
    MemoryOutboxRepository,
    OutboxSender,
)
from qualify_api.whatsapp.template_reply import (
    MissingValues,
    NoPermission,
    Permission,
    PromotionNeedsConsent,
    TemplateNotAvailable,
    TemplateReplyService,
    TemplateVariable,
    allowed_categories,
    permission_for,
    prefill,
    render_preview,
    send_components,
    template_variables,
    unfillable_reason,
    variable_examples,
)
from qualify_api.whatsapp.templates import MemoryTemplateRepository, TemplateRecord
from qualify_api.whatsapp.window import is_free_form_allowed, window_state

NOW = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)
TENANT = uuid4()
OTHER_TENANT = uuid4()
USER = uuid4()
CONN = uuid4()
WABA = "waba-1"
WA_ID = "573001112233"
PHONE = "+573001112233"


def _body(text: str) -> list[dict[str, Any]]:
    return [{"type": "BODY", "text": text}]


class World:
    def __init__(self) -> None:
        self.chats_repo = MemoryChatRepository()
        self.outbox = MemoryOutboxRepository(clock=lambda: NOW)
        self.templates = MemoryTemplateRepository(clock=lambda: NOW)
        self.optins_repo = MemoryOptInRepository()
        self.optins = OptInService(self.optins_repo, clock=lambda: NOW)
        self.chats = ChatService(self.chats_repo, self.outbox, clock=lambda: NOW)
        self.service = TemplateReplyService(
            self.chats, self.templates, self.optins, self.outbox, clock=lambda: NOW
        )
        self.templates.add_number(
            tenant_id=TENANT, connection_id=CONN, waba_id=WABA, phone_row_id=uuid4()
        )

    def thread(self, *, wrote: bool = True, name: str | None = "María José") -> UUID:
        thread_id = self.chats_repo.add_thread(
            tenant_id=TENANT, connection_id=CONN, wa_id=WA_ID, last_inbound_at=None
        )
        if wrote:
            self.chats_repo.add_message(
                thread_id=thread_id,
                direction="inbound",
                text_value="Hola, ¿tienen envío?",
                posted_at=NOW - timedelta(days=3),
                author_username=name,
            )
        return thread_id

    def template(
        self,
        name: str,
        category: str,
        *,
        status: str = "APPROVED",
        components: list[dict[str, Any]] | None = None,
        waba: str = WABA,
        tenant: UUID = TENANT,
    ) -> UUID:
        record = TemplateRecord(
            id=uuid4(),
            tenant_id=tenant,
            waba_id=waba,
            name=name,
            language="es",
            category=category,
            status=status,
            components=components if components is not None else _body("Hola, ¿cómo vas?"),
        )
        self.templates.insert(record)
        return record.id

    def opt_in(self) -> None:
        self.optins.record(
            tenant_id=TENANT, phone=PHONE, source="manual", consent_text="Acepto promociones"
        )


@pytest.fixture
def world() -> World:
    return World()


# --- the permission rule -------------------------------------------------------------


def test_permission_rule_matches_the_founder_decision() -> None:
    assert permission_for(has_written=True, opted_in=False) is Permission.CHAT
    assert permission_for(has_written=False, opted_in=True) is Permission.EXPLICIT
    assert permission_for(has_written=True, opted_in=True) is Permission.EXPLICIT
    assert permission_for(has_written=False, opted_in=False) is Permission.NONE
    assert allowed_categories(Permission.CHAT) == {"utility"}
    assert allowed_categories(Permission.EXPLICIT) == {"utility", "marketing"}
    assert allowed_categories(Permission.NONE) == frozenset()


def test_template_reply_goes_through_with_the_window_closed() -> None:
    closed = window_state(NOW - timedelta(days=2), NOW)
    assert not closed.is_open
    assert is_free_form_allowed("template_reply", closed)
    assert not is_free_form_allowed("reply", closed)


# --- options -------------------------------------------------------------------------


def test_chat_only_lists_followups_and_says_promotions_need_consent(world: World) -> None:
    thread = world.thread()
    followup = world.template("seguimiento_pedido", "utility")
    world.template("promo_2x1", "marketing")
    world.template("pendiente", "utility", status="PENDING")
    world.template("codigo", "authentication")
    world.template("de_otra_cuenta", "utility", waba="waba-2")

    options = world.service.options(TENANT, thread)

    assert options.permission is Permission.CHAT
    assert [o.template_id for o in options.options] == [followup]
    assert options.promotions_blocked is True
    assert options.consent_request is None  # no «pedir_permiso…» template: no button
    assert options.has_followups is True


def test_consent_request_template_is_offered_only_when_it_exists(world: World) -> None:
    thread = world.thread()
    ask = world.template("pedir_permiso_promos", "utility")

    options = world.service.options(TENANT, thread)

    assert options.consent_request is not None
    assert options.consent_request.template_id == ask


def test_explicit_opt_in_lists_followups_then_promotions(world: World) -> None:
    thread = world.thread()
    world.opt_in()
    promo = world.template("promo_2x1", "marketing")
    followup = world.template("seguimiento_pedido", "utility")
    world.template("pedir_permiso_promos", "utility")

    options = world.service.options(TENANT, thread)

    assert options.permission is Permission.EXPLICIT
    ids = [o.template_id for o in options.options]
    assert ids[-1] == promo and followup in ids
    assert options.promotions_blocked is False
    assert options.consent_request is None  # nothing to ask: they already accepted


def test_no_followups_is_reported_for_the_create_link(world: World) -> None:
    thread = world.thread()
    world.template("promo_2x1", "marketing")

    options = world.service.options(TENANT, thread)

    assert options.options == []
    assert options.has_followups is False


def test_options_prefill_the_persons_first_name(world: World) -> None:
    thread = world.thread(name="María José")
    world.template("seguimiento", "utility", components=_body("Hola {{1}}, ¿seguimos con {{2}}?"))

    (option,) = world.service.options(TENANT, thread).options

    assert option.prefill == {"body:1": "María"}
    assert option.preview == "Hola María, ¿seguimos con {{2}}?"


def test_unfillable_templates_are_not_listed(world: World) -> None:
    thread = world.thread()
    world.template(
        "con_foto",
        "utility",
        components=[{"type": "HEADER", "format": "IMAGE"}, *_body("Mira esto")],
    )

    assert world.service.options(TENANT, thread).options == []


def test_another_tenants_thread_reads_as_missing(world: World) -> None:
    thread = world.thread()
    with pytest.raises(ThreadNotFound):
        world.service.options(OTHER_TENANT, thread)


# --- send: the server enforces the rule ----------------------------------------------


def test_server_refuses_a_promotion_without_explicit_consent(world: World) -> None:
    thread = world.thread()
    promo = world.template("promo_2x1", "marketing")

    with pytest.raises(PromotionNeedsConsent):
        world.service.send(TENANT, thread, USER, template_id=promo, values={}, request_key="k-1")
    assert world.outbox.rows == {}


def test_nothing_goes_to_someone_who_never_wrote_nor_accepted(world: World) -> None:
    thread = world.thread(wrote=False)
    followup = world.template("seguimiento_pedido", "utility")

    with pytest.raises(NoPermission):
        world.service.send(TENANT, thread, USER, template_id=followup, values={}, request_key="k-1")
    assert world.outbox.rows == {}


def test_promotion_with_consent_is_queued(world: World) -> None:
    thread = world.thread()
    world.opt_in()
    promo = world.template("promo_2x1", "marketing")

    outbox_id = world.service.send(
        TENANT, thread, USER, template_id=promo, values={}, request_key="k-1"
    )

    row = world.outbox.rows[outbox_id]
    assert row.kind == "template_reply"
    assert row.template_category == "marketing"
    assert row.template_id == promo
    assert row.created_by_user_id == USER


def test_send_builds_the_body_server_side_and_keeps_the_preview(world: World) -> None:
    thread = world.thread()
    followup = world.template(
        "seguimiento", "utility", components=_body("Hola {{1}}, tu pedido {{2}} está listo")
    )

    outbox_id = world.service.send(
        TENANT,
        thread,
        USER,
        template_id=followup,
        values={"body:1": " María ", "body:2": "#45", "body:9": "ignorado"},
        request_key="k-1",
    )

    row = world.outbox.rows[outbox_id]
    assert row.payload["type"] == "template"
    assert row.payload["to"] == WA_ID
    assert row.payload["template"]["name"] == "seguimiento"
    assert row.payload["template"]["components"] == [
        {
            "type": "body",
            "parameters": [{"type": "text", "text": "María"}, {"type": "text", "text": "#45"}],
        }
    ]
    assert row.preview_text == "Hola María, tu pedido #45 está listo"
    # A person took the chat: the menu automation pauses, as with any reply.
    assert world.chats.get_thread_summary(TENANT, thread).automation_paused is True


def test_missing_values_are_refused_before_writing(world: World) -> None:
    thread = world.thread()
    followup = world.template("seguimiento", "utility", components=_body("Hola {{1}}"))

    with pytest.raises(MissingValues) as err:
        world.service.send(
            TENANT, thread, USER, template_id=followup, values={"body:1": "  "}, request_key="k"
        )
    assert err.value.variable_ids == ["body:1"]
    assert world.outbox.rows == {}


@pytest.mark.parametrize(
    ("status", "category", "waba", "tenant"),
    [
        ("PENDING", "utility", WABA, TENANT),
        ("APPROVED", "authentication", WABA, TENANT),
        ("APPROVED", "utility", "waba-2", TENANT),
        ("APPROVED", "utility", WABA, OTHER_TENANT),
    ],
)
def test_send_refuses_a_template_that_is_not_available(
    world: World, status: str, category: str, waba: str, tenant: UUID
) -> None:
    thread = world.thread()
    template = world.template("x", category, status=status, waba=waba, tenant=tenant)

    with pytest.raises(TemplateNotAvailable):
        world.service.send(TENANT, thread, USER, template_id=template, values={}, request_key="k-1")


def test_same_request_key_never_queues_twice(world: World) -> None:
    thread = world.thread()
    followup = world.template("seguimiento_pedido", "utility")

    first = world.service.send(
        TENANT, thread, USER, template_id=followup, values={}, request_key="tap-1"
    )
    again = world.service.send(
        TENANT, thread, USER, template_id=followup, values={}, request_key="tap-1"
    )
    other = world.service.send(
        TENANT, thread, USER, template_id=followup, values={}, request_key="tap-2"
    )

    assert first == again != other
    assert len(world.outbox.rows) == 2


@pytest.mark.parametrize("key", ["", "   ", "x" * 129])
def test_request_key_is_required(world: World, key: str) -> None:
    thread = world.thread()
    followup = world.template("seguimiento_pedido", "utility")
    with pytest.raises(ValueError):
        world.service.send(TENANT, thread, USER, template_id=followup, values={}, request_key=key)


def test_outbox_refuses_a_template_reply_without_its_columns() -> None:
    outbox = MemoryOutboxRepository(clock=lambda: NOW)
    base: dict[str, Any] = {
        "tenant_id": TENANT,
        "connection_id": CONN,
        "thread_id": uuid4(),
        "kind": "template_reply",
        "payload": {"to": WA_ID, "type": "template"},
        "created_by_user_id": USER,
    }
    with pytest.raises(ValueError):
        outbox.enqueue(**base)
    with pytest.raises(ValueError):
        outbox.enqueue(
            **base, request_key="k", template_id=uuid4(), template_category="authentication"
        )


# --- the sender ----------------------------------------------------------------------


class _Client:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_payload(self, payload: dict[str, Any]) -> str:
        self.sent.append(payload)
        return f"wamid.{len(self.sent)}"


def _sender(world: World, client: _Client) -> OutboxSender:
    async def factory(*, tenant_id: UUID, connection_id: UUID) -> Any:
        return client

    return OutboxSender(
        world.outbox,
        factory,
        lambda **_: None,
        worker_id="test",
        opt_ins=world.optins,
        clock=lambda: NOW,
    )


async def test_sender_delivers_a_followup_with_the_window_closed(world: World) -> None:
    thread = world.thread()
    followup = world.template("seguimiento", "utility", components=_body("Hola {{1}}"))
    outbox_id = world.service.send(
        TENANT, thread, USER, template_id=followup, values={"body:1": "Ana"}, request_key="k"
    )
    world.outbox.threads[thread] = NOW - timedelta(days=3)
    client = _Client()

    report = await _sender(world, client).run_once(TENANT)

    assert report.sent == 1
    assert world.outbox.rows[outbox_id].status == "sent"
    (message,) = world.outbox.messages
    assert message.text == "Hola Ana"  # the conversation shows what went out


async def test_sender_stops_a_promotion_after_a_stop(world: World) -> None:
    thread = world.thread()
    world.opt_in()
    promo = world.template("promo_2x1", "marketing")
    outbox_id = world.service.send(
        TENANT, thread, USER, template_id=promo, values={}, request_key="k"
    )
    world.optins.revoke(tenant_id=TENANT, phone=PHONE)  # STOP after «Enviar»
    client = _Client()

    report = await _sender(world, client).run_once(TENANT)

    assert report.failed == 1 and client.sent == []
    assert world.outbox.rows[outbox_id].error_code == ERROR_OPTED_OUT


def test_needs_opt_in_fails_closed() -> None:
    def item(kind: str, category: str | None) -> ClaimedOutboxItem:
        return ClaimedOutboxItem(
            id=uuid4(),
            tenant_id=TENANT,
            connection_id=CONN,
            thread_id=uuid4(),
            kind=kind,
            payload={"to": WA_ID},
            attempts=0,
            template_category=category,
        )

    assert item("template_reply", "utility").needs_opt_in is False
    assert item("template_reply", "marketing").needs_opt_in is True
    assert item("template_reply", None).needs_opt_in is True
    assert item("campaign_send", None).needs_opt_in is True
    assert item("reply", None).needs_opt_in is False


# --- pure helpers --------------------------------------------------------------------


def test_variables_positional_and_named() -> None:
    components = [
        {"type": "HEADER", "format": "TEXT", "text": "Pedido {{1}}"},
        {"type": "BODY", "text": "Hola {{2}} y {{1}}"},
    ]
    assert template_variables(components) == [
        TemplateVariable("header", "1", False),
        TemplateVariable("body", "1", False),
        TemplateVariable("body", "2", False),
    ]
    named = template_variables(_body("Hola {{nombre}}, tu {{pedido}}"))
    assert [v.id for v in named] == ["body:nombre", "body:pedido"]
    assert prefill(named, "Ana Pérez") == {"body:nombre": "Ana"}
    assert prefill(named, None) == {}
    assert send_components(named, {"body:nombre": "Ana", "body:pedido": "#4"}) == [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "Ana", "parameter_name": "nombre"},
                {"type": "text", "text": "#4", "parameter_name": "pedido"},
            ],
        }
    ]


def test_preview_joins_header_body_and_footer() -> None:
    components = [
        {"type": "HEADER", "format": "TEXT", "text": "Tu pedido"},
        {"type": "BODY", "text": "Hola {{1}}"},
        {"type": "FOOTER", "text": "Responde STOP para no recibir más"},
    ]
    assert render_preview(components, {"body:1": "Ana"}) == (
        "Tu pedido\n\nHola Ana\n\nResponde STOP para no recibir más"
    )


def test_unfillable_reasons() -> None:
    assert unfillable_reason(_body("Hola")) == ""
    assert unfillable_reason([{"type": "HEADER", "format": "VIDEO"}]) == "media_header"
    url_var = [{"type": "BUTTONS", "buttons": [{"type": "URL", "url": "https://x.co/{{1}}"}]}]
    assert unfillable_reason(url_var) == "button_variable"
    flow = [{"type": "BUTTONS", "buttons": [{"type": "FLOW"}]}]
    assert unfillable_reason(flow) == "button_kind"


def test_variable_examples_reads_meta_positional_and_named_examples() -> None:
    positional = [
        {"type": "HEADER", "format": "TEXT", "text": "{{1}}", "example": {"header_text": ["2x1"]}},
        {"type": "BODY", "text": "Hola {{1}}, {{2}}", "example": {"body_text": [["Ana", "12"]]}},
    ]
    assert variable_examples(positional) == {
        "header:1": "2x1",
        "body:1": "Ana",
        "body:2": "12",
    }
    named = [
        {
            "type": "BODY",
            "text": "Hola {{nombre}}",
            "example": {"body_text_named_params": [{"param_name": "nombre", "example": "Ana"}]},
        }
    ]
    assert variable_examples(named) == {"body:nombre": "Ana"}
    # Missing or malformed examples are skipped, never raised.
    assert variable_examples([{"type": "BODY", "text": "Hola", "example": "x"}]) == {}
    assert variable_examples([{"type": "BODY", "text": "Hola {{1}}"}]) == {}
