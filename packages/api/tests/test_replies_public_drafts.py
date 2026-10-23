"""Fase B (m-24789645, PR 2): grounded PUBLIC drafts for commercial comments — offline,
over the Memory repository, a fake grounded generator and, for the prompt itself, the
real `ClaudeDraftGenerator` over a fake Anthropic client. No network, no database.

What is pinned: the gate runs before any model call; the model never receives a price
(D1) and a price token in its text forces review; availability/store/location/hours force
review (D2); an empty catalog, an unpriced price question and an ungrounded claim force
review, while an unreliable class is only a recorded note; grounding + provenance are
stored with product ids; `regenerate` replaces the live draft atomically; nothing here
ever posts a reply."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.assisted.grounding import GroundedProduct, Grounding, has_price_token
from qualify_api.conversations.suggest import TOOL_NAME, ClaudeDraftGenerator, Proposal
from qualify_api.intent.contract import IntentClass
from qualify_api.replies.composition import public_reply_generator
from qualify_api.replies.public_drafts import (
    COMMENT_SPEAKER,
    PUBLIC_GENERATOR_VERSION,
    PUBLIC_GENERATOR_VERSION_PREFIX,
    PUBLIC_SYSTEM_PROMPT,
    is_blocking_reason,
    needs_review_for,
    public_context,
)
from qualify_api.replies.repository import CandidateComment, MemoryReplyRepository
from qualify_api.replies.service import RegenerationRefused, ReplyService
from qualify_api.sentiment.repository import AnalysisVersion

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")
USER = UUID("33333333-3333-4333-8333-333333333333")
SENTIMENT = AnalysisVersion("det-1", "pipe-1", "model-1", None)
INTENT = AnalysisVersion("intent-claude-v2", "intent-pipeline-v1", "claude-haiku-5-5", None)
STALE_INTENT = AnalysisVersion("intent-claude-v1", "intent-pipeline-v1", "claude-haiku-5-5", None)
ALL_RELIABLE: Mapping[IntentClass, bool] = {c: True for c in IntentClass}

TARO_ID = uuid4()
CATALOG = Grounding(
    "Polette",
    (
        GroundedProduct(
            "Yogurt de taro",
            "$4.5",
            "bebidas",
            "Vaso grande, $4.50 en promoción",
            product_id=TARO_ID,
            price_amount=Decimal("4.50"),
            currency="USD",
            updated_at=datetime(2026, 10, 1, tzinfo=UTC),
        ),
    ),
)
UNPRICED = Grounding("Polette", (GroundedProduct("Yogurt de taro", product_id=TARO_ID),))


class FakeGroundedGenerator:
    version = f"{PUBLIC_GENERATOR_VERSION_PREFIX}:fake"

    def __init__(self, proposals: Sequence[Proposal] = ()) -> None:
        self._proposals = list(proposals)
        self.calls: list[dict[str, Any]] = []

    def propose(
        self,
        *,
        grounding: Grounding,
        messages: Sequence[Any],
        counterpart: str,
        context: str | None = None,
    ) -> Proposal:
        self.calls.append(
            {
                "grounding": grounding,
                "messages": list(messages),
                "counterpart": counterpart,
                "context": context,
            }
        )
        if self._proposals:
            return self._proposals.pop(0)
        return _proposal("¡Hola! Te escribimos por DM con los detalles.")


class FakeProvider:
    model_id = "fake"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def draft_reply(self, *, comment_text: str, business_name: str | None = None) -> str:
        self.calls.append(comment_text)
        return "¡Gracias por tu comentario!"


class RecordingClientFactory:
    """Any `post_reply` here would be a generation path that sends — there must be none."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, str]] = []

    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> Any:
        factory = self

        class _Client:
            async def post_reply(self, *, ig_comment_id: str, message: str) -> str:
                factory.posts.append((ig_comment_id, message))
                return "never"

        return _Client()


def _proposal(
    text: str, *, only_facts: bool = True, claims: tuple[str, ...] = (), cost: float = 0.00031
) -> Proposal:
    return Proposal(
        text=text,
        used_only_given_facts=only_facts,
        unsupported_claims=claims,
        model_id="claude-haiku-5-5",
        model_revision="claude-haiku-5-5-20260901",
        input_tokens=120,
        output_tokens=40,
        cost_usd=cost,
    )


