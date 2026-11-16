"""Hashtags for one caption (draft review, QUA-118 v2 polish).

The operator writes a caption and wants hashtags that fit ALL of it — not the words one by
one. Claude reads the whole text and proposes a mix:

- **popular** — broad tags people keep using (what makes a post discoverable);
- **nicho** — specific to what the caption is about (where the right audience is);
- **marca** — local or brand tags the text itself names (a city, a product, the brand).

It is grounded in the tenant's hashtag catalog (`HashtagRepository`): tags actually seen on
Instagram/TikTok posts, with how often (`seen_count`). Those are shown to the model first
and flagged as such, so «popular» is backed by what we observed, not by a guess about
today's trends — the model has no live trend feed, and the prompt says so.

Pure orchestration: the client comes from `claude_tools.default_client` with an explicit
`api_key` (`QUALIFY_ANTHROPIC_API_KEY`), injectable for tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from qualify_shared import observability

from ..claude_tools import (
    Attribution,
    ClientFactory,
    Meter,
    ModelConfig,
    create_turn,
    default_client,
    forced_or_auto,
    strict_tool,
    tool_uses,
)
from .repository import fold

CAPTION_MODEL = ModelConfig("claude-haiku-4-5")
SUGGEST_TOOL = "sugerir_hashtags"
KINDS: tuple[str, ...] = ("popular", "nicho", "marca")
MAX_PICKS = 12
CAPTION_MAX_CHARS = 4000  # what the model is shown — a caption is at most 2,200

#: The prompt with the watched tags (m-25032581). A call without them sends exactly the
#: previous prompt, byte for byte, so it is booked as `PROMPT_VERSION_WITHOUT_WATCHED`.
PROMPT_VERSION = "caption-hashtags/2"
PROMPT_VERSION_WITHOUT_WATCHED = "caption-hashtags/1"
#: At most this many watched tags reach the model.
MAX_WATCHED = 20


@dataclass(frozen=True)
class SeenTag:
    """A catalog tag offered to the model: the tag and how often it was seen."""

    tag: str
    seen_count: int


@dataclass(frozen=True)
class WatchedTag:
    """A tag that accompanies the business's own rubro tags on the most watched videos
    the weekly read found (m-25032581; `HashtagRepository.companions`)."""

    tag: str
    views: int  # summed views of the rubro's read videos carrying it (last 90 days)
    posts: int  # how many of those videos


@dataclass(frozen=True)
class CaptionHashtag:
    tag: str  # without «#», lowercase, no accents or spaces
    kind: str  # popular / nicho / marca
    reason: str  # one short line, in Spanish, for the chip's tooltip
    seen_count: int = 0  # > 0 when the catalog has seen it on real posts
    #: True when the pick is one of the watched tags sent to the model AND not one of the
    #: `seen` catalog tags (m-25032581, UX review): the editor marks it «Mejor» only when
    #: `named_in_text` says the publication names it.
    watched: bool = False


#: A tag shorter than this (folded) only matches a whole word of the text: `te`, `sol`
#: inside longer words mean nothing.
NAMED_MIN_LENGTH = 4


def _folded_words(text: str) -> list[str]:
    return [word for word in (fold(chunk) for chunk in text.split()) if word]


def named_in_text(tag: str, caption: str) -> bool:
    """Whether the publication's text names `tag` — pure, deterministic, no model.

    Both are folded (`fold`: accents, case, anything not a letter or digit dropped). The
    tag must appear in the text with spaces and punctuation removed, STARTING at the
    start of one of its words (so `ensaladasaludable` matches «ensalada saludable» and
    `pollo` «el pollo jugoso», while `pollo` does not match «repollo»); its end may run
    into the word (`pollo` matches «pollos»). A trailing plural differs either way: a tag
    ending in «s» / «es» also matches without it (`ensaladas` ↔ «ensalada»), provided what
    is left keeps `NAMED_MIN_LENGTH`. A tag shorter than `NAMED_MIN_LENGTH` matches only
    a whole word of the text. Nothing smarter: «receta fácil» does not name
    `recetasfaciles`."""
    target = fold(tag)
    words = _folded_words(caption)
    if not target or not words:
        return False
    if len(target) < NAMED_MIN_LENGTH:
        return target in words
    variants = {target}
    for suffix in ("es", "s"):
        stem = target[: -len(suffix)]
        if target.endswith(suffix) and len(stem) >= NAMED_MIN_LENGTH:
            variants.add(stem)
    squashed = "".join(words)
    starts, offset = [], 0
    for word in words:
        starts.append(offset)
        offset += len(word)
    return any(squashed.startswith(v, start) for v in variants for start in starts)


#: Tags of a platform's own communities (`foodtok`, `booktok`, `tiktokfood`): on
#: Instagram or Facebook they name TikTok, not what the publication is about.
_PLATFORM_NAME = "tiktok"
_PLATFORM_SUFFIX = "tok"
#: `<community>tok` needs at least this much before «tok» (`foodtok`); `tok` alone is not.
_PLATFORM_STEM = 2


def is_platform_tag(tag: str) -> bool:
    """A TikTok tag that means nothing on Instagram or Facebook (UX review, m-25032581).
    Narrow and explicit, on the folded tag: it contains «tiktok» (`tiktok`, `tiktokfood`,
    `comidatiktok`), or it ends in «tok» with at least `_PLATFORM_STEM` characters before
    it (`foodtok`, `booktok`, `momtok`). A word that merely ends in «tok» is dropped too
    (`autoestok`): Spanish has no common word ending so, and losing a misspelling is
    cheaper than a TikTok tag on Instagram. `stock` (ends in «ock»), `tokio`, `toki`
    and `tok` alone are kept."""
    folded = fold(tag)
    if _PLATFORM_NAME in folded:
        return True
    return folded.endswith(_PLATFORM_SUFFIX) and (
        len(folded) - len(_PLATFORM_SUFFIX) >= _PLATFORM_STEM
    )


SYSTEM = """Eres estratega de redes sociales para marcas de Latinoamérica.
Lees el texto COMPLETO de una publicación de Instagram/TikTok y recomiendas hashtags que
encajen con TODO lo que dice (tema, producto, ocasión, lugar, tono), no con palabras sueltas.

