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

No scheduler, no automatic run chained after `sentiment.analyze_pending_comments()` —
same manual-trigger-only posture that module's own docstring documents. This module
does not know when it is called, only what to do when it is.
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from qualify_api.assisted.approval import ApprovalRequired, HumanApproval
from qualify_api.assisted.grounding import Grounding, GroundingProvider
from qualify_api.intent.contract import IntentClass
from qualify_api.intent.reliability import class_reliability
from qualify_api.replies.client import CommentReplyClient, CommentReplyError
from qualify_api.replies.gate import (
    ROUTE_COMMERCIAL,
    GateInput,
    GateVerdict,
    IntentEvidence,
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
    ) -> None:
        """`version` is the sentiment version (QUA-22's POS path, `provider`).
        `intent_version` turns on Fase B (m-24789645): commercial comments under it are
        drafted by `grounded_generator` over `grounding` — both required for that route,
        which fails loudly without them rather than falling back to the ungrounded one."""
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

    # -- generation ---------------------------------------------------------------------

    def _gate_input(self, candidate: CandidateComment, *, has_live_draft: bool) -> GateInput:
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
        )

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
    ) -> _Composed:
        """The one place a generator is called — only ever for a verdict that passed."""
        if verdict.route != ROUTE_COMMERCIAL:
            text = self._sentiment_provider().draft_reply(
                comment_text=candidate.text, business_name=self._business_name
            )
            provenance = (
                DraftProvenance(intent_result_id=candidate.intent_result_id)
                if candidate.intent_result_id is not None
                else None
            )
            return _Composed(text, self._generator_version, provenance)

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

    def generate_drafts(self, *, tenant_id: UUID, connection_id: UUID) -> GenerationSummary:
        """The gate runs on EVERY candidate before the generator is ever called — see
        `gate.py`'s module docstring. A rejected candidate produces no draft and no
        generator call; nothing records a rejection, only what passed does. A comment
        whose earlier draft was discarded is not a candidate here (`regenerate` is)."""
        candidates = self._repo.list_reply_candidates(
            tenant_id=tenant_id,
            connection_id=connection_id,
            sentiment_version=self._version,
            intent_version=self._intent_version,
        )
        cache = _BatchCache()
        created = 0
        rejected = 0
        for candidate in candidates:
            live = self._repo.get_live_draft(tenant_id=tenant_id, message_id=candidate.message_id)
            verdict = evaluate_gate(self._gate_input(candidate, has_live_draft=live is not None))
            if not verdict.passed:
                rejected += 1
                continue
            composed = self._compose(
                tenant_id=tenant_id,
                connection_id=connection_id,
                candidate=candidate,
                verdict=verdict,
                cache=cache,
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
        verdict = evaluate_gate(self._gate_input(candidate, has_live_draft=False))
        if not verdict.passed:
            raise RegenerationRefused(verdict.reason)
        composed = self._compose(
            tenant_id=tenant_id,
            connection_id=old.connection_id,
            candidate=candidate,
            verdict=verdict,
            cache=_BatchCache(),
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
            if exc.http_status == 401 or exc.platform_code == 190:
                # QUA-90: an auth refusal means the send did NOT go out — not the same
                # ambiguity as a timeout, so settling failed here is not a lie.
                self._degrade(tenant_id=tenant_id, connection_id=record.connection_id)
                return self._repo.mark_send_failed(
                    tenant_id=tenant_id, draft_id=draft_id, error_code=f"auth:{exc.platform_code}"
                )
            if exc.is_ambiguous:
                # Transport failure — the reply may or may not have posted. Settle
                # NOTHING; a human resolves this by checking Meta directly.
                return self._repo.mark_send_ambiguous(
                    tenant_id=tenant_id, draft_id=draft_id, error_code=str(exc)
                )
            return self._repo.mark_send_failed(
                tenant_id=tenant_id,
                draft_id=draft_id,
                error_code=(
                    f"platform:{exc.platform_code}" if exc.platform_code is not None else "unknown"
                ),
            )
        return self._repo.mark_sent(
            tenant_id=tenant_id, draft_id=draft_id, external_reply_id=external_id
        )
