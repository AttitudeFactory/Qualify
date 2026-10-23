"""Taps that reach Conversaciones (m-24789472, PR 2: B4, B5), offline, against fixtures of
the documented contracts:

- the `postback` item of the `messages` webhook (`business-messaging/instagram-messaging/
  webhooks.md` «Messaging postbacks»: `{"mid", "title", "payload"}`; `features/
  ice-breakers.md` shows the same item WITHOUT `mid`);
- a quick reply: a normal `message` whose `text` is the title, plus `quick_reply.payload`
  (`features/quick-replies.md`).

Pins:
1. `choice_label` / `postback_kind` / the payload-prefix convention and its defaults.
2. A postback becomes ONE inbound message (thread created), idempotent by `mid` — or by a
   deterministic synthetic id when Meta sent none; echo, orphan and ambiguous write nothing.
3. A quick reply keeps its text and adds kind + payload; an echo never carries a choice.
4. Poll-first then webhook ENRICHES the row; webhook-first then poll keeps it; a stored
   choice is never replaced.
5. B5: nothing in the intake path can reach the outbox, and a draft for a tap is a
   `proposed` draft that carries the tap as context — never a send.
6. The migration's CHECKed kinds are the module's.
"""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from qualify_api.conversations.choices import (
    CHOICE_BUTTON,
    CHOICE_ICE_BREAKER,
    CHOICE_KINDS,
    CHOICE_MENU,
    CHOICE_QUICK_REPLY,
    DEFAULT_ICE_BREAKERS,
    MAX_CHOICE_PAYLOAD_CHARS,
    choice_context,
    choice_label,
    default_ice_breaker,
    normalize_payload,
    postback_kind,
)
from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    RemoteConversation,
    RemoteMessage,
    SourceConnection,
)
from qualify_api.conversations.drafts import DraftStatus, MemoryDraftRepository
from qualify_api.conversations.instagram_source import SHAPE_VERSION_IG_DM
from qualify_api.conversations.repository import MemoryConversationRepository
from qualify_api.conversations.suggest import (
    ConversationDraftService,
    Grounding,
    Proposal,
    message_context,
)
from qualify_api.conversations.sync import ConversationSyncService
from qualify_api.conversations.webhook import (
    CONTRACT_VIOLATION,
    POSTBACK_ECHO,
    SHAPE_VERSION_IG_POSTBACK,
    SYNTHETIC_POSTBACK_PREFIX,
    instagram_messages_handler,
    parse_messaging_item,
    synthetic_postback_mid,
)
from qualify_api.mentions.resolve import ResolutionOutcome, TenantResolution
from qualify_api.webhooks.repository import (
    MESSAGING_NOT_A_MESSAGE,
    STATUS_AMBIGUOUS,
    STATUS_DEAD,
    STATUS_ORPHAN,
    STATUS_PROCESSED,
    STATUS_UNSUPPORTED,
)

from .test_conversations_webhook import CONNECTION_ID, IGID, TENANT, _event, _resolved

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONVERSATIONS = _REPO_ROOT / "packages/api/src/qualify_api/conversations"

TS = 1760616000000
AT = datetime.fromtimestamp(TS / 1000, UTC)

# `webhooks.md` «Messaging postbacks», with Qualify's default Ice Breaker payload.
ICE_BREAKER = {
    "sender": {"id": "igsid-alice"},
    "recipient": {"id": IGID},
    "timestamp": TS,
    "postback": {
        "mid": "mid.ib.1",
        "title": "¿Quieres consultar un precio?",
        "payload": "QF_PRECIO",
    },
}
# `features/ice-breakers.md`: the same item, as documented there, without `mid`.
ICE_BREAKER_NO_MID = {
    **ICE_BREAKER,
    "postback": {"title": "¿Quieres consultar un precio?", "payload": "QF_PRECIO"},
}
# `features/quick-replies.md`: the title is the text, the payload rides along.
QUICK_REPLY = {
    "sender": {"id": "igsid-alice"},
    "recipient": {"id": IGID},
    "timestamp": TS + 60_000,
    "message": {"mid": "mid.qr.1", "text": "Sí", "quick_reply": {"payload": "QFQ_CONFIRMA_SI"}},
}


def _postback(payload: object, *, mid: str = "mid.pb", title: object = "Ver catálogo") -> dict:
    return {**ICE_BREAKER, "postback": {"mid": mid, "title": title, "payload": payload}}


