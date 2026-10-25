"""The cheap gate (QUA-22's own criterion: "puerta barata con nombre propio antes de
cualquier paso generativo"). Pure, synchronous, zero network/model dependency — the
whole point of naming it is that a comment must pass THIS, deterministically and
testably, before any generator call is ever made. *"La IA lee el comentario y
responde"* is not an acceptable path; this function is what stands in the way of it.

Comments tranche only (QUA-22's DM tranche stays out entirely — blocked by Advanced
Access + Business Verification, see QUA-20/QUA-69 — this module has no DM-shaped input
at all, not even a disabled one). A comment passes when ALL of these hold:

- `channel` is `'comment'`. A DM-shaped input is refused with a reason that names the
  real blocker, not a generic "wrong channel".
- The comment text is non-empty after stripping — nothing generates a reply to silence.
- No LIVE draft exists for this comment (0080's `uq_reply_draft_live_message`; the gate
  re-checks it so a rejection carries a reason instead of a raw `IntegrityError`).
  Regeneration (`ReplyService.regenerate`) evaluates the gate with this condition off,
  because it replaces the live draft itself.
- It has a signal that earns a public reply — either:
  - `sentiment_label == 'POS'` (QUA-22: "sólo con polaridad positiva") → route
    `sentiment`, the original thank-you reply; or
  - commercial intent (Fase A, m-24789644) under the CURRENT intent version → route
    `commercial`, the grounded reply of Fase B (m-24789645). A signal recorded under an
    older version does not count: the classifier that produced it is no longer the one
    this deployment trusts. When both hold, `commercial` wins — a «¡me encanta! ¿cuánto
    cuesta?» must not reach the ungrounded thank-you generator.
- Nobody already chose to answer it privately: a Fase C followup (`interaction_followups`)
  in status `approved` means a person approved a DM to this comment's author (queued in
  the outbox, maybe already sent, maybe with a public «Te escribimos por DM» notice). A
  second, public reply from the business would duplicate that answer, so the comment
  gets no public draft. An `open` followup (nobody decided yet) or a `discarded` one does
  not block: the person still chooses between the two routes.

**Any comment (ATENDER-4b, m-24848533; QUA-22 amended by the founder 2026-10-23).**
With `any_comment` on (a per-tenant setting, OFF by default until ATENDER-4a's
measurement passes on real comments — `replies.any_comment`), the comment's triage
(`replies.triage`: kind + tone by Claude Haiku) opens a third route, `any_comment`:

- a **complaint** goes there FIRST, before the commercial and thank-you routes — a
  sarcastic «excelente servicio, dos horas esperando» must never get a thank-you, and a
  complaint about a product must not get the sales reply;
- a **praise** or **question** goes there when neither older route took it;
- an **other** (spam, tags between friends) gets no draft in the batch (ATENDER-4a's
  finding); only when the owner asked for this one comment («Responder aquí»,
  `owner_requested`) does it get one.

The route needs a stored analysis row (`has_analysis_row`): `comment_reply_drafts`
demands a sentiment or intent result to stand on (`ck_reply_draft_has_signal`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from qualify_api.sentiment.repository import AnalysisVersion

COMMENT_CHANNEL: Final = "comment"
REQUIRED_SENTIMENT_LABEL: Final = "POS"
#: The `interaction_followups.status` that means "this comment is answered by DM".
FOLLOWUP_APPROVED: Final = "approved"

ROUTE_SENTIMENT: Final = "sentiment"
ROUTE_COMMERCIAL: Final = "commercial"
ROUTE_ANY_COMMENT: Final = "any_comment"

KIND_PRAISE: Final = "praise"
KIND_QUESTION: Final = "question"
KIND_COMPLAINT: Final = "complaint"
KIND_OTHER: Final = "other"


@dataclass(frozen=True)
class TriageEvidence:
    """The comment's triage (`replies.triage.Triage`) as the gate and the draft's
    provenance need it. `cost_usd` is this comment's share of its batch call."""

    kind: str
    sentiment: str
    needs_reply: bool
    model_id: str
    prompt_version: str
    cost_usd: float = 0.0


@dataclass(frozen=True)
class IntentEvidence:
    """The comment's Fase A signal as the gate needs it: whether it is commercial, and
    under which analysis version it was recorded."""

    commercial_intent: bool
    version: AnalysisVersion


