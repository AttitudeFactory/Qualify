"""Hashtags CREATED from what the account says about itself (§ request 2026-10-05: "que se
creen los hashtags a partir de la descripción del creador, los últimos videos /
publicaciones que tenga y su categoría").

Until this module the rubro step's pills came from the shared catalog: Claude explored it
with tools (`ai.select_hashtags`) and could only pick tags the catalog already held — so a
niche the catalog had never seen got nothing, or a neighbour's tags. Here the model reads
the account itself and proposes the tags its content lives under:

- the bio (the creator's own description of what they do),
- the profile's category (Instagram's business category, when there is one),
- the captions of its latest posts / videos, and the hashtags it already uses most,
- the rubro and place the operator confirmed, so local tags (`#cucutafood`) are possible.

One strict tool call, `proponer_hashtags`, which also names the account's RUBRO in a short
phrase (§ third round of 2026-10-05: "que autocompletes el input de tu rubro"). Nothing is
written here — the wizard asks the shared catalog first and only uses these tags when the
catalog has none for the rubro, storing them there so the next search finds them
(`Qualify/hashtag_catalog.remember_created`). Without an API key, or when the call fails,
the caller falls back to `from_posts`: the account's own most-used hashtags, real and free.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from qualify_shared import observability

from ..claude_tools import (
    CallStats,
    ClaudeToolError,
    ClientFactory,
    Meter,
    ModelConfig,
    create_turn,
    default_client,
    forced_or_auto,
    strict_tool,
    tool_uses,
)
from .repository import normalize_tag

#: Choosing tags for a brand is the judgement the eval set measured: Haiku fell into the
#: trap of the neighbour niche (`#comidacallejera` for a smash-burger place) where Sonnet
#: did not (`packages/api/evals/hashtag_ai`). Low effort: one read, no exploration.
MODEL = "claude-sonnet-5"
EFFORT = "low"
TOOL = "proponer_hashtags"
#: What the model reads of the account — enough to see what it is about, bounded so one
#: verbose caption cannot dominate the prompt.
MAX_CAPTIONS = 12
MAX_CAPTION_CHARS = 280
MAX_BIO_CHARS = 600
#: The rubro is one short phrase for an input field, not a description.
MAX_RUBRO_CHARS = 80


@dataclass(frozen=True)
class AccountText:
    """What the account and the operator say, as plain text."""

    handle: str = ""
    bio: str = ""
    category: str = ""
    captions: Sequence[str] = ()
    used_hashtags: Sequence[str] = ()
    rubro: str = ""
    city: str = ""
    country: str = ""

    @property
    def has_content(self) -> bool:
        return bool(
            self.bio.strip()
            or self.category.strip()
            or any(c.strip() for c in self.captions)
            or self.used_hashtags
            or self.rubro.strip()
        )


@dataclass(frozen=True)
class ProposedTag:
    tag: str
    reason: str = ""


@dataclass(frozen=True)
class Proposal:
    tags: tuple[ProposedTag, ...]
    stats: CallStats | None = None
    #: `ai` (Claude created them) or `posts` (the fallback: the account's own hashtags).
    by: str = "ai"
    model: str = field(default="")
    #: What the account does, in a few words ("hamburguesería smash para llevar") — what
    #: fills Tu rubro when the operator has not written one. "" from the fallback.
    rubro: str = ""


SYSTEM = """\
Propones los hashtags con los que se encuentra el contenido de una cuenta de TikTok o \
Instagram, para buscar cuentas parecidas (referentes y competencia). Lees lo que la cuenta \
dice de sí misma —su descripción, su categoría, los textos de sus últimas publicaciones y \
los hashtags que ya usa— y respondes con la herramienta proponer_hashtags, una sola vez.

