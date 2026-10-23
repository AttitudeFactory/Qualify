"""Network- and Postgres-free tests for `conversations_provider` (QUA-226, E2).

The real `ConversationService` runs over the backend's own in-memory repositories
(`MemoryConversationRepository` / `MemoryConversationOutboxRepository`), the in-memory
channel and fake doors (store, R2 sink, media viewer, connection resolver), so these pin
the gateway's behaviour, not a re-implementation of it:

- account scoping: a thread of another account of the same tenant reads as missing;
- tenant isolation: another tenant's thread reads as missing, never as forbidden;
- opening marks read; a reply lands in the outbox with THIS user's approval, never
  inline; a closed window, an over-long text or a channel without sender refuse BEFORE
  anything is written;
- an attachment is staged in R2 under the tenant's prefix and queued as a media reply
  whose public URL is NOT minted yet; the screen gets `/r2media` paths for what Qualify
  sent and the CDN URL for what the counterpart sent;
- presence signals reach the channel sender and never the outbox;
- unsent outbox rows are visible with their reason;
- structural guarantee: Postgres only through `tenant_session`.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_api.conversations.contracts import (
    ACTION_MARK_SEEN,
    ACTION_TYPING_ON,
    CHANNEL_DM,
    ChannelRegistry,
    RemoteConversation,
    RemoteMessage,
    SourceConnection,
    UnknownChannel,
)
from qualify_api.conversations.drafts import DraftStatus, MemoryDraftRepository
from qualify_api.conversations.memory_source import (
    SHAPE_VERSION_MEMORY,
    MemoryConversationSender,
    MemoryConversationSource,
)
from qualify_api.conversations.outbox import MemoryConversationOutboxRepository
from qualify_api.conversations.repository import MemoryConversationRepository
from qualify_api.conversations.service import (
    AttentionState,
    ConversationService,
    ThreadNotFound,
    WindowClosed,
)
from qualify_api.conversations.suggest import (
    ConversationDraftService,
    Grounding,
    Proposal,
    SuggestionRefused,
)
from qualify_api.conversations.sync import ConversationSyncService
from qualify_api.conversations.templates import (
    MESSAGES,
    MemoryReplyTemplateRepository,
    ReplyTemplateError,
    ReplyTemplateNotFound,
    ReplyTemplateService,
)

from . import conversations_provider
from .conversations_provider import ConversationsGateway
from .conversations_vm import AccountVM, ThreadExtra

NOW = datetime(2026, 10, 16, 17, 0, tzinfo=UTC)
TENANT = uuid4()
OTHER_TENANT = uuid4()
USER = uuid4()
CONNECTION = uuid4()
OTHER_CONNECTION = uuid4()
SOURCE_CONNECTION = SourceConnection(
    tenant_id=TENANT, connection_id=CONNECTION, external_account_id="ig-1", linked_page_id="p1"
)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class FakeStore:
    def __init__(self) -> None:
        self.extras: dict[str, ThreadExtra] = {}
        self.users: dict[str, UUID] = {"ana@bianki.co": USER}

    def thread_extras(self, tenant_id: UUID, thread_ids) -> dict[str, ThreadExtra]:
        return {str(t): self.extras[str(t)] for t in thread_ids if str(t) in self.extras}

    def user_id_for_email(self, tenant_id: UUID, email: str) -> UUID | None:
        return self.users.get(email.lower())

    def timezone(self, tenant_id: UUID) -> str:
        return "America/Bogota"


class FakeSink:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[UUID, bytes, str]] = {}

    def put_media(self, tenant_id: UUID, object_key: str, fileobj, content_type: str) -> None:
        self.objects[object_key] = (tenant_id, fileobj.read(), content_type)


def _viewer(tenant_id: UUID, object_key: str, media_type: str, content_type) -> str:
    return f"/r2media/{media_type}/{object_key.rsplit('/', 1)[-1]}"


def _account(connection_id: UUID, **overrides) -> AccountVM:
    base = AccountVM(
        connection_id=str(connection_id),
        label="@qualifymkt.co",
        brand="Bianki",
        platform="instagram",
        channel_label="Instagram Direct",
        status="active",
        can_manage_dms=True,
        dm_reason="",
    )
    return AccountVM(**{**base.__dict__, **overrides})


class StubGenerator:
    version = "stub:1"

    def __init__(self) -> None:
        self.calls = 0

    def propose(self, *, grounding: Grounding, messages, counterpart: str) -> Proposal:
        self.calls += 1
        return Proposal("¡Hola! Sí, tenemos talla M.", used_only_given_facts=True)


class World:
    def __init__(self, *, with_sender: bool = True) -> None:
        self.clock = Clock(NOW)
        self.repo = MemoryConversationRepository()
        self.generator = StubGenerator()
        self.draft_rows = MemoryDraftRepository(clock=self.clock)
        self.outbox = MemoryConversationOutboxRepository(clock=self.clock)
        self.sender = MemoryConversationSender()
        registry = ChannelRegistry()
        if with_sender:
            registry.register(source=MemoryConversationSource(), sender=self.sender)
        else:
            registry.register(source=MemoryConversationSource())
        self.service = ConversationService(
            repository=self.repo, outbox=self.outbox, registry=registry, clock=self.clock
        )
        self.sync = ConversationSyncService(repository=self.repo, clock=self.clock)
        self.store = FakeStore()
        self.sink = FakeSink()
        self.drafts = ConversationDraftService(
            repository=self.repo,
            drafts=self.draft_rows,
            generator=self.generator,
            grounding=lambda tenant, connection: Grounding("Bianki"),
            clock=self.clock,
        )
        # m-24789472: the template library over the backend's own memory repository.
        self.template_rows = MemoryReplyTemplateRepository(
            connections={CONNECTION: TENANT, OTHER_CONNECTION: TENANT}, clock=self.clock
        )
        self.templates = ReplyTemplateService(
            repository=self.template_rows,
            threads=self.repo,
            brand_name=lambda tenant, connection: "Bianki",
        )
        self.gateway = ConversationsGateway(
            service=self.service,
            repository=self.repo,
            outbox=self.outbox,
            store=self.store,
            accounts=lambda tenant_id: [_account(CONNECTION)] if tenant_id == TENANT else [],
            sink=self.sink,
            viewer=_viewer,
            connections=lambda t, c: SOURCE_CONNECTION if c == CONNECTION else None,
            drafts=self.drafts,
            clock=self.clock,
            templates=self.templates,
        )

    def inbound(
        self,
        *,
        tenant_id: UUID = TENANT,
        connection_id: UUID = CONNECTION,
        counterpart: str = "igsid-alice",
        at: datetime = NOW - timedelta(hours=1),
        mid: str | None = None,
        media_type: str | None = None,
        media_url: str | None = None,
    ) -> UUID:
        connection = SourceConnection(
            tenant_id=tenant_id, connection_id=connection_id, external_account_id="ig-1"
        )
        result = self.sync.ingest_message(
            connection,
            channel=CHANNEL_DM,
            conversation=RemoteConversation(counterpart_external_id=counterpart),
            message=RemoteMessage(
                external_message_id=mid or f"mid.{uuid4().hex[:8]}",
                direction="inbound",
                text=None if media_type else "hola",
                posted_at=at,
                shape_version=SHAPE_VERSION_MEMORY,
                author_external_id=counterpart,
                author_username="alice",
                media_type=media_type,
                media_url=media_url,
            ),
        )
        return UUID(result.thread_id)


@pytest.fixture
def world() -> World:
    return World()


def test_accounts_and_access_come_from_the_injected_readers(world: World) -> None:
    assert [a.label for a in world.gateway.accounts(TENANT)] == ["@qualifymkt.co"]
    assert world.gateway.accounts(OTHER_TENANT) == []
    assert world.gateway.access(TENANT, CONNECTION) is None
    assert world.gateway.timezone(TENANT) == "America/Bogota"
    assert world.gateway.acting_user(TENANT, "ANA@bianki.co") == USER
    assert world.gateway.acting_user(TENANT, "nadie@bianki.co") is None


def test_threads_are_scoped_to_the_account_and_decorated(world: World) -> None:
    mine = world.inbound()
    world.inbound(connection_id=OTHER_CONNECTION, counterpart="igsid-bob")
    world.store.extras[str(mine)] = ThreadExtra(username="alice", preview="hola")

    listing = world.gateway.threads(TENANT, CONNECTION)

    assert [item.view.thread.id for item in listing] == [mine]
    assert listing[0].extra.username == "alice"
    assert listing[0].view.attention is AttentionState.PENDING
    assert listing[0].view.window.is_open


def test_a_thread_of_another_account_reads_as_missing(world: World) -> None:
    theirs = world.inbound(connection_id=OTHER_CONNECTION, counterpart="igsid-bob")
    with pytest.raises(ThreadNotFound):
        world.gateway.conversation(TENANT, CONNECTION, theirs)
    with pytest.raises(ThreadNotFound):
        world.gateway.mark_read(TENANT, CONNECTION, theirs)
    with pytest.raises(ThreadNotFound):
        world.gateway.reply(TENANT, CONNECTION, theirs, USER, "hola")
    assert world.outbox.rows == {}


def test_another_tenant_sees_nothing(world: World) -> None:
    mine = world.inbound()
    assert world.gateway.threads(OTHER_TENANT, CONNECTION) == []
    with pytest.raises(ThreadNotFound):
        world.gateway.conversation(OTHER_TENANT, CONNECTION, mine)
    with pytest.raises(ThreadNotFound):
        world.gateway.reply(OTHER_TENANT, CONNECTION, mine, USER, "hola")
    assert world.outbox.rows == {}


def test_opening_reads_the_newest_page_and_marking_read_flips_attention(world: World) -> None:
    thread = world.inbound()
    conversation = world.gateway.conversation(TENANT, CONNECTION, thread)
    assert [m.direction for m in conversation.messages] == ["inbound"]
    assert conversation.unsent == []
    assert conversation.view.attention is AttentionState.PENDING

    view = world.gateway.mark_read(TENANT, CONNECTION, thread)
    assert view.attention is AttentionState.READ
    assert view.thread.last_read_at == NOW


def test_a_reply_lands_in_the_outbox_with_this_users_approval(world: World) -> None:
    thread = world.inbound()
    (item_id,) = world.gateway.reply(TENANT, CONNECTION, thread, USER, "  claro, hay talla M ")

    row = world.outbox.rows[item_id]
    assert row.approved_by_user_id == USER
    assert row.approved_at == NOW
    assert row.status == "pending"
    assert row.payload == {
        "recipient": {"id": "igsid-alice"},
        "message": {"text": "claro, hay talla M"},
    }
    assert world.sender.sent == []  # nothing inline: the worker drains the queue
    unsent = world.gateway.conversation(TENANT, CONNECTION, thread).unsent
    assert [(u.status, u.text) for u in unsent] == [("pending", "claro, hay talla M")]


def test_a_closed_window_refuses_before_anything_is_written(world: World) -> None:
    thread = world.inbound(at=NOW - timedelta(hours=25))
    with pytest.raises(WindowClosed):
        world.gateway.reply(TENANT, CONNECTION, thread, USER, "tarde")
    assert world.outbox.rows == {}


def test_an_empty_reply_is_refused_and_a_long_one_becomes_parts(world: World) -> None:
    thread = world.inbound()
    with pytest.raises(ValueError):
        world.gateway.reply(TENANT, CONNECTION, thread, USER, "   ")
    assert world.outbox.rows == {}
    ids = world.gateway.reply(TENANT, CONNECTION, thread, USER, "palabra " * 200)
    assert len(ids) == 2
    texts = [world.outbox.rows[i].payload["message"]["text"] for i in ids]
    assert all(len(t) <= 1000 for t in texts)
    assert " ".join(texts) == ("palabra " * 200).strip()
    assert {world.outbox.rows[i].approved_by_user_id for i in ids} == {USER}


def test_a_heart_is_a_sticker_row_without_an_object(world: World) -> None:
    """The backend's sticker path (kept: it is the channel's own). The screen sends the
    ❤️ emoji as text instead — the API sticker arrives white in Instagram."""
    thread = world.inbound()
    item_id = world.gateway.reply_sticker(TENANT, CONNECTION, thread, USER)
    row = world.outbox.rows[item_id]
    assert row.payload == {
        "recipient": {"id": "igsid-alice"},
        "message": {"attachment": {"type": "like_heart"}},
    }
    assert row.media is not None and row.media.media_type == "sticker"
    assert not row.media.needs_link and row.approved_by_user_id == USER
    unsent = world.gateway.conversation(TENANT, CONNECTION, thread).unsent
    assert [(u.media_type, u.text, u.media_src) for u in unsent] == [("sticker", "", "")]


def test_a_channel_without_sender_is_refused_before_anything_is_written() -> None:
    world = World(with_sender=False)
    thread = world.inbound()
    with pytest.raises(UnknownChannel):
        world.gateway.reply(TENANT, CONNECTION, thread, USER, "hola")
    assert world.outbox.rows == {}


def test_failed_outbox_rows_stay_visible_with_their_reason(world: World) -> None:
    thread = world.inbound()
    (item_id,) = world.gateway.reply(TENANT, CONNECTION, thread, USER, "hola")
    world.outbox.claim(tenant_id=TENANT, worker_id="w", now=NOW)
    world.outbox.mark_failed(tenant_id=TENANT, item_id=item_id, error_code="window_closed")

    unsent = world.gateway.conversation(TENANT, CONNECTION, thread).unsent
    assert [(u.status, u.error_code) for u in unsent] == [("failed", "window_closed")]

    # A sent row is a message now, not an unsent one.
    (other,) = world.gateway.reply(TENANT, CONNECTION, thread, USER, "otra")
    world.outbox.claim(tenant_id=TENANT, worker_id="w", now=NOW)
    world.outbox.mark_sent(tenant_id=TENANT, item_id=other, external_message_id="m.1", now=NOW)
    unsent = world.gateway.conversation(TENANT, CONNECTION, thread).unsent
    assert [u.id for u in unsent] == [str(item_id)]


# --- media --------------------------------------------------------------------------------


def test_an_attachment_is_staged_under_the_tenant_prefix_and_queued_without_a_url(
    world: World,
) -> None:
    thread = world.inbound()
    staged = world.gateway.stage_attachment(
        TENANT,
        CONNECTION,
        name="foto.jpg",
        content_type="image/jpeg",
        media_type="image",
        data=b"\xff\xd8",
    )
    assert staged.object_key.startswith(f"t/{TENANT}/media/{CONNECTION}/dm-")
    assert world.sink.objects[staged.object_key] == (TENANT, b"\xff\xd8", "image/jpeg")
    assert staged.preview_src.startswith("/r2media/image/")
    assert staged.name == "foto.jpg"

    item_id = world.gateway.reply_media(TENANT, CONNECTION, thread, USER, staged)
    row = world.outbox.rows[item_id]
    assert row.approved_by_user_id == USER
    assert row.media is not None and row.media.object_key == staged.object_key
    assert row.payload == {
        "recipient": {"id": "igsid-alice"},
        "message": {"attachment": {"type": "image", "payload": {}}},
    }
    unsent = world.gateway.conversation(TENANT, CONNECTION, thread).unsent
    assert [(u.media_type, u.text) for u in unsent] == [("image", "")]
    assert unsent[0].media_src.startswith("/r2media/image/")


def test_an_outbound_echo_renders_from_the_channels_cdn_url(world: World) -> None:
    """A retry Meta accepted, or a reply sent from the Instagram app, reaches the inbox
    through the sync as an outbound echo with a CDN URL and no R2 object."""
    thread = world.inbound()
    world.sync.ingest_message(
        SOURCE_CONNECTION,
        channel=CHANNEL_DM,
        conversation=RemoteConversation(counterpart_external_id="igsid-alice"),
        message=RemoteMessage(
            external_message_id="mid.echo",
            direction="outbound",
            text=None,
            posted_at=NOW,
            shape_version=SHAPE_VERSION_MEMORY,
            media_type="image",
            media_url="https://cdn.example/echo.jpg",
        ),
    )
    conv = world.gateway.conversation(TENANT, CONNECTION, thread)
    echo = next(m for m in conv.messages if m.external_message_id == "mid.echo")
    assert conv.media_sources[str(echo.id)] == "https://cdn.example/echo.jpg"


def test_hide_message_is_local_scoped_and_never_touches_the_channel(world: World) -> None:
    thread = world.inbound()
    message = world.gateway.conversation(TENANT, CONNECTION, thread).messages[0]
    assert world.gateway.hide_message(TENANT, CONNECTION, thread, message.id) is True
    assert world.gateway.conversation(TENANT, CONNECTION, thread).messages == []
    assert world.gateway.hide_message(TENANT, CONNECTION, thread, message.id) is False
    assert world.sender.sent == [] and world.sender.actions == []
    with pytest.raises(ThreadNotFound):
        world.gateway.hide_message(TENANT, OTHER_CONNECTION, thread, message.id)


def test_media_sources_distinguish_the_counterparts_cdn_from_our_r2(world: World) -> None:
    thread = world.inbound(media_type="image", media_url="https://cdn.example/in.jpg")
    item_id = world.gateway.reply_media(
        TENANT,
        CONNECTION,
        thread,
        USER,
        world.gateway.stage_attachment(
            TENANT,
            CONNECTION,
            name="a.m4a",
            content_type="audio/mp4",
            media_type="audio",
            data=b"x",
        ),
    )
    world.outbox.claim(tenant_id=TENANT, worker_id="w", now=NOW)
    world.outbox.mark_sent(tenant_id=TENANT, item_id=item_id, external_message_id="m.9", now=NOW)
    # The memory outbox records the outbound message aside; the repository in this world
    # does not see it, so the inbound one is what the conversation returns.
    conv = world.gateway.conversation(TENANT, CONNECTION, thread)
    assert list(conv.media_sources.values()) == ["https://cdn.example/in.jpg"]


# --- assisted replies (E4) ----------------------------------------------------------------


def test_suggest_decide_and_send_carry_the_draft_into_the_approval(world: World) -> None:
    thread = world.inbound()
    draft = world.gateway.suggest(TENANT, CONNECTION, thread)
    assert draft.status is DraftStatus.PROPOSED and world.generator.calls == 1
    assert draft.generated_text == "¡Hola! Sí, tenemos talla M."
    # The pending draft travels with the conversation, so a re-opened thread shows it.
    assert world.gateway.conversation(TENANT, CONNECTION, thread).pending_draft == draft
    # Asking again does not pay again.
    assert world.gateway.suggest(TENANT, CONNECTION, thread) == draft
    assert world.generator.calls == 1

    edited = world.gateway.decide_draft(
        TENANT, draft.id, status=DraftStatus.EDITED, final_text="¡Hola! Sí, hay M.", user_id=USER
    )
    assert edited.status is DraftStatus.EDITED and edited.decided_by_user_id == USER
    (item_id,) = world.gateway.reply(
        TENANT, CONNECTION, thread, USER, "¡Hola! Sí, hay M.", draft_id=draft.id
    )
    assert world.outbox.rows[item_id].draft_id == draft.id
    assert world.sender.sent == []  # still nothing inline
    assert world.gateway.conversation(TENANT, CONNECTION, thread).pending_draft is None


def test_suggest_is_scoped_and_gated(world: World) -> None:
    theirs = world.inbound(connection_id=OTHER_CONNECTION, counterpart="igsid-bob")
    with pytest.raises(ThreadNotFound):
        world.gateway.suggest(TENANT, CONNECTION, theirs)
    mine = world.inbound()
    world.gateway.reply(TENANT, CONNECTION, mine, USER, "ya respondí")
    # The outbox row is not a message yet: the gate still sees an inbound last. Settle it.
    (item_id,) = [i for i in world.outbox.rows]
    world.outbox.claim(tenant_id=TENANT, worker_id="w", now=NOW)
    world.outbox.mark_sent(tenant_id=TENANT, item_id=item_id, external_message_id="m.1", now=NOW)
    world.repo.insert_message(
        tenant_id=TENANT,
        thread_id=mine,
        connection_id=CONNECTION,
        message=RemoteMessage(
            external_message_id="m.1",
            direction="outbound",
            text="ya respondí",
            posted_at=NOW,
            shape_version=SHAPE_VERSION_MEMORY,
        ),
    )
    with pytest.raises(SuggestionRefused) as refusal:
        world.gateway.suggest(TENANT, CONNECTION, mine)
    assert refusal.value.reason == "last_message_outbound"
    assert world.generator.calls == 0


# --- presence -----------------------------------------------------------------------------


async def test_signals_reach_the_channel_and_never_the_outbox(world: World) -> None:
    thread = world.inbound()
    assert await world.gateway.signal(TENANT, CONNECTION, thread, ACTION_MARK_SEEN) is True
    assert await world.gateway.signal(TENANT, CONNECTION, thread, ACTION_TYPING_ON) is True
    assert [(a.recipient_external_id, a.action) for a in world.sender.actions] == [
        ("igsid-alice", "mark_seen"),
        ("igsid-alice", "typing_on"),
    ]
    assert world.outbox.rows == {}
    # An unknown connection, a closed window or a channel failure all answer False.
    assert await world.gateway.signal(TENANT, OTHER_CONNECTION, thread, ACTION_MARK_SEEN) is False
    closed = world.inbound(counterpart="igsid-old", at=NOW - timedelta(days=2))
    assert await world.gateway.signal(TENANT, CONNECTION, closed, ACTION_TYPING_ON) is False
    world.sender.fail_with = RuntimeError("down")
    assert await world.gateway.signal(TENANT, CONNECTION, thread, ACTION_TYPING_ON) is False


def test_postgres_only_through_tenant_session() -> None:
    store = conversations_provider.PostgresConversationsStore
    for name in ("thread_extras", "user_id_for_email", "timezone"):
        assert "tenant_session(tenant_id)" in inspect.getsource(getattr(store, name)), name
    source = inspect.getsource(conversations_provider)
    assert "admin_session" not in source
    assert "create_engine" not in source


# --- message templates (m-24789472) ----------------------------------------------------


def _by_title(world: World, connection_id: UUID = CONNECTION) -> dict[str, UUID]:
    return {t.title: t.id for t in world.gateway.templates(TENANT, connection_id)}


def test_the_library_opens_with_the_four_defaults_in_spanish(world: World) -> None:
    titles = [t.title for t in world.gateway.templates(TENANT, CONNECTION)]
    assert titles == ["Saludo", "Precio", "Horario", "Catálogo"]
    # Seeded once: a second open adds nothing.
    assert len(world.gateway.templates(TENANT, CONNECTION)) == 4


def test_rendering_fills_the_brand_and_leaves_a_missing_name_visible(world: World) -> None:
    thread = world.inbound()
    ids = _by_title(world)

    greeting = world.gateway.render_template(TENANT, CONNECTION, thread, ids["Saludo"])
    assert "Bianki" in greeting.text
    assert "{nombre}" in greeting.text  # this counterpart has no name on the thread
    assert greeting.unresolved == ("{nombre}",)

    price = world.gateway.render_template(TENANT, CONNECTION, thread, ids["Precio"])
    assert price.blanks == ("[precio]",)
    assert price.unresolved == ()


def test_rendering_never_queues_and_never_reaches_the_channel(world: World) -> None:
    """B5: a template is a starting point for the box. Only `reply` writes the outbox."""
    thread = world.inbound()
    for template_id in _by_title(world).values():
        world.gateway.render_template(TENANT, CONNECTION, thread, template_id)
    world.gateway.create_template(TENANT, CONNECTION, USER, "Envíos", "Enviamos a todo el país.")
    assert world.outbox.rows == {}
    assert world.sender.sent == []


def test_rendering_is_scoped_to_the_account_on_screen(world: World) -> None:
    mine = world.inbound()
    theirs = world.inbound(connection_id=OTHER_CONNECTION, counterpart="igsid-bob")
    other_template = _by_title(world, OTHER_CONNECTION)["Saludo"]

    with pytest.raises(ThreadNotFound):
        world.gateway.render_template(TENANT, CONNECTION, theirs, _by_title(world)["Saludo"])
    with pytest.raises(ReplyTemplateError) as refused:
        world.gateway.render_template(TENANT, CONNECTION, mine, other_template)
    assert refused.value.code == "other_account"


def test_a_template_of_another_account_cannot_be_edited_or_deleted(world: World) -> None:
    other_template = _by_title(world, OTHER_CONNECTION)["Saludo"]
    with pytest.raises(ReplyTemplateNotFound):
        world.gateway.update_template(TENANT, CONNECTION, other_template, USER, "X", "Y")
    with pytest.raises(ReplyTemplateNotFound):
        world.gateway.delete_template(TENANT, CONNECTION, other_template)
    assert world.template_rows.rows[other_template].title == "Saludo"


def test_create_edit_delete_and_their_spanish_refusals(world: World) -> None:
    created = world.gateway.create_template(
        TENANT, CONNECTION, USER, "  Envíos  ", "Enviamos a todo el país."
    )
    assert created.title == "Envíos" and created.created_by_user_id == USER
    assert [t.title for t in world.gateway.templates(TENANT, CONNECTION)][-1] == "Envíos"

    with pytest.raises(ReplyTemplateError) as empty:
        world.gateway.create_template(TENANT, CONNECTION, USER, "  ", "Algo")
    assert str(empty.value) == MESSAGES["title_empty"]
    with pytest.raises(ReplyTemplateError) as long_body:
        world.gateway.update_template(TENANT, CONNECTION, created.id, USER, "Envíos", "x" * 1001)
    assert long_body.value.message == MESSAGES["body_too_long"]

    edited = world.gateway.update_template(
        TENANT, CONNECTION, created.id, USER, "Envíos", "Enviamos a todo Uruguay."
    )
    assert edited.body == "Enviamos a todo Uruguay."
    assert world.gateway.delete_template(TENANT, CONNECTION, created.id) is True
    assert "Envíos" not in _by_title(world)


def test_reorder_takes_the_whole_library_or_nothing(world: World) -> None:
    library = world.gateway.templates(TENANT, CONNECTION)
    ids = [t.id for t in library]
    moved = [ids[1], ids[0], *ids[2:]]
    assert [t.id for t in world.gateway.reorder_templates(TENANT, CONNECTION, moved)] == moved

    with pytest.raises(ReplyTemplateError) as stale:
        world.gateway.reorder_templates(TENANT, CONNECTION, moved[:-1])
    assert stale.value.code == "order_stale"
    assert [t.id for t in world.gateway.templates(TENANT, CONNECTION)] == moved


def test_the_template_service_is_wired_lazily_from_composition() -> None:
    source = inspect.getsource(ConversationsGateway.template_service.fget)
    assert "production_template_service" in source