def _messages(repo: MemoryConversationRepository) -> list[Any]:
    threads = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])
    return [m for t in threads for m in repo.list_messages(tenant_id=TENANT, thread_id=t.id)]


@pytest.fixture
def world():
    repo = MemoryConversationRepository()
    sync = ConversationSyncService(repository=repo)
    return repo, sync, instagram_messages_handler(resolve=_resolved(), sync=sync)


# --- 1. the convention ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "payload", "title", "label"),
    [
        (
            CHOICE_ICE_BREAKER,
            "QF_PRECIO",
            "¿Quieres consultar un precio?",
            "Pregunta inicial: Precio",
        ),
        (
            CHOICE_ICE_BREAKER,
            "QF_PRODUCTO",
            "¿Qué producto te interesa?",
            "Pregunta inicial: Productos",
        ),
        # The owner rewrote a default question and kept its payload: the thread names
        # what the person saw, never the default's short name.
        (
            CHOICE_ICE_BREAKER,
            "QF_PRECIO",
            "¿Hacen domicilios?",
            "Pregunta inicial: ¿Hacen domicilios?",
        ),
        (
            CHOICE_ICE_BREAKER,
            "QF_PRECIO",
            "  ¿quieres CONSULTAR un precio? ",
            "Pregunta inicial: Precio",
        ),
        (CHOICE_ICE_BREAKER, "QF_PRECIO", None, "Pregunta inicial: Precio"),
        (
            CHOICE_ICE_BREAKER,
            "QF_UBICACION_HORARIO",
            None,
            "Pregunta inicial: Ubicación y horario",
        ),
        (
            CHOICE_ICE_BREAKER,
            "QF_CATALOGO",
            "¿Quieres conocer el catálogo?",
            "Pregunta inicial: Catálogo",
        ),
        # A QF_ payload that is not a default: the title the person saw.
        (CHOICE_ICE_BREAKER, "QF_ENVIOS", "¿Hacen envíos?", "Pregunta inicial: ¿Hacen envíos?"),
        (CHOICE_QUICK_REPLY, "QFQ_SI", "Sí", "Respuesta rápida: Sí"),
        (CHOICE_QUICK_REPLY, None, "No, gracias", "Respuesta rápida: No, gracias"),
        (CHOICE_BUTTON, "QFB_VER_CATALOGO", "Ver catálogo", "Botón: Ver catálogo"),
        (CHOICE_MENU, "QFM_HABLAR", "Hablar con alguien", "Menú: Hablar con alguien"),
        # No title and no default name: the kind alone — a payload is never shown.
        (CHOICE_BUTTON, "QFB_VER_CATALOGO", None, "Botón"),
        (CHOICE_MENU, "QFM_X", "   ", "Menú"),
        # Typed, or a kind this module does not know.
        (None, None, "hola", None),
        ("reaction", "x", "y", None),
    ],
)
def test_choice_label_table(
    kind: str | None, payload: str | None, title: str | None, label: str | None
) -> None:
    assert choice_label(kind, payload, title) == label


def test_choice_label_cuts_a_long_title_and_collapses_spaces() -> None:
    label = choice_label(CHOICE_BUTTON, None, "uno  dos\n" + "x" * 200)
    assert label is not None and label.startswith("Botón: uno dos x") and label.endswith("…")
    assert len(label) <= len("Botón: ") + 80


@pytest.mark.parametrize(
    ("payload", "kind"),
    [
        ("QF_PRECIO", CHOICE_ICE_BREAKER),
        ("QF_LO_QUE_SEA", CHOICE_ICE_BREAKER),
        ("QFB_VER_CATALOGO", CHOICE_BUTTON),
        ("QFM_HABLAR", CHOICE_MENU),
        ("CARE_HELP", CHOICE_BUTTON),  # persistent-menu.md's own sample: not ours
        ("qf_precio", CHOICE_BUTTON),  # case-sensitive
        (None, CHOICE_BUTTON),
    ],
)
def test_postback_kind_by_payload_prefix(payload: str | None, kind: str) -> None:
    assert postback_kind(payload) == kind


def test_the_four_default_ice_breakers_are_ours_and_named_in_spanish() -> None:
    assert [ib.payload for ib in DEFAULT_ICE_BREAKERS] == [
        "QF_PRODUCTO",
        "QF_PRECIO",
        "QF_UBICACION_HORARIO",
        "QF_CATALOGO",
    ]
    for ib in DEFAULT_ICE_BREAKERS:
        assert postback_kind(ib.payload) == CHOICE_ICE_BREAKER
        assert default_ice_breaker(ib.payload) == ib
        assert ib.label and ib.question.strip()
        assert len(ib.question) <= 80
    assert default_ice_breaker("QF_ENVIOS") is None


