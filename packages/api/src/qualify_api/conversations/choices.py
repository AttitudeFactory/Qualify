"""Taps that reach Conversaciones (m-24789472, PR 2): what a person CHOSE instead of typing.

Instagram delivers four kinds of tap, in two shapes
(`business-messaging/instagram-messaging/webhooks.md`, `features/ice-breakers.md`,
`features/quick-replies.md`, `features/persistent-menu.md`, `button-template.md`):

- a **quick reply** is an ordinary `message` whose `text` is the button's title and
  which carries `quick_reply.payload`;
- an **Ice Breaker** («pregunta inicial»), a **template button** and a **persistent-menu
  item** all arrive as the SAME `postback` item — `{"mid"?, "title", "payload"}` — and
  nothing in it says which of the three it was.

Only the payload can tell them apart, and the payload is ours: Qualify writes it when it
configures the account. So the convention lives here, in one place:

| Payload prefix | Kind (`messages.choice_kind`) | Configured by |
|---|---|---|
| `QF_`  | `ice_breaker` | the account's Ice Breakers (PR 3; the four defaults below) |
| `QFB_` | `button`      | a button template / generic template Qualify sends |
| `QFM_` | `menu`        | the account's persistent menu |
| anything else | `button` | a postback Qualify did not configure (another tool, or by hand) |

A quick reply is `quick_reply` whatever its payload says: the shape decides first, the
prefix only splits postbacks. The prefixes are case-sensitive and `QFB_`/`QFM_` do not
start with `QF_`, so no payload matches two rows.

`choice_label` is the origin line Conversaciones shows next to the message («Pregunta
inicial: Precio», «Respuesta rápida: Sí», «Botón: Ver catálogo»); `choice_context` is the
sentence the draft generator receives about it. Both are pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

CHOICE_ICE_BREAKER: Final = "ice_breaker"
CHOICE_QUICK_REPLY: Final = "quick_reply"
CHOICE_BUTTON: Final = "button"
CHOICE_MENU: Final = "menu"
#: `messages.choice_kind`'s CHECKed list (migration 0082) — keep the two in step.
CHOICE_KINDS: Final[tuple[str, ...]] = (
    CHOICE_ICE_BREAKER,
    CHOICE_QUICK_REPLY,
    CHOICE_BUTTON,
    CHOICE_MENU,
)

#: Meta caps a postback / quick-reply payload at 1000 characters; 0082 CHECKs the same.
MAX_CHOICE_PAYLOAD_CHARS: Final = 1000

PREFIX_ICE_BREAKER: Final = "QF_"
PREFIX_TEMPLATE_BUTTON: Final = "QFB_"
PREFIX_PERSISTENT_MENU: Final = "QFM_"

# How long the readable part of a label may be before it is cut (an Ice Breaker question
# is short; a template button title is at most 20 characters).
_LABEL_TEXT_CHARS: Final = 80
# How much of the payload the model is shown.
_CONTEXT_PAYLOAD_CHARS: Final = 120


@dataclass(frozen=True)
class DefaultIceBreaker:
    """One of the ticket's four default Ice Breakers. `payload` is what Meta sends back,
    `label` is the short Spanish name Conversaciones shows («Pregunta inicial: Precio»),
    `question` is the proposed text the person taps (PR 3 publishes it; editable)."""

    payload: str
    label: str
    question: str


DEFAULT_ICE_BREAKERS: Final[tuple[DefaultIceBreaker, ...]] = (
    DefaultIceBreaker("QF_PRODUCTO", "Productos", "¿Qué productos tienen?"),
    DefaultIceBreaker("QF_PRECIO", "Precio", "¿Cuánto cuesta?"),
    DefaultIceBreaker(
        "QF_UBICACION_HORARIO", "Ubicación y horario", "¿Dónde están y en qué horario atienden?"
    ),
    DefaultIceBreaker("QF_CATALOGO", "Catálogo", "¿Me compartes el catálogo?"),
)

_DEFAULT_LABELS: Final[dict[str, str]] = {ib.payload: ib.label for ib in DEFAULT_ICE_BREAKERS}

#: The first words of each origin label, in the client's Spanish (qualify-copy-es).
CHOICE_LABEL_PREFIXES: Final[dict[str, str]] = {
    CHOICE_ICE_BREAKER: "Pregunta inicial",
    CHOICE_QUICK_REPLY: "Respuesta rápida",
    CHOICE_BUTTON: "Botón",
    CHOICE_MENU: "Menú",
}


def normalize_payload(payload: object) -> str | None:
    """The payload as stored: a non-empty string, cut at `MAX_CHOICE_PAYLOAD_CHARS`;
    `None` for anything else (Meta documents it as optional on a quick reply)."""
    if isinstance(payload, bool) or not isinstance(payload, str | int):
        return None
    value = str(payload)
    if not value.strip():
        return None
    return value[:MAX_CHOICE_PAYLOAD_CHARS]


def postback_kind(payload: str | None) -> str:
    """Which tap a `postback` was, by Qualify's payload prefix (module docstring)."""
    if payload is None:
        return CHOICE_BUTTON
    if payload.startswith(PREFIX_ICE_BREAKER):
        return CHOICE_ICE_BREAKER
    if payload.startswith(PREFIX_PERSISTENT_MENU):
        return CHOICE_MENU
    # `QFB_` (a template button Qualify sent) and any payload Qualify did not write.
    return CHOICE_BUTTON


