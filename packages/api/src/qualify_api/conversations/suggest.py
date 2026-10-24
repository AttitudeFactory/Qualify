"""Assisted replies for private conversations — generation and decision (QUA-226, E4).

What a person sees as «Sugerir respuesta»: one draft, written by Claude Haiku, grounded
ONLY in what the tenant has validated (the business name, the product catalog with its
prices) plus the conversation itself. The person then accepts, edits or discards it; a
send is still, and only, `ConversationService.reply(..., approval=HumanApproval(draft_id))`
— this module never queues anything.

## The three disciplines (QUA-22's, kept)

1. **Gate before generator.** A draft is asked for only when the conversation's last
   message is an inbound with text and the 24 h window is open. `gate()` answers with a
   reason either way and the reason is stamped on the draft (`gate_reason`).
2. **Grounding is explicit and recorded.** The generator receives a `Grounding` (facts
   the tenant owns) and the draft stores it verbatim, so a reviewer can see what the
   model was allowed to say. The model is told to use nothing else; it must also report
   whether it did. `needs_review` is True when it says it could not ground a claim OR
   when a cheap local check disagrees (a price-looking token in the reply with no price
   in the grounding). The grounding types (`Grounding`, `GroundedProduct`,
   `grounding_from_products`) live in `qualify_api.assisted.grounding` since m-24789645
   — shared with the public comment drafts — and are re-exported here unchanged.
3. **Cost is provenance.** Model id, revision, tokens and USD are written on the row
   (QUA-144), computed by `claude_tools.Meter` from the response, never estimated.

## A tapped option is context (m-24789472, PR 2)

When the message the draft answers was TAPPED — an Ice Breaker, a quick reply, a button,
a menu item (`messages.choice_kind` / `choice_payload`, 0082) — the generator receives it
through the existing `context` slot (`choices.choice_context`: «La persona tocó la
pregunta inicial «¿Cuánto cuesta?» (QF_PRECIO: Precio)…»), so the reply answers the
option, not a sentence the person never wrote. The draft records it under
`grounding["choice"]` — what the model was told, per row. The system prompt, the tool and
`propose`'s signature are unchanged (followups already fill the same slot), so
`GENERATOR_VERSION` stays: the version names the generator, the row names its input.
Still a draft: nothing here answers a tap on its own.

## Why strict tool use

The model answers through one `strict` tool (`propose_reply`) so the three fields —
the reply, whether it used only the given facts, the claims it could not ground — come
back typed, not parsed out of prose. Haiku 5.5 thinks (`effort: low`), so the tool choice
is `auto` and the call is checked for the tool having been used (`claude_tools.
forced_or_auto`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from uuid import UUID

from qualify_api.assisted.grounding import (
    PRICE_TOKEN,
    GroundedProduct,
    Grounding,
    GroundingProvider,
    grounding_from_products,
)
from qualify_api.claude_tools import (
    ClaudeToolError,
    ClientFactory,
    Meter,
    ModelConfig,
    api_key_from_env,
    create_turn,
    default_client,
    forced_or_auto,
    strict_tool,
    tool_uses,
)
from qualify_api.conversations.choices import choice_context
from qualify_api.conversations.drafts import (
    ConversationDraft,
    DraftPending,
    DraftRepository,
    DraftStatus,
    new_draft,
)
from qualify_api.conversations.repository import (
    ConversationRepository,
    MessageRecord,
    ThreadRecord,
)
from qualify_api.conversations.window import window_state

logger = logging.getLogger("qualify_api.conversations.suggest")

DRAFT_MODEL: Final = ModelConfig("claude-haiku-5-5", effort="low")
GENERATOR_VERSION: Final = f"qua226.1:{DRAFT_MODEL.model_id}"

#: Room for Haiku's (low-effort) thinking plus the tool call. Thinking counts against
#: `max_tokens`, so this is far above the visible reply's length on purpose.
MAX_TOKENS: Final = 2048
#: How much of the conversation the model sees: the newest messages, oldest first.
CONTEXT_MESSAGES: Final = 12
#: A reply longer than this is cut by the channel anyway (Instagram: 1000 chars).
MAX_DRAFT_CHARS: Final = 1000

# Gate reasons — stamped on the draft (`gate_reason`) or returned as the refusal.
GATE_OK: Final = "inbound_text"
GATE_NO_MESSAGES: Final = "no_messages"
GATE_LAST_OUTBOUND: Final = "last_message_outbound"
GATE_NO_TEXT: Final = "inbound_without_text"
GATE_WINDOW_CLOSED: Final = "window_closed"
GATE_PENDING: Final = "draft_pending"

TOOL_NAME: Final = "propose_reply"

SYSTEM_PROMPT: Final = (
    "Eres quien responde mensajes privados de Instagram en nombre de un negocio. Te llega "
    "una conversación (los mensajes del cliente y los que el negocio ya envió) y una lista "
    "de HECHOS VALIDADOS del negocio: su nombre y, si los hay, sus productos con precio.\n\n"
    "Escribe UNA respuesta al último mensaje del cliente: breve (una a tres frases), cálida "
    "y natural, en el idioma del cliente (normalmente español), sin saludos repetidos si la "
    "conversación ya está en curso. Puedes afirmar SOLO lo que digan los hechos validados o "
    "el propio hilo. Nunca inventes precios, promociones, horarios, direcciones, plazos de "
    "envío ni disponibilidad: si el cliente pregunta algo que los hechos no cubren, "
    "responde con amabilidad que lo confirmas y se lo dices enseguida, y repórtalo como "
    "una afirmación no respaldada. Máximo un emoji. Nada de hashtags.\n\n"
    "Responde ÚNICAMENTE llamando a la herramienta propose_reply."
)

_PRICE_TOKEN = PRICE_TOKEN  # moved to `assisted.grounding` (shared with public replies)


@dataclass(frozen=True)
class GateVerdict:
    allowed: bool
    reason: str
    # The inbound message the draft would answer (set only when allowed).
    target: MessageRecord | None = None


def gate(thread: ThreadRecord, messages: Sequence[MessageRecord], now: datetime) -> GateVerdict:
    """Whether this thread deserves a draft right now. `messages` oldest-first."""
    if not messages:
        return GateVerdict(False, GATE_NO_MESSAGES)
    last = messages[-1]
    if last.direction != "inbound":
        return GateVerdict(False, GATE_LAST_OUTBOUND)
    if not (last.text or "").strip():
        return GateVerdict(False, GATE_NO_TEXT)
    if not window_state(thread.last_inbound_at, now).is_open:
        return GateVerdict(False, GATE_WINDOW_CLOSED)
    return GateVerdict(True, GATE_OK, target=last)


@dataclass(frozen=True)
class Proposal:
    """What a generator returns: the text, its own grounding verdict, and the cost."""

    text: str
    used_only_given_facts: bool
    unsupported_claims: tuple[str, ...] = ()
    model_id: str | None = None
    model_revision: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class DraftGenerator(Protocol):
    @property
    def version(self) -> str: ...

    def propose(
        self,
        *,
        grounding: Grounding,
        messages: Sequence[MessageRecord],
        counterpart: str,
        context: str | None = None,
    ) -> Proposal:
        """`context`: what the model must know about where the reply goes that the
        messages do not say (m-24789646: «this answers a public comment, by DM»)."""
        ...


def transcript(messages: Sequence[MessageRecord], counterpart: str, business: str) -> str:
    """The newest `CONTEXT_MESSAGES`, oldest first, one line each. A media-only message
    is named by its kind so the model knows something was sent."""
    window = list(messages)[-CONTEXT_MESSAGES:]
    lines: list[str] = []
    for m in window:
        who = counterpart if m.direction == "inbound" else business
        body = (m.text or "").strip() or f"[{m.media_type or 'adjunto'}]"
        lines.append(f"{who}: {body}")
    return "\n".join(lines)


def message_context(message: MessageRecord) -> str | None:
    """What the generator must know about the message it answers that its text does not
    say: today, that it was a tapped option (m-24789472). `None` for a typed message."""
    return choice_context(message.choice_kind, message.choice_payload, message.text)


def needs_review(proposal: Proposal, grounding: Grounding) -> bool:
    """The model's own verdict, plus one local check it cannot talk its way out of: a
    price-looking token in a reply built on a grounding without prices."""
    if not proposal.used_only_given_facts or proposal.unsupported_claims:
        return True
    if _PRICE_TOKEN.search(proposal.text) and not grounding.has_prices:
        return True
    return False


#: The prefix of `GENERATOR_VERSION`; another prompt over the same tool contract (the
#: public comment reply, `replies.public_drafts`) passes its own.
GENERATOR_VERSION_PREFIX: Final = "qua226.1"


class ClaudeDraftGenerator:
    """`DraftGenerator` over the Messages API (`claude_tools`). The client is built on
    the first proposal, not at construction, so the service can be composed without the
    key and fail only when a draft is actually asked for.

    `system_prompt` / `version_prefix` let another surface reuse the same strict tool
    contract with its own instructions and its own version (m-24789645: public comment
    replies); the defaults are the private-conversation generator, unchanged."""

    def __init__(
        self,
        *,
        config: ModelConfig = DRAFT_MODEL,
        client_factory: ClientFactory = default_client,
        api_key: str | None = None,
        system_prompt: str = SYSTEM_PROMPT,
        version_prefix: str = GENERATOR_VERSION_PREFIX,
    ) -> None:
        self._config = config
        self._client_factory = client_factory
        self._api_key = api_key
        self._system_prompt = system_prompt
        self._version_prefix = version_prefix
        self._client: Any = None

    @property
    def version(self) -> str:
        return f"{self._version_prefix}:{self._config.model_id}"

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory(self._api_key or api_key_from_env())
        return self._client

    def propose(
        self,
        *,
        grounding: Grounding,
        messages: Sequence[MessageRecord],
        counterpart: str,
        context: str | None = None,
    ) -> Proposal:
        business = grounding.business_name or "Negocio"
        situation = f"CONTEXTO\n{context.strip()}\n\n" if context and context.strip() else ""
        user_content = (
            f"HECHOS VALIDADOS\n{grounding.as_prompt()}\n\n"
            f"{situation}"
            f"CONVERSACIÓN (la última línea es la que respondes)\n"
            f"{transcript(messages, counterpart, business)}"
        )
        tool = strict_tool(
            TOOL_NAME,
            "La respuesta propuesta al último mensaje del cliente y si se apoya solo en "
            "los hechos validados.",
            {
                "reply": {
                    "type": "string",
                    "description": "El texto de la respuesta, listo para enviar.",
                },
                "uses_only_given_facts": {
                    "type": "boolean",
                    "description": (
                        "true si todo lo afirmado sale de los hechos validados o del hilo."
                    ),
                },
                "unsupported_claims": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Afirmaciones del cliente o preguntas que los hechos no cubren y "
                        "que una persona debe confirmar. Vacío si no hay."
                    ),
                },
            },
        )
        meter = Meter(self._config)
        response = create_turn(
            self._get_client(),
            self._config,
            meter,
            system=self._system_prompt,
            messages=[{"role": "user", "content": user_content}],
            tools=[tool],
            tool_choice=forced_or_auto(self._config, TOOL_NAME),
            max_tokens=MAX_TOKENS,
        )
        uses = [u for u in tool_uses(response) if getattr(u, "name", None) == TOOL_NAME]
        if not uses:
            raise ClaudeToolError(f"{self._config.model_id} answered without {TOOL_NAME}")
        payload = dict(uses[0].input)
        text = str(payload.get("reply", "")).strip()
        if not text:
            raise ClaudeToolError(f"{self._config.model_id} proposed an empty reply")
        stats = meter.stats()
        logger.info(
            "conversations.draft model=%s input_tokens=%d output_tokens=%d cost_usd=%.6f",
            stats.model_revision or stats.model_id,
            stats.input_tokens,
            stats.output_tokens,
            stats.cost_usd,
        )
        claims = payload.get("unsupported_claims") or []
        return Proposal(
            text=text[:MAX_DRAFT_CHARS],
            used_only_given_facts=bool(payload.get("uses_only_given_facts", False)),
            unsupported_claims=tuple(str(c) for c in claims if str(c).strip()),
            model_id=stats.model_id,
            model_revision=stats.model_revision,
            input_tokens=stats.input_tokens,
            output_tokens=stats.output_tokens,
            cost_usd=stats.cost_usd,
        )


class SuggestionRefused(ValueError):
    """The gate said no; `reason` is one of the `GATE_*` constants."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ThreadNotFound(LookupError):
    pass


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class ConversationDraftService:
    """`suggest` → one `proposed` draft (or the one already pending for that message);
    `decide` → the person's verdict. Nothing here sends."""

    repository: ConversationRepository
    drafts: DraftRepository
    generator: DraftGenerator
    grounding: GroundingProvider
    clock: Callable[[], datetime] = field(default=_utcnow)

    def pending_for(self, *, tenant_id: UUID, thread_id: UUID) -> ConversationDraft | None:
        pending = self.drafts.list_pending(tenant_id=tenant_id, thread_id=thread_id)
        return pending[-1] if pending else None

    def suggest(self, *, tenant_id: UUID, thread_id: UUID) -> ConversationDraft:
        """Raises `ThreadNotFound`, `SuggestionRefused` (gate) or `ClaudeToolError` /
        `MissingAPIKey` from the generator. Returns the pending draft for the same message
        when one exists instead of paying for a second one."""
        thread = self.repository.get_thread(tenant_id=tenant_id, thread_id=thread_id)
        if thread is None:
            raise ThreadNotFound(str(thread_id))
        messages = self.repository.list_messages(
            tenant_id=tenant_id, thread_id=thread_id, limit=CONTEXT_MESSAGES * 2
        )
        verdict = gate(thread, messages, self.clock())
        if not verdict.allowed or verdict.target is None:
            raise SuggestionRefused(verdict.reason)
        for pending in self.drafts.list_pending(tenant_id=tenant_id, thread_id=thread_id):
            if pending.message_id == verdict.target.id:
                return pending
        grounding = self.grounding(tenant_id, thread.connection_id)
        counterpart = thread.counterpart_name or thread.counterpart_username or "Cliente"
        target = verdict.target
        context = message_context(target)
        # A typed message calls the generator exactly as before (no `context` at all).
        situation = {"context": context} if context is not None else {}
        proposal = self.generator.propose(
            grounding=grounding, messages=messages, counterpart=counterpart, **situation
        )
        choice = (
            {"kind": target.choice_kind, "payload": target.choice_payload}
            if target.choice_kind is not None
            else None
        )
        draft = new_draft(
            tenant_id=tenant_id,
            thread_id=thread_id,
            message_id=verdict.target.id,
            generator_version=self.generator.version,
            generated_text=proposal.text,
            gate_reason=verdict.reason,
            needs_review=needs_review(proposal, grounding),
            now=self.clock(),
            model_id=proposal.model_id,
            model_revision=proposal.model_revision,
            input_tokens=proposal.input_tokens,
            output_tokens=proposal.output_tokens,
            cost_usd=proposal.cost_usd,
            grounding={
                **grounding.as_record(),
                "unsupported_claims": list(proposal.unsupported_claims),
                **({"choice": choice} if choice is not None else {}),
            },
        )
        try:
            return self.drafts.create(draft)
        except DraftPending:
            # Lost a race with another person's click: hand back theirs.
            existing = self.pending_for(tenant_id=tenant_id, thread_id=thread_id)
            if existing is None:
                raise
            return existing

    def decide(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        status: DraftStatus,
        final_text: str | None,
        user_id: UUID,
    ) -> ConversationDraft:
        return self.drafts.decide(
            tenant_id=tenant_id,
            draft_id=draft_id,
            status=status,
            final_text=final_text,
            decided_by_user_id=user_id,
            now=self.clock(),
        )


__all__ = [
    "CONTEXT_MESSAGES",
    "DRAFT_MODEL",
    "GATE_LAST_OUTBOUND",
    "GATE_NO_MESSAGES",
    "GATE_NO_TEXT",
    "GATE_OK",
    "GATE_PENDING",
    "GATE_WINDOW_CLOSED",
    "GENERATOR_VERSION",
    "GENERATOR_VERSION_PREFIX",
    "MAX_DRAFT_CHARS",
    "SYSTEM_PROMPT",
    "TOOL_NAME",
    "ClaudeDraftGenerator",
    "ConversationDraftService",
    "DraftGenerator",
    "GateVerdict",
    "GroundedProduct",
    "Grounding",
    "GroundingProvider",
    "Proposal",
    "SuggestionRefused",
    "ThreadNotFound",
    "gate",
    "grounding_from_products",
    "message_context",
    "needs_review",
    "transcript",
]
