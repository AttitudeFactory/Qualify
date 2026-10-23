"""The reply-draft service (QUA-22, comments tranche): generate → decide → send.

Two write-aheads, mirroring `publishing/service.py`'s own:

1. `create_draft` — the row is written as `'proposed'` before ever being shown to a
   human; nothing generates a reply text without a persisted trace of why the gate let
   it through (`gate_reason`) and under which `generator_version`.
2. `mark_sending` — the row is marked BEFORE the Meta call. A transport failure after
   the marker is unsettled ambiguity (`send_ambiguous`), never a lie in either
   direction — see migration 0014's docstring and `PublishService.advance()`'s own
   "Settle NOTHING" branch, the same decision copied for the same reason.

3. **No send without a `HumanApproval`** (m-24789645). `send` takes the same
   `qualify_api.assisted.HumanApproval` the private outbox demands, naming THIS draft;
   without it, it raises `ApprovalRequired` before reading anything. The status guard
   (`accepted`/`edited`) is kept underneath it. A static test
   (`test_replies_send_sanctity.py`) pins `post_reply` to this method and the notice
   poster, and every caller of `send`/`send_draft` to passing an approval.

**Fase B (m-24789645, PR 2).** A comment with commercial intent under the current intent
version is a candidate too; the gate routes it to the grounded generator (`public_drafts`:
catalog only, prices withheld, review reasons recorded) instead of the thank-you
provider. `regenerate` replaces a `proposed` draft atomically. Generation never sends.

**Any comment (ATENDER-4b, m-24848533).** For a business with the per-tenant setting on
(`replies.any_comment`, OFF by default), every candidate is first triaged in one batched
Claude Haiku call (`replies.triage`, ATENDER-4a's measured candidate) and the gate's
`any_comment` route drafts questions and complaints with ATENDER-4a's prompt
(`any_comment_drafts`, `atender4a.2`) over the same grounded generator. A complaint draft
always carries the blocking `complaint` review reason. The triage (kind, tone, model,
prompt version, cost share) is stored inside the draft's grounding record, so no new
column was needed. `prepare_for_comment` is «Responder aquí»: one comment, on the
owner's tap. Neither ever sends.

No scheduler, no automatic run chained after `sentiment.analyze_pending_comments()` —
same manual-trigger-only posture that module's own docstring documents. This module
does not know when it is called, only what to do when it is.
"""

from __future__ import annotations

import difflib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from qualify_api.assisted.approval import ApprovalRequired, HumanApproval
from qualify_api.assisted.grounding import Grounding, GroundingProvider
from qualify_api.claude_tools import CallStats, ClaudeToolError
from qualify_api.intent.contract import IntentClass
from qualify_api.intent.reliability import class_reliability
from qualify_api.replies.any_comment import COMPLAINT_REASON
from qualify_api.replies.any_comment_drafts import any_comment_context
from qualify_api.replies.client import CommentReplyClient, CommentReplyError
from qualify_api.replies.failures import classify_reply_error, error_code_for, is_retryable
from qualify_api.replies.gate import (
    KIND_COMPLAINT,
    ROUTE_ANY_COMMENT,
    ROUTE_COMMERCIAL,
    GateInput,
    GateVerdict,
    IntentEvidence,
    TriageEvidence,
    evaluate_gate,
)
from qualify_api.replies.public_drafts import (
    COMMENT_SPEAKER,
    ReliabilityReader,
    comment_message,
    cost_decimal,
    grounding_record,
    needs_review_for,
    parse_classes,
    public_context,
    review_reasons,
)
from qualify_api.replies.repository import (
    CandidateComment,
    DraftProvenance,
    DraftRecord,
    ReplyRepository,
)
from qualify_api.replies.triage import CommentKind, CommentTriager, Sentiment
from qualify_api.sentiment.repository import AnalysisVersion