def default_ice_breaker(payload: str | None) -> DefaultIceBreaker | None:
    for ice_breaker in DEFAULT_ICE_BREAKERS:
        if ice_breaker.payload == payload:
            return ice_breaker
    return None


def _clip(value: str, limit: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def choice_label(kind: str | None, payload: str | None, title: str | None) -> str | None:
    """The origin line of a tapped message, or `None` when it was typed.

    The readable part is the default Ice Breaker's Spanish name for a `QF_*` default
    payload, else the title the person saw (the message text), else nothing — a payload
    is an internal key and is never shown to the client.

    >>> choice_label("ice_breaker", "QF_PRECIO", "¿Cuánto cuesta?")
    'Pregunta inicial: Precio'
    >>> choice_label("quick_reply", "SI", "Sí")
    'Respuesta rápida: Sí'
    >>> choice_label("button", "QFB_VER_CATALOGO", "Ver catálogo")
    'Botón: Ver catálogo'
    >>> choice_label("menu", "QFM_X", None)
    'Menú'
    """
    prefix = CHOICE_LABEL_PREFIXES.get(kind or "")
    if prefix is None:
        return None
    readable = _DEFAULT_LABELS.get(payload or "") if kind == CHOICE_ICE_BREAKER else None
    if readable is None and title and title.strip():
        readable = _clip(title, _LABEL_TEXT_CHARS)
    return f"{prefix}: {readable}" if readable else prefix


_CONTEXT_LEADS: Final[dict[str, str]] = {
    CHOICE_ICE_BREAKER: "La persona tocó la pregunta inicial",
    CHOICE_QUICK_REPLY: "La persona eligió la respuesta rápida",
    CHOICE_BUTTON: "La persona tocó el botón",
    CHOICE_MENU: "La persona eligió en el menú de la conversación la opción",
}


def choice_context(kind: str | None, payload: str | None, title: str | None) -> str | None:
    """What the draft generator must know about a tapped message: that it is an option
    the business offered, which one, and its payload (the business's own key, which may
    name a product or a topic). `None` for a typed message — e.g. «La persona tocó la
    pregunta inicial «¿Cuánto cuesta?» (QF_PRECIO: Precio). No lo escribió: …»."""
    lead = _CONTEXT_LEADS.get(kind or "")
    if lead is None:
        return None
    shown = f" «{_clip(title, _LABEL_TEXT_CHARS)}»" if title and title.strip() else ""
    key = _clip(payload, _CONTEXT_PAYLOAD_CHARS) if payload else None
    default = _DEFAULT_LABELS.get(payload or "") if kind == CHOICE_ICE_BREAKER else None
    if key and default:
        key = f"{key}: {default}"
    return (
        f"{lead}{shown}"
        + (f" ({key})" if key else "")
        + ". No lo escribió: es una opción que le ofreció el negocio. "
        "Responde a lo que esa opción pide."
    )


__all__ = [
    "CHOICE_BUTTON",
    "CHOICE_ICE_BREAKER",
    "CHOICE_KINDS",
    "CHOICE_LABEL_PREFIXES",
    "CHOICE_MENU",
    "CHOICE_QUICK_REPLY",
    "DEFAULT_ICE_BREAKERS",
    "MAX_CHOICE_PAYLOAD_CHARS",
    "PREFIX_ICE_BREAKER",
    "PREFIX_PERSISTENT_MENU",
    "PREFIX_TEMPLATE_BUTTON",
    "DefaultIceBreaker",
    "choice_context",
    "choice_label",
    "default_ice_breaker",
    "normalize_payload",
    "postback_kind",
]
