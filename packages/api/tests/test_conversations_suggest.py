"""E4 — assisted replies, offline (QUA-226): the gate, the grounding verdict, the
generator over a fake Messages client, and the service's suggest/decide loop.

The property guarded above all: nothing in `suggest.py` can send. The service has no
outbox; a draft becomes a message only through `ConversationService.reply(...,
approval=HumanApproval(draft_id=...))`, which `test_conversations_service.py` guards.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from qualify_api.claude_tools import ClaudeToolError, ModelConfig
from qualify_api.conversations.contracts import RemoteConversation, RemoteMessage
from qualify_api.conversations.drafts import (
    DraftPending,
    DraftStatus,
    InvalidDraftTransition,
    MemoryDraftRepository,
    new_draft,
)
from qualify_api.conversations.memory_source import SHAPE_VERSION_MEMORY
from qualify_api.conversations.repository import MemoryConversationRepository
from qualify_api.conversations.suggest import (
    GATE_LAST_OUTBOUND,
    GATE_NO_MESSAGES,
    GATE_NO_TEXT,
    GATE_OK,
    GATE_WINDOW_CLOSED,
    TOOL_NAME,
    ClaudeDraftGenerator,
    ConversationDraftService,
    GroundedProduct,
    Grounding,
    Proposal,
    SuggestionRefused,
    ThreadNotFound,
    gate,
    grounding_from_products,
    needs_review,
    transcript,
)

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
TENANT = uuid4()
CONNECTION = uuid4()
USER = uuid4()
ALICE = RemoteConversation(counterpart_external_id="igsid-alice", counterpart_username="alice")


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _message(mid: str, direction: str, text: str | None, at: datetime, **kw: Any) -> RemoteMessage:
    return RemoteMessage(
        external_message_id=mid,
        direction=direction,  # type: ignore[arg-type]
        text=text,
        posted_at=at,
        shape_version=SHAPE_VERSION_MEMORY,
        **kw,
    )


def _thread_with(repo: MemoryConversationRepository, messages: list[RemoteMessage]) -> Any:
    up = repo.upsert_thread(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        channel="dm",
        counterpart_external_id=ALICE.counterpart_external_id,
        external_conversation_id=None,
    )
    newest_in = None
    newest = None
    for m in messages:
        repo.insert_message(
            tenant_id=TENANT, thread_id=up.thread_id, connection_id=CONNECTION, message=m
        )
        newest = m.posted_at
        if m.direction == "inbound":
            newest_in = m.posted_at
    repo.bump_thread_activity(
        tenant_id=TENANT, thread_id=up.thread_id, last_inbound_at=newest_in, last_message_at=newest
    )
    return up.thread_id


# --- the gate ---------------------------------------------------------------------------


def test_gate_wants_an_inbound_text_inside_the_window() -> None:
    repo = MemoryConversationRepository()
    tid = _thread_with(
        repo, [_message("m1", "inbound", "Hola, ¿tienen envíos?", T0 - timedelta(hours=2))]
    )
    thread = repo.get_thread(tenant_id=TENANT, thread_id=tid)
    msgs = repo.list_messages(tenant_id=TENANT, thread_id=tid)
    verdict = gate(thread, msgs, T0)
    assert verdict.allowed and verdict.reason == GATE_OK
    assert verdict.target is not None and verdict.target.external_message_id == "m1"


@pytest.mark.parametrize(
    ("messages", "now", "reason"),
    [
        ([], T0, GATE_NO_MESSAGES),
        (
            [
                _message("m1", "inbound", "Hola", T0 - timedelta(hours=1)),
                _message("m2", "outbound", "¡Hola!", T0 - timedelta(minutes=30)),
            ],
            T0,
            GATE_LAST_OUTBOUND,
        ),
        (
            [_message("m1", "inbound", None, T0 - timedelta(hours=1), media_type="image")],
            T0,
            GATE_NO_TEXT,
        ),
        ([_message("m1", "inbound", "Hola", T0 - timedelta(hours=30))], T0, GATE_WINDOW_CLOSED),
    ],
)
def test_gate_refuses_with_a_named_reason(
    messages: list[RemoteMessage], now: datetime, reason: str
) -> None:
    repo = MemoryConversationRepository()
    tid = _thread_with(repo, messages)
    thread = repo.get_thread(tenant_id=TENANT, thread_id=tid)
    verdict = gate(thread, repo.list_messages(tenant_id=TENANT, thread_id=tid), now)
    assert not verdict.allowed and verdict.reason == reason and verdict.target is None


# --- grounding and the review verdict ----------------------------------------------------


def test_grounding_from_products_keeps_only_named_products() -> None:
    g = grounding_from_products(
        "  Tienda Sol ",
        [
            {"name": "Gorra", "price_label": "$12", "category": "ropa", "description": "Azul"},
            {"name": "   ", "price_label": "$1"},
        ],
    )
    assert g.business_name == "Tienda Sol"
    assert g.products == (GroundedProduct("Gorra", "$12", "ropa", "Azul"),)
    assert g.has_prices
    assert g.as_record() == {
        "business_name": "Tienda Sol",
        "products": [
            {
                "product_id": None,
                "name": "Gorra",
                "price": "$12",
                "price_amount": None,
                "currency": "",
                "category": "ropa",
                "updated_at": None,
            }
        ],
    }
    assert "Gorra — $12 — ropa — Azul" in g.as_prompt()
    assert "ninguno validado" in Grounding().as_prompt()


def test_needs_review_follows_the_model_and_the_price_check() -> None:
    priced = Grounding("Sol", (GroundedProduct("Gorra", "$12"),))
    bare = Grounding("Sol")
    ok = Proposal("Claro, te confirmo.", used_only_given_facts=True)
    assert not needs_review(ok, bare)
    assert needs_review(Proposal("x", used_only_given_facts=False), priced)
    assert needs_review(Proposal("x", True, unsupported_claims=("envíos",)), priced)
    # A price in the reply with no price in the grounding is flagged even if the model
    # swears it used only the given facts.
    assert needs_review(Proposal("Cuesta $12", used_only_given_facts=True), bare)
    assert not needs_review(Proposal("Cuesta $12", used_only_given_facts=True), priced)


def test_transcript_names_both_sides_and_media_only_messages() -> None:
    repo = MemoryConversationRepository()
    tid = _thread_with(
        repo,
        [
            _message("m1", "inbound", "Hola", T0 - timedelta(hours=1)),
            _message("m2", "outbound", "¡Hola!", T0 - timedelta(minutes=40)),
            _message("m3", "inbound", None, T0 - timedelta(minutes=30), media_type="image"),
        ],
    )
    lines = transcript(repo.list_messages(tenant_id=TENANT, thread_id=tid), "alice", "Sol")
    assert lines.splitlines() == ["alice: Hola", "Sol: ¡Hola!", "alice: [image]"]


# --- the generator over a fake client ------------------------------------------------------


class FakeMessages:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[Any]) -> None:
        self.messages = FakeMessages(responses)


def _tool_response(
    reply: str, *, only_facts: bool = True, claims: list[str] | None = None, stop: str = "tool_use"
) -> Any:
    return SimpleNamespace(
        model="claude-haiku-5-5-20260901",
        stop_reason=stop,
        usage=SimpleNamespace(input_tokens=300, output_tokens=40, cache_read_input_tokens=0),
        content=[
            SimpleNamespace(type="text", text="pensando…"),
            SimpleNamespace(
                type="tool_use",
                name=TOOL_NAME,
                input={
                    "reply": reply,
                    "uses_only_given_facts": only_facts,
                    "unsupported_claims": claims or [],
                },
            ),
        ],
    )


def _generator(responses: list[Any]) -> tuple[ClaudeDraftGenerator, FakeClient]:
    client = FakeClient(responses)
    gen = ClaudeDraftGenerator(client_factory=lambda key: client, api_key="k")
    return gen, client


def test_generator_asks_with_strict_tool_and_reports_cost() -> None:
    gen, client = _generator([_tool_response("¡Hola Alice! Sí, hacemos envíos.")])
    repo = MemoryConversationRepository()
    tid = _thread_with(repo, [_message("m1", "inbound", "¿Hacen envíos?", T0)])
    proposal = gen.propose(
        grounding=Grounding("Sol", (GroundedProduct("Gorra", "$12"),)),
        messages=repo.list_messages(tenant_id=TENANT, thread_id=tid),
        counterpart="alice",
    )
    assert proposal.text == "¡Hola Alice! Sí, hacemos envíos."
    assert proposal.used_only_given_facts and proposal.unsupported_claims == ()
    assert proposal.model_id == "claude-haiku-5-5"
    assert proposal.model_revision == "claude-haiku-5-5-20260901"
    assert (proposal.input_tokens, proposal.output_tokens) == (300, 40)
    assert proposal.cost_usd == pytest.approx((300 * 0.10 + 40 * 0.50) / 1_000_000)

    call = client.messages.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["output_config"] == {"effort": "low"}
    assert call["tools"][0]["name"] == TOOL_NAME and call["tools"][0]["strict"] is True
    assert call["tool_choice"] == {"type": "auto"}  # Haiku 5.5 thinks → auto
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    user = call["messages"][0]["content"]
    assert "Gorra — $12" in user and "alice: ¿Hacen envíos?" in user
    assert gen.version == "qua226.1:claude-haiku-5-5"


def test_generator_without_the_tool_or_with_empty_reply_is_an_error() -> None:
    no_tool = SimpleNamespace(
        model="m",
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        content=[SimpleNamespace(type="text", text="hola")],
    )
    gen, _ = _generator([no_tool])
    with pytest.raises(ClaudeToolError, match=TOOL_NAME):
        gen.propose(grounding=Grounding(), messages=[], counterpart="a")
    gen, _ = _generator([_tool_response("   ")])
    with pytest.raises(ClaudeToolError, match="empty"):
        gen.propose(grounding=Grounding(), messages=[], counterpart="a")
    gen, _ = _generator([_tool_response("x", stop="refusal")])
    with pytest.raises(ClaudeToolError, match="refused"):
        gen.propose(grounding=Grounding(), messages=[], counterpart="a")


def test_generator_forces_the_tool_on_a_non_thinking_model() -> None:
    client = FakeClient([_tool_response("ok")])
    gen = ClaudeDraftGenerator(
        config=ModelConfig("claude-haiku-4-5"), client_factory=lambda k: client, api_key="k"
    )
    gen.propose(grounding=Grounding(), messages=[], counterpart="a")
    call = client.messages.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    assert "output_config" not in call


# --- the service ------------------------------------------------------------------------


class StubGenerator:
    version = "stub:1"

    def __init__(self, proposals: list[Proposal]) -> None:
        self.proposals = list(proposals)
        self.calls = 0
        self.last: tuple[Grounding, list[Any], str] | None = None

    def propose(self, *, grounding: Grounding, messages: Any, counterpart: str) -> Proposal:
        self.calls += 1
        self.last = (grounding, list(messages), counterpart)
        return self.proposals.pop(0)


def _service(
    repo: MemoryConversationRepository, gen: StubGenerator, clock: Clock
) -> ConversationDraftService:
    return ConversationDraftService(
        repository=repo,
        drafts=MemoryDraftRepository(clock=clock),
        generator=gen,
        grounding=lambda tenant, conn: Grounding("Sol", (GroundedProduct("Gorra", "$12"),)),
        clock=clock,
    )


def test_suggest_creates_one_proposed_draft_with_provenance() -> None:
    repo = MemoryConversationRepository()
    tid = _thread_with(repo, [_message("m1", "inbound", "¿Precio de la gorra?", T0)])
    gen = StubGenerator(
        [
            Proposal(
                "La gorra cuesta $12 🙂",
                used_only_given_facts=True,
                model_id="claude-haiku-5-5",
                model_revision="rev",
                input_tokens=10,
                output_tokens=5,
                cost_usd=0.0000035,
            )
        ]
    )
    svc = _service(repo, gen, Clock(T0 + timedelta(minutes=1)))
    draft = svc.suggest(tenant_id=TENANT, thread_id=tid)
    assert draft.status is DraftStatus.PROPOSED
    assert draft.generated_text == "La gorra cuesta $12 🙂"
    assert draft.gate_reason == GATE_OK and draft.needs_review is False
    assert draft.generator_version == "stub:1"
    assert (draft.model_id, draft.model_revision) == ("claude-haiku-5-5", "rev")
    assert (draft.input_tokens, draft.output_tokens) == (10, 5)
    assert draft.cost_usd == pytest.approx(0.0000035)
    assert draft.grounding["business_name"] == "Sol"
    assert [(p["name"], p["price"], p["category"]) for p in draft.grounding["products"]] == [
        ("Gorra", "$12", "")
    ]
    assert draft.grounding["unsupported_claims"] == []
    # No profile on the thread yet → the generic counterpart label.
    assert gen.last is not None and gen.last[2] == "Cliente"
    assert svc.pending_for(tenant_id=TENANT, thread_id=tid) == draft


def test_suggest_returns_the_pending_draft_instead_of_paying_twice() -> None:
    repo = MemoryConversationRepository()
    tid = _thread_with(repo, [_message("m1", "inbound", "Hola", T0)])
    gen = StubGenerator([Proposal("¡Hola!", True)])
    svc = _service(repo, gen, Clock(T0))
    first = svc.suggest(tenant_id=TENANT, thread_id=tid)
    second = svc.suggest(tenant_id=TENANT, thread_id=tid)
    assert first == second and gen.calls == 1


def test_suggest_again_after_discarding_generates_a_new_draft() -> None:
    repo = MemoryConversationRepository()
    tid = _thread_with(repo, [_message("m1", "inbound", "Hola", T0)])
    gen = StubGenerator([Proposal("v1", True), Proposal("v2", True)])
    svc = _service(repo, gen, Clock(T0))
    first = svc.suggest(tenant_id=TENANT, thread_id=tid)
    svc.decide(
        tenant_id=TENANT,
        draft_id=first.id,
        status=DraftStatus.DISCARDED,
        final_text=None,
        user_id=USER,
    )
    second = svc.suggest(tenant_id=TENANT, thread_id=tid)
    assert second.id != first.id and second.generated_text == "v2" and gen.calls == 2


def test_suggest_flags_review_when_the_model_could_not_ground() -> None:
    repo = MemoryConversationRepository()
    tid = _thread_with(repo, [_message("m1", "inbound", "¿Envían a Maracaibo?", T0)])
    gen = StubGenerator(
        [Proposal("Te confirmo el envío enseguida.", False, unsupported_claims=("envíos",))]
    )
    draft = _service(repo, gen, Clock(T0)).suggest(tenant_id=TENANT, thread_id=tid)
    assert draft.needs_review is True
    assert draft.grounding["unsupported_claims"] == ["envíos"]


def test_suggest_refuses_when_the_gate_says_no_and_calls_no_model() -> None:
    repo = MemoryConversationRepository()
    tid = _thread_with(
        repo,
        [
            _message("m1", "inbound", "Hola", T0 - timedelta(hours=1)),
            _message("m2", "outbound", "¡Hola!", T0),
        ],
    )
    gen = StubGenerator([])
    svc = _service(repo, gen, Clock(T0))
    with pytest.raises(SuggestionRefused) as exc:
        svc.suggest(tenant_id=TENANT, thread_id=tid)
    assert exc.value.reason == GATE_LAST_OUTBOUND and gen.calls == 0
    with pytest.raises(ThreadNotFound):
        svc.suggest(tenant_id=TENANT, thread_id=uuid4())


def test_decide_accept_edit_discard_and_only_once() -> None:
    repo = MemoryConversationRepository()
    tid = _thread_with(repo, [_message("m1", "inbound", "Hola", T0)])
    gen = StubGenerator([Proposal("¡Hola!", True)])
    svc = _service(repo, gen, Clock(T0))
    draft = svc.suggest(tenant_id=TENANT, thread_id=tid)
    edited = svc.decide(
        tenant_id=TENANT,
        draft_id=draft.id,
        status=DraftStatus.EDITED,
        final_text="¡Hola, Alice!",
        user_id=USER,
    )
    assert edited.status is DraftStatus.EDITED and edited.final_text == "¡Hola, Alice!"
    assert edited.decided_by_user_id == USER and edited.decided_at == T0
    with pytest.raises(InvalidDraftTransition):
        svc.decide(
            tenant_id=TENANT,
            draft_id=draft.id,
            status=DraftStatus.ACCEPTED,
            final_text=None,
            user_id=USER,
        )
    assert svc.pending_for(tenant_id=TENANT, thread_id=tid) is None


def test_memory_drafts_refuse_a_second_proposed_draft_per_message() -> None:
    drafts = MemoryDraftRepository()
    mid = uuid4()
    first = drafts.create(
        new_draft(
            tenant_id=TENANT,
            thread_id=uuid4(),
            message_id=mid,
            generator_version="v",
            generated_text="a",
            gate_reason=GATE_OK,
        )
    )
    with pytest.raises(DraftPending):
        drafts.create(
            new_draft(
                tenant_id=TENANT,
                thread_id=first.thread_id,
                message_id=mid,
                generator_version="v",
                generated_text="b",
                gate_reason=GATE_OK,
            )
        )
