"""ATENDER-4b (m-24848533): public drafts for ANY comment — questions and complaints too —
behind a per-tenant setting that is OFF by default (ATENDER-4a's measurement has not
passed on real comments yet). Offline: Memory repository, a fake triager and a fake
grounded generator; no network, no database.

Pinned here: the setting fails closed; with it OFF nothing changes (no triage call, NEG
comments still get no draft); with it ON a complaint is routed FIRST and always carries
the blocking `complaint` review reason; `other` comments get no draft from the batch but
do on the owner's «Responder aquí»; the triage's model, prompt version and cost share
are stored on the draft; a deleted comment gets none; nothing here ever posts a reply."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.assisted.grounding import GroundedProduct, Grounding
from qualify_api.claude_tools import ClaudeToolError
from qualify_api.conversations.suggest import Proposal
from qualify_api.replies.any_comment import (
    COMPLAINT_REASON,
    ENV_ANY_COMMENT_TENANTS,
    any_comment_enabled,
)
from qualify_api.replies.any_comment_drafts import ANY_COMMENT_VERSION_PREFIX
from qualify_api.replies.gate import (
    ROUTE_ANY_COMMENT,
    ROUTE_COMMERCIAL,
    ROUTE_SENTIMENT,
    GateInput,
    IntentEvidence,
    TriageEvidence,
    evaluate_gate,
)
from qualify_api.replies.repository import CandidateComment, MemoryReplyRepository
from qualify_api.replies.service import RegenerationRefused, ReplyService
from qualify_api.replies.triage import CommentKind, Sentiment, Triage
from qualify_api.sentiment.repository import AnalysisVersion

TENANT = UUID("11111111-1111-4111-8111-111111111111")
OTHER_TENANT = UUID("44444444-4444-4444-8444-444444444444")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")
USER = UUID("33333333-3333-4333-8333-333333333333")
SENTIMENT = AnalysisVersion("det-1", "pipe-1", "model-1", None)
INTENT = AnalysisVersion("intent-claude-v2", "intent-pipeline-v1", "claude-haiku-5-5", None)
CATALOG = Grounding("Polette", (GroundedProduct("Yogurt de taro", "$4.5"),))


# --- the setting ---------------------------------------------------------------------


def test_the_setting_is_off_by_default_and_fails_closed() -> None:
    assert any_comment_enabled(TENANT, env={}) is False
    assert any_comment_enabled(TENANT, env={ENV_ANY_COMMENT_TENANTS: "  "}) is False
    # A typo never turns it on for anyone.
    assert any_comment_enabled(TENANT, env={ENV_ANY_COMMENT_TENANTS: f"{TENANT},nope"}) is False


def test_the_setting_is_per_tenant_or_all() -> None:
    env = {ENV_ANY_COMMENT_TENANTS: f" {TENANT} , "}
    assert any_comment_enabled(TENANT, env=env) is True
    assert any_comment_enabled(OTHER_TENANT, env=env) is False
    assert any_comment_enabled(OTHER_TENANT, env={ENV_ANY_COMMENT_TENANTS: "ALL"}) is True


# --- the gate ------------------------------------------------------------------------


def _triage(kind: str, sentiment: str = "neu") -> TriageEvidence:
    return TriageEvidence(
        kind=kind,
        sentiment=sentiment,
        needs_reply=kind in ("question", "complaint"),
        model_id="claude-haiku-5-5",
        prompt_version="atender4a.1",
        cost_usd=0.00002,
    )


def _gate(**kwargs: Any) -> GateInput:
    base: dict[str, Any] = {
        "channel": "comment",
        "sentiment_label": "",
        "comment_text": "llegó frío el pedido",
        "has_live_draft": False,
        "current_intent_version": INTENT,
        "any_comment": True,
        "has_analysis_row": True,
    }
    base.update(kwargs)
    return GateInput(**base)


def test_a_complaint_goes_to_the_any_comment_route_before_thanks_or_sales() -> None:
    commercial = IntentEvidence(commercial_intent=True, version=INTENT)
    verdict = evaluate_gate(
        _gate(sentiment_label="POS", intent=commercial, triage=_triage("complaint", "neg"))
    )
    assert verdict.passed and verdict.route == ROUTE_ANY_COMMENT
    assert "complaint" in verdict.reason and "atender4a.1" in verdict.reason


@pytest.mark.parametrize("kind", ["praise", "question"])
def test_praise_and_questions_get_a_draft_when_no_older_route_takes_them(kind: str) -> None:
    verdict = evaluate_gate(_gate(triage=_triage(kind)))
    assert verdict.passed and verdict.route == ROUTE_ANY_COMMENT


def test_the_older_routes_still_win_for_non_complaints() -> None:
    commercial = IntentEvidence(commercial_intent=True, version=INTENT)
    assert evaluate_gate(_gate(intent=commercial, triage=_triage("question"))).route == (
        ROUTE_COMMERCIAL
    )
    assert evaluate_gate(_gate(sentiment_label="POS", triage=_triage("praise"))).route == (
        ROUTE_SENTIMENT
    )


def test_other_comments_get_no_batch_draft_but_do_when_the_owner_asks() -> None:
    assert not evaluate_gate(_gate(triage=_triage("other"))).passed
    asked = evaluate_gate(_gate(triage=_triage("other"), owner_requested=True))
    assert asked.passed and asked.route == ROUTE_ANY_COMMENT
    assert "owner asked" in asked.reason


def test_the_route_needs_a_stored_analysis_row() -> None:
    verdict = evaluate_gate(_gate(triage=_triage("complaint"), has_analysis_row=False))
    assert not verdict.passed and "Ordenar por prioridad" in verdict.reason


def test_with_the_setting_off_the_triage_is_ignored() -> None:
    verdict = evaluate_gate(_gate(any_comment=False, triage=_triage("complaint")))
    assert not verdict.passed


def test_the_hard_refusals_still_come_first() -> None:
    for refused in (
        _gate(triage=_triage("complaint"), followup_status="approved"),
        _gate(triage=_triage("complaint"), has_live_draft=True),
        _gate(triage=_triage("complaint"), comment_text="   "),
    ):
        assert not evaluate_gate(refused).passed


# --- the service ---------------------------------------------------------------------


@dataclass
class _Stats:
    cost_usd: float


class FakeTriager:
    model_id = "claude-haiku-5-5"
    prompt_version = "atender4a.1"

    def __init__(self, by_text: dict[str, CommentKind], *, fail: bool = False) -> None:
        self._by_text = by_text
        self._fail = fail
        self.calls: list[list[str]] = []
        self.last_stats: list[_Stats] = []

    def triage(self, texts: Sequence[str]) -> list[Triage | None]:
        self.calls.append(list(texts))
        if self._fail:
            raise ClaudeToolError("claude-haiku-5-5 did not call registrar_comentarios")
        self.last_stats = [_Stats(cost_usd=0.00004 * len(texts))]
        out: list[Triage | None] = []
        for text in texts:
            kind = self._by_text.get(text)
            if kind is None:
                out.append(None)
                continue
            tone = Sentiment.NEG if kind is CommentKind.COMPLAINT else Sentiment.NEU
            out.append(Triage(sentiment=tone, kind=kind, needs_reply=True))
        return out


class FakeAnyGenerator:
    version = f"{ANY_COMMENT_VERSION_PREFIX}:claude-haiku-5-5"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def propose(
        self,
        *,
        grounding: Grounding,
        messages: Sequence[Any],
        counterpart: str,
        context: str | None = None,
    ) -> Proposal:
        self.calls.append({"grounding": grounding, "context": context, "messages": messages})
        return Proposal(
            text="Lamentamos lo que pasó. Escríbenos por mensaje privado y lo revisamos contigo.",
            used_only_given_facts=True,
            unsupported_claims=(),
            model_id="claude-haiku-5-5",
            model_revision=None,
            input_tokens=200,
            output_tokens=30,
            cost_usd=0.0002,
        )


class NoGrounded:
    version = "never"

    def propose(self, **kwargs: Any) -> Proposal:
        raise AssertionError("the commercial generator must not run in these tests")


class NoProvider:
    def draft_reply(self, *, comment_text: str, business_name: str | None = None) -> str:
        raise AssertionError("the thank-you provider must not run in these tests")


def _candidate(text: str, *, sentiment: str = "NEG", commercial: bool = False) -> CandidateComment:
    return CandidateComment(
        message_id=uuid4(),
        source_id=f"ig-{uuid4().hex[:6]}",
        text=text,
        sentiment_result_id=uuid4(),
        sentiment_label=sentiment,
        intent_result_id=uuid4(),
        intent_classes=("general",),
        commercial_intent=commercial,
        intent_version=INTENT,
    )


def _service(
    repo: MemoryReplyRepository,
    triager: FakeTriager,
    generator: FakeAnyGenerator,
    *,
    enabled: bool = True,
) -> ReplyService:
    return ReplyService(
        repository=repo,
        version=SENTIMENT,
        generator_version="qua22.2:test",
        provider=NoProvider(),  # type: ignore[arg-type]
        intent_version=INTENT,
        grounded_generator=NoGrounded(),  # type: ignore[arg-type]
        grounding=lambda tenant_id, connection_id: CATALOG,
        reliability=lambda detector: {},
        any_comment_generator=generator,  # type: ignore[arg-type]
        triager_factory=lambda: triager,
        any_comment_enabled=lambda tenant_id: enabled and tenant_id == TENANT,
    )


COMPLAINT = "llegó frío el pedido"
QUESTION = "¿abren el domingo?"
SPAM = "Gana dinero desde casa"


def test_with_the_setting_off_nothing_is_triaged_and_complaints_get_no_draft() -> None:
    repo = MemoryReplyRepository()
    repo.seed_candidates(connection_id=CONNECTION, candidates=(_candidate(COMPLAINT),))
    triager = FakeTriager({COMPLAINT: CommentKind.COMPLAINT})
    generator = FakeAnyGenerator()

    summary = _service(repo, triager, generator, enabled=False).generate_drafts(
        tenant_id=TENANT, connection_id=CONNECTION
    )

    assert summary.drafts_created == 0 and summary.gate_rejected == 1
    assert triager.calls == [] and generator.calls == []


def test_a_complaint_draft_needs_review_and_records_its_triage_and_cost() -> None:
    repo = MemoryReplyRepository()
    repo.seed_candidates(
        connection_id=CONNECTION,
        candidates=(_candidate(COMPLAINT), _candidate(QUESTION, sentiment="NEU")),
    )
    triager = FakeTriager({COMPLAINT: CommentKind.COMPLAINT, QUESTION: CommentKind.QUESTION})
    generator = FakeAnyGenerator()

    summary = _service(repo, triager, generator).generate_drafts(
        tenant_id=TENANT, connection_id=CONNECTION
    )

    assert summary.drafts_created == 2
    assert len(triager.calls) == 1  # one batched triage call for the whole run
    by_text = {
        d.comment_text: d
        for d in repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    }
    complaint = by_text[COMPLAINT]
    assert complaint.needs_review is True
    assert complaint.grounding is not None
    assert complaint.grounding["review_reasons"][0] == COMPLAINT_REASON
    assert complaint.grounding["triage"]["kind"] == "complaint"
    assert complaint.grounding["triage"]["prompt_version"] == "atender4a.1"
    assert complaint.generator_version.startswith(ANY_COMMENT_VERSION_PREFIX)
    assert complaint.model_id == "claude-haiku-5-5"
    # The draft's cost includes its share of the triage call (0.00008 / 2 comments).
    assert complaint.cost_usd is not None and float(complaint.cost_usd) == pytest.approx(0.00024)
    question = by_text[QUESTION]
    assert COMPLAINT_REASON not in question.grounding["review_reasons"]
    # The complaint context reaches the generator; the catalog never carries a price.
    contexts = [c["context"] for c in generator.calls]
    assert any("queja" in (ctx or "") for ctx in contexts)
    assert all(c["grounding"].prices_withheld for c in generator.calls)


def test_the_batch_skips_other_comments() -> None:
    repo = MemoryReplyRepository()
    repo.seed_candidates(connection_id=CONNECTION, candidates=(_candidate(SPAM, sentiment="NEU"),))
    generator = FakeAnyGenerator()

    summary = _service(repo, FakeTriager({SPAM: CommentKind.OTHER}), generator).generate_drafts(
        tenant_id=TENANT, connection_id=CONNECTION
    )

    assert summary.drafts_created == 0 and generator.calls == []


def test_a_failed_triage_falls_back_to_the_older_rules() -> None:
    repo = MemoryReplyRepository()
    repo.seed_candidates(connection_id=CONNECTION, candidates=(_candidate(COMPLAINT),))
    generator = FakeAnyGenerator()

    summary = _service(repo, FakeTriager({}, fail=True), generator).generate_drafts(
        tenant_id=TENANT, connection_id=CONNECTION
    )

    assert summary.drafts_created == 0 and generator.calls == []


def test_reply_here_creates_one_draft_and_a_second_tap_returns_the_same() -> None:
    repo = MemoryReplyRepository()
    candidate = _candidate(COMPLAINT)
    repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
    generator = FakeAnyGenerator()
    service = _service(repo, FakeTriager({COMPLAINT: CommentKind.COMPLAINT}), generator)

    first = service.prepare_for_comment(
        tenant_id=TENANT, connection_id=CONNECTION, message_id=candidate.message_id
    )
    second = service.prepare_for_comment(
        tenant_id=TENANT, connection_id=CONNECTION, message_id=candidate.message_id
    )

    assert first.id == second.id and first.status == "proposed"
    assert len(generator.calls) == 1
    assert "owner asked" in first.gate_reason


def test_reply_here_drafts_an_other_comment_because_the_owner_asked() -> None:
    repo = MemoryReplyRepository()
    candidate = _candidate("@sofi_m para tu cumple", sentiment="NEU")
    repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
    service = _service(repo, FakeTriager({candidate.text: CommentKind.OTHER}), FakeAnyGenerator())

    draft = service.prepare_for_comment(
        tenant_id=TENANT, connection_id=CONNECTION, message_id=candidate.message_id
    )

    assert draft.grounding is not None and draft.grounding["triage"]["kind"] == "other"


def test_reply_here_with_the_setting_off_refuses_a_complaint() -> None:
    repo = MemoryReplyRepository()
    candidate = _candidate(COMPLAINT)
    repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
    service = _service(
        repo, FakeTriager({COMPLAINT: CommentKind.COMPLAINT}), FakeAnyGenerator(), enabled=False
    )

    with pytest.raises(RegenerationRefused, match="POS"):
        service.prepare_for_comment(
            tenant_id=TENANT, connection_id=CONNECTION, message_id=candidate.message_id
        )
    assert repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION) == ()


def test_reply_here_on_a_deleted_comment_gets_no_draft() -> None:
    repo = MemoryReplyRepository()  # a deleted comment is not a candidate at all
    generator = FakeAnyGenerator()
    service = _service(repo, FakeTriager({}), generator)

    with pytest.raises(RegenerationRefused, match="no longer available"):
        service.prepare_for_comment(tenant_id=TENANT, connection_id=CONNECTION, message_id=uuid4())
    assert generator.calls == []


def test_reply_here_on_a_comment_answered_by_dm_gets_no_draft() -> None:
    repo = MemoryReplyRepository()
    candidate = replace(_candidate(COMPLAINT), followup_status="approved")
    repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
    service = _service(repo, FakeTriager({COMPLAINT: CommentKind.COMPLAINT}), FakeAnyGenerator())

    with pytest.raises(RegenerationRefused, match="answered by DM"):
        service.prepare_for_comment(
            tenant_id=TENANT, connection_id=CONNECTION, message_id=candidate.message_id
        )


def test_regenerate_keeps_the_complaint_route() -> None:
    repo = MemoryReplyRepository()
    candidate = _candidate(COMPLAINT)
    repo.seed_candidates(connection_id=CONNECTION, candidates=(candidate,))
    service = _service(repo, FakeTriager({COMPLAINT: CommentKind.COMPLAINT}), FakeAnyGenerator())
    old = service.prepare_for_comment(
        tenant_id=TENANT, connection_id=CONNECTION, message_id=candidate.message_id
    )

    new = service.regenerate(tenant_id=TENANT, draft_id=old.id, user_id=USER)

    assert new.id != old.id and new.needs_review is True
    assert new.grounding is not None and new.grounding["review_reasons"][0] == COMPLAINT_REASON


def test_generation_never_posts_a_reply() -> None:
    """No client factory at all: any path that tried to send would raise."""
    repo = MemoryReplyRepository()
    repo.seed_candidates(connection_id=CONNECTION, candidates=(_candidate(COMPLAINT),))
    service = _service(repo, FakeTriager({COMPLAINT: CommentKind.COMPLAINT}), FakeAnyGenerator())
    service.generate_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    (draft,) = repo.list_pending_drafts(tenant_id=TENANT, connection_id=CONNECTION)
    assert draft.status == "proposed" and draft.sent_at is None
