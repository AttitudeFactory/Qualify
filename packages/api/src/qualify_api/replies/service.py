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

No scheduler, no automatic run chained after `sentiment.analyze_pending_comments()` —
same manual-trigger-only posture that module's own docstring documents. This module
does not know when it is called, only what to do when it is.
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from qualify_api.assisted.approval import ApprovalRequired, HumanApproval
from qualify_api.replies.client import CommentReplyClient, CommentReplyError
from qualify_api.replies.gate import GateInput, evaluate_gate
from qualify_api.replies.repository import DraftRecord, ReplyRepository
from qualify_api.sentiment.repository import AnalysisVersion

if TYPE_CHECKING:
    # `qualify_models` lives in the `ml` dependency group, deliberately excluded from
    # the default install — same TYPE_CHECKING-only reasoning `sentiment/service.py`
    # documents for `SentimentProvider`.
    from qualify_models.providers import ReplyDraftProvider

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
    ) -> None:
        self._repo = repository
        self._version = version
        self._generator_version = generator_version
        self._provider = provider
        self._clients = client_factory
        self._business_name = business_name
        self._degrade = connection_degrader or _no_op_degrader

    def generate_drafts(self, *, tenant_id: UUID, connection_id: UUID) -> GenerationSummary:
        """The gate runs on EVERY candidate before the generator is ever called — see
        `gate.py`'s module docstring. A rejected candidate produces no draft and no
        generator call; nothing records a rejection, only what passed does."""
        provider = self._provider
        if provider is None:
            from qualify_models.providers import HFInferenceReplyDraftProvider  # noqa: PLC0415

            provider = HFInferenceReplyDraftProvider()

        candidates = self._repo.list_positive_comments_without_draft(
            tenant_id=tenant_id, connection_id=connection_id, version=self._version
        )
        created = 0
        rejected = 0
        for candidate in candidates:
            verdict = evaluate_gate(
                GateInput(
                    channel="comment",
                    sentiment_label=candidate.sentiment_label,
                    comment_text=candidate.text,
                    has_existing_draft=self._repo.has_draft(
                        tenant_id=tenant_id, message_id=candidate.message_id
                    ),
                )
            )
            if not verdict.passed:
                rejected += 1
                continue
            text = provider.draft_reply(
                comment_text=candidate.text, business_name=self._business_name
            )
            result = self._repo.create_draft(
                tenant_id=tenant_id,
                connection_id=connection_id,
                candidate=candidate,
                gate_reason=verdict.reason,
                generator_version=self._generator_version,
                generated_text=text,
            )
            if result is not None:
                created += 1
        return GenerationSummary(
            candidates_seen=len(candidates), drafts_created=created, gate_rejected=rejected
        )

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