def test_the_default_questions_are_the_tickets_verbatim() -> None:
    assert [ib.question for ib in DEFAULT_ICE_BREAKERS] == [
        "¿Qué producto te interesa?",
        "¿Quieres consultar un precio?",
        "¿Dónde están y cuál es su horario?",
        "¿Quieres conocer el catálogo?",
    ]


def test_normalize_payload() -> None:
    assert normalize_payload("QF_PRECIO") == "QF_PRECIO"
    assert normalize_payload(42) == "42"
    assert normalize_payload("x" * 2000) == "x" * MAX_CHOICE_PAYLOAD_CHARS
    for nothing in (None, "", "   ", True, {"a": 1}, ["x"]):
        assert normalize_payload(nothing) is None


def test_the_migration_checks_exactly_the_module_kinds() -> None:
    source = (_REPO_ROOT / "migrations/postgres/versions/0082_message_choice.py").read_text(
        encoding="utf-8"
    )
    found = re.search(r"_KINDS = \(([^)]*)\)", source)
    assert found is not None
    assert tuple(re.findall(r'"([a-z_]+)"', found.group(1))) == CHOICE_KINDS
    assert f"_MAX_PAYLOAD_CHARS = {MAX_CHOICE_PAYLOAD_CHARS}" in source


# --- 2. postbacks through the webhook ----------------------------------------------------------


def test_an_ice_breaker_postback_parses_as_an_inbound_message() -> None:
    conversation, message = parse_messaging_item(ICE_BREAKER, own_account_id=IGID)
    assert conversation == RemoteConversation(counterpart_external_id="igsid-alice")
    assert message.external_message_id == "mid.ib.1"
    assert message.direction == "inbound"
    assert message.text == "¿Quieres consultar un precio?"
    assert message.posted_at == AT
    assert message.author_external_id == "igsid-alice"
    assert (message.choice_kind, message.choice_payload) == (CHOICE_ICE_BREAKER, "QF_PRECIO")
    assert message.shape_version == SHAPE_VERSION_IG_POSTBACK
    assert message.media_type is None and message.story_reply_id is None


@pytest.mark.parametrize(
    ("payload", "kind"),
    [("QFB_VER_CATALOGO", CHOICE_BUTTON), ("QFM_HABLAR", CHOICE_MENU), ("OTRA_COSA", "button")],
)
def test_template_button_menu_and_unknown_postbacks(payload: str, kind: str) -> None:
    _c, message = parse_messaging_item(_postback(payload), own_account_id=IGID)
    assert (message.choice_kind, message.choice_payload) == (kind, payload)
    assert message.text == "Ver catálogo"


def test_a_postback_without_mid_gets_a_deterministic_synthetic_id() -> None:
    _c, first = parse_messaging_item(ICE_BREAKER_NO_MID, own_account_id=IGID)
    _c, again = parse_messaging_item(dict(ICE_BREAKER_NO_MID), own_account_id=IGID)
    assert first.external_message_id == again.external_message_id
    assert first.external_message_id.startswith(SYNTHETIC_POSTBACK_PREFIX)
    assert first.external_message_id == synthetic_postback_mid(
        sender_id="igsid-alice",
        timestamp=TS,
        payload="QF_PRECIO",
        title="¿Quieres consultar un precio?",
    )
    # Another tap — another instant, another option — is another message.
    later = {**ICE_BREAKER_NO_MID, "timestamp": TS + 1}
    other = {**ICE_BREAKER_NO_MID, "postback": {"title": "x", "payload": "QF_CATALOGO"}}
    ids = {
        parse_messaging_item(v, own_account_id=IGID)[1].external_message_id  # type: ignore[index]
        for v in (ICE_BREAKER_NO_MID, later, other)
    }
    assert len(ids) == 3


def test_a_postback_from_the_account_itself_is_not_a_tap() -> None:
    echo = {**ICE_BREAKER, "sender": {"id": IGID}, "recipient": {"id": "igsid-alice"}}
    assert parse_messaging_item(echo, own_account_id=IGID) == POSTBACK_ECHO