def _candidate(
    classes: Sequence[str] = ("price",),
    *,
    text: str = "¿Cuánto cuesta el de taro?",
    sentiment: str = "NEU",
    commercial: bool = True,
    version: AnalysisVersion | None = INTENT,
    followup_status: str | None = None,
) -> CandidateComment:
    return CandidateComment(
        message_id=uuid4(),
        source_id=f"ig-comment-{uuid4().hex[:6]}",
        text=text,
        sentiment_result_id=uuid4() if sentiment else None,
        sentiment_label=sentiment,
        intent_result_id=uuid4() if version is not None else None,
        intent_classes=tuple(classes),
        commercial_intent=commercial,
        intent_version=version,
        followup_status=followup_status,
    )


def _service(
    repo: MemoryReplyRepository,
    generator: FakeGroundedGenerator,
    *,
    grounding: Grounding = CATALOG,
    reliable: Mapping[IntentClass, bool] = ALL_RELIABLE,
    provider: FakeProvider | None = None,
    clients: RecordingClientFactory | None = None,
) -> ReplyService:
    return ReplyService(
        repository=repo,
        version=SENTIMENT,
        generator_version="qua22.2:test",
        provider=provider or FakeProvider(),
        client_factory=clients,
        intent_version=INTENT,
        grounded_generator=generator,
        grounding=lambda tenant_id, connection_id: grounding,
        reliability=lambda detector: reliable,
    )


def _draft_one(
    candidate: CandidateComment,
    generator: FakeGroundedGenerator,
    **kwargs: Any,
) -> Any:
    repo = MemoryReplyRepository()
    repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
    summary = _service(repo, generator, **kwargs).generate_drafts(
        tenant_id=TENANT, connection_id=CONNECTION
    )
    assert summary.drafts_created == 1
    (draft,) = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    return draft


# --- criterion 2: grounding and review -------------------------------------------------


def test_empty_catalog_needs_review_and_the_model_is_told_there_are_no_products() -> None:
    gen = FakeGroundedGenerator()
    draft = _draft_one(_candidate(("product",)), gen, grounding=Grounding("Polette"))

    assert draft.needs_review is True
    assert "empty_catalog" in draft.grounding["review_reasons"]
    given = gen.calls[0]["grounding"]
    assert given.products == ()
    assert "ninguno validado" in given.as_prompt()
    assert draft.grounding["products"] == []


def test_a_product_the_catalog_does_not_have_needs_review() -> None:
    gen = FakeGroundedGenerator(
        [_proposal("¡Hola! Te escribimos por DM.", only_facts=False, claims=("yogurt de mango",))]
    )
    draft = _draft_one(_candidate(("product",), text="¿Tienen de mango?"), gen)

    assert draft.needs_review is True
    assert "model_unsupported" in draft.grounding["review_reasons"]
    assert draft.unsupported_claims == ("yogurt de mango",)


def test_an_unpriced_product_asked_for_its_price_gets_no_amount_and_needs_review() -> None:
    gen = FakeGroundedGenerator([_proposal("¡Hola! Te escribimos por DM con el precio.")])
    draft = _draft_one(_candidate(("price",)), gen, grounding=UNPRICED)

    assert not has_price_token(draft.generated_text)
    assert draft.needs_review is True
    assert draft.grounding["review_reasons"] == ["price_unknown"]
    assert "no lo digas" in gen.calls[0]["context"]


def test_a_priced_catalog_never_reaches_the_model_and_a_price_in_the_text_forces_review() -> None:
    gen = FakeGroundedGenerator([_proposal("¡Hola! Cuesta $4.5, te esperamos.")])
    draft = _draft_one(_candidate(("price",)), gen)

    given: Grounding = gen.calls[0]["grounding"]
    assert given.prices_withheld is True and given.has_prices is False
    assert all(p.price_amount is None and not p.currency for p in given.products)
    prompt = given.as_prompt()
    assert "$" not in prompt and "4.5" not in prompt and "precio" not in prompt.lower()
    assert given.products[0].description == "Vaso grande, en promoción"  # amount scrubbed

    assert draft.needs_review is True
    assert draft.grounding["review_reasons"] == ["price_token"]


def test_a_price_question_on_a_priced_catalog_with_a_clean_reply_needs_no_review() -> None:
    gen = FakeGroundedGenerator([_proposal("¡Hola! Te escribimos por DM con el precio.")])
    draft = _draft_one(_candidate(("price",)), gen)
    assert draft.needs_review is False
    assert draft.grounding["review_reasons"] == []