Reglas:
- Hashtags del TEMA de la cuenta: lo que hace, vende o enseña. Nada genérico de alcance \
(#fyp, #parati, #viral, #reels, #explore, #instagood, #tiktok).
- Especificidad antes que volumen: #smashburger mejor que #comida. No te vayas al nicho \
vecino: una hamburguesería no es #comidacallejera; una academia de programación no es \
#tecnologia a secas.
- Usa el idioma en que la cuenta escribe. Mezcla con el inglés solo si la cuenta lo usa.
- Si conoces la ciudad, puedes proponer 1 o 2 hashtags locales que de verdad se usen \
(#bogotafood, #cucutaemprende). Nunca inventes combinaciones raras.
- Los hashtags que la cuenta ya usa son evidencia fuerte: inclúyelos si son del tema.
- Sin el símbolo #, en minúsculas, sin espacios ni tildes (como se escriben en la red).
- reason: una frase corta en español que diga de qué texto sale (la bio, la categoría, \
una publicación, un hashtag que ya usa).
- rubro: lo que hace o vende la cuenta en 2 a 6 palabras, en minúsculas y como lo diría \
el dueño (hamburguesería smash para llevar, academia de programación online). Si el \
negocio ya confirmó su rubro, devuélvelo tal cual."""


def _tool(max_tags: int) -> dict[str, Any]:
    return strict_tool(
        TOOL,
        f"Entrega el rubro de la cuenta y hasta {max_tags} hashtags para buscar cuentas "
        "parecidas a esta.",
        {
            "rubro": {"type": "string", "description": "Lo que hace o vende, en pocas palabras."},
            "hashtags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["tag", "reason"],
                    "additionalProperties": False,
                },
            },
        },
    )


def _message(account: AccountText, max_tags: int) -> str:
    lines = [f"Propón hasta {max_tags} hashtags para esta cuenta."]
    if account.handle:
        lines.append(f"Cuenta: @{account.handle.lstrip('@')}")
    if account.category.strip():
        lines.append(f"Categoría del perfil: {account.category.strip()}")
    if account.rubro.strip():
        lines.append(f"Rubro que confirmó el negocio: {account.rubro.strip()}")
    place = ", ".join(p for p in (account.city.strip(), account.country.strip()) if p)
    if place:
        lines.append(f"Ubicación: {place}")
    if account.bio.strip():
        lines.append(f"<descripcion>\n{account.bio.strip()[:MAX_BIO_CHARS]}\n</descripcion>")
    if account.used_hashtags:
        lines.append("Hashtags que ya usa (de más a menos): " + ", ".join(account.used_hashtags))
    captions = [c.strip()[:MAX_CAPTION_CHARS] for c in account.captions if c.strip()]
    if captions:
        lines.append("<ultimas_publicaciones>")
        lines.extend(f"- {c}" for c in captions[:MAX_CAPTIONS])
        lines.append("</ultimas_publicaciones>")
    return "\n".join(lines)


def _clean(raw: Any, max_tags: int) -> tuple[ProposedTag, ...]:
    out: list[ProposedTag] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            tag = normalize_tag(str(item.get("tag", "")))
        except ValueError:
            continue
        if tag in seen:
            continue
        seen.add(tag)
        out.append(ProposedTag(tag, " ".join(str(item.get("reason") or "").split())[:200]))
        if len(out) == max_tags:
            break
    return tuple(out)


@observability.traced("rubro desde la cuenta", tags=("brand_kit",))
def generate(
    account: AccountText,
    *,
    api_key: str,
    max_tags: int,
    config: ModelConfig = ModelConfig(MODEL, EFFORT),
    client_factory: ClientFactory | None = None,
) -> Proposal:
    """Claude reads the account and proposes up to `max_tags` hashtags. Raises
    `ClaudeToolError` on a refusal, a truncation or no tool call; `ValueError` when there
    is nothing to read at all."""
    if not account.has_content:
        raise ValueError("nothing to read: no bio, category, posts or rubro")
    client = (client_factory or default_client)(api_key)
    meter = Meter(config)
    messages: list[dict[str, Any]] = [{"role": "user", "content": _message(account, max_tags)}]
    for attempt in range(2):
        response = create_turn(
            client,
            config,
            meter,
            system=SYSTEM,
            messages=messages,
            tools=[_tool(max_tags)],
            tool_choice=forced_or_auto(config, TOOL),
            max_tokens=4000,
        )
        calls = [u for u in tool_uses(response) if u.name == TOOL]
        if calls:
            meter.tool_calls += 1
            stats = meter.stats()
            answer = calls[0].input or {}
            tags = _clean(answer.get("hashtags"), max_tags)
            rubro = " ".join(str(answer.get("rubro") or "").split())[:MAX_RUBRO_CHARS]
            return Proposal(tags, stats, "ai", stats.model_revision or stats.model_id, rubro)
        if attempt == 0:
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": f"Entrega la respuesta con {TOOL}."})
    raise ClaudeToolError(f"{config.model_id} did not call {TOOL}")


#: Reach-only tags an account's own list is full of; never a topic.
_GENERIC = frozenset(
    {
        "fyp",
        "foryou",
        "foryoupage",
        "parati",
        "paratii",
        "viral",
        "viralvideo",
        "trending",
        "tiktok",
        "reels",
        "reel",
        "instagram",
        "instagood",
        "explore",
        "explorepage",
        "fypシ",
        "xyzbca",
        "capcut",
    }
)


def from_posts(used_hashtags: Sequence[str], *, max_tags: int) -> Proposal:
    """The fallback without Claude: the account's own most-used hashtags, minus the
    reach-only ones (#fyp, #viral…). Real tags the account already lives under."""
    out: list[ProposedTag] = []
    seen: set[str] = set()
    for raw in used_hashtags:
        try:
            tag = normalize_tag(raw)
        except ValueError:
            continue
        if tag in seen or tag in _GENERIC:
            continue
        seen.add(tag)
        out.append(ProposedTag(tag, "La cuenta ya lo usa en sus publicaciones."))
        if len(out) == max_tags:
            break
    return Proposal(tuple(out), None, "posts")