@pytest.mark.parametrize(
    "value",
    [
        {**ICE_BREAKER, "postback": {"mid": "m", "title": "  ", "payload": ""}},  # empty
        {**ICE_BREAKER_NO_MID, "timestamp": None},  # no mid, nothing to key it by
        {"recipient": {"id": IGID}, "postback": {"mid": "m", "title": "x"}},  # no sender
    ],
)
def test_off_contract_postbacks_raise(value: dict) -> None:
    with pytest.raises(ValueError):
        parse_messaging_item(value, own_account_id=IGID)


def test_a_postback_with_only_a_payload_or_only_a_title_is_kept() -> None:
    _c, only_payload = parse_messaging_item(_postback("QFB_X", title=None), own_account_id=IGID)
    assert only_payload.text is None and only_payload.choice_payload == "QFB_X"
    _c, only_title = parse_messaging_item(_postback(None, title="Sí"), own_account_id=IGID)
    assert (only_title.text, only_title.choice_kind, only_title.choice_payload) == (
        "Sí",
        CHOICE_BUTTON,
        None,
    )


async def test_an_ice_breaker_creates_the_thread_and_the_message_and_a_replay_is_a_no_op(
    world,
) -> None:
    repo, _sync, handler = world
    assert (await handler(_event(ICE_BREAKER))).status == STATUS_PROCESSED
    assert (await handler(_event(ICE_BREAKER))).status == STATUS_PROCESSED  # replayed
    threads = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])
    assert len(threads) == 1
    thread = threads[0]
    assert (thread.counterpart_external_id, thread.connection_id) == ("igsid-alice", CONNECTION_ID)
    # A tap opens the 24 h window like a typed message: it is the person writing.
    assert thread.last_inbound_at == AT
    [message] = repo.list_messages(tenant_id=TENANT, thread_id=thread.id)
    assert (message.external_message_id, message.direction) == ("mid.ib.1", "inbound")
    assert (message.choice_kind, message.choice_payload) == (CHOICE_ICE_BREAKER, "QF_PRECIO")
    assert message.choice_label == "Pregunta inicial: Precio"


async def test_a_postback_without_mid_replayed_is_still_one_row(world) -> None:
    repo, _sync, handler = world
    for _ in range(3):
        assert (await handler(_event(ICE_BREAKER_NO_MID))).status == STATUS_PROCESSED
    assert len(_messages(repo)) == 1


async def test_echo_orphan_ambiguous_and_broken_postbacks_write_nothing() -> None:
    repo = MemoryConversationRepository()
    sync = ConversationSyncService(repository=repo)
    calls: list[str] = []

    def orphan(**kwargs: Any) -> TenantResolution:
        calls.append("orphan")
        return TenantResolution(outcome=ResolutionOutcome.ORPHAN)

    def ambiguous(**kwargs: Any) -> TenantResolution:
        return TenantResolution(outcome=ResolutionOutcome.AMBIGUOUS)

    echo = {**ICE_BREAKER, "sender": {"id": IGID}, "recipient": {"id": "igsid-alice"}}
    outcome = await instagram_messages_handler(resolve=orphan, sync=sync)(_event(echo))
    assert (outcome.status, outcome.error) == (STATUS_UNSUPPORTED, POSTBACK_ECHO)
    assert calls == []  # judged before resolving, like every unsupported item
    assert (
        await instagram_messages_handler(resolve=orphan, sync=sync)(_event(ICE_BREAKER))
    ).status == STATUS_ORPHAN
    assert (
        await instagram_messages_handler(resolve=ambiguous, sync=sync)(_event(ICE_BREAKER))
    ).status == STATUS_AMBIGUOUS
    broken = {**ICE_BREAKER, "postback": {"mid": "m"}}
    dead = await instagram_messages_handler(resolve=_resolved(), sync=sync)(_event(broken))
    assert (dead.status, dead.error) == (STATUS_DEAD, CONTRACT_VIOLATION)
    assert repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM]) == []


def test_the_queue_spells_the_handlers_not_a_message_reason() -> None:
    from qualify_api.conversations.webhook import NOT_A_MESSAGE

    assert MESSAGING_NOT_A_MESSAGE == NOT_A_MESSAGE


# --- 3. quick replies -----------------------------------------------------------------------------