@pytest.mark.parametrize("intent_class", ["availability", "store", "location", "hours"])
def test_unvalidated_classes_always_need_review(intent_class: str) -> None:
    gen = FakeGroundedGenerator()
    draft = _draft_one(_candidate((intent_class,), text="¿Dónde están y a qué hora abren?"), gen)

    assert draft.needs_review is True
    assert f"unvalidated:{intent_class}" in draft.grounding["review_reasons"]
    assert "no es un dato validado" in gen.calls[0]["context"]


def test_an_unreliable_class_alone_is_a_note_not_a_review() -> None:
    """Founder decision (2026-10-23): `unreliable:<class>` is recorded for the screen to
    show, but on its own it does not make the draft «Requiere revisión»."""
    reliable = {**ALL_RELIABLE, IntentClass.PRODUCT: False}
    gen = FakeGroundedGenerator()
    draft = _draft_one(_candidate(("product",)), gen, reliable=reliable)
    assert draft.needs_review is False
    assert draft.grounding["review_reasons"] == ["unreliable:product"]


def test_an_unreliable_class_next_to_a_blocking_reason_still_needs_review() -> None:
    reliable = {**ALL_RELIABLE, IntentClass.HOURS: False}
    draft = _draft_one(_candidate(("hours",)), FakeGroundedGenerator(), reliable=reliable)
    assert draft.needs_review is True
    assert draft.grounding["review_reasons"] == ["unvalidated:hours", "unreliable:hours"]


@pytest.mark.parametrize(
    ("code", "blocking"),
    [
        ("model_unsupported", True),
        ("price_token", True),
        ("empty_catalog", True),
        ("price_unknown", True),
        ("unvalidated:hours", True),
        ("unreliable:product", False),
        ("unreliable:", False),
        ("something_new", True),  # unknown codes fail closed
        ("", True),
    ],
)
def test_is_blocking_reason(code: str, blocking: bool) -> None:
    assert is_blocking_reason(code) is blocking


def test_needs_review_for() -> None:
    assert needs_review_for([]) is False
    assert needs_review_for(["unreliable:product", "unreliable:models"]) is False
    assert needs_review_for(["unreliable:product", "price_token"]) is True


def test_grounding_and_provenance_are_stored_with_product_ids() -> None:
    gen = FakeGroundedGenerator([_proposal("¡Hola! Te escribimos por DM.", cost=0.000310)])
    candidate = _candidate(("price", "variants"))
    draft = _draft_one(candidate, gen)

    assert draft.generator_version == gen.version
    assert draft.intent_result_id == candidate.intent_result_id
    assert draft.sentiment_result_id == candidate.sentiment_result_id
    assert (draft.model_id, draft.model_revision) == (
        "claude-haiku-5-5",
        "claude-haiku-5-5-20260901",
    )
    assert (draft.input_tokens, draft.output_tokens) == (120, 40)
    assert draft.cost_usd == Decimal("0.00031")
    record = draft.grounding
    assert record["prices_withheld"] is True
    (product,) = record["products"]
    assert product["product_id"] == str(TARO_ID)
    assert product["price"] == "" and product["price_amount"] is None
    assert product["updated_at"] == "2026-10-01T00:00:00+00:00"
    assert "commercial intent" in draft.gate_reason


def test_the_comment_reaches_the_model_without_personal_data() -> None:
    gen = FakeGroundedGenerator()
    _draft_one(_candidate(("price", "hours")), gen)
    call = gen.calls[0]
    assert call["counterpart"] == COMMENT_SPEAKER
    (message,) = call["messages"]
    assert (message.author_username, message.author_external_id) == (None, None)
    assert "Precio" in call["context"] and "horario" in call["context"]


# --- the gate runs before the model ------------------------------------------------------


def test_a_failing_comment_never_reaches_any_generator() -> None:
    repo = MemoryReplyRepository()
    failing = (
        _candidate(followup_status="approved"),  # answered by DM
        _candidate(version=STALE_INTENT),  # stale intent, NEU
        _candidate(("general",), commercial=False),  # general, NEU
        _candidate(text="   "),  # empty
    )
    repo.seed_candidates(connection_id=CONNECTION, candidates=failing)
    gen, provider = FakeGroundedGenerator(), FakeProvider()

    summary = _service(repo, gen, provider=provider).generate_drafts(
        tenant_id=TENANT, connection_id=CONNECTION
    )

    assert (summary.candidates_seen, summary.drafts_created, summary.gate_rejected) == (4, 0, 4)
    assert gen.calls == [] and provider.calls == []