if TYPE_CHECKING:
    # `qualify_models` lives in the `ml` dependency group, deliberately excluded from
    # the default install — same TYPE_CHECKING-only reasoning `sentiment/service.py`
    # documents for `SentimentProvider`.
    from qualify_models.providers import ReplyDraftProvider

    from qualify_api.conversations.suggest import DraftGenerator

logger = logging.getLogger("qualify_api.replies.service")


class ConnectionDegrader(Protocol):
    """QUA-90: degrades a connection to `degraded` after a runtime 401/190. Same shape
    `publishing.service.ConnectionDegrader` already establishes — duplicated rather
    than imported, same self-containment discipline every module in this codebase
    follows for its own client-facing Protocols."""

    def __call__(self, *, tenant_id: UUID, connection_id: UUID) -> object | None: ...


def _no_op_degrader(*, tenant_id: UUID, connection_id: UUID) -> None:
    return None


class ReplyClientFactory(Protocol):
    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> CommentReplyClient: ...


class UnknownDraft(Exception):
    """No draft with that id is visible in this tenant."""


def require_approval(approval: object, *, draft_id: UUID) -> HumanApproval:
    """The approval guard of every public reply: a `HumanApproval` that names this exact
    draft. Raises `ApprovalRequired` otherwise — a missing approval, a look-alike object,
    or an approval given for another draft (or for no draft: a public comment reply is
    always a draft's text)."""
    if not isinstance(approval, HumanApproval):
        raise ApprovalRequired("a public reply cannot be sent without a human approval")
    if approval.draft_id != draft_id:
        raise ApprovalRequired(f"the approval does not name draft {draft_id}")
    return approval


