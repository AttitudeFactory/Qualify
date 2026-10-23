"""Message templates for the Conversaciones composer (m-24789472, PR 1), offline.

What these pin:

- validation (title 1–60, body 1–1000, the per-account cap) with Spanish messages;
- the defaults: seeded once, in Spanish, editable, and NOT re-created after deletion;
- reorder takes the whole library or nothing;
- `{nombre}` / `{marca}` rendering, and that a missing or unknown variable stays visible;
- B5: picking or rendering a template never puts anything in `conversation_outbox` — by
  behaviour (a real `ConversationService` beside it stays empty) and by construction (the
  module imports neither the outbox nor a channel).
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from qualify_api.conversations import templates as templates_module
from qualify_api.conversations.contracts import CHANNEL_DM, ChannelRegistry
from qualify_api.conversations.memory_source import (
    MemoryConversationSender,
    MemoryConversationSource,
)
from qualify_api.conversations.outbox import MemoryConversationOutboxRepository
from qualify_api.conversations.repository import MemoryConversationRepository, ThreadRecord
from qualify_api.conversations.service import MAX_REPLY_CHARS, ConversationService
from qualify_api.conversations.templates import (
    DEFAULT_TEMPLATES,
    MAX_BODY_CHARS,
    MAX_TEMPLATES_PER_CONNECTION,
    MAX_TITLE_CHARS,
    MESSAGES,
    MemoryReplyTemplateRepository,
    ReplyTemplateError,
    ReplyTemplateNotFound,
    ReplyTemplateService,
    clean_template,
    render_template,
)

TENANT = UUID("a0000000-0000-4000-8000-0000000007a1")
OTHER = UUID("a0000000-0000-4000-8000-0000000007a2")
CONN = UUID("c0000000-0000-4000-8000-0000000007a1")
CONN_2 = UUID("c0000000-0000-4000-8000-0000000007a2")
OTHER_CONN = UUID("c0000000-0000-4000-8000-0000000007a3")
USER = UUID("b0000000-0000-4000-8000-0000000007a1")
T0 = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


class _Threads:
    def __init__(self, *threads: ThreadRecord) -> None:
        self._threads = {t.id: t for t in threads}

    def get_thread(self, *, tenant_id: UUID, thread_id: UUID) -> ThreadRecord | None:
        thread = self._threads.get(thread_id)
        return thread if thread is not None and thread.tenant_id == tenant_id else None


def _thread(
    *,
    connection_id: UUID = CONN,
    tenant_id: UUID = TENANT,
    name: str | None = "Ana Pérez",
    username: str | None = "ana.perez",
) -> ThreadRecord:
    return ThreadRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        connection_id=connection_id,
        channel=CHANNEL_DM,
        counterpart_external_id="igsid-ana",
        external_conversation_id=None,
        status="open",
        assigned_agent_id=None,
        last_message_at=T0,
        last_inbound_at=T0,
        last_outbound_at=None,
        last_read_at=None,
        created_at=T0,
        counterpart_name=name,
        counterpart_username=username,
    )


def _repo() -> MemoryReplyTemplateRepository:
    return MemoryReplyTemplateRepository(
        connections={CONN: TENANT, CONN_2: TENANT, OTHER_CONN: OTHER}
    )


def _service(
    repo: MemoryReplyTemplateRepository | None = None,
    *threads: ThreadRecord,
    brand: str | None = "Polet Bubble Tea",
) -> ReplyTemplateService:
    return ReplyTemplateService(
        repository=repo if repo is not None else _repo(),
        threads=_Threads(*threads),
        brand_name=lambda _tenant, _conn: brand,
    )


# --- validation ------------------------------------------------------------------------


def test_body_limit_is_one_instagram_message() -> None:
    assert MAX_BODY_CHARS == MAX_REPLY_CHARS == 1000


def test_clean_collapses_the_title_and_trims_the_body() -> None:
    title, body = clean_template("  Precio \n del  día ", "\n Hola.\n\nChao. \n")
    assert title == "Precio del día"
    assert body == "Hola.\n\nChao."


@pytest.mark.parametrize(
    ("title", "body", "code"),
    [
        ("   ", "Hola", "title_empty"),
        ("x" * (MAX_TITLE_CHARS + 1), "Hola", "title_too_long"),
        ("Saludo", " \n ", "body_empty"),
        ("Saludo", "x" * (MAX_BODY_CHARS + 1), "body_too_long"),
    ],
)
def test_clean_refuses_with_a_spanish_message(title: str, body: str, code: str) -> None:
    with pytest.raises(ReplyTemplateError) as caught:
        clean_template(title, body)
    assert caught.value.code == code
    assert str(caught.value) == caught.value.message == MESSAGES[code]


def test_limits_at_the_edge_are_accepted() -> None:
    clean_template("x" * MAX_TITLE_CHARS, "y" * MAX_BODY_CHARS)


def test_every_message_is_spanish_prose() -> None:
    for code, message in MESSAGES.items():
        assert message.endswith("."), code
        assert message[0].isupper(), code
        for english in ("template", "error", "please", "post", "inbox"):
            assert english not in message.lower(), (code, english)


# --- defaults --------------------------------------------------------------------------


def test_defaults_are_four_valid_spanish_templates() -> None:
    assert [d.key for d in DEFAULT_TEMPLATES] == ["greeting", "price", "hours", "catalog"]
    for default in DEFAULT_TEMPLATES:
        assert clean_template(default.title, default.body) == (default.title, default.body)
    bodies = " ".join(d.body for d in DEFAULT_TEMPLATES)
    assert "Gracias por escribirnos" in bodies
    assert "Te comparto el precio" in bodies
    assert "Nuestro horario" in bodies
    assert "Aquí tienes nuestro catálogo" in bodies


def test_first_open_seeds_the_defaults_once() -> None:
    repo = _repo()
    service = _service(repo)
    first = service.list_for_connection(tenant_id=TENANT, connection_id=CONN)
    second = service.list_for_connection(tenant_id=TENANT, connection_id=CONN)
    assert [t.default_key for t in first] == ["greeting", "price", "hours", "catalog"]
    assert [t.id for t in second] == [t.id for t in first]
    assert [t.position for t in first] == [0, 1, 2, 3]
    assert all(t.is_default and t.created_by_user_id is None for t in first)


def test_each_account_has_its_own_library() -> None:
    service = _service()
    a = service.list_for_connection(tenant_id=TENANT, connection_id=CONN)
    b = service.list_for_connection(tenant_id=TENANT, connection_id=CONN_2)
    assert len(a) == len(b) == 4
    assert {t.id for t in a}.isdisjoint({t.id for t in b})


def test_deleted_defaults_are_not_recreated() -> None:
    service = _service()
    for template in service.list_for_connection(tenant_id=TENANT, connection_id=CONN):
        assert service.delete(tenant_id=TENANT, template_id=template.id) is True
    assert service.list_for_connection(tenant_id=TENANT, connection_id=CONN) == []


def test_create_first_still_seeds_the_defaults_before_it() -> None:
    service = _service()
    created = service.create(
        tenant_id=TENANT,
        connection_id=CONN,
        title="Envíos",
        body="Enviamos a todo el país.",
        user_id=USER,
    )
    listed = service.list_for_connection(tenant_id=TENANT, connection_id=CONN)
    assert [t.id for t in listed][-1] == created.id
    assert len(listed) == 5
    assert created.position == 4
    assert created.created_by_user_id == USER and created.default_key is None


# --- create / update / delete ----------------------------------------------------------


def test_cap_per_account() -> None:
    service = _service()
    service.list_for_connection(tenant_id=TENANT, connection_id=CONN)
    for n in range(MAX_TEMPLATES_PER_CONNECTION - len(DEFAULT_TEMPLATES)):
        service.create(
            tenant_id=TENANT, connection_id=CONN, title=f"P{n}", body="Hola", user_id=USER
        )
    with pytest.raises(ReplyTemplateError) as caught:
        service.create(
            tenant_id=TENANT, connection_id=CONN, title="Una más", body="Hola", user_id=USER
        )
    assert caught.value.code == "limit_reached"
    # The cap is per account: another one still has room.
    service.create(tenant_id=TENANT, connection_id=CONN_2, title="Otra", body="Hola", user_id=USER)


def test_update_a_default_keeps_its_key() -> None:
    service = _service()
    greeting = service.list_for_connection(tenant_id=TENANT, connection_id=CONN)[0]
    updated = service.update(
        tenant_id=TENANT,
        template_id=greeting.id,
        title=" Bienvenida ",
        body="¡Hola, {nombre}!",
        user_id=USER,
    )
    assert updated.title == "Bienvenida" and updated.body == "¡Hola, {nombre}!"
    assert updated.default_key == "greeting"
    assert updated.updated_by_user_id == USER


def test_update_validates_before_writing() -> None:
    service = _service()
    greeting = service.list_for_connection(tenant_id=TENANT, connection_id=CONN)[0]
    with pytest.raises(ReplyTemplateError):
        service.update(tenant_id=TENANT, template_id=greeting.id, title="", body="x", user_id=USER)
    again = service.list_for_connection(tenant_id=TENANT, connection_id=CONN)[0]
    assert again.title == greeting.title


def test_update_unknown_template() -> None:
    with pytest.raises(ReplyTemplateNotFound) as caught:
        _service().update(tenant_id=TENANT, template_id=uuid4(), title="a", body="b", user_id=None)
    assert caught.value.code == "template_not_found"
    assert isinstance(caught.value, LookupError)


def test_delete_is_idempotent() -> None:
    service = _service()
    template = service.list_for_connection(tenant_id=TENANT, connection_id=CONN)[0]
    assert service.delete(tenant_id=TENANT, template_id=template.id) is True
    assert service.delete(tenant_id=TENANT, template_id=template.id) is False


# --- reorder ---------------------------------------------------------------------------


def test_reorder_rewrites_positions() -> None:
    service = _service()
    ids = [t.id for t in service.list_for_connection(tenant_id=TENANT, connection_id=CONN)]
    wanted = list(reversed(ids))
    result = service.reorder(tenant_id=TENANT, connection_id=CONN, template_ids=wanted)
    assert [t.id for t in result] == wanted
    assert [t.position for t in result] == [0, 1, 2, 3]
    listed = service.list_for_connection(tenant_id=TENANT, connection_id=CONN)
    assert [t.id for t in listed] == wanted


@pytest.mark.parametrize("change", ["missing", "extra", "repeated"])
def test_reorder_refuses_a_stale_list_and_moves_nothing(change: str) -> None:
    service = _service()
    ids = [t.id for t in service.list_for_connection(tenant_id=TENANT, connection_id=CONN)]
    wanted = {
        "missing": ids[:-1],
        "extra": [*ids, uuid4()],
        "repeated": [ids[0], *ids[:-1]],
    }[change]
    with pytest.raises(ReplyTemplateError) as caught:
        service.reorder(tenant_id=TENANT, connection_id=CONN, template_ids=wanted)
    assert caught.value.code == "order_stale"
    assert [t.id for t in service.list_for_connection(tenant_id=TENANT, connection_id=CONN)] == ids


# --- tenancy ---------------------------------------------------------------------------


def test_another_tenant_sees_nothing() -> None:
    repo = _repo()
    mine = _service(repo).list_for_connection(tenant_id=TENANT, connection_id=CONN)[0]
    theirs = _service(repo)
    with pytest.raises(ReplyTemplateNotFound) as caught:
        theirs.list_for_connection(tenant_id=OTHER, connection_id=CONN)
    assert caught.value.code == "connection_not_found"
    with pytest.raises(ReplyTemplateNotFound):
        theirs.update(tenant_id=OTHER, template_id=mine.id, title="x", body="y", user_id=None)
    assert theirs.delete(tenant_id=OTHER, template_id=mine.id) is False
    with pytest.raises(ReplyTemplateNotFound):
        theirs.create(tenant_id=OTHER, connection_id=CONN, title="x", body="y", user_id=None)
    assert repo.get_template(tenant_id=TENANT, template_id=mine.id) == mine


# --- rendering -------------------------------------------------------------------------


def test_render_substitutes_name_and_brand() -> None:
    thread = _thread()
    service = _service(None, thread)
    greeting = service.list_for_connection(tenant_id=TENANT, connection_id=CONN)[0]
    rendered = service.render(tenant_id=TENANT, template_id=greeting.id, thread_id=thread.id)
    assert rendered.text == (
        "¡Hola, Ana Pérez! Gracias por escribirnos a Polet Bubble Tea. ¿En qué te podemos ayudar?"
    )
    assert rendered.unresolved == () and rendered.blanks == ()
    assert rendered.template_id == greeting.id
    assert not rendered.needs_attention


def test_render_falls_back_to_the_username() -> None:
    thread = _thread(name=None, username="ana.perez")
    service = _service(None, thread)
    greeting = service.list_for_connection(tenant_id=TENANT, connection_id=CONN)[0]
    rendered = service.render(tenant_id=TENANT, template_id=greeting.id, thread_id=thread.id)
    assert rendered.text.startswith("¡Hola, ana.perez!")


def test_render_leaves_missing_values_visible() -> None:
    thread = _thread(name=None, username="  ")
    service = _service(None, thread, brand=None)
    greeting = service.list_for_connection(tenant_id=TENANT, connection_id=CONN)[0]
    rendered = service.render(tenant_id=TENANT, template_id=greeting.id, thread_id=thread.id)
    assert rendered.text == (
        "¡Hola, {nombre}! Gracias por escribirnos a {marca}. ¿En qué te podemos ayudar?"
    )
    assert rendered.unresolved == ("{nombre}", "{marca}")
    assert rendered.needs_attention


def test_render_lists_the_blanks_of_a_default() -> None:
    thread = _thread()
    service = _service(None, thread)
    price = service.list_for_connection(tenant_id=TENANT, connection_id=CONN)[1]
    rendered = service.render(tenant_id=TENANT, template_id=price.id, thread_id=thread.id)
    assert rendered.blanks == ("[precio]",)
    assert rendered.text == price.body


def test_render_template_is_tolerant_and_never_raises() -> None:
    rendered = render_template(
        "Hola { Nombre }, {NOMBRE} y {precio} de {marca} {} {{nombre}} {sin cerrar",
        {"nombre": "Ana", "marca": "Bianki"},
    )
    assert rendered.text == "Hola Ana, Ana y {precio} de Bianki {} {Ana} {sin cerrar"
    assert rendered.unresolved == ("{precio}",)


def test_render_refuses_a_template_of_another_account() -> None:
    thread = _thread(connection_id=CONN_2)
    service = _service(None, thread)
    greeting = service.list_for_connection(tenant_id=TENANT, connection_id=CONN)[0]
    with pytest.raises(ReplyTemplateError) as caught:
        service.render(tenant_id=TENANT, template_id=greeting.id, thread_id=thread.id)
    assert caught.value.code == "other_account"


def test_render_unknown_thread_or_template() -> None:
    thread = _thread()
    service = _service(None, thread)
    greeting = service.list_for_connection(tenant_id=TENANT, connection_id=CONN)[0]
    with pytest.raises(ReplyTemplateNotFound) as caught:
        service.render(tenant_id=TENANT, template_id=greeting.id, thread_id=uuid4())
    assert caught.value.code == "thread_not_found"
    with pytest.raises(ReplyTemplateNotFound) as caught:
        service.render(tenant_id=TENANT, template_id=uuid4(), thread_id=thread.id)
    assert caught.value.code == "template_not_found"
    # Another tenant's thread reads as missing too.
    with pytest.raises(ReplyTemplateNotFound):
        service.render(tenant_id=OTHER, template_id=greeting.id, thread_id=thread.id)


# --- B5: a template never queues anything ----------------------------------------------


def test_picking_and_rendering_never_enqueue() -> None:
    """The real reply path is wired beside the library over the SAME thread store; every
    template operation runs; the outbox stays empty. Only `reply_text` — a person's
    approved send, not exercised here — may fill it."""
    conversations = MemoryConversationRepository()
    outbox = MemoryConversationOutboxRepository(clock=lambda: T0)
    registry = ChannelRegistry()
    registry.register(source=MemoryConversationSource(), sender=MemoryConversationSender())
    ConversationService(
        repository=conversations, outbox=outbox, registry=registry, clock=lambda: T0
    )
    upsert = conversations.upsert_thread(
        tenant_id=TENANT, connection_id=CONN, channel=CHANNEL_DM, counterpart_external_id="igsid"
    )
    conversations.bump_thread_activity(
        tenant_id=TENANT,
        thread_id=upsert.thread_id,
        last_inbound_at=T0 - timedelta(minutes=5),
        last_message_at=T0 - timedelta(minutes=5),
    )
    service = ReplyTemplateService(
        repository=_repo(), threads=conversations, brand_name=lambda _t, _c: "Polet"
    )

    listed = service.list_for_connection(tenant_id=TENANT, connection_id=CONN)
    created = service.create(
        tenant_id=TENANT,
        connection_id=CONN,
        title="Gracias",
        body="¡Gracias, {nombre}!",
        user_id=USER,
    )
    service.update(
        tenant_id=TENANT,
        template_id=created.id,
        title="Gracias",
        body="¡Mil gracias!",
        user_id=USER,
    )
    service.reorder(
        tenant_id=TENANT,
        connection_id=CONN,
        template_ids=[created.id, *(t.id for t in listed)],
    )
    for template in service.list_for_connection(tenant_id=TENANT, connection_id=CONN):
        service.render(tenant_id=TENANT, template_id=template.id, thread_id=upsert.thread_id)
    service.delete(tenant_id=TENANT, template_id=created.id)

    assert outbox.rows == {}
    assert outbox.messages == []


def test_the_module_cannot_reach_the_outbox_or_a_channel() -> None:
    source = Path(inspect.getfile(templates_module)).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    forbidden = {
        "qualify_api.conversations.outbox",
        "qualify_api.conversations.sender",
        "qualify_api.conversations.service",
        "qualify_api.conversations.contracts",
        "qualify_api.conversations.instagram_source",
        "httpx",
    }
    assert imported.isdisjoint(forbidden), imported & forbidden
    params = set(inspect.signature(ReplyTemplateService.__init__).parameters)
    assert params == {"self", "repository", "threads", "brand_name"}