def test_a_pos_comment_without_commercial_intent_keeps_the_original_provider() -> None:
    repo = MemoryReplyRepository()
    pos = _candidate(("general",), sentiment="POS", commercial=False, text="¡Qué rico!")
    repo.seed_candidates(connection_id=CONNECTION, candidates=(pos,))
    gen, provider = FakeGroundedGenerator(), FakeProvider()

    _service(repo, gen, provider=provider).generate_drafts(
        tenant_id=TENANT, connection_id=CONNECTION
    )

    assert provider.calls == ["¡Qué rico!"] and gen.calls == []
    (draft,) = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    assert draft.generator_version == "qua22.2:test"
    assert (draft.grounding, draft.needs_review) == (None, False)
    assert draft.intent_result_id == pos.intent_result_id  # the signal it was judged on


def test_the_commercial_route_without_a_grounded_generator_fails_loudly() -> None:
    repo = MemoryReplyRepository()
    repo.seed_candidates(connection_id=CONNECTION, candidates=(_candidate(),))
    service = ReplyService(
        repository=repo, version=SENTIMENT, generator_version="v", intent_version=INTENT
    )
    with pytest.raises(RuntimeError, match="grounded generator"):
        service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    assert repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION) == ()


def test_generation_never_posts_a_reply() -> None:
    repo = MemoryReplyRepository()
    repo.seed_candidates(
        connection_id=CONNECTION,
        candidates=(_candidate(), _candidate(("general",), sentiment="POS", commercial=False)),
    )
    clients = RecordingClientFactory()
    service = _service(repo, FakeGroundedGenerator(), clients=clients)
    service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    draft = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)[0]
    service.regenerate(tenant_id=TENANT, draft_id=draft.id, user_id=USER)
    assert clients.posts == []
    assert all(
        d.status == "proposed"
        for d in repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    )


# --- regenerate ----------------------------------------------------------------------------


def test_regenerate_discards_the_old_draft_and_proposes_a_new_live_one() -> None:
    repo = MemoryReplyRepository()
    candidate = _candidate()
    repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
    gen = FakeGroundedGenerator([_proposal("primera"), _proposal("segunda")])
    service = _service(repo, gen)
    service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    (old,) = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)

    new = service.regenerate(tenant_id=TENANT, draft_id=old.id, user_id=USER)

    assert new.id != old.id and new.generated_text == "segunda" and new.status == "proposed"
    discarded = repo.get_draft(tenant_id=TENANT, draft_id=old.id)
    assert discarded is not None and discarded.status == "discarded"
    assert discarded.decided_by_user_id == USER and discarded.settled_at is not None
    live = repo.get_live_draft(tenant_id=TENANT, message_id=candidate.message_id)
    assert live is not None and live.id == new.id
    # The automatic batch does not touch the comment again.
    summary = service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    assert summary.candidates_seen == 0


def test_a_double_regenerate_leaves_exactly_one_live_draft() -> None:
    repo = MemoryReplyRepository()
    candidate = _candidate()
    repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
    service = _service(repo, FakeGroundedGenerator())
    service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    (old,) = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)

    first = service.regenerate(tenant_id=TENANT, draft_id=old.id, user_id=USER)
    with pytest.raises(ValueError, match="only 'proposed'"):
        service.regenerate(tenant_id=TENANT, draft_id=old.id, user_id=USER)

    pending = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    assert [d.id for d in pending] == [first.id]


class _StaleReadRepository(MemoryReplyRepository):
    """A double click: the second request read the draft BEFORE the first one replaced
    it, so it still sees `'proposed'` and goes all the way to `supersede_draft`."""

    def __init__(self) -> None:
        super().__init__()
        self.stale: dict[UUID, Any] = {}

    def get_draft(self, *, tenant_id: UUID, draft_id: UUID) -> Any:
        return self.stale.get(draft_id) or super().get_draft(tenant_id=tenant_id, draft_id=draft_id)