class RegenerationRefused(ValueError):
    """The comment no longer earns a public draft (the gate said no, or it is gone).
    `reason` is the gate's reason; the live draft is left exactly as it was."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RetryRefused(ValueError):
    """«Reintentar» has nothing to do: the draft is not a passing failure, or it was
    already retried (a second tap) or replaced meanwhile. Nothing was written."""


#: Stores one comment's analysis row: `(tenant_id, connection_id, message_id)`.
CommentAnalyzer = Callable[[UUID, UUID, UUID], None]


@dataclass(frozen=True)
class GenerationSummary:
    candidates_seen: int
    drafts_created: int
    gate_rejected: int


@dataclass(frozen=True)
class DecisionResult:
    draft: DraftRecord
    # A line-level diff between generated_text and final_text — empty on a plain
    # 'accepted' (the two are equal) and on 'discarded' (final_text is None).
    # Computed here, never stored a third time (migration 0014's docstring).
    diff: tuple[str, ...]


@dataclass(frozen=True)
class _Composed:
    text: str
    generator_version: str
    provenance: DraftProvenance | None


def _sentiment_provenance(
    provider: object, intent_result_id: UUID | None
) -> DraftProvenance | None:
    """Model, tokens and cost of the thank-you draft when the provider reports them
    (`ClaudeReplyDraftProvider.last_stats`; ATENDER-4a, m-24848532). A provider that does
    not (the HF one, test fakes) keeps the previous behaviour: only the intent link."""
    stats = getattr(provider, "last_stats", None)
    if not isinstance(stats, CallStats):
        if intent_result_id is None:
            return None
        return DraftProvenance(intent_result_id=intent_result_id)
    return DraftProvenance(
        model_id=stats.model_id,
        model_revision=stats.model_revision,
        input_tokens=stats.input_tokens,
        output_tokens=stats.output_tokens,
        cost_usd=cost_decimal(stats.cost_usd),
        intent_result_id=intent_result_id,
    )


@dataclass
class _BatchCache:
    """Per-call memo: one catalog read per connection and one reliability read per
    detector version, however many comments the batch drafts."""

    grounding: dict[UUID, Grounding] = field(default_factory=dict)
    reliability: dict[str, dict[IntentClass, bool]] = field(default_factory=dict)


class ReplyService:
    def __init__(
        self,
        *,
        repository: ReplyRepository,
        version: AnalysisVersion,
        generator_version: str,
        provider: ReplyDraftProvider | None = None,
        client_factory: ReplyClientFactory | None = None,
        business_name: str | None = None,
        connection_degrader: ConnectionDegrader | None = None,
        intent_version: AnalysisVersion | None = None,
        grounded_generator: DraftGenerator | None = None,
        grounding: GroundingProvider | None = None,
        reliability: ReliabilityReader = class_reliability,
        any_comment_generator: DraftGenerator | None = None,
        triager_factory: Callable[[], CommentTriager] | None = None,
        any_comment_enabled: Callable[[UUID], bool] | None = None,
        comment_analyzer: CommentAnalyzer | None = None,
    ) -> None:
        """`version` is the sentiment version (QUA-22's POS path, `provider`).
        `intent_version` turns on Fase B (m-24789645): commercial comments under it are
        drafted by `grounded_generator` over `grounding` — both required for that route,
        which fails loudly without them rather than falling back to the ungrounded one.

        ATENDER-4b: `any_comment_enabled(tenant_id)` is the per-tenant setting (None =
        OFF for everyone); `triager_factory` builds the triager on first use (it needs the
        API key, which a service that never triages must not demand) and
        `any_comment_generator` writes the drafts of the `any_comment` route.
        `comment_analyzer(tenant_id, connection_id, message_id)` stores ONE comment's
        analysis row when «Responder aquí» finds none (the intent pass of «Ordenar por
        prioridad», limited to that comment); None = the owner must sort first."""
        self._repo = repository
        self._version = version
        self._generator_version = generator_version
        self._provider = provider
        self._clients = client_factory
        self._business_name = business_name
        self._degrade = connection_degrader or _no_op_degrader
        self._intent_version = intent_version
        self._grounded = grounded_generator
        self._grounding = grounding
        self._reliability = reliability
        self._any_generator = any_comment_generator
        self._triager_factory = triager_factory
        self._triager: CommentTriager | None = None
        self._any_enabled = any_comment_enabled or (lambda _tenant_id: False)
        self._analyze_comment = comment_analyzer

    # -- generation ---------------------------------------------------------------------

    def _gate_input(
        self,
        candidate: CandidateComment,
        *,
        has_live_draft: bool,
        any_comment: bool = False,
        triage: TriageEvidence | None = None,
        owner_requested: bool = False,
    ) -> GateInput:
        intent = (
            IntentEvidence(
                commercial_intent=candidate.commercial_intent, version=candidate.intent_version
            )
            if candidate.intent_version is not None
            else None
        )
        return GateInput(
            channel="comment",
            sentiment_label=candidate.sentiment_label,
            comment_text=candidate.text,
            has_live_draft=has_live_draft,
            intent=intent,
            current_intent_version=self._intent_version,
            followup_status=candidate.followup_status,
            any_comment=any_comment,
            triage=triage,
            has_analysis_row=(
                candidate.sentiment_result_id is not None or candidate.intent_result_id is not None
            ),
            owner_requested=owner_requested,
        )

    def _triage(self, candidates: Sequence[CandidateComment]) -> dict[UUID, TriageEvidence]:
        """One batched triage call over `candidates` (ATENDER-4b). A failure (no key, the
        model did not answer) leaves every comment untriaged — the gate then applies the
        older rules, it never guesses a kind. Each comment carries its share of the cost."""
        if not candidates or self._triager_factory is None:
            return {}
        try:
            if self._triager is None:
                self._triager = self._triager_factory()
            results = self._triager.triage([c.text for c in candidates])
        except (ClaudeToolError, RuntimeError, ValueError) as exc:
            logger.warning("replies.triage failed, drafting with the older rules: %s", exc)
            return {}
        stats = getattr(self._triager, "last_stats", None) or []
        total = sum(float(getattr(st, "cost_usd", 0.0) or 0.0) for st in stats)
        share = total / len(candidates)
        found: dict[UUID, TriageEvidence] = {}
        for candidate, result in zip(candidates, results, strict=False):
            if result is None:
                continue
            found[candidate.message_id] = TriageEvidence(
                kind=result.kind.value,
                sentiment=result.sentiment.value,
                needs_reply=result.needs_reply,
                model_id=result.model_id,
                prompt_version=result.prompt_version,
                cost_usd=share,
            )
        return found

    def _sentiment_provider(self) -> ReplyDraftProvider:
        if self._provider is None:
            from qualify_models.providers import HFInferenceReplyDraftProvider  # noqa: PLC0415

            self._provider = HFInferenceReplyDraftProvider()
        return self._provider

    def _compose(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        candidate: CandidateComment,
        verdict: GateVerdict,
        cache: _BatchCache,
        triage: TriageEvidence | None = None,
    ) -> _Composed:
        """The one place a generator is called — only ever for a verdict that passed."""
        if verdict.route == ROUTE_ANY_COMMENT:
            if triage is None:
                raise RuntimeError("the any_comment route needs the comment's triage")
            return self._compose_any(
                tenant_id=tenant_id,
                connection_id=connection_id,
                candidate=candidate,
                triage=triage,
                cache=cache,
            )
        if verdict.route != ROUTE_COMMERCIAL:
            text = self._sentiment_provider().draft_reply(
                comment_text=candidate.text, business_name=self._business_name
            )
            return _Composed(
                text,
                self._generator_version,
                _sentiment_provenance(self._sentiment_provider(), candidate.intent_result_id),
            )

        if self._grounded is None or self._grounding is None:
            raise RuntimeError(
                "ReplyService was built without a grounded generator and grounding provider"
            )
        full = cache.grounding.get(connection_id)
        if full is None:
            full = self._grounding(tenant_id, connection_id)
            cache.grounding[connection_id] = full
        public_view = full.without_prices()  # D1: the model never sees a price
        classes = parse_classes(candidate.intent_classes)
        proposal = self._grounded.propose(
            grounding=public_view,
            messages=[
                comment_message(
                    message_id=candidate.message_id,
                    connection_id=connection_id,
                    source_id=candidate.source_id,
                    text=candidate.text,
                )
            ],
            counterpart=COMMENT_SPEAKER,
            context=public_context(classes),
        )
        detector = candidate.intent_version.detector_version if candidate.intent_version else ""
        reliable = cache.reliability.get(detector)
        if reliable is None:
            reliable = dict(self._reliability(detector)) if detector else {}
            cache.reliability[detector] = reliable
        reasons = review_reasons(
            text=proposal.text,
            used_only_given_facts=proposal.used_only_given_facts,
            unsupported_claims=proposal.unsupported_claims,
            grounding=full,
            classes=classes,
            reliable=reliable,
        )
        return _Composed(
            proposal.text,
            self._grounded.version,
            DraftProvenance(
                grounding=grounding_record(public_view, reasons),
                needs_review=needs_review_for(reasons),
                unsupported_claims=tuple(proposal.unsupported_claims),
                model_id=proposal.model_id,
                model_revision=proposal.model_revision,
                input_tokens=proposal.input_tokens,
                output_tokens=proposal.output_tokens,
                cost_usd=cost_decimal(proposal.cost_usd),
                intent_result_id=candidate.intent_result_id,
            ),
        )

    def _compose_any(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        candidate: CandidateComment,
        triage: TriageEvidence,
        cache: _BatchCache,
    ) -> _Composed:
        """ATENDER-4b: a praise, question or complaint drafted with ATENDER-4a's prompt
        (`atender4a.2`) over the catalog WITHOUT prices (D1), judged by the same review
        reasons as Fase B plus `complaint` — a complaint never goes out unreviewed."""
        if self._any_generator is None or self._grounding is None:
            raise RuntimeError(
                "ReplyService was built without an any-comment generator and grounding"
            )
        full = cache.grounding.get(connection_id)
        if full is None:
            full = self._grounding(tenant_id, connection_id)
            cache.grounding[connection_id] = full
        public_view = full.without_prices()
        classes = parse_classes(candidate.intent_classes)
        try:
            kind = CommentKind(triage.kind)
            tone = Sentiment(triage.sentiment)
        except ValueError:
            kind, tone = CommentKind.OTHER, Sentiment.NEU
        proposal = self._any_generator.propose(
            grounding=public_view,
            messages=[
                comment_message(
                    message_id=candidate.message_id,
                    connection_id=connection_id,
                    source_id=candidate.source_id,
                    text=candidate.text,
                )
            ],
            counterpart=COMMENT_SPEAKER,
            context=any_comment_context(kind=kind, sentiment=tone, classes=classes),
        )
        reasons = review_reasons(
            text=proposal.text,
            used_only_given_facts=proposal.used_only_given_facts,
            unsupported_claims=proposal.unsupported_claims,
            grounding=full,
            classes=classes,
            # The triage routed this draft, not the intent chips: their reliability
            # notes do not apply. Only the D1/D2 checks do.
            reliable=dict.fromkeys(classes, True),
        )
        if triage.kind == KIND_COMPLAINT:
            reasons = (COMPLAINT_REASON, *reasons)
        record = grounding_record(public_view, reasons)
        record["triage"] = {
            "kind": triage.kind,
            "sentiment": triage.sentiment,
            "needs_reply": triage.needs_reply,
            "model_id": triage.model_id,
            "prompt_version": triage.prompt_version,
            "cost_usd": round(triage.cost_usd, 8),
        }
        return _Composed(
            proposal.text,
            self._any_generator.version,
            DraftProvenance(
                grounding=record,
                needs_review=needs_review_for(reasons),
                unsupported_claims=tuple(proposal.unsupported_claims),
                model_id=proposal.model_id,
                model_revision=proposal.model_revision,
                input_tokens=proposal.input_tokens,
                output_tokens=proposal.output_tokens,
                # The draft's cost includes its share of the triage call.
                cost_usd=cost_decimal(proposal.cost_usd + triage.cost_usd),
                intent_result_id=candidate.intent_result_id,
            ),
        )

    def generate_drafts(self, *, tenant_id: UUID, connection_id: UUID) -> GenerationSummary:
        """The gate runs on EVERY candidate before the generator is ever called — see
        `gate.py`'s module docstring. A rejected candidate produces no draft and no
        generator call; nothing records a rejection, only what passed does. A comment
        whose earlier draft was discarded is not a candidate here (`regenerate` is)."""
        any_comment = self._any_enabled(tenant_id)
        candidates = self._repo.list_reply_candidates(
            tenant_id=tenant_id,
            connection_id=connection_id,
            sentiment_version=self._version,
            intent_version=self._intent_version,
            any_comment=any_comment,
        )
        triages = self._triage(candidates) if any_comment else {}
        cache = _BatchCache()
        created = 0
        rejected = 0
        for candidate in candidates:
            live = self._repo.get_live_draft(tenant_id=tenant_id, message_id=candidate.message_id)
            triage = triages.get(candidate.message_id)
            verdict = evaluate_gate(
                self._gate_input(
                    candidate,
                    has_live_draft=live is not None,
                    any_comment=any_comment,
                    triage=triage,
                )
            )
            if not verdict.passed:
                rejected += 1
                continue
            composed = self._compose(
                tenant_id=tenant_id,
                connection_id=connection_id,
                candidate=candidate,
                verdict=verdict,
                cache=cache,
                triage=triage,
            )
            result = self._repo.create_draft(
                tenant_id=tenant_id,
                connection_id=connection_id,
                candidate=candidate,
                gate_reason=verdict.reason,
                generator_version=composed.generator_version,
                generated_text=composed.text,
                provenance=composed.provenance,
            )
            if result is not None:
                created += 1
        return GenerationSummary(
            candidates_seen=len(candidates), drafts_created=created, gate_rejected=rejected
        )

    def prepare_for_comment(
        self, *, tenant_id: UUID, connection_id: UUID, message_id: UUID
    ) -> DraftRecord:
        """«Responder aquí» (ATENDER-4b): the public draft for ONE comment, on the
        owner's tap. Returns the comment's live draft when it already has one (a second
        tap, or the batch got there first) — never a second draft, never a send.

        Raises `RegenerationRefused` when the gate says no (a deleted comment, a comment
        already answered by DM, or — with the setting OFF — a comment that is neither
        positive nor commercial). Its `reason` is the gate's, for the log; the screen
        translates it (`replies_vm.reply_here_error_message`)."""
        live = self._repo.get_live_draft(tenant_id=tenant_id, message_id=message_id)
        if live is not None:
            return live
        candidate = self._repo.get_reply_candidate(
            tenant_id=tenant_id,
            message_id=message_id,
            sentiment_version=self._version,
            intent_version=self._intent_version,
        )
        if candidate is None:
            raise RegenerationRefused("the comment is no longer available on Instagram")
        candidate = self._ensure_analysis_row(
            tenant_id=tenant_id, connection_id=connection_id, candidate=candidate
        )
        any_comment = self._any_enabled(tenant_id)
        triage = self._triage([candidate]).get(candidate.message_id) if any_comment else None
        verdict = evaluate_gate(
            self._gate_input(
                candidate,
                has_live_draft=False,
                any_comment=any_comment,
                triage=triage,
                owner_requested=True,
            )
        )
        if not verdict.passed:
            raise RegenerationRefused(verdict.reason)
        composed = self._compose(
            tenant_id=tenant_id,
            connection_id=connection_id,
            candidate=candidate,
            verdict=verdict,
            cache=_BatchCache(),
            triage=triage,
        )
        created = self._repo.create_draft(
            tenant_id=tenant_id,
            connection_id=connection_id,
            candidate=candidate,
            gate_reason=verdict.reason,
            generator_version=composed.generator_version,
            generated_text=composed.text,
            provenance=composed.provenance,
        )
        if created is not None:
            return created
        # A double tap lost the race: hand back the draft that won.
        live = self._repo.get_live_draft(tenant_id=tenant_id, message_id=message_id)
        if live is None:
            raise RegenerationRefused(f"comment {message_id} was answered meanwhile")
        return live

    def _ensure_analysis_row(
        self, *, tenant_id: UUID, connection_id: UUID, candidate: CandidateComment
    ) -> CandidateComment:
        """«Responder aquí» on a comment not yet sorted: analyze THAT comment first, so
        the owner taps once (UX review, m-24848533). A failure is logged and the gate
        then refuses as before (`ck_reply_draft_has_signal` needs the row)."""
        if self._analyze_comment is None or (
            candidate.sentiment_result_id is not None or candidate.intent_result_id is not None
        ):
            return candidate
        try:
            self._analyze_comment(tenant_id, connection_id, candidate.message_id)
        except Exception as exc:  # the gate's refusal below is the answer
            logger.warning("replies.reply_here analysis failed: %s", type(exc).__name__)
            return candidate
        refreshed = self._repo.get_reply_candidate(
            tenant_id=tenant_id,
            message_id=candidate.message_id,
            sentiment_version=self._version,
            intent_version=self._intent_version,
        )
        return refreshed if refreshed is not None else candidate

    def regenerate(self, *, tenant_id: UUID, draft_id: UUID, user_id: UUID) -> DraftRecord:
        """«Regenerar» (m-24789645): discard the comment's `'proposed'` draft as `user_id`
        and propose a fresh one, through the same gate minus «no live draft» (this call
        replaces it). The gate runs on the comment's CURRENT signals before the model.

        The discard and the new draft commit together (`supersede_draft`); on a refusal
        or a generator error nothing changes. A double click: both requests may pay for
        a proposal, but only one replaces the draft — the other returns the winner's live
        draft, so the comment never holds two. Raises `UnknownDraft`, `ValueError` (not
        `'proposed'`: an approved or sent reply is never regenerated) or
        `RegenerationRefused`."""
        old = self._repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
        if old is None:
            raise UnknownDraft(str(draft_id))
        if old.status != "proposed":
            raise ValueError(f"draft {draft_id} is {old.status!r}; only 'proposed' regenerates")
        candidate = self._repo.get_reply_candidate(
            tenant_id=tenant_id,
            message_id=old.message_id,
            sentiment_version=self._version,
            intent_version=self._intent_version,
        )
        if candidate is None:
            raise RegenerationRefused("the comment is no longer available on Instagram")
        any_comment = self._any_enabled(tenant_id)
        triage = self._triage([candidate]).get(candidate.message_id) if any_comment else None
        # «Regenerar» is the owner's own tap on this comment, like «Responder aquí».
        verdict = evaluate_gate(
            self._gate_input(
                candidate,
                has_live_draft=False,
                any_comment=any_comment,
                triage=triage,
                owner_requested=True,
            )
        )
        if not verdict.passed:
            raise RegenerationRefused(verdict.reason)
        composed = self._compose(
            tenant_id=tenant_id,
            connection_id=old.connection_id,
            candidate=candidate,
            verdict=verdict,
            cache=_BatchCache(),
            triage=triage,
        )
        new = self._repo.supersede_draft(
            tenant_id=tenant_id,
            draft_id=draft_id,
            decided_by_user_id=user_id,
            candidate=candidate,
            gate_reason=verdict.reason,
            generator_version=composed.generator_version,
            generated_text=composed.text,
            provenance=composed.provenance,
        )
        if new is not None:
            return new
        # Lost the race (a double click, or a decision made meanwhile): hand back
        # whichever draft now holds the comment.
        live = self._repo.get_live_draft(tenant_id=tenant_id, message_id=old.message_id)
        if live is None:
            raise RegenerationRefused(f"draft {draft_id} was decided meanwhile")
        return live

    # -- decision and send ----------------------------------------------------------------

    def list_pending_drafts(
        self, *, tenant_id: UUID, connection_id: UUID
    ) -> tuple[DraftRecord, ...]:
        return self._repo.list_pending_drafts(tenant_id=tenant_id, connection_id=connection_id)

    def list_retryable_drafts(
        self, *, tenant_id: UUID, connection_id: UUID
    ) -> tuple[DraftRecord, ...]:
        """ATENDER-9: the replies that did not go out for a passing reason, still waiting
        for the owner's «Reintentar»."""
        return self._repo.list_retryable_drafts(tenant_id=tenant_id, connection_id=connection_id)

    def prepare_retry(self, *, tenant_id: UUID, draft_id: UUID, user_id: UUID) -> DraftRecord:
        """«Reintentar» (ATENDER-9, m-24849130), step one: a NEW `accepted`/`edited`
        draft with the failed one's approved text, decided by `user_id` (the person who
        tapped). Never sends — the caller sends it through `send`, with a
        `HumanApproval` naming the new draft, so there is still exactly one way out.

        Only a passing failure is retried (`replies.failures.is_retryable`): a deleted
        comment, another refusal or an unknown outcome never is. A second tap finds the
        first tap's draft and raises `RetryRefused` — the reply is never doubled. Raises
        `UnknownDraft` when the id is not visible to this tenant."""
        old = self._repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
        if old is None:
            raise UnknownDraft(str(draft_id))
        if not is_retryable(old.status, old.send_error_code):
            raise RetryRefused(f"draft {draft_id} is {old.status!r}; not a passing failure")
        new = self._repo.clone_for_retry(
            tenant_id=tenant_id, draft_id=draft_id, decided_by_user_id=user_id
        )
        if new is None:
            raise RetryRefused(f"draft {draft_id} was already retried or replaced")
        logger.info("replies.retry draft_id=%s new_draft_id=%s by=%s", draft_id, new.id, user_id)
        return new

    def decide(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        decision: str,
        final_text: str | None,
        decided_by_user_id: UUID,
    ) -> DecisionResult:
        """`decision` in `('accepted', 'edited', 'discarded')`. Every draft records
        which of the three a human chose — QUA-22's own criterion, verbatim."""
        record = self._repo.decide_draft(
            tenant_id=tenant_id,
            draft_id=draft_id,
            decision=decision,
            final_text=final_text,
            decided_by_user_id=decided_by_user_id,
        )
        diff: tuple[str, ...] = ()
        if record.final_text is not None and record.final_text != record.generated_text:
            diff = tuple(
                difflib.unified_diff(
                    record.generated_text.splitlines(),
                    record.final_text.splitlines(),
                    lineterm="",
                )
            )
        return DecisionResult(draft=record, diff=diff)

    async def send(
        self, *, tenant_id: UUID, draft_id: UUID, approval: HumanApproval
    ) -> DraftRecord:
        """The one transition here that is FORBIDDEN a blind retry, same posture
        `PublishService._publish_once` documents for its own send. Two guards, in order:
        a `HumanApproval` naming this draft (`require_approval`, before any read), then
        the status — only an `accepted`/`edited` draft goes out. QUA-22's "ninguna
        respuesta se envía sin acción humana explícita" is enforced structurally here:
        there is no code path from `'proposed'` straight into this method, and none
        into `post_reply` without an approval."""
        require_approval(approval, draft_id=draft_id)
        record = self._repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
        if record is None:
            raise UnknownDraft(str(draft_id))
        if record.status not in ("accepted", "edited"):
            raise ValueError(f"draft {draft_id} is {record.status!r}, cannot send")
        if self._clients is None:
            raise RuntimeError("ReplyService was built without a client_factory")

        record = self._repo.mark_sending(tenant_id=tenant_id, draft_id=draft_id)
        logger.info(
            "replies.send draft_id=%s approved_by=%s approved_at=%s",
            draft_id,
            approval.user_id,
            approval.approved_at.isoformat(),
        )
        client = await self._clients.client_for(
            tenant_id=tenant_id, connection_id=record.connection_id
        )
        try:
            external_id = await client.post_reply(
                ig_comment_id=record.source_id,
                message=record.final_text or record.generated_text,
            )
        except CommentReplyError as exc:
            # ATENDER-9 (m-24849130): one of four kinds, see `replies.failures`. The
            # stored code is for the team; the screen only ever shows the kind's sentence.
            kind = classify_reply_error(exc)
            code = error_code_for(exc, kind)
            logger.info("replies.send draft_id=%s failed kind=%s code=%s", draft_id, kind, code)
            if exc.http_status == 401 or exc.platform_code == 190:
                # QUA-90: an auth refusal means the send did NOT go out — not the same
                # ambiguity as a timeout, so settling failed here is not a lie.
                self._degrade(tenant_id=tenant_id, connection_id=record.connection_id)
            if kind == "unknown":
                # The reply may or may not have posted. Settle NOTHING; a human resolves
                # this by checking Meta directly — and it is never offered a retry.
                return self._repo.mark_send_ambiguous(
                    tenant_id=tenant_id, draft_id=draft_id, error_code=code
                )
            return self._repo.mark_send_failed(
                tenant_id=tenant_id, draft_id=draft_id, error_code=code
            )
        return self._repo.mark_sent(
            tenant_id=tenant_id, draft_id=draft_id, external_reply_id=external_id
        )
