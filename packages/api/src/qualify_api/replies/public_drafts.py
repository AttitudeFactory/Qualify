"""Grounded PUBLIC replies to Instagram comments with commercial intent (m-24789645,
Interacciones · Fase B). What the reply generator is told, and when its draft needs a
person's closer look.

The generator is the private-conversation one (`conversations.suggest.
ClaudeDraftGenerator`, strict tool `propose_reply`), reused with its own system prompt and
version: the tool contract — text, «used only the given facts», unsupported claims, cost —
is exactly what a public draft needs too. Only the instructions differ, because a public
reply is read by everyone under the post.

## Founder decisions this module enforces

- **D1 — a public reply never states a price.** Twice: the model is given the catalog
  WITHOUT prices (`Grounding.without_prices()`, descriptions scrubbed too), so it cannot
  copy one; and any price-looking token in its text forces review (`has_price_token`).
  A price question is answered by inviting the person to continue by DM.
- **D2 — the catalog is the only validated source in v1.** Availability, store,
  location and hours are in no table a tenant validated: a comment asking about them gets
  a draft that does not state such data, and the draft always needs review.

## When a draft needs review (`review_reasons`)

Any of these, each recorded by code on the draft (`grounding.review_reasons`):

- `model_unsupported` — the model says it used something outside the facts, or listed a
  claim it could not ground (e.g. a product the catalog does not have);
- `price_token` — a price-looking token in the text (D1);
- `unvalidated:<class>` — availability / store / location / hours asked (D2);
- `empty_catalog` — no validated product at all, so nothing product-related is grounded;
- `price_unknown` — a price was asked and no catalog product has one, so even «te
  escribimos por DM con el precio» promises a figure nobody validated;
- `unreliable:<class>` — the classifier is not reliable for that class under its
  detector version (`intent.reliability`). Fail closed, like `reliability.py` itself:
  the class steers what the reply answers and withholds, so when it may be wrong a
  person checks the reply addresses what was really asked. It does not block the draft
  — the gate uses only `commercial_intent`, which is measured reliable.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from qualify_api.assisted.grounding import Grounding, has_price_token
from qualify_api.conversations.repository import MessageRecord
from qualify_api.intent.contract import INTENT_CLASS_LABELS, IntentClass

#: The Claude model is the private generator's (`conversations.suggest.DRAFT_MODEL`);
#: the version names THIS prompt. Bump the prefix whenever the prompt changes.
PUBLIC_GENERATOR_VERSION_PREFIX: Final = "m24789645.1"
PUBLIC_DRAFT_MODEL_ID: Final = "claude-haiku-5-5"
PUBLIC_GENERATOR_VERSION: Final = f"{PUBLIC_GENERATOR_VERSION_PREFIX}:{PUBLIC_DRAFT_MODEL_ID}"

#: How the comment is labelled in the one-line transcript the generator receives. Never
#: the author's name or handle: a public reply carries no personal data.
COMMENT_SPEAKER: Final = "Comentario"

PUBLIC_SYSTEM_PROMPT: Final = (
    "Eres quien responde, en nombre de un negocio, los comentarios PÚBLICOS de sus "
    "publicaciones de Instagram. Lo que escribas lo leerá cualquiera que vea la "
    "publicación. Te llegan el comentario, lo que la persona quiere saber y una lista de "
    "HECHOS VALIDADOS del negocio: su nombre y, si los hay, sus productos.\n\n"
    "Escribe UNA respuesta breve (una o dos frases), cálida y sencilla, en español "
    "neutro, tuteando, sin palabras en inglés ni modismos de un solo país. Máximo un "
    "emoji y ningún hashtag. No uses el nombre ni el usuario de la persona ni ningún "
    "dato personal.\n\n"
    "Reglas que no se rompen:\n"
    "1. NUNCA escribas un precio, un monto ni una cifra de dinero, aunque te la pidan. "
    "Si preguntan el precio, invita a seguir por mensaje privado, por ejemplo: «¡Hola! "
    "Te escribimos por DM con el precio».\n"
    "2. Afirma SOLO lo que digan los hechos validados. Nunca digas si hay existencias, "
    "ni direcciones, sucursales, horarios, envíos, plazos o promociones: no están "
    "validados. Si preguntan algo de eso, invita a seguir por mensaje privado sin "
    "afirmarlo.\n"
    "3. Si preguntan por un producto que no está en los hechos, no lo confirmes ni lo "
    "niegues: invita a seguir por mensaje privado.\n"
    "4. Todo lo que no puedas respaldar con los hechos, repórtalo como afirmación no "
    "respaldada.\n\n"
    "Responde ÚNICAMENTE llamando a la herramienta propose_reply."
)

#: D2: classes whose answer is in no validated source in v1.
UNVALIDATED_CLASSES: Final = frozenset(
    {IntentClass.AVAILABILITY, IntentClass.STORE, IntentClass.LOCATION, IntentClass.HOURS}
)

ReliabilityReader = Callable[[str], Mapping[IntentClass, bool]]


def parse_classes(names: Sequence[str]) -> tuple[IntentClass, ...]:
    """Stored class names back into `IntentClass`, dropping any this code no longer
    knows (a renamed class is a contract change; it must not crash generation)."""
    parsed: list[IntentClass] = []
    for name in names:
        try:
            parsed.append(IntentClass(name))
        except ValueError:
            continue
    return tuple(parsed)


def public_context(classes: Sequence[IntentClass]) -> str:
    """What the generator must know that the comment alone does not say: where the reply
    goes and what the person asked about, plus the D1/D2 reminders that apply."""
    lines = ["Respondes un comentario PÚBLICO de Instagram: tu respuesta la verá todo el mundo."]
    asked = [INTENT_CLASS_LABELS[c] for c in classes if c is not IntentClass.GENERAL]
    if asked:
        lines.append("Lo que la persona quiere saber: " + ", ".join(asked) + ".")
    if IntentClass.PRICE in classes:
        lines.append("Pregunta el precio: no lo digas; invítala a seguir por mensaje privado.")
    unvalidated = [INTENT_CLASS_LABELS[c] for c in classes if c in UNVALIDATED_CLASSES]
    if unvalidated:
        lines.append(
            "Pregunta por " + ", ".join(unvalidated).lower() + ": no es un dato validado; "
            "no lo afirmes e invítala a seguir por mensaje privado."
        )
    return "\n".join(lines)


def review_reasons(
    *,
    text: str,
    used_only_given_facts: bool,
    unsupported_claims: Sequence[str],
    grounding: Grounding,
    classes: Sequence[IntentClass],
    reliable: Mapping[IntentClass, bool],
) -> tuple[str, ...]:
    """Every reason this public draft needs review, in a stable order; empty = none.
    `grounding` is the FULL catalog grounding (with prices), not the public view."""
    reasons: list[str] = []
    if not used_only_given_facts or any(c.strip() for c in unsupported_claims):
        reasons.append("model_unsupported")
    if has_price_token(text):
        reasons.append("price_token")
    reasons.extend(f"unvalidated:{c.value}" for c in classes if c in UNVALIDATED_CLASSES)
    if not grounding.products:
        reasons.append("empty_catalog")
    if IntentClass.PRICE in classes and not grounding.has_prices:
        reasons.append("price_unknown")
    reasons.extend(
        f"unreliable:{c.value}"
        for c in classes
        if c is not IntentClass.GENERAL and not reliable.get(c, False)
    )
    return tuple(dict.fromkeys(reasons))


def grounding_record(public_view: Grounding, reasons: Sequence[str]) -> dict[str, Any]:
    """What the draft stores: the facts the model was actually given (prices withheld,
    product ids and `updated_at` kept for the reviewer) and why it needs review."""
    return {**public_view.as_record(), "review_reasons": list(reasons)}


def cost_decimal(cost_usd: float) -> Decimal:
    """`Proposal.cost_usd` (float) as the column's NUMERIC(10, 6)."""
    return Decimal(str(round(cost_usd, 6)))


def comment_message(
    *, message_id: UUID, connection_id: UUID, source_id: str, text: str
) -> MessageRecord:
    """The comment as the one inbound line of the generator's transcript. Author fields
    are left empty on purpose (no personal data reaches a public prompt)."""
    return MessageRecord(
        id=message_id,
        thread_id=message_id,
        connection_id=connection_id,
        external_message_id=source_id,
        direction="inbound",
        author_external_id=None,
        author_username=None,
        text=text,
        posted_at=None,
        ingested_at=datetime.now(UTC),
        delivery_status=None,
        media_type=None,
    )


__all__ = [
    "COMMENT_SPEAKER",
    "PUBLIC_DRAFT_MODEL_ID",
    "PUBLIC_GENERATOR_VERSION",
    "PUBLIC_GENERATOR_VERSION_PREFIX",
    "PUBLIC_SYSTEM_PROMPT",
    "UNVALIDATED_CLASSES",
    "ReliabilityReader",
    "comment_message",
    "cost_decimal",
    "grounding_record",
    "parse_classes",
    "public_context",
    "review_reasons",
]