def test_a_quick_reply_keeps_its_text_and_adds_kind_and_payload() -> None:
    _c, message = parse_messaging_item(QUICK_REPLY, own_account_id=IGID)
    assert (message.external_message_id, message.direction, message.text) == (
        "mid.qr.1",
        "inbound",
        "Sí",
    )
    assert (message.choice_kind, message.choice_payload) == (CHOICE_QUICK_REPLY, "QFQ_CONFIRMA_SI")
    assert message.shape_version == SHAPE_VERSION_IG_DM


def test_a_quick_reply_without_payload_is_still_a_quick_reply() -> None:
    value = {**QUICK_REPLY, "message": {"mid": "mid.qr.2", "text": "Sí", "quick_reply": {}}}
    _c, message = parse_messaging_item(value, own_account_id=IGID)
    assert (message.choice_kind, message.choice_payload) == (CHOICE_QUICK_REPLY, None)


def test_a_typed_message_and_an_echo_carry_no_choice() -> None:
    typed = {**QUICK_REPLY, "message": {"mid": "mid.t", "text": "Sí"}}
    _c, message = parse_messaging_item(typed, own_account_id=IGID)
    assert (message.choice_kind, message.choice_payload) == (None, None)
    echo = {
        "sender": {"id": IGID},
        "recipient": {"id": "igsid-alice"},
        "timestamp": TS,
        "message": {**QUICK_REPLY["message"], "mid": "mid.e", "is_echo": True},
    }
    _c, message = parse_messaging_item(echo, own_account_id=IGID)
    assert message.direction == "outbound" and message.choice_kind is None


async def test_a_quick_reply_is_stored_with_its_payload(world) -> None:
    repo, _sync, handler = world
    assert (await handler(_event(QUICK_REPLY))).status == STATUS_PROCESSED
    [message] = _messages(repo)
    assert (message.text, message.choice_kind, message.choice_payload) == (
        "Sí",
        CHOICE_QUICK_REPLY,
        "QFQ_CONFIRMA_SI",
    )
    assert message.choice_label == "Respuesta rápida: Sí"


# --- 4. poll and webhook, in either order -------------------------------------------------------


def _poll_copy(mid: str, text: str) -> RemoteMessage:
    """What `GET /{conversation-id}/messages` gives for the same `mid`: the Message node
    has no postback or quick-reply field, so no kind and no payload."""
    return RemoteMessage(
        external_message_id=mid,
        direction="inbound",
        text=text,
        posted_at=AT,
        shape_version=SHAPE_VERSION_IG_DM,
    )


def _poll(sync: ConversationSyncService, message: RemoteMessage) -> bool:
    connection = SourceConnection(
        tenant_id=TENANT, connection_id=CONNECTION_ID, external_account_id=IGID
    )
    return sync.ingest_message(
        connection,
        channel=CHANNEL_DM,
        conversation=RemoteConversation(
            counterpart_external_id="igsid-alice", external_conversation_id="t_1"
        ),
        message=message,
    ).message_created


async def test_poll_first_then_the_webhook_enriches_the_same_row(world) -> None:
    repo, sync, handler = world
    assert _poll(sync, _poll_copy("mid.ib.1", "¿Quieres consultar un precio?")) is True
    assert _poll(sync, _poll_copy("mid.qr.1", "Sí")) is True
    [before, _] = _messages(repo)
    assert before.choice_kind is None

    assert (await handler(_event(ICE_BREAKER))).status == STATUS_PROCESSED
    assert (await handler(_event(QUICK_REPLY))).status == STATUS_PROCESSED
    ib, qr = _messages(repo)
    assert ib.id == before.id  # the same row, never a second one
    assert (ib.choice_kind, ib.choice_payload) == (CHOICE_ICE_BREAKER, "QF_PRECIO")
    assert (qr.choice_kind, qr.choice_payload) == (CHOICE_QUICK_REPLY, "QFQ_CONFIRMA_SI")
    assert len(_messages(repo)) == 2


async def test_webhook_first_then_the_poll_keeps_the_choice(world) -> None:
    repo, sync, handler = world
    await handler(_event(ICE_BREAKER))
    assert _poll(sync, _poll_copy("mid.ib.1", "¿Quieres consultar un precio?")) is False
    [message] = _messages(repo)
    assert (message.choice_kind, message.choice_payload) == (CHOICE_ICE_BREAKER, "QF_PRECIO")


async def test_a_stored_choice_is_never_replaced(world) -> None:
    repo, _sync, handler = world
    await handler(_event(ICE_BREAKER))
    await handler(_event({**ICE_BREAKER, "postback": {"mid": "mid.ib.1", "payload": "QFB_X"}}))
    [message] = _messages(repo)
    assert (message.choice_kind, message.choice_payload) == (CHOICE_ICE_BREAKER, "QF_PRECIO")


