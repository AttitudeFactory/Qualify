"""The cheap gate (QUA-22's own criterion: "puerta barata con nombre propio antes de
cualquier paso generativo"). Pure, synchronous, zero network/model dependency — the
whole point of naming it is that a comment must pass THIS, deterministically and
testably, before any generator call is ever made. *"La IA lee el comentario y
responde"* is not an acceptable path; this function is what stands in the way of it.

v1 rule, comments tranche only (QUA-22's DM tranche stays out entirely — blocked by
Advanced Access + Business Verification, see QUA-20/QUA-69 — this module has no
DM-shaped input at all, not even a disabled one):

- `channel` must be `'comment'`. A DM-shaped input is refused with a reason that names
  the real blocker, not a generic "wrong channel".
- `sentiment_label` must be `'POS'` — QUA-22's own criterion, verbatim: "los
  comentarios públicos entran después y sólo con polaridad positiva".
- The comment text must be non-empty after stripping — same restriction QUA-21 AC5
  already applies to sentiment analysis itself (`sentiment/service.py`): nothing
  generates a reply to silence.
- No draft may already exist for this comment — `UNIQUE(message_id)` enforces this at
  the DB layer regardless; the gate re-checks it so a rejection carries a reason
  instead of surfacing as a raw `IntegrityError`.
"""

from __future__ import annotations

from dataclasses import dataclass

COMMENT_CHANNEL = "comment"
REQUIRED_SENTIMENT_LABEL = "POS"


@dataclass(frozen=True)
class GateInput:
    channel: str
    sentiment_label: str
    comment_text: str | None
    has_existing_draft: bool


@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reason: str


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
    if gate_input.has_existing_draft:
        return GateVerdict(passed=False, reason="a reply draft already exists for this comment")
    if gate_input.sentiment_label != REQUIRED_SENTIMENT_LABEL:
        return GateVerdict(
            passed=False,
            reason=(
                f"sentiment {gate_input.sentiment_label!r} is not "
                f"{REQUIRED_SENTIMENT_LABEL!r} — only positive-sentiment comments get an "
                "assisted draft (QUA-22)"
            ),
        )
    if gate_input.comment_text is None or not gate_input.comment_text.strip():
        return GateVerdict(passed=False, reason="comment text is empty or whitespace-only")
    return GateVerdict(
        passed=True,
        reason="comment channel, POS sentiment, non-empty text, no existing draft",
    )