@dataclass(frozen=True)
class GateInput:
    channel: str
    # The current-version sentiment label; `""`/None when the comment has none.
    sentiment_label: str | None
    comment_text: str | None
    has_live_draft: bool
    intent: IntentEvidence | None = None
    # The version this deployment classifies under (`intent.CURRENT_INTENT_VERSION`);
    # None means intent is not considered at all (the QUA-22-only path).
    current_intent_version: AnalysisVersion | None = None
    # `interaction_followups.status` of the comment's followup, None if it has none.
    followup_status: str | None = None
    # ATENDER-4b: the per-tenant setting, the comment's triage (None = not triaged) and
    # whether the comment has a stored sentiment/intent row a draft can stand on.
    any_comment: bool = False
    triage: TriageEvidence | None = None
    has_analysis_row: bool = False
    # «Responder aquí»: the owner asked for THIS comment, so an `other` one gets a
    # draft too. Never set by the batch.
    owner_requested: bool = False


@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reason: str
    # Which generator a passing comment goes to (`ROUTE_*`); None when it failed.
    route: str | None = None


def evaluate_gate(gate_input: GateInput) -> GateVerdict:
    """Total and side-effect-free: always returns a verdict, never raises. Order
    matters for the reason a caller sees first, not for correctness — every failing
    condition is independently sufficient to fail the gate."""
    if gate_input.channel != COMMENT_CHANNEL:
        return GateVerdict(
            passed=False,
            reason=(
                f"channel {gate_input.channel!r} is not {COMMENT_CHANNEL!r} — the DM tranche "
                "stays out of this gate entirely, blocked by Advanced Access + Business "
                "Verification (QUA-20/QUA-69), not a generative-gate decision"
            ),
        )
    if gate_input.comment_text is None or not gate_input.comment_text.strip():
        return GateVerdict(passed=False, reason="comment text is empty or whitespace-only")
    if gate_input.has_live_draft:
        return GateVerdict(
            passed=False, reason="a live reply draft already exists for this comment"
        )
    if gate_input.followup_status == FOLLOWUP_APPROVED:
        return GateVerdict(
            passed=False,
            reason=(
                "a person already approved a private message (Fase C followup) for this "
                "comment — it is answered by DM, not publicly"
            ),
        )

    triage = gate_input.triage if gate_input.any_comment else None
    if triage is not None and triage.kind == KIND_COMPLAINT:
        return _any_comment_verdict(gate_input, triage)

    intent = gate_input.intent
    current = gate_input.current_intent_version
    commercial = intent is not None and intent.commercial_intent and current is not None
    if commercial and intent is not None and current is not None and intent.version == current:
        return GateVerdict(
            passed=True,
            reason=(
                f"comment channel, commercial intent under {current.detector_version}, "
                "non-empty text, no live draft, no approved DM followup"
            ),
            route=ROUTE_COMMERCIAL,
        )
    if gate_input.sentiment_label == REQUIRED_SENTIMENT_LABEL:
        return GateVerdict(
            passed=True,
            reason="comment channel, POS sentiment, non-empty text, no live draft",
            route=ROUTE_SENTIMENT,
        )

    if triage is not None and (
        triage.kind in (KIND_PRAISE, KIND_QUESTION) or gate_input.owner_requested
    ):
        return _any_comment_verdict(gate_input, triage)
    if triage is not None:
        return GateVerdict(
            passed=False,
            reason=(
                f"triage {triage.prompt_version} says {triage.kind!r} (not addressed to the "
                "business) — no draft unless the owner asks for this comment"
            ),
        )

    sentiment = f"sentiment {gate_input.sentiment_label or 'none'!r} is not 'POS'"
    if commercial and intent is not None and current is not None:
        # Commercial, but recorded by a classifier this deployment no longer runs.
        reason = (
            f"{sentiment} and the commercial-intent signal is from "
            f"{intent.version.detector_version}/{intent.version.pipeline_version}, not the "
            f"current {current.detector_version}/{current.pipeline_version} — re-run intent"
        )
    else:
        reason = (
            f"{sentiment} and no current commercial intent — only positive (QUA-22) or "
            "commercial (m-24789645) comments get an assisted draft"
        )
    return GateVerdict(passed=False, reason=reason)


def _any_comment_verdict(gate_input: GateInput, triage: TriageEvidence) -> GateVerdict:
    """The `any_comment` route, or its refusal when there is no row to stand on."""
    if not gate_input.has_analysis_row:
        return GateVerdict(
            passed=False,
            reason=(
                f"triage says {triage.kind!r} but the comment has no stored sentiment or "
                "intent row yet — the automatic analysis has not reached it"
            ),
        )
    who = "owner asked, " if gate_input.owner_requested else ""
    return GateVerdict(
        passed=True,
        reason=(
            f"comment channel, {who}triage {triage.prompt_version}/{triage.model_id}: "
            f"kind {triage.kind!r}, tone {triage.sentiment!r}, non-empty text, no live "
            "draft, no approved DM followup"
        ),
        route=ROUTE_ANY_COMMENT,
    )
