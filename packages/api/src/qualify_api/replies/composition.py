"""Production assembly for the replies module (QUA-22, comments tranche) — the
analogue of `publishing/composition.py`. Same shape: `ReplyService` takes a
`client_factory` and resolves credentials PER CALL inside `send()`, so, like
`PublishService` (and unlike `InboxService`), one `@cache`d service instance is safe —
nothing here holds a per-request credential until `send()` actually resolves one.
"""

from __future__ import annotations

from functools import cache
from uuid import UUID

from qualify_api.assisted.approval import HumanApproval
from qualify_api.assisted.grounding import catalog_grounding_for
from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.composition import degrade_connection_on_auth_error
from qualify_api.connections.credential_reader import DbCredentialReader
from qualify_api.connections.crypto import DevEncryptor, Encryptor
from qualify_api.connections.resolver import InjectingCredentialResolver
from qualify_api.conversations.suggest import ClaudeDraftGenerator
from qualify_api.replies.claude_drafts import DRAFT_MODEL, ClaudeReplyDraftProvider
from qualify_api.replies.client import CommentReplyClient, HttpCommentReplyClient
from qualify_api.replies.public_drafts import (
    PUBLIC_GENERATOR_VERSION_PREFIX,
    PUBLIC_SYSTEM_PROMPT,
)
from qualify_api.replies.repository import DraftRecord, PostgresReplyRepository
from qualify_api.replies.service import DecisionResult, GenerationSummary, ReplyService


class ResolverReplyClientFactory:
    """One authenticated client per send — resolved at send time, same seam
    `ResolverPublishClientFactory` already establishes for publishing. Nothing here
    ever holds a token."""

    def __init__(self, settings: MetaOAuthSettings, encryptor: Encryptor) -> None:
        self._settings = settings
        self._encryptor = encryptor

    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> CommentReplyClient:
        resolver = InjectingCredentialResolver(DbCredentialReader(tenant_id), self._encryptor)
        graph = await resolver.client_for(connection_id, scheme=self._settings.graph_auth_scheme)
        return HttpCommentReplyClient(graph_client=graph, graph_url=self._settings.graph_url)


@cache
def current_reply_generator_version() -> str:
    """The generator version this deployment stamps on every draft — provenance, not a
    live pointer: bumping it changes what a NEW draft records, never a past one (no
    UPDATE grant would let it, even if code tried). `qua22.2` = drafts by Claude
    (QUA-128); `qua22.1` drafts were written by the HF provider."""
    return f"qua22.2:{DRAFT_MODEL.model_id}"


def public_reply_generator() -> ClaudeDraftGenerator:
    """Fase B's grounded generator (m-24789645): the private-conversation tool contract
    with the PUBLIC reply prompt and its own version (`m24789645.1:<model>`)."""
    return ClaudeDraftGenerator(
        system_prompt=PUBLIC_SYSTEM_PROMPT, version_prefix=PUBLIC_GENERATOR_VERSION_PREFIX
    )


@cache
def production_reply_service() -> ReplyService:
    from qualify_api.intent.composition import CURRENT_INTENT_VERSION  # noqa: PLC0415
    from qualify_api.sentiment.composition import current_analysis_version  # noqa: PLC0415

    settings = MetaOAuthSettings.from_env()
    return ReplyService(
        repository=PostgresReplyRepository(),
        version=current_analysis_version(),
        generator_version=current_reply_generator_version(),
        provider=ClaudeReplyDraftProvider(),
        client_factory=ResolverReplyClientFactory(settings, DevEncryptor()),
        connection_degrader=degrade_connection_on_auth_error,
        intent_version=CURRENT_INTENT_VERSION,
        grounded_generator=public_reply_generator(),
        # The comment's own connection → its brand → that brand's active catalog, read
        # under the tenant's RLS (`tenant_session`): never another tenant's products.
        grounding=catalog_grounding_for,
    )


def generate_drafts(*, tenant_id: UUID, connection_id: UUID) -> GenerationSummary:
    """The published seam for Reflex's "generar borradores" trigger — manual, same
    posture `sentiment.composition.analyze_pending_comments` documents for its own
    manual trigger: nothing here runs on a schedule."""
    return production_reply_service().generate_drafts(
        tenant_id=tenant_id, connection_id=connection_id
    )


def regenerate_draft(*, tenant_id: UUID, draft_id: UUID, user_id: UUID) -> DraftRecord:
    """«Regenerar» (m-24789645; the button on each draft card in `/inbox`): replaces a
    `proposed` draft with a fresh one, through the gate. Never sends."""
    return production_reply_service().regenerate(
        tenant_id=tenant_id, draft_id=draft_id, user_id=user_id
    )


def list_pending_drafts(*, tenant_id: UUID, connection_id: UUID) -> tuple[DraftRecord, ...]:
    return production_reply_service().list_pending_drafts(
        tenant_id=tenant_id, connection_id=connection_id
    )


def decide_draft(
    *,
    tenant_id: UUID,
    draft_id: UUID,
    decision: str,
    final_text: str | None,
    decided_by_user_id: UUID,
) -> DecisionResult:
    return production_reply_service().decide(
        tenant_id=tenant_id,
        draft_id=draft_id,
        decision=decision,
        final_text=final_text,
        decided_by_user_id=decided_by_user_id,
    )


async def send_draft(*, tenant_id: UUID, draft_id: UUID, approval: HumanApproval) -> DraftRecord:
    """Posts the approved reply publicly. `approval` is required and must name this draft
    (`ApprovalRequired` otherwise) — m-24789645, criterion 1."""
    return await production_reply_service().send(
        tenant_id=tenant_id, draft_id=draft_id, approval=approval
    )


def list_retryable_drafts(*, tenant_id: UUID, connection_id: UUID) -> tuple[DraftRecord, ...]:
    """ATENDER-9 (m-24849130): replies that did not go out for a passing reason."""
    return production_reply_service().list_retryable_drafts(
        tenant_id=tenant_id, connection_id=connection_id
    )


def prepare_retry(*, tenant_id: UUID, draft_id: UUID, user_id: UUID) -> DraftRecord:
    """«Reintentar», step one: a new approved draft with the same text. Never sends —
    the caller sends it with `send_draft(..., approval=...)` naming the new draft."""
    return production_reply_service().prepare_retry(
        tenant_id=tenant_id, draft_id=draft_id, user_id=user_id
    )