# --- 5. B5: assisted, never autonomous ------------------------------------------------------------


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


@pytest.mark.parametrize("module", ["webhook.py", "choices.py", "sync.py"])
def test_the_intake_path_cannot_reach_a_sender_or_the_outbox(module: str) -> None:
    imported = _imported_modules(_CONVERSATIONS / module)
    assert not {m for m in imported if m.endswith((".outbox", ".sender", ".worker"))}


class RecordingGenerator:
    version = "stub:1"

    def __init__(self) -> None:
        self.kwargs: list[dict[str, Any]] = []

    def propose(self, **kwargs: Any) -> Proposal:
        self.kwargs.append(kwargs)
        return Proposal("Tenemos precios desde [precio].", used_only_given_facts=True)


def _draft_service(
    repo: MemoryConversationRepository, gen: RecordingGenerator
) -> ConversationDraftService:
    now = AT + timedelta(minutes=5)
    return ConversationDraftService(
        repository=repo,
        drafts=MemoryDraftRepository(clock=lambda: now),
        generator=gen,
        grounding=lambda tenant, conn: Grounding("Sol"),
        clock=lambda: now,
    )


async def test_a_tap_steers_the_draft_as_context_and_stays_a_proposal(world) -> None:
    repo, _sync, handler = world
    await handler(_event(ICE_BREAKER))
    thread = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])[0]
    gen = RecordingGenerator()
    draft = _draft_service(repo, gen).suggest(tenant_id=TENANT, thread_id=thread.id)

    [call] = gen.kwargs
    assert call["context"] == choice_context(
        CHOICE_ICE_BREAKER, "QF_PRECIO", "¿Quieres consultar un precio?"
    )
    assert "pregunta inicial «¿Quieres consultar un precio?» (QF_PRECIO: Precio)" in call["context"]
    assert draft.status is DraftStatus.PROPOSED  # a person still decides
    assert draft.grounding["choice"] == {"kind": CHOICE_ICE_BREAKER, "payload": "QF_PRECIO"}


async def test_a_typed_message_calls_the_generator_without_context(world) -> None:
    repo, sync, _handler = world
    _poll(sync, _poll_copy("mid.t", "Hola, ¿tienen envíos?"))
    thread = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])[0]
    gen = RecordingGenerator()
    draft = _draft_service(repo, gen).suggest(tenant_id=TENANT, thread_id=thread.id)
    assert "context" not in gen.kwargs[0]
    assert "choice" not in draft.grounding


@pytest.mark.parametrize(
    ("kind", "lead"),
    [
        (CHOICE_QUICK_REPLY, "La persona eligió la respuesta rápida «Sí» (QFQ_SI)."),
        (CHOICE_BUTTON, "La persona tocó el botón «Sí» (QFQ_SI)."),
        (CHOICE_MENU, "La persona eligió en el menú de la conversación la opción «Sí» (QFQ_SI)."),
    ],
)
def test_choice_context_names_the_option(kind: str, lead: str) -> None:
    context = choice_context(kind, "QFQ_SI", "Sí")
    assert context is not None and context.startswith(lead)
    assert "No lo escribió" in context
    assert choice_context(None, None, "Sí") is None


def test_message_context_reads_the_record() -> None:
    repo = MemoryConversationRepository()
    upsert = repo.upsert_thread(
        tenant_id=TENANT,
        connection_id=CONNECTION_ID,
        channel=CHANNEL_DM,
        counterpart_external_id="igsid-bob",
    )
    repo.insert_message(
        tenant_id=TENANT,
        thread_id=upsert.thread_id,
        connection_id=CONNECTION_ID,
        message=RemoteMessage(
            external_message_id=f"mid.{uuid4()}",
            direction="inbound",
            text="Ver catálogo",
            posted_at=AT,
            shape_version=SHAPE_VERSION_IG_POSTBACK,
            choice_kind=CHOICE_BUTTON,
            choice_payload="QFB_VER_CATALOGO",
        ),
    )
    [record] = repo.list_messages(tenant_id=TENANT, thread_id=upsert.thread_id)
    assert record.choice_label == "Botón: Ver catálogo"
    assert message_context(record) == choice_context(
        CHOICE_BUTTON, "QFB_VER_CATALOGO", "Ver catálogo"
    )