Devuelve una mezcla:
- popular: hashtags amplios que mucha gente usa y sigue en ese tema.
- nicho: hashtags específicos del tema de la publicación, donde está la audiencia correcta.
- marca: hashtags locales o de marca que el propio texto nombra (ciudad, producto, marca).

Reglas:
- Prefiere los hashtags del catálogo (vistos en publicaciones reales, con su conteo) cuando
  encajen; puedes proponer otros si el texto lo pide.
- No tienes datos de tendencias en vivo: no digas que algo es «tendencia hoy». «popular»
  significa amplio y muy usado.
- Formato: sin «#», en minúsculas, sin tildes ni espacios (ej. heladoartesanal).
- Nada genérico sin relación con el texto (#love, #instagood) ni repetidos.
- El motivo es una frase corta en español."""

#: Appended to `SYSTEM` only when watched tags are sent (m-25032581). `SYSTEM` itself is
#: never edited: a call without them is today's request byte for byte.
WATCHED_ADDENDUM = """Hashtags que acompañan a los del negocio:
- Son hashtags que aparecen junto a los hashtags del propio negocio en videos recientes \
de su rubro (se indican las vistas sumadas y en cuántos videos aparecen). Los publicó \
gente que no es este negocio: muchos no sirven para este texto.
- Toma uno SOLO si nombra algo que el texto dice: el producto, un ingrediente, la \
ocasión o el lugar del texto. Lo normal es que encajen pocos o ninguno; no rellenes con \
ellos.
- El que sí encaja (el ingrediente o el tipo de comida que el texto nombra, en una palabra \
común) ponlo entre los cinco primeros: es lo que la gente de su rubro busca.
- Si un hashtag no es una palabra o frase común (lleva un nombre propio, un apodo o una \
marca, como #tacosdonpepe o #burgerlarry), es el nombre de otro negocio o de una \
cuenta: nunca lo elijas, aunque lleve el nombre del plato.
- Hashtags de recetas o de cocinar en casa solo si el texto enseña a preparar algo.
- Las vistas no hacen que encaje: un video viral puede llevar hashtags que no tienen \
nada que ver con este texto. Uno visto en un solo video es una pista débil.
- Son videos de TikTok y no dicen nada de «tendencia hoy».
- El motivo dice qué palabra o idea del texto nombra el hashtag. No menciones TikTok, \
videos, vistas, «virales», «audiencia» ni el rubro, y escribe sin palabras en inglés."""


def _views_label(views: int) -> str:
    """`2,4 M de vistas`, `12 mil vistas`, `850 vistas` — compact and unambiguous."""
    if views >= 1_000_000:
        number = f"{views / 1_000_000:.1f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{number} M de vistas"
    if views >= 1_000:
        return f"{views // 1_000} mil vistas"
    return "1 vista" if views == 1 else f"{views} vistas"


def _watched_block(watched: Sequence[WatchedTag]) -> list[str]:
    lines = [
        "Hashtags que acompañan a los del negocio en los videos recientes más vistos de su "
        "rubro (TikTok, últimos 90 días):"
    ]
    for item in watched[:MAX_WATCHED]:
        videos = "1 video" if item.posts == 1 else f"{item.posts} videos"
        lines.append(f"- {item.tag} ({_views_label(item.views)}, {videos})")
    return lines


def _tool(max_picks: int) -> dict[str, Any]:
    return strict_tool(
        SUGGEST_TOOL,
        f"Entrega hasta {max_picks} hashtags para el texto, el mejor primero.",
        {
            "hashtags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string"},
                        "tipo": {"type": "string", "enum": list(KINDS)},
                        "motivo": {"type": "string"},
                    },
                    "required": ["tag", "tipo", "motivo"],
                    "additionalProperties": False,
                },
            }
        },
    )


def _message(
    caption: str,
    seen: Sequence[SeenTag],
    current: Sequence[str],
    watched: Sequence[WatchedTag] = (),
) -> str:
    lines = [f"Texto de la publicación:\n«{caption[:CAPTION_MAX_CHARS]}»", ""]
    if seen:
        lines.append("Hashtags del catálogo (vistos en publicaciones reales, veces vistos):")
        lines.extend(f"- {t.tag} ({t.seen_count})" for t in seen)
    else:
        lines.append("El catálogo no tiene hashtags para este tema todavía.")
    if watched:
        lines.append("")
        lines.extend(_watched_block(watched))
    if current:
        lines.append("")
        lines.append("Ya elegidos (no los repitas): " + ", ".join(current))
    return "\n".join(lines)


def _clean(tag: str) -> str:
    return "".join(ch for ch in fold(tag.strip().lstrip("#")) if ch.isalnum() or ch == "_")


#: The function the consumption ledger books these calls to (m-24955649).
FEATURE = "hashtags-pie"


@observability.traced("hashtags del caption", tags=("generador",))
def suggest_for_caption(
    caption: str,
    *,
    attribution: Attribution,
    seen: Sequence[SeenTag] = (),
    watched: Sequence[WatchedTag] = (),
    current: Sequence[str] = (),
    api_key: str,
    max_picks: int = MAX_PICKS,
    client_factory: ClientFactory | None = None,
) -> list[CaptionHashtag]:
    """Up to `max_picks` hashtags for the whole caption, best first, none already in
    `current`. Raises `ClaudeToolError` (via `create_turn`) on a refusal or truncation.

    `watched` (m-25032581) adds `WATCHED_ADDENDUM` to the system prompt and a block of at
    most `MAX_WATCHED` tags to the message; without it the request is the previous one,
    byte for byte. The call is booked with its prompt version (`Attribution.versioned`):
    `PROMPT_VERSION` with watched tags, `PROMPT_VERSION_WITHOUT_WATCHED` without."""
    if not caption.strip():
        return []
    watched = tuple(w for w in watched if not is_platform_tag(w.tag))[:MAX_WATCHED]
    client = (client_factory or default_client)(api_key)
    meter = Meter(CAPTION_MODEL)
    response = create_turn(
        client,
        CAPTION_MODEL,
        meter,
        system=f"{SYSTEM}\n\n{WATCHED_ADDENDUM}" if watched else SYSTEM,
        messages=[{"role": "user", "content": _message(caption, seen, current, watched)}],
        tools=[_tool(max_picks)],
        tool_choice=forced_or_auto(CAPTION_MODEL, SUGGEST_TOOL),
        max_tokens=2048,
        attribution=attribution.versioned(
            PROMPT_VERSION if watched else PROMPT_VERSION_WITHOUT_WATCHED
        ),
    )
    use = next((u for u in tool_uses(response) if u.name == SUGGEST_TOOL), None)
    if use is None:
        return []
    counts = {fold(t.tag): t.seen_count for t in seen}
    watched_only = {fold(w.tag) for w in watched} - set(counts)
    taken = {fold(t) for t in current}
    picks: list[CaptionHashtag] = []
    for item in (use.input or {}).get("hashtags", []):
        tag = _clean(str(item.get("tag", "")))
        kind = str(item.get("tipo", ""))
        if len(tag) < 3 or tag in taken or kind not in KINDS:
            continue
        taken.add(tag)
        picks.append(
            CaptionHashtag(
                tag=tag,
                kind=kind,
                reason=str(item.get("motivo", "")).strip(),
                seen_count=counts.get(tag, 0),
                watched=tag in watched_only,
            )
        )
        if len(picks) >= max_picks:
            break
    return picks
