"""«Consultas desde comentarios» (m-24789646, PR 3): what the Conversaciones screen does
with a commercial query found in Interacciones — the one facade the UI talks to.

- **Opening, automatically (B1).** After an intent analysis, `open_from_intents` opens a
  followup for each commercial comment that has none, provenance included (the exact
  `comment_intent_results` row), and writes its draft. Only comments of the last 7 days:
  older ones cannot get a private reply any more, and a person who already writes by DM
  is answered there. A person can still open any comment by hand.
- **Opening, by hand.** «Responder por DM» in Interacciones (`open_manual`): same row
  (idempotent per comment), same draft.
- **The draft** is a `conversation_drafts` row of the ORIGIN message (its comment thread),
  written by the same generator as Conversaciones' «Sugerir respuesta», told where it
  goes (a DM answering a public comment on a given post, with the intents detected). It
  uses only the tenant's validated facts and says «requiere revisión» when it could not
  ground something. Writing it never blocks opening: a failed draft leaves the card with
  «Generar borrador».
- **Cards** (`list_open`): the comment, its author, the post, the intents with their
  reliability, the route available NOW (or why none) and the pending draft — one batch
  read for the origins and one for the drafts.
- **Approving** sends through `FollowupService.approve_and_queue` with a
  `HumanApproval` that carries the draft id; the draft is then decided `accepted` (sent as
  written) or `edited` (with the text sent), so `generated_text` vs `final_text` is the
  stored draft→sent diff (B2). Regenerating discards the pending draft and writes a new
  one; discarding the followup discards its draft too.
- **The public notice** (PR 4, B4): when `public_notice` is on, a comment's card offers
  it (`notice_available`) and the person approves its text together with the message;
  it is posted later, only after the message is confirmed sent (`followups.notice`).

Nothing here talks to a channel: the only way out stays the outbox.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from qualify_api.conversations.drafts import (
    ConversationDraft,
    DraftPending,
    DraftRepository,
    DraftStatus,
    InvalidDraftTransition,
    new_draft,
)
from qualify_api.conversations.outbox import HumanApproval
from qualify_api.conversations.repository import MessageRecord
from qualify_api.conversations.suggest import DraftGenerator, GroundingProvider, needs_review
from qualify_api.conversations.window import PRIVATE_REPLY_WINDOW
from qualify_api.followups.origins import CommercialIntentReader, OriginMessage, OriginReader
from qualify_api.followups.repository import (
    Followup,
    FollowupOpening,
    FollowupRepository,
    FollowupTrigger,
    UnknownFollowup,
)
from qualify_api.followups.service import FollowupService, SendOptions
from qualify_api.intent.contract import (
    COMMERCIAL_CLASSES,
    INTENT_CLASS_LABELS,
    IntentClass,
    IntentSignal,
)
from qualify_api.sentiment.repository import AnalysisVersion

logger = logging.getLogger("qualify_api.followups.workspace")

# `conversation_drafts.gate_reason` of a followup's draft.
GATE_COMMERCIAL_COMMENT: Final = "commercial_comment"
GATE_MANUAL_FOLLOWUP: Final = "manual_followup"
# How many followups one analysis may open (and draft) at once.
OPEN_BATCH: Final = 20

SURFACE_LABELS: Final[Mapping[str, str]] = {
    "REELS": "tu Reel",
    "FEED": "tu publicación",
    "STORY": "tu historia",
}

SignalsReader = Callable[[UUID, Sequence[UUID]], Mapping[UUID, IntentSignal]]
ReliabilityReader = Callable[[], Mapping[IntentClass, bool]]


@dataclass(frozen=True)
class IntentChip:
    label: str
    confidence: float
    commercial: bool
    reliable: bool


@dataclass(frozen=True)
class FollowupCard:
    followup: Followup
    origin: OriginMessage
    options: SendOptions
    intents: tuple[IntentChip, ...]
    draft: ConversationDraft | None
    # Whether the card may offer the public notice under the comment (PR 4).
    notice_available: bool = False


@dataclass(frozen=True)
class OpenSummary:
    opened: int
    drafted: int
    draft_failed: int


def _utcnow() -> datetime:
    return datetime.now(UTC)


def surface_label(media_product_type: str | None) -> str:
    return SURFACE_LABELS.get((media_product_type or "").upper(), "tu publicación")


def draft_context(origin: OriginMessage, intents: Sequence[IntentChip]) -> str:
    """What the generator must know that the comment alone does not say."""
    where = surface_label(origin.media_product_type)
    lines = [
        f"La persona dejó un comentario PÚBLICO en {where}"
        + (f" («{origin.media_caption.strip()[:200]}»)" if origin.media_caption else "")
        + ". Tu respuesta le llega por MENSAJE PRIVADO (DM): puede que nunca le haya "
        "escrito al negocio, así que saluda brevemente y responde a lo que preguntó.",
    ]
    commercial = [chip.label for chip in intents if chip.commercial]
    if commercial:
        lines.append("Intención comercial detectada: " + ", ".join(commercial) + ".")
    return "\n".join(lines)


def _as_message(origin: OriginMessage) -> MessageRecord:
    return MessageRecord(
        id=origin.id,
        thread_id=origin.thread_id,
        connection_id=origin.connection_id,
        external_message_id=origin.external_message_id,
        direction="inbound",
        author_external_id=origin.author_external_id,
        author_username=origin.author_username,
        text=origin.text,
        posted_at=origin.posted_at,
        ingested_at=origin.posted_at or _utcnow(),
        delivery_status=None,
        media_type=None,
    )


def intent_chips(
    signal: IntentSignal | None, reliable: Mapping[IntentClass, bool]
) -> tuple[IntentChip, ...]:
    if signal is None:
        return ()
    ranked = sorted(
        signal.classes.items(), key=lambda item: (-item[1], INTENT_CLASS_LABELS[item[0]])
    )
    return tuple(
        IntentChip(
            label=INTENT_CLASS_LABELS[cls],
            confidence=confidence,
            commercial=cls in COMMERCIAL_CLASSES,
            reliable=reliable.get(cls, False),
        )
        for cls, confidence in ranked
    )


class FollowupWorkspace:
    def __init__(
        self,
        *,
        service: FollowupService,
        followups: FollowupRepository,
        origins: OriginReader,
        commercial: CommercialIntentReader,
        drafts: DraftRepository,
        generator: DraftGenerator,
        grounding: GroundingProvider,
        signals: SignalsReader,
        reliability: ReliabilityReader,
        intent_version: AnalysisVersion,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._service = service
        self._followups = followups
        self._origins = origins
        self._commercial = commercial
        self._drafts = drafts
        self._generator = generator
        self._grounding = grounding
        self._signals = signals
        self._reliability = reliability
        self._intent_version = intent_version
        self._clock = clock

    # -- opening ------------------------------------------------------------------------

    def open_from_intents(self, *, tenant_id: UUID, connection_id: UUID) -> OpenSummary:
        """B1: a followup (and its draft) for every recent commercial comment without one."""
        flagged = self._commercial.unfollowed(
            tenant_id=tenant_id,
            connection_id=connection_id,
            version=self._intent_version,
            posted_since=self._clock() - PRIVATE_REPLY_WINDOW,
            limit=OPEN_BATCH,
        )
        opened = drafted = failed = 0
        for flag in flagged:
            opening = self._service.open_for_interaction(
                tenant_id=tenant_id,
                origin_message_id=flag.message_id,
                trigger=FollowupTrigger.INTENT,
                intent_result_id=flag.intent_result_id,
            )
            if not opening.created:
                continue
            opened += 1
            if self._try_draft(tenant_id, opening.followup, GATE_COMMERCIAL_COMMENT):
                drafted += 1
            else:
                failed += 1
        if opened:
            logger.info(
                "followups.opened tenant_id=%s connection_id=%s opened=%d drafted=%d failed=%d",
                tenant_id,
                connection_id,
                opened,
                drafted,
                failed,
            )
        return OpenSummary(opened=opened, drafted=drafted, draft_failed=failed)

    def open_manual(self, *, tenant_id: UUID, origin_message_id: UUID) -> FollowupOpening:
        """«Responder por DM»: the comment's followup (existing or new), with a draft when
        it has none. Raises `UnknownOrigin` / `OriginNotSupported`."""
        opening = self._service.open_for_interaction(
            tenant_id=tenant_id,
            origin_message_id=origin_message_id,
            trigger=FollowupTrigger.MANUAL,
        )
        if self._pending_draft(tenant_id, opening.followup) is None:
            self._try_draft(tenant_id, opening.followup, GATE_MANUAL_FOLLOWUP)
        return opening

    # -- cards --------------------------------------------------------------------------

    def list_open(
        self, *, tenant_id: UUID, connection_id: UUID | None = None
    ) -> list[FollowupCard]:
        followups = self._followups.list_open(tenant_id=tenant_id, connection_id=connection_id)
        if not followups:
            return []
        message_ids = [f.origin_message_id for f in followups]
        origins = self._origins.get_many(tenant_id=tenant_id, message_ids=message_ids)
        signals = self._signals(tenant_id, message_ids)
        reliable = self._reliability() if signals else {}
        drafts = self._pending_by_message(tenant_id)
        now = self._clock()
        cards: list[FollowupCard] = []
        for followup in followups:
            origin = origins.get(followup.origin_message_id)
            if origin is None:  # the message is gone from this tenant's view
                continue
            cards.append(
                FollowupCard(
                    followup=followup,
                    origin=origin,
                    options=self._service.options_from_origin(followup, origin, now),
                    intents=intent_chips(signals.get(origin.id), reliable),
                    draft=drafts.get(origin.id),
                    notice_available=self._service.public_notice_available(followup),
                )
            )
        return cards

    # -- drafts -------------------------------------------------------------------------

    def suggest(self, *, tenant_id: UUID, followup_id: UUID) -> ConversationDraft:
        """The pending draft, or a new one. Raises `UnknownFollowup` and the generator's
        errors (`ClaudeToolError`, `MissingAPIKey`)."""
        followup = self._followup(tenant_id, followup_id)
        pending = self._pending_draft(tenant_id, followup)
        if pending is not None:
            return pending
        return self._write_draft(tenant_id, followup, self._gate_reason(followup))

    def regenerate(self, *, tenant_id: UUID, followup_id: UUID, user_id: UUID) -> ConversationDraft:
        """Discard the pending draft (kept, as `discarded`) and write a new one."""
        followup = self._followup(tenant_id, followup_id)
        pending = self._pending_draft(tenant_id, followup)
        if pending is not None:
            self._decide(tenant_id, pending, DraftStatus.DISCARDED, None, user_id)
        return self._write_draft(tenant_id, followup, self._gate_reason(followup))

    # -- deciding -----------------------------------------------------------------------

    def approve(
        self,
        *,
        tenant_id: UUID,
        followup_id: UUID,
        text: str,
        user_id: UUID,
        draft_id: UUID | None = None,
        notice_text: str | None = None,
    ) -> Followup:
        """Queue `text` (the draft as written or edited) with this person's approval, then
        record the draft's verdict. `notice_text` is the public notice the same person
        approved with it (None: no notice). Raises what `FollowupService.approve_and_queue`
        raises; a draft that is not this followup's pending one is ignored (the send still
        happens, unlinked) rather than mis-recorded."""
        followup = self._followup(tenant_id, followup_id)
        pending = self._pending_draft(tenant_id, followup)
        draft = pending if pending is not None and pending.id == draft_id else None
        approved = self._service.approve_and_queue(
            tenant_id=tenant_id,
            followup_id=followup_id,
            text=text,
            approval=HumanApproval(
                user_id=user_id,
                approved_at=self._clock(),
                draft_id=draft.id if draft else None,
            ),
            notice_text=notice_text,
        )
        if draft is not None:
            sent = text.strip()
            if sent == draft.generated_text.strip():
                self._decide(tenant_id, draft, DraftStatus.ACCEPTED, None, user_id)
            else:
                self._decide(tenant_id, draft, DraftStatus.EDITED, sent, user_id)
        return approved

    def discard(self, *, tenant_id: UUID, followup_id: UUID, user_id: UUID) -> Followup:
        followup = self._followup(tenant_id, followup_id)
        discarded = self._service.discard(
            tenant_id=tenant_id, followup_id=followup_id, user_id=user_id
        )
        pending = self._pending_draft(tenant_id, followup)
        if pending is not None:
            self._decide(tenant_id, pending, DraftStatus.DISCARDED, None, user_id)
        return discarded

    # -- plumbing -----------------------------------------------------------------------

    def _followup(self, tenant_id: UUID, followup_id: UUID) -> Followup:
        followup = self._followups.get(tenant_id=tenant_id, followup_id=followup_id)
        if followup is None:
            raise UnknownFollowup(str(followup_id))
        return followup

    @staticmethod
    def _gate_reason(followup: Followup) -> str:
        if followup.trigger is FollowupTrigger.INTENT:
            return GATE_COMMERCIAL_COMMENT
        return GATE_MANUAL_FOLLOWUP

    def _pending_by_message(self, tenant_id: UUID) -> dict[UUID, ConversationDraft]:
        latest: dict[UUID, ConversationDraft] = {}
        for draft in self._drafts.list_pending(tenant_id=tenant_id):
            latest[draft.message_id] = draft  # oldest first: the newest wins
        return latest

    def _pending_draft(self, tenant_id: UUID, followup: Followup) -> ConversationDraft | None:
        origin = self._origins.get(tenant_id=tenant_id, message_id=followup.origin_message_id)
        if origin is None:
            return None
        pending = [
            d
            for d in self._drafts.list_pending(tenant_id=tenant_id, thread_id=origin.thread_id)
            if d.message_id == origin.id
        ]
        return pending[-1] if pending else None

    def _try_draft(self, tenant_id: UUID, followup: Followup, gate_reason: str) -> bool:
        try:
            self._write_draft(tenant_id, followup, gate_reason)
        except Exception as exc:  # noqa: BLE001 — a draft never blocks opening
            logger.warning(
                "followups.draft_failed followup_id=%s error=%s", followup.id, type(exc).__name__
            )
            return False
        return True

    def _write_draft(
        self, tenant_id: UUID, followup: Followup, gate_reason: str
    ) -> ConversationDraft:
        origin = self._origins.get(tenant_id=tenant_id, message_id=followup.origin_message_id)
        if origin is None:
            raise UnknownFollowup(str(followup.id))
        signal = self._signals(tenant_id, [origin.id]).get(origin.id)
        chips = intent_chips(signal, self._reliability() if signal else {})
        grounding = self._grounding(tenant_id, origin.connection_id)
        proposal = self._generator.propose(
            grounding=grounding,
            messages=[_as_message(origin)],
            counterpart=origin.author_username or "Cliente",
            context=draft_context(origin, chips),
        )
        draft = new_draft(
            tenant_id=tenant_id,
            thread_id=origin.thread_id,
            message_id=origin.id,
            generator_version=self._generator.version,
            generated_text=proposal.text,
            gate_reason=gate_reason,
            needs_review=needs_review(proposal, grounding),
            now=self._clock(),
            model_id=proposal.model_id,
            model_revision=proposal.model_revision,
            input_tokens=proposal.input_tokens,
            output_tokens=proposal.output_tokens,
            cost_usd=proposal.cost_usd,
            grounding={
                **grounding.as_record(),
                "unsupported_claims": list(proposal.unsupported_claims),
                "followup_id": str(followup.id),
            },
        )
        try:
            return self._drafts.create(draft)
        except DraftPending:
            existing = self._pending_draft(tenant_id, followup)
            if existing is None:
                raise
            return existing

    def _decide(
        self,
        tenant_id: UUID,
        draft: ConversationDraft,
        status: DraftStatus,
        final_text: str | None,
        user_id: UUID,
    ) -> None:
        try:
            self._drafts.decide(
                tenant_id=tenant_id,
                draft_id=draft.id,
                status=status,
                final_text=final_text,
                decided_by_user_id=user_id,
                now=self._clock(),
            )
        except InvalidDraftTransition:
            # Someone decided it first; the send (if any) already went through the outbox.
            logger.warning("followups.draft_decided_concurrently draft_id=%s", draft.id)
