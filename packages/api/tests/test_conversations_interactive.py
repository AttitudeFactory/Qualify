"""Quick replies and button templates (m-24789472, phase 3, B3/B5), offline against the
corpus shapes (`instagram-messaging/features/quick-replies.md`, `button-template.md`):

- the exact wire bodies the Instagram sender builds, and every validation bound (13/14
  quick replies, 20/21 characters, 640/641, 3/4 buttons, a non-https link), with Spanish
  messages;
- the service: quick replies only on the LAST chunk of a split reply, a button template
  never split, both refused with «no disponible todavía» while their capability is off and
  without a `HumanApproval`, nothing written before every check passed;
- the sender re-checks the capability from the stored body before calling Meta, and sends
  the body unchanged; the outbound bubble carries the button template's text;
- an echo of a button template (no `text`) is ingested;
- the template library: buttons validated, `kind`, rendered with the text, kept on a
  PR-1 style update, and an old text template unchanged;
- the migration's constants stay in step with `interactive`.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from qualify_api.conversations.choices import CHOICE_BUTTON, postback_kind
from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    ChannelRegistry,
    RemoteConversation,
    RemoteMessage,
    SourceConnection,
)
from qualify_api.conversations.instagram_source import InstagramDirectSender
from qualify_api.conversations.interactive import (
    ERR_BUTTON_KIND_UNKNOWN,
    ERR_BUTTON_PAYLOAD_TOO_LONG,
    ERR_BUTTON_TEXT_EMPTY,
    ERR_BUTTON_TEXT_TOO_LONG,
    ERR_BUTTON_TITLE_EMPTY,
    ERR_BUTTON_TITLE_REPEATED,
    ERR_BUTTON_TITLE_TOO_LONG,
    ERR_BUTTON_URL_INVALID,
    ERR_BUTTONS_EMPTY,
    ERR_BUTTONS_TOO_MANY,
    ERR_QUICK_REPLIES_TOO_MANY,
    ERR_QUICK_REPLY_KIND_UNKNOWN,
    ERR_QUICK_REPLY_PAYLOAD_TOO_LONG,
    ERR_QUICK_REPLY_PHONE_REPEATED,
    ERR_QUICK_REPLY_TITLE_EMPTY,
    ERR_QUICK_REPLY_TITLE_REPEATED,
    ERR_QUICK_REPLY_TITLE_TOO_LONG,
    MAX_BUTTON_TEMPLATE_TEXT_CHARS,
    MAX_BUTTON_TITLE_CHARS,
    MAX_BUTTONS,
    MESSAGES,
    InteractiveMessageError,
    QuickReply,
    TemplateButton,
    buttons_from_json,
    buttons_wire,
    clean_buttons,
    clean_quick_replies,
    has_quick_replies,
    is_structured_template,
    payload_slug,
)
from qualify_api.conversations.memory_source import (
    SHAPE_VERSION_MEMORY,
    MemoryConversationSender,
    MemoryConversationSource,
)
from qualify_api.conversations.outbox import (
    ApprovalRequired,
    HumanApproval,
    MemoryConversationOutboxRepository,
    payload_text,
)
from qualify_api.conversations.repository import MemoryConversationRepository
from qualify_api.conversations.sender import (
    ERROR_QUICK_REPLIES_DISABLED,
    ERROR_STRUCTURED_TEMPLATES_DISABLED,
    ConversationOutboxSender,
)
from qualify_api.conversations.service import (
    MAX_REPLY_CHARS,
    CapabilityUnavailable,
    ConversationService,
    WindowClosed,
)
from qualify_api.conversations.sync import ConversationSyncService
from qualify_api.conversations.templates import (
    ERR_BODY_TOO_LONG_FOR_BUTTONS,
    KIND_BUTTONS,
    KIND_TEXT,
    MAX_BUTTONS_BODY_CHARS,
    MemoryReplyTemplateRepository,
    ReplyTemplateError,
    ReplyTemplateService,
)
from qualify_api.conversations.webhook import parse_messaging_item
from qualify_api.followups.capabilities import Capabilities, Capability

T0 = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
TENANT = uuid4()
USER = uuid4()
CONNECTION = SourceConnection(
    tenant_id=TENANT, connection_id=uuid4(), external_account_id="ig-1", linked_page_id="p1"
)
ALICE = RemoteConversation(counterpart_external_id="igsid-alice")
APPROVAL = HumanApproval(user_id=USER, approved_at=T0)
ALL_ON = Capabilities(frozenset({Capability.QUICK_REPLIES, Capability.STRUCTURED_TEMPLATES}))
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _code(exc: pytest.ExceptionInfo[BaseException]) -> str:
    return exc.value.code  # type: ignore[attr-defined]


async def _no_client(tenant_id: UUID, connection_id: UUID):  # pragma: no cover - unused
    raise AssertionError("builders never call Meta")


def _ig() -> InstagramDirectSender:
    return InstagramDirectSender(client_factory=_no_client, graph_url="https://graph.test/v21.0")


# --- exact wire bodies (corpus shapes) ----------------------------------------------------


def test_quick_replies_ride_on_the_text_message_in_the_corpus_shape() -> None:
    body = _ig().build_payload(
        recipient_external_id="igsid",
        text=" ¿Te lo apartamos? ",
        quick_replies=[
            QuickReply("Sí"),
            QuickReply("No, gracias", payload="NO"),
            QuickReply.phone(),
        ],
    )
    assert body == {
        "recipient": {"id": "igsid"},
        "message": {
            "text": "¿Te lo apartamos?",
            "quick_replies": [
                {"content_type": "text", "title": "Sí", "payload": "QR_SI"},
                {"content_type": "text", "title": "No, gracias", "payload": "NO"},
                {"content_type": "user_phone_number"},
            ],
        },
    }
    assert has_quick_replies(body) and not is_structured_template(body)


def test_no_quick_replies_is_the_unchanged_text_body() -> None:
    sender = _ig()
    assert sender.build_payload(recipient_external_id="igsid", text="hola", quick_replies=[]) == {
        "recipient": {"id": "igsid"},
        "message": {"text": "hola"},
    }


def test_button_template_body_is_the_corpus_shape() -> None:
    body = _ig().build_button_template_payload(
        recipient_external_id="igsid",
        text="  ¿Qué quieres hacer?  ",
        buttons=[
            TemplateButton.web_url("Ver catálogo", "https://polette.co/catalogo"),
            TemplateButton.postback("Hablar con alguien"),
            TemplateButton.postback("Precios", payload="PRECIOS"),
        ],
    )
    assert body == {
        "recipient": {"id": "igsid"},
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": "¿Qué quieres hacer?",
                    "buttons": [
                        {
                            "type": "web_url",
                            "url": "https://polette.co/catalogo",
                            "title": "Ver catálogo",
                        },
                        {
                            "type": "postback",
                            "title": "Hablar con alguien",
                            "payload": "QFB_HABLAR_CON_ALGUIEN",
                        },
                        {"type": "postback", "title": "Precios", "payload": "QFB_PRECIOS"},
                    ],
                },
            }
        },
    }
    assert is_structured_template(body) and not has_quick_replies(body)
    assert payload_text(body) == "¿Qué quieres hacer?"
    # The tap comes back as a postback that phase 1 already reads as a button.
    assert postback_kind("QFB_HABLAR_CON_ALGUIEN") == CHOICE_BUTTON


def test_the_memory_sender_builds_the_same_bodies() -> None:
    memory, ig = MemoryConversationSender(), _ig()
    replies = [QuickReply("Sí")]
    buttons = [TemplateButton.postback("Sí")]
    assert memory.build_payload(
        recipient_external_id="x", text="hola", quick_replies=replies
    ) == ig.build_payload(recipient_external_id="x", text="hola", quick_replies=replies)
    assert memory.build_button_template_payload(
        recipient_external_id="x", text="hola", buttons=buttons
    ) == ig.build_button_template_payload(recipient_external_id="x", text="hola", buttons=buttons)


# --- validation bounds --------------------------------------------------------------------


def test_thirteen_quick_replies_pass_fourteen_do_not() -> None:
    thirteen = [QuickReply(f"Opción {n}") for n in range(13)]
    assert len(clean_quick_replies(thirteen)) == 13
    with pytest.raises(InteractiveMessageError) as exc:
        clean_quick_replies([*thirteen, QuickReply("Otra")])
    assert _code(exc) == ERR_QUICK_REPLIES_TOO_MANY


def test_quick_reply_title_is_one_to_twenty_characters() -> None:
    (reply,) = clean_quick_replies([QuickReply("  " + "a" * 20 + " ")])
    assert reply.title == "a" * 20
    with pytest.raises(InteractiveMessageError) as exc:
        clean_quick_replies([QuickReply("ok"), QuickReply("a" * 21)])
    assert _code(exc) == ERR_QUICK_REPLY_TITLE_TOO_LONG and exc.value.index == 1
    with pytest.raises(InteractiveMessageError) as exc:
        clean_quick_replies([QuickReply("   ")])
    assert _code(exc) == ERR_QUICK_REPLY_TITLE_EMPTY


def test_quick_reply_titles_are_unique_ignoring_case_and_spaces() -> None:
    with pytest.raises(InteractiveMessageError) as exc:
        clean_quick_replies([QuickReply("Sí  claro"), QuickReply("sí claro")])
    assert _code(exc) == ERR_QUICK_REPLY_TITLE_REPEATED


def test_default_payloads_are_slugs_and_never_collide() -> None:
    cleaned = clean_quick_replies([QuickReply("Sí"), QuickReply("Si!"), QuickReply("¿?")])
    assert [r.payload for r in cleaned] == ["QR_SI", "QR_SI_2", "QR_OPCION"]
    assert payload_slug("¿Ver catálogo?") == "VER_CATALOGO"


def test_quick_reply_payload_limit_and_kinds() -> None:
    assert clean_quick_replies([QuickReply("a", payload="x" * 1000)])[0].payload == "x" * 1000
    with pytest.raises(InteractiveMessageError) as exc:
        clean_quick_replies([QuickReply("a", payload="x" * 1001)])
    assert _code(exc) == ERR_QUICK_REPLY_PAYLOAD_TOO_LONG
    with pytest.raises(InteractiveMessageError) as exc:
        clean_quick_replies([QuickReply("a", content_type="user_email")])
    assert _code(exc) == ERR_QUICK_REPLY_KIND_UNKNOWN
    with pytest.raises(InteractiveMessageError) as exc:
        clean_quick_replies([QuickReply.phone(), QuickReply.phone()])
    assert _code(exc) == ERR_QUICK_REPLY_PHONE_REPEATED


def test_three_buttons_pass_four_and_none_do_not() -> None:
    three = [TemplateButton.postback(f"Botón {n}") for n in range(MAX_BUTTONS)]
    assert len(clean_buttons(three)) == 3
    with pytest.raises(InteractiveMessageError) as exc:
        clean_buttons([*three, TemplateButton.postback("Otro")])
    assert _code(exc) == ERR_BUTTONS_TOO_MANY
    with pytest.raises(InteractiveMessageError) as exc:
        clean_buttons([])
    assert _code(exc) == ERR_BUTTONS_EMPTY


def test_button_title_is_one_to_twenty_characters_and_unique() -> None:
    assert clean_buttons([TemplateButton.postback("b" * MAX_BUTTON_TITLE_CHARS)])
    with pytest.raises(InteractiveMessageError) as exc:
        clean_buttons([TemplateButton.postback("b" * 21)])
    assert _code(exc) == ERR_BUTTON_TITLE_TOO_LONG
    with pytest.raises(InteractiveMessageError) as exc:
        clean_buttons([TemplateButton.postback(" ")])
    assert _code(exc) == ERR_BUTTON_TITLE_EMPTY
    with pytest.raises(InteractiveMessageError) as exc:
        clean_buttons([TemplateButton.postback("Sí"), TemplateButton.web_url("SÍ", "https://a.co")])
    assert _code(exc) == ERR_BUTTON_TITLE_REPEATED and exc.value.index == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://polette.co",
        "ftp://polette.co/x",
        "https://",
        "https://localhost/x",
        "https://polette.co/a b",
        "polette.co",
        "",
        "https://" + "a" * 2000 + ".co",
    ],
)
def test_a_link_button_must_be_a_full_https_address(url: str) -> None:
    with pytest.raises(InteractiveMessageError) as exc:
        clean_buttons([TemplateButton.web_url("Ver", url)])
    assert _code(exc) == ERR_BUTTON_URL_INVALID


def test_postback_payloads_always_carry_the_qfb_prefix() -> None:
    cleaned = clean_buttons(
        [
            TemplateButton.postback("Ver catálogo"),
            TemplateButton.postback("Precio", payload="PRECIO"),
            TemplateButton.postback("Horario", payload="QFB_HORARIO"),
        ]
    )
    assert [b.payload for b in cleaned] == ["QFB_VER_CATALOGO", "QFB_PRECIO", "QFB_HORARIO"]
    with pytest.raises(InteractiveMessageError) as exc:
        clean_buttons([TemplateButton.postback("a", payload="x" * 1000)])
    assert _code(exc) == ERR_BUTTON_PAYLOAD_TOO_LONG
    with pytest.raises(InteractiveMessageError) as exc:
        clean_buttons([TemplateButton(type="phone_number", title="Llamar")])
    assert _code(exc) == ERR_BUTTON_KIND_UNKNOWN


def test_button_template_text_is_one_to_640_characters() -> None:
    sender = _ig()
    ok = sender.build_button_template_payload(
        recipient_external_id="x", text="t" * 640, buttons=[TemplateButton.postback("Sí")]
    )
    assert ok["message"]["attachment"]["payload"]["text"] == "t" * 640
    for text, code in (("t" * 641, ERR_BUTTON_TEXT_TOO_LONG), ("  ", ERR_BUTTON_TEXT_EMPTY)):
        with pytest.raises(InteractiveMessageError) as exc:
            sender.build_button_template_payload(
                recipient_external_id="x", text=text, buttons=[TemplateButton.postback("Sí")]
            )
        assert _code(exc) == code


def test_every_message_is_spanish_and_is_the_error_text() -> None:
    english = re.compile(r"\b(the|button|link|reply|must|payload|title)\b", re.I)
    for code, message in MESSAGES.items():
        assert message and not english.search(message), code
        assert str(InteractiveMessageError(code)) == message


def test_stored_buttons_read_back_leniently() -> None:
    buttons = clean_buttons(
        [TemplateButton.postback("Sí"), TemplateButton.web_url("Web", "https://a.co")]
    )
    assert buttons_from_json(buttons_wire(buttons)) == buttons
    assert buttons_from_json([{"type": "call"}, "x", {"type": "postback", "title": "A"}]) == (
        TemplateButton.postback("A"),
    )
    assert buttons_from_json(None) == ()


# --- service + outbox + sender ------------------------------------------------------------


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _world(*, enqueue_caps: Capabilities | None, send_caps: bool):
    clock = Clock(T0 + timedelta(minutes=5))
    repo = MemoryConversationRepository()
    outbox = MemoryConversationOutboxRepository(clock=clock)
    sender = MemoryConversationSender()
    registry = ChannelRegistry()
    registry.register(source=MemoryConversationSource(), sender=sender)
    service = ConversationService(
        repository=repo, outbox=outbox, registry=registry, clock=clock, capabilities=enqueue_caps
    )
    ConversationSyncService(repository=repo, clock=clock).ingest_message(
        CONNECTION,
        channel=CHANNEL_DM,
        conversation=ALICE,
        message=RemoteMessage(
            external_message_id="mid.1",
            direction="inbound",
            text="hola",
            posted_at=T0,
            shape_version=SHAPE_VERSION_MEMORY,
            author_external_id="igsid-alice",
        ),
    )
    thread = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])[0]
    loop = ConversationOutboxSender(
        outbox=outbox,
        repository=repo,
        registry=registry,
        connections=lambda t, c: CONNECTION,
        quick_replies=send_caps,
        structured_templates=send_caps,
        worker_id="test:1",
        clock=clock,
    )
    return clock, outbox, sender, service, thread, loop


def test_quick_replies_are_refused_while_their_capability_is_off() -> None:
    _c, outbox, _s, service, thread, _l = _world(enqueue_caps=None, send_caps=False)
    with pytest.raises(CapabilityUnavailable) as exc:
        service.reply_text(
            tenant_id=TENANT,
            thread_id=thread.id,
            text="hola",
            approval=APPROVAL,
            quick_replies=[QuickReply("Sí")],
        )
    assert str(exc.value) == "Las respuestas rápidas no están disponibles todavía."
    assert exc.value.state_label == "Por verificar"
    assert "QUALIFY_QUICK_REPLIES" in exc.value.reason
    assert outbox.rows == {}
    off = service.availability(Capability.QUICK_REPLIES)
    assert off.enabled is False


def test_a_button_template_is_refused_while_its_capability_is_off() -> None:
    _c, outbox, _s, service, thread, _l = _world(
        enqueue_caps=Capabilities(frozenset({Capability.QUICK_REPLIES})), send_caps=False
    )
    with pytest.raises(CapabilityUnavailable) as exc:
        service.reply_buttons(
            tenant_id=TENANT,
            thread_id=thread.id,
            text="hola",
            buttons=[TemplateButton.postback("Sí")],
            approval=APPROVAL,
        )
    assert str(exc.value) == "Los mensajes con botones no están disponibles todavía."
    assert "QUALIFY_STRUCTURED_TEMPLATES" in exc.value.reason
    assert outbox.rows == {}


def test_quick_replies_attach_only_to_the_last_chunk_of_a_split_reply() -> None:
    _c, outbox, _s, service, thread, _l = _world(enqueue_caps=ALL_ON, send_caps=True)
    long_text = ("Primera frase larga. " * 60).strip() + " ¿Lo quieres?"
    assert len(long_text) > MAX_REPLY_CHARS
    ids = service.reply_text(
        tenant_id=TENANT,
        thread_id=thread.id,
        text=long_text,
        approval=APPROVAL,
        quick_replies=[QuickReply("Sí"), QuickReply("No")],
    )
    assert len(ids) >= 2
    payloads = [outbox.rows[i].payload for i in ids]
    assert [has_quick_replies(p) for p in payloads] == [False] * (len(ids) - 1) + [True]
    assert payloads[-1]["message"]["quick_replies"] == [
        {"content_type": "text", "title": "Sí", "payload": "QR_SI"},
        {"content_type": "text", "title": "No", "payload": "QR_NO"},
    ]
    assert all(outbox.rows[i].approved_by_user_id == USER for i in ids)


def test_invalid_quick_replies_write_nothing_even_for_a_split_reply() -> None:
    _c, outbox, _s, service, thread, _l = _world(enqueue_caps=ALL_ON, send_caps=True)
    with pytest.raises(InteractiveMessageError):
        service.reply_text(
            tenant_id=TENANT,
            thread_id=thread.id,
            text="x. " * 600,
            approval=APPROVAL,
            quick_replies=[QuickReply("a" * 21)],
        )
    assert outbox.rows == {}


def test_a_button_template_is_never_split() -> None:
    _c, outbox, _s, service, thread, _l = _world(enqueue_caps=ALL_ON, send_caps=True)
    with pytest.raises(InteractiveMessageError) as exc:
        service.reply_buttons(
            tenant_id=TENANT,
            thread_id=thread.id,
            text="t" * (MAX_BUTTON_TEMPLATE_TEXT_CHARS + 1),
            buttons=[TemplateButton.postback("Sí")],
            approval=APPROVAL,
        )
    assert _code(exc) == ERR_BUTTON_TEXT_TOO_LONG
    assert outbox.rows == {}


def test_both_need_a_human_approval() -> None:
    _c, outbox, _s, service, thread, _l = _world(enqueue_caps=ALL_ON, send_caps=True)
    with pytest.raises(ApprovalRequired):
        service.reply_buttons(
            tenant_id=TENANT,
            thread_id=thread.id,
            text="hola",
            buttons=[TemplateButton.postback("Sí")],
            approval=None,  # type: ignore[arg-type]
        )
    with pytest.raises(ApprovalRequired):
        service.reply_text(
            tenant_id=TENANT,
            thread_id=thread.id,
            text="hola",
            approval=None,  # type: ignore[arg-type]
            quick_replies=[QuickReply("Sí")],
        )
    assert outbox.rows == {}


def test_both_respect_the_24_hour_window() -> None:
    clock, outbox, _s, service, thread, _l = _world(enqueue_caps=ALL_ON, send_caps=True)
    clock.now = T0 + timedelta(hours=25)
    with pytest.raises(WindowClosed):
        service.reply_buttons(
            tenant_id=TENANT,
            thread_id=thread.id,
            text="hola",
            buttons=[TemplateButton.postback("Sí")],
            approval=APPROVAL,
        )
    with pytest.raises(WindowClosed):
        service.reply_text(
            tenant_id=TENANT,
            thread_id=thread.id,
            text="hola",
            approval=APPROVAL,
            quick_replies=[QuickReply("Sí")],
        )
    assert outbox.rows == {}


async def test_the_sender_sends_both_bodies_unchanged_while_on() -> None:
    _c, outbox, sender, service, thread, loop = _world(enqueue_caps=ALL_ON, send_caps=True)
    (qr_id,) = service.reply_text(
        tenant_id=TENANT,
        thread_id=thread.id,
        text="¿Te lo apartamos?",
        approval=APPROVAL,
        quick_replies=[QuickReply("Sí")],
    )
    bt_id = service.reply_buttons(
        tenant_id=TENANT,
        thread_id=thread.id,
        text="¿Qué quieres hacer?",
        buttons=[TemplateButton.postback("Ver catálogo")],
        approval=APPROVAL,
    )
    stored = {i: dict(outbox.rows[i].payload) for i in (qr_id, bt_id)}

    report = await loop.run_once(TENANT)

    assert (report.sent, report.failed) == (2, 0)
    assert [r.payload for r in sender.sent] == [stored[qr_id], stored[bt_id]]
    assert [m.text for m in outbox.messages] == ["¿Te lo apartamos?", "¿Qué quieres hacer?"]


async def test_the_sender_rechecks_the_capability_before_calling_meta() -> None:
    _c, outbox, sender, service, thread, loop = _world(enqueue_caps=ALL_ON, send_caps=False)
    (qr_id,) = service.reply_text(
        tenant_id=TENANT,
        thread_id=thread.id,
        text="hola",
        approval=APPROVAL,
        quick_replies=[QuickReply("Sí")],
    )
    bt_id = service.reply_buttons(
        tenant_id=TENANT,
        thread_id=thread.id,
        text="hola",
        buttons=[TemplateButton.postback("Sí")],
        approval=APPROVAL,
    )
    (plain_id,) = service.reply_text(
        tenant_id=TENANT, thread_id=thread.id, text="hola", approval=APPROVAL
    )

    report = await loop.run_once(TENANT)

    assert (report.sent, report.failed) == (1, 2)
    assert outbox.rows[qr_id].error_code == ERROR_QUICK_REPLIES_DISABLED
    assert outbox.rows[bt_id].error_code == ERROR_STRUCTURED_TEMPLATES_DISABLED
    assert outbox.rows[plain_id].status == "sent"
    assert [r.payload for r in sender.sent] == [outbox.rows[plain_id].payload]


# --- the echo of a button template ------------------------------------------------------


def test_a_button_template_echo_is_ingested_with_its_text() -> None:
    item = {
        "sender": {"id": "ig-1"},
        "recipient": {"id": "igsid-alice"},
        "timestamp": 1761220800000,
        "message": {
            "mid": "m_echo_1",
            "is_echo": True,
            "attachments": [
                {
                    "type": "template",
                    "payload": {
                        "template_type": "button",
                        "text": "¿Qué quieres hacer?",
                        "buttons": [
                            {"type": "postback", "title": "Sí", "payload": "QFB_SI"},
                        ],
                    },
                }
            ],
        },
    }
    conversation, message = parse_messaging_item(item, own_account_id="ig-1")  # type: ignore[misc]
    assert conversation.counterpart_external_id == "igsid-alice"
    assert message.direction == "outbound"
    assert message.text == "¿Qué quieres hacer?"
    assert message.media_type == "interactive" and message.media_url is None
    assert message.choice_kind is None

    repo = MemoryConversationRepository()
    result = ConversationSyncService(repository=repo, clock=lambda: T0).ingest_message(
        CONNECTION, channel=CHANNEL_DM, conversation=conversation, message=message
    )
    assert result.message_created is True
    stored = repo.list_messages(tenant_id=TENANT, thread_id=UUID(result.thread_id), limit=5)
    assert [(m.direction, m.text) for m in stored] == [("outbound", "¿Qué quieres hacer?")]


def test_an_echo_of_a_quick_reply_message_is_not_a_tap() -> None:
    item = {
        "sender": {"id": "ig-1"},
        "recipient": {"id": "igsid-alice"},
        "timestamp": 1761220800000,
        "message": {"mid": "m_echo_2", "is_echo": True, "text": "¿Te lo apartamos?"},
    }
    _conversation, message = parse_messaging_item(item, own_account_id="ig-1")  # type: ignore[misc]
    assert message.direction == "outbound" and message.choice_kind is None


# --- the template library with buttons --------------------------------------------------


def _library():
    _c, _o, _s, _service, thread, _l = _world(enqueue_caps=None, send_caps=False)
    templates = ReplyTemplateService(
        repository=MemoryReplyTemplateRepository(),
        threads=_ThreadReader(thread),
        brand_name=lambda t, c: "Polette",
    )
    return templates, thread


class _ThreadReader:
    def __init__(self, thread) -> None:
        self._thread = thread

    def get_thread(self, *, tenant_id: UUID, thread_id: UUID):
        return self._thread if thread_id == self._thread.id else None


def test_a_template_with_buttons_is_validated_and_rendered_with_them() -> None:
    templates, thread = _library()
    created = templates.create(
        tenant_id=TENANT,
        connection_id=thread.connection_id,
        title="Catálogo con botones",
        body="Hola {nombre}, ¿qué quieres ver de {marca}?",
        user_id=USER,
        buttons=[
            TemplateButton.web_url("Ver catálogo", "https://polette.co"),
            TemplateButton.postback("Precios"),
        ],
    )
    assert created.kind == KIND_BUTTONS
    assert [b.payload for b in created.buttons] == [None, "QFB_PRECIOS"]
    rendered = templates.render(tenant_id=TENANT, template_id=created.id, thread_id=thread.id)
    assert rendered.kind == KIND_BUTTONS and rendered.buttons == created.buttons
    assert "Polette" in rendered.text

    # A PR-1 style edit (title and body only) keeps the buttons; `()` removes them.
    kept = templates.update(
        tenant_id=TENANT, template_id=created.id, title="Catálogo", body="Mira:", user_id=USER
    )
    assert kept.buttons == created.buttons
    plain = templates.update(
        tenant_id=TENANT,
        template_id=created.id,
        title="Catálogo",
        body="x" * 1000,
        user_id=USER,
        buttons=(),
    )
    assert plain.kind == KIND_TEXT and plain.buttons == ()


def test_template_buttons_errors_are_template_errors_in_spanish() -> None:
    templates, thread = _library()
    with pytest.raises(ReplyTemplateError) as exc:
        templates.create(
            tenant_id=TENANT,
            connection_id=thread.connection_id,
            title="Mucho",
            body="hola",
            user_id=USER,
            buttons=[TemplateButton.postback(f"B{n}") for n in range(4)],
        )
    assert exc.value.code == ERR_BUTTONS_TOO_MANY
    assert str(exc.value) == MESSAGES[ERR_BUTTONS_TOO_MANY]
    with pytest.raises(ReplyTemplateError) as exc:
        templates.create(
            tenant_id=TENANT,
            connection_id=thread.connection_id,
            title="Largo",
            body="t" * (MAX_BUTTONS_BODY_CHARS + 1),
            user_id=USER,
            buttons=[TemplateButton.postback("Sí")],
        )
    assert exc.value.code == ERR_BODY_TOO_LONG_FOR_BUTTONS
    assert "640" in str(exc.value)


def test_an_old_text_template_is_unchanged() -> None:
    templates, thread = _library()
    library = templates.list_for_connection(tenant_id=TENANT, connection_id=thread.connection_id)
    assert library and all(t.kind == KIND_TEXT and t.buttons == () for t in library)
    rendered = templates.render(tenant_id=TENANT, template_id=library[0].id, thread_id=thread.id)
    assert rendered.kind == KIND_TEXT and rendered.buttons == ()


# --- the migration stays in step ---------------------------------------------------------


def test_migration_0084_mirrors_the_interactive_limits() -> None:
    source = (_REPO_ROOT / "migrations/postgres/versions/0084_reply_template_buttons.py").read_text(
        encoding="utf-8"
    )
    assert f"_MAX_BUTTONS = {MAX_BUTTONS}" in source
    assert f"_MAX_BUTTON_TITLE = {MAX_BUTTON_TITLE_CHARS}" in source
    assert f"_MAX_BUTTON_BODY = {MAX_BUTTON_TEMPLATE_TEXT_CHARS}" in source
    assert '"QFB_"' in source and '"https://"' in source
