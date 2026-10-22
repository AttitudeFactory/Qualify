"""«Consultas desde comentarios» (m-24789646, PR 3), offline: opening from commercial
intents (B1: recent, commercial, not yet followed, with provenance and a draft), opening
by hand, the cards, and the person's decisions — approve as written or edited (the
draft→sent diff, B2), regenerate, discard — all through the outbox with a
`HumanApproval` (B3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.conversations.contracts import CHANNEL_DM, ChannelRegistry
from qualify_api.conversations.drafts import DraftStatus, MemoryDraftRepository
from qualify_api.conversations.memory_source import MemoryConversationSender
from qualify_api.conversations.outbox import MemoryConversationOutboxRepository
from qualify_api.conversations.repository import MemoryConversationRepository, MessageRecord
from qualify_api.conversations.suggest import GroundedProduct, Grounding, Proposal
from qualify_api.followups import (
    Capabilities,
    Capability,
    FollowupService,
    FollowupStatus,
    FollowupTrigger,
    MemoryFollowupRepository,
    MemoryOriginReader,
    OriginMessage,
    SendRoute,
)
from qualify_api.followups.origins import CommercialComment, MemoryCommercialIntentReader
from qualify_api.followups.workspace import (
    GATE_COMMERCIAL_COMMENT,
    GATE_MANUAL_FOLLOWUP,
    FollowupWorkspace,
)
from qualify_api.intent import CURRENT_INTENT_VERSION, IntentClass, IntentSignal

T0 = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
TENANT = uuid4()
USER = uuid4()
CONNECTION_ID = uuid4()
PRIVATE_REPLY_ON = Capabilities(frozenset({Capability.COMMENT_PRIVATE_REPLY}))


@dataclass
class FakeGenerator:
    text: str = "¡Hola! La chaqueta cuesta 120.000 y la tenemos en M."
    fail: Exception | None = None
    calls: list[dict[str, object]] = field(default_factory=list)

    @property
    def version(self) -> str:
        return "fake.1"

    def propose(
        self,
        *,
        grounding: Grounding,
        messages: Sequence[MessageRecord],
        counterpart: str,
        context: str | None = None,
    ) -> Proposal:
        self.calls.append(
            {"messages": list(messages), "counterpart": counterpart, "context": context}
        )
        if self.fail is not None:
            raise self.fail
        return Proposal(text=self.text, used_only_given_facts=True)


class World:
    def __init__(self, capabilities: Capabilities = PRIVATE_REPLY_ON) -> None:
        self.now = T0 + timedelta(hours=1)
        self.conversations = MemoryConversationRepository()
        self.outbox = MemoryConversationOutboxRepository(clock=lambda: self.now)
        self.registry = ChannelRegistry()
        self.registry.register(sender=MemoryConversationSender())
        self.origins = MemoryOriginReader()
        self.followups = MemoryFollowupRepository()
        self.commercial = MemoryCommercialIntentReader(self.origins, self.followups)
        self.drafts = MemoryDraftRepository(clock=lambda: self.now)
        self.generator = FakeGenerator()
        self.signals: dict[UUID, IntentSignal] = {}
        service = FollowupService(
            followups=self.followups,
            origins=self.origins,
            conversations=self.conversations,
            outbox=self.outbox,
            registry=self.registry,
            capabilities=capabilities,
            clock=lambda: self.now,
        )
        self.workspace = FollowupWorkspace(
            service=service,
            followups=self.followups,
            origins=self.origins,
            commercial=self.commercial,
            drafts=self.drafts,
            generator=self.generator,
            grounding=lambda _t, _c: Grounding(
                business_name="Tienda Ana",
                products=(GroundedProduct("Chaqueta", "120.000 COP"),),
            ),
            signals=self._signals,
            reliability=lambda: {IntentClass.PRICE: True},
            intent_version=CURRENT_INTENT_VERSION,
            clock=lambda: self.now,
        )
        self.media_thread = self.conversations.upsert_thread(
            tenant_id=TENANT,
            connection_id=CONNECTION_ID,
            channel="comment",
            counterpart_external_id="media-1",
        ).thread_id

    def _signals(self, _tenant: UUID, ids: Sequence[UUID]) -> Mapping[UUID, IntentSignal]:
        return {i: self.signals[i] for i in ids if i in self.signals}

    def comment(
        self, *, posted_at: datetime = T0, author: str = "igsid-ana", flagged: bool = True
    ) -> OriginMessage:
        origin = self.origins.add(
            OriginMessage(
                id=uuid4(),
                tenant_id=TENANT,
                connection_id=CONNECTION_ID,
                thread_id=self.media_thread,
                channel="comment",
                external_message_id=f"c-{uuid4().hex[:8]}",
                direction="inbound",
                author_external_id=author,
                author_username="ana",
                text="¿Cuánto cuesta la chaqueta? ¿Hay en M?",
                posted_at=posted_at,
                media_id="media-1",
                media_caption="Llegó la colección de otoño",
                media_permalink="https://instagram.com/p/x",
                media_product_type="REELS",
            )
        )
        self.signals[origin.id] = IntentSignal(
            comment_id=origin.id,
            source_id=origin.external_message_id,
            classes={IntentClass.PRICE: 0.9, IntentClass.VARIANTS: 0.7},
            detector_version=CURRENT_INTENT_VERSION.detector_version,
            pipeline_version=CURRENT_INTENT_VERSION.pipeline_version,
            model_id=CURRENT_INTENT_VERSION.model_id,
            model_revision=CURRENT_INTENT_VERSION.model_revision,
        )
        if flagged:
            self.commercial.flagged.append(CommercialComment(origin.id, uuid4()))
        return origin

    def open_all(self) -> int:
        return self.workspace.open_from_intents(
            tenant_id=TENANT, connection_id=CONNECTION_ID
        ).opened


# --- opening from intents (B1) ------------------------------------------------------------


def test_recent_commercial_comments_are_opened_with_provenance_and_a_draft() -> None:
    world = World()
    origin = world.comment()
    summary = world.workspace.open_from_intents(tenant_id=TENANT, connection_id=CONNECTION_ID)
    assert (summary.opened, summary.drafted, summary.draft_failed) == (1, 1, 0)
    [followup] = world.followups.rows.values()
    assert followup.trigger is FollowupTrigger.INTENT
    assert followup.intent_result_id == world.commercial.flagged[0].intent_result_id
    assert followup.dm_thread_id is None  # nothing created in Conversaciones yet
    [draft] = world.drafts.rows.values()
    assert (draft.thread_id, draft.message_id) == (origin.thread_id, origin.id)
    assert draft.gate_reason == GATE_COMMERCIAL_COMMENT
    assert draft.grounding["followup_id"] == str(followup.id)
    [call] = world.generator.calls
    assert call["counterpart"] == "ana"
    context = str(call["context"])
    assert "PÚBLICO" in context and "MENSAJE PRIVADO" in context
    assert "Llegó la colección de otoño" in context
    assert "Precio" in context


def test_opening_is_idempotent_and_skips_old_or_unflagged_comments() -> None:
    world = World()
    world.comment()
    world.comment(posted_at=world.now - timedelta(days=8))  # past the private-reply limit
    world.comment(flagged=False)
    assert world.open_all() == 1
    assert world.open_all() == 0
    assert len(world.followups.rows) == 1
    assert len(world.generator.calls) == 1


def test_a_failed_draft_never_blocks_opening() -> None:
    world = World()
    world.generator.fail = RuntimeError("model down")
    world.comment()
    summary = world.workspace.open_from_intents(tenant_id=TENANT, connection_id=CONNECTION_ID)
    assert (summary.opened, summary.drafted, summary.draft_failed) == (1, 0, 1)
    [card] = world.workspace.list_open(tenant_id=TENANT)
    assert card.draft is None


# --- opening by hand ------------------------------------------------------------------------


def test_reply_by_dm_opens_once_with_one_draft() -> None:
    world = World()
    origin = world.comment(flagged=False)
    first = world.workspace.open_manual(tenant_id=TENANT, origin_message_id=origin.id)
    again = world.workspace.open_manual(tenant_id=TENANT, origin_message_id=origin.id)
    assert first.created is True and again.created is False
    assert first.followup.trigger is FollowupTrigger.MANUAL
    assert [d.gate_reason for d in world.drafts.rows.values()] == [GATE_MANUAL_FOLLOWUP]


# --- cards ----------------------------------------------------------------------------------


def test_cards_carry_context_intents_route_and_draft() -> None:
    world = World()
    origin = world.comment()
    world.open_all()
    [card] = world.workspace.list_open(tenant_id=TENANT)
    assert card.origin.id == origin.id
    assert [c.label for c in card.intents] == ["Precio", "Variantes"]
    assert [c.reliable for c in card.intents] == [True, False]
    assert card.options.chosen is card.options.private_reply
    assert card.options.private_reply.closes_at == T0 + timedelta(days=7)
    assert card.draft is not None and card.draft.generated_text == world.generator.text


def test_a_card_uses_the_dm_when_the_author_wrote_in_the_last_24h() -> None:
    world = World()
    origin = world.comment()
    world.origins.add(replace(origin, dm_last_inbound_at=world.now - timedelta(hours=2)))
    world.open_all()
    [card] = world.workspace.list_open(tenant_id=TENANT)
    assert card.options.chosen is card.options.dm


# --- decisions ------------------------------------------------------------------------------


def _open_one(world: World) -> tuple[UUID, UUID]:
    world.comment()
    world.open_all()
    [card] = world.workspace.list_open(tenant_id=TENANT)
    assert card.draft is not None
    return card.followup.id, card.draft.id


def test_approving_the_draft_as_written_accepts_it_and_links_the_send() -> None:
    world = World()
    followup_id, draft_id = _open_one(world)
    approved = world.workspace.approve(
        tenant_id=TENANT,
        followup_id=followup_id,
        text=world.generator.text,
        user_id=USER,
        draft_id=draft_id,
    )
    assert approved.status is FollowupStatus.APPROVED
    assert approved.send_route is SendRoute.PRIVATE_REPLY
    [row] = world.outbox.rows.values()
    assert (row.draft_id, row.approved_by_user_id) == (draft_id, USER)
    draft = world.drafts.rows[draft_id]
    assert draft.status is DraftStatus.ACCEPTED
    assert draft.final_text == world.generator.text
    assert world.workspace.list_open(tenant_id=TENANT) == []


def test_approving_an_edited_draft_keeps_the_diff() -> None:
    world = World()
    followup_id, draft_id = _open_one(world)
    sent = "¡Hola Ana! La chaqueta cuesta 120.000 COP. ¿Te la aparto en M?"
    world.workspace.approve(
        tenant_id=TENANT, followup_id=followup_id, text=sent, user_id=USER, draft_id=draft_id
    )
    draft = world.drafts.rows[draft_id]
    assert draft.status is DraftStatus.EDITED
    assert (draft.generated_text, draft.final_text) == (world.generator.text, sent)
    [row] = world.outbox.rows.values()
    assert row.payload["message"]["text"] == sent


def test_a_stale_draft_id_sends_unlinked_and_leaves_the_pending_draft_alone() -> None:
    world = World()
    followup_id, draft_id = _open_one(world)
    world.workspace.approve(
        tenant_id=TENANT, followup_id=followup_id, text="Hola", user_id=USER, draft_id=uuid4()
    )
    [row] = world.outbox.rows.values()
    assert row.draft_id is None
    assert world.drafts.rows[draft_id].status is DraftStatus.PROPOSED


def test_regenerating_discards_the_old_draft_and_writes_a_new_one() -> None:
    world = World()
    followup_id, draft_id = _open_one(world)
    world.generator.text = "Otra versión"
    new = world.workspace.regenerate(tenant_id=TENANT, followup_id=followup_id, user_id=USER)
    assert world.drafts.rows[draft_id].status is DraftStatus.DISCARDED
    assert new.id != draft_id and new.generated_text == "Otra versión"
    assert world.workspace.suggest(tenant_id=TENANT, followup_id=followup_id).id == new.id


def test_discarding_the_query_discards_its_draft_and_sends_nothing() -> None:
    world = World()
    followup_id, draft_id = _open_one(world)
    discarded = world.workspace.discard(tenant_id=TENANT, followup_id=followup_id, user_id=USER)
    assert discarded.status is FollowupStatus.DISCARDED
    assert world.drafts.rows[draft_id].status is DraftStatus.DISCARDED
    assert world.outbox.rows == {}
    assert world.workspace.list_open(tenant_id=TENANT) == []


def test_another_tenant_sees_no_cards() -> None:
    world = World()
    _open_one(world)
    assert world.workspace.list_open(tenant_id=uuid4()) == []


@pytest.mark.parametrize("channel", [CHANNEL_DM])
def test_a_dm_origin_is_not_opened_while_story_reply_context_is_off(channel: str) -> None:
    world = World()
    origin = world.comment(flagged=False)
    world.origins.add(replace(origin, channel=channel))
    from qualify_api.followups import OriginNotSupported

    with pytest.raises(OriginNotSupported):
        world.workspace.open_manual(tenant_id=TENANT, origin_message_id=origin.id)