def test_the_losing_double_click_gets_the_winners_draft_not_a_second_one() -> None:
    repo = _StaleReadRepository()
    candidate = _candidate()
    repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
    service = _service(repo, FakeGroundedGenerator())
    service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    (old,) = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    repo.stale[old.id] = old  # both requests read it as 'proposed'

    winner = service.regenerate(tenant_id=TENANT, draft_id=old.id, user_id=USER)
    loser = service.regenerate(tenant_id=TENANT, draft_id=old.id, user_id=USER)

    assert loser.id == winner.id
    pending = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    assert [d.id for d in pending] == [winner.id]


def test_regenerate_runs_the_gate_first_and_changes_nothing_on_refusal() -> None:
    repo = MemoryReplyRepository()
    candidate = _candidate()
    repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
    gen = FakeGroundedGenerator()
    service = _service(repo, gen)
    service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    (old,) = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    # Meanwhile a person approved a DM for this comment (Fase C).
    from dataclasses import replace

    repo.seed_candidates(
        connection_id=CONNECTION, candidates=(replace(candidate, followup_status="approved"),)
    )

    with pytest.raises(RegenerationRefused, match="answered by DM"):
        service.regenerate(tenant_id=TENANT, draft_id=old.id, user_id=USER)

    assert len(gen.calls) == 1  # only the first generation
    still = repo.get_draft(tenant_id=TENANT, draft_id=old.id)
    assert still is not None and still.status == "proposed"


# --- the real generator with the public prompt ------------------------------------------


class _FakeMessages:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response


def _tool_response(reply: str) -> Any:
    return SimpleNamespace(
        model="claude-haiku-5-5-20260901",
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=300, output_tokens=40, cache_read_input_tokens=0),
        content=[
            SimpleNamespace(
                type="tool_use",
                name=TOOL_NAME,
                input={"reply": reply, "uses_only_given_facts": True, "unsupported_claims": []},
            )
        ],
    )


def test_the_public_generator_uses_its_own_prompt_and_version_and_sees_no_price() -> None:
    messages = _FakeMessages(_tool_response("¡Hola! Te escribimos por DM con el precio."))
    client = SimpleNamespace(messages=messages)
    gen = ClaudeDraftGenerator(
        system_prompt=PUBLIC_SYSTEM_PROMPT,
        version_prefix=PUBLIC_GENERATOR_VERSION_PREFIX,
        client_factory=lambda key: client,
        api_key="k",
    )
    repo = MemoryReplyRepository()
    repo.seed_candidates(connection_id=CONNECTION, candidates=(_candidate(),))
    service = ReplyService(
        repository=repo,
        version=SENTIMENT,
        generator_version="v",
        intent_version=INTENT,
        grounded_generator=gen,
        grounding=lambda t, c: CATALOG,
        reliability=lambda d: ALL_RELIABLE,
    )

    service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)

    assert gen.version == PUBLIC_GENERATOR_VERSION == "m24789645.1:claude-haiku-5-5"
    assert public_reply_generator().version == PUBLIC_GENERATOR_VERSION
    (call,) = messages.calls
    system = call["system"][0]["text"] if isinstance(call["system"], list) else call["system"]
    assert system == PUBLIC_SYSTEM_PROMPT
    user = call["messages"][0]["content"]
    assert "Yogurt de taro" in user
    assert not has_price_token(user) and "4.5" not in user
    assert f"{COMMENT_SPEAKER}: ¿Cuánto cuesta el de taro?" in user
    (draft,) = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    assert draft.generator_version == PUBLIC_GENERATOR_VERSION
    assert draft.cost_usd == Decimal(str(round((300 * 0.10 + 40 * 0.50) / 1_000_000, 6)))


def test_public_prompt_states_d1_and_d2() -> None:
    assert "NUNCA escribas un precio" in PUBLIC_SYSTEM_PROMPT
    assert "horarios" in PUBLIC_SYSTEM_PROMPT and "existencias" in PUBLIC_SYSTEM_PROMPT
    assert "dato personal" in PUBLIC_SYSTEM_PROMPT
    assert public_context(()).startswith("Respondes un comentario PÚBLICO")


def test_has_price_token_covers_the_markets() -> None:
    for text in ("Cuesta $12", "12 USD", "U$S 300", "15 pesos", "350 Bs", "COP 20.000"):
        assert has_price_token(text), text
    for text in ("mil gracias", "Te escribimos por DM con el precio", "Abrimos a las 9"):
        assert not has_price_token(text), text
