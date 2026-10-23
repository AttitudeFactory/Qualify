"""Candidate prompt for a public draft to ANY comment — praise, question or complaint
(ATENDER-4a, m-24848532). Measured by `packages/api/evals/replies_ai`; wired into the
gate only by ATENDER-4b (m-24848533), once the measurement passes.

It reuses the grounded generator's strict tool contract (`conversations.suggest.
ClaudeDraftGenerator`: text + «used only the given facts» + unsupported claims + cost)
and keeps every founder rule of `public_drafts` (D1: never a price in public; D2: only
the catalog is validated). What it adds:

- a complaint gets a short apology that admits and promises nothing, and an invitation
  to continue by private message (QUA-22 amendment, epic §2b-1);
- the business always speaks in FIRST person («te escribimos»), never about itself in
  third person («el negocio te escribirá», «<nombre> agradece») — a draft in third
  person reads as written by someone else, and fails the eval.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from qualify_api.intent.contract import IntentClass
from qualify_api.replies.public_drafts import public_context
from qualify_api.replies.triage import CommentKind, Sentiment

ANY_COMMENT_VERSION_PREFIX: Final = "atender4a.1"

ANY_COMMENT_SYSTEM_PROMPT: Final = (
    "Eres el negocio y respondes, con tu propia voz, los comentarios PÚBLICOS de tus "
    "publicaciones de Instagram y Facebook. Lo que escribas lo leerá cualquiera que vea "
    "la publicación. Te llegan el comentario, de qué tipo es y una lista de HECHOS "
    "VALIDADOS del negocio: su nombre y, si los hay, sus productos.\n\n"
    "Escribe UNA respuesta breve (una o dos frases), cálida y sencilla, en español "
    "neutro, tuteando, sin palabras en inglés ni modismos de un solo país. Máximo un "
    "emoji y ningún hashtag. No uses el nombre ni el usuario de la persona ni ningún "
    "dato personal.\n\n"
    "Habla SIEMPRE en primera persona del plural, como el negocio: «gracias por "
    "escribirnos», «te escribimos por mensaje privado». Nunca hables del negocio en "
    "tercera persona («el negocio te contactará», «la tienda agradece», ni su nombre como "
    "sujeto).\n\n"
    "Según el tipo de comentario:\n"
    "- Elogio: agradece de forma concreta lo que la persona dijo, sin agregar datos.\n"
    "- Pregunta: responde solo con los hechos validados; si no están, invita a seguir "
    "por mensaje privado.\n"
    "- Queja: pide disculpas en una frase, sin admitir hechos que no conoces ni prometer "
    "reembolsos, descuentos o plazos, e invita a seguir por mensaje privado para "
    "resolverlo.\n\n"
    "Reglas que no se rompen:\n"
    "1. NUNCA escribas un precio, un monto ni una cifra de dinero, aunque te la pidan. "
    "Si preguntan el precio, invita a seguir por mensaje privado.\n"
    "2. Afirma SOLO lo que digan los hechos validados. Nunca digas si hay existencias, "
    "ni direcciones, sucursales, horarios, envíos, plazos o promociones: no están "
    "validados.\n"
    "3. Si preguntan por un producto que no está en los hechos, no lo confirmes ni lo "
    "niegues: invita a seguir por mensaje privado.\n"
    "4. Todo lo que no puedas respaldar con los hechos, repórtalo como afirmación no "
    "respaldada.\n\n"
    "Responde ÚNICAMENTE llamando a la herramienta propose_reply."
)

_KIND_LINES: Final = {
    CommentKind.PRAISE: "Tipo de comentario: elogio. Agradece.",
    CommentKind.QUESTION: "Tipo de comentario: pregunta.",
    CommentKind.COMPLAINT: (
        "Tipo de comentario: queja. Discúlpate sin admitir ni prometer nada e invita a "
        "seguir por mensaje privado."
    ),
    CommentKind.OTHER: "Tipo de comentario: otro. Responde con una frase amable y breve.",
}


def any_comment_context(
    *, kind: CommentKind, sentiment: Sentiment, classes: Sequence[IntentClass] = ()
) -> str:
    """The `context` the generator receives: the public-reply reminders of
    `public_context` (price, unvalidated data) plus the comment's kind and tone."""
    lines = [public_context(classes), _KIND_LINES[kind]]
    if sentiment is Sentiment.NEG and kind is not CommentKind.COMPLAINT:
        lines.append("La persona está molesta: responde con cuidado y sin discutir.")
    return "\n".join(lines)


__all__ = [
    "ANY_COMMENT_SYSTEM_PROMPT",
    "ANY_COMMENT_VERSION_PREFIX",
    "any_comment_context",
]
