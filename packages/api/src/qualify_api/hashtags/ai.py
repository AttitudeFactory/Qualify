"""Claude over the hashtag catalog, as TOOLS — stateless, nothing learned from use.

- `select_hashtags` — an agent loop: Claude gets two catalog tools (`buscar_hashtags`,
  `hashtags_del_nicho`), explores the catalog with the words it judges useful (synonyms,
  singular/plural, the English form), and finishes by calling `elegir_hashtags` with the
  tags that fit ONE brand's business (a restaurant is not `#streetfood`). A judgement
  about that brand: returned to the caller, NEVER written back as a term → tag link, so
  nothing accumulates per rubro. The prompts carry principles, not per-rubro rules.
- `classify_hashtags` — one call whose answer is the `clasificar_hashtags` tool: what a
  tag IS (`topic` / `place` / `generic` / `noise` + niche). A property of the tag alone,
  so the caller stores it on the shared catalog (`classified_by='ai'`).

Only tags a catalog tool actually returned can be chosen: whatever the model writes, a
tag it was never shown is dropped here. The catalog side of the tools (what a search
returns, which tags are filtered out) is the caller's `CatalogSearch`.

API facts pinned from the `claude-api` skill (2026-09), not from memory:

- Model ids are the bare aliases (`claude-haiku-4-5`, `claude-sonnet-5`).
- Tools are `strict: true` (arguments guaranteed to match the schema). Forced
  `tool_choice` is used only where the model runs without thinking (Haiku); a thinking
  model gets `auto` plus the loop's own check that the final tool was called.
- The whole `response.content` (thinking blocks included) is appended back on every
  turn of the loop; every `tool_use` gets its `tool_result` in ONE user message.
- `effort` lives in `output_config` and is rejected by Haiku 4.5; Sonnet 5 runs adaptive
  thinking when `thinking` is omitted. No sampling parameters are sent.
- A refusal is an HTTP 200 with `stop_reason == "refusal"`: checked before `content`.
- The client is always built with an explicit `api_key` (`QUALIFY_ANTHROPIC_API_KEY`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from qualify_shared import observability

from ..claude_tools import (
    API_KEY_ENV,
    PRICES,
    CallStats,
    ClaudeToolError,
    ClientFactory,
    DollarMeter,
    Meter,
    MissingAPIKey,
    ModelConfig,
    api_key_from_env,
    create_turn,
    default_client,
    forced_or_auto,
    strict_tool,
    tool_uses,
)
from .repository import fold, normalize_tag

__all__ = ["API_KEY_ENV", "PRICES", "MissingAPIKey", "api_key_from_env"]

#: Defaults chosen by `packages/api/evals/hashtag_ai` (Haiku 4.5 vs Sonnet 5) — see that
#: directory's README for the numbers behind each one. Classifying a tag is easy and
#: bulk: Haiku matches Sonnet at a fraction of the cost. Choosing tags for a brand is the
#: judgement the feature exists for, and Haiku fell into the very trap it must avoid
#: (`#comidacallejera` for a smash-burger restaurant) where Sonnet did not.
CLASSIFY_MODEL = "claude-haiku-4-5"
SELECT_MODEL = "claude-sonnet-5"
SELECT_EFFORT = "medium"

#: Tags per classification call: large enough to amortise the system prompt, small
#: enough that one malformed answer only costs a batch.
CLASSIFY_BATCH = 80

#: Model turns an agent run may take before it must have called `elegir_hashtags`.
MAX_TURNS = 8
#: Output ceiling per turn of a thinking run (the SDK's non-streaming maximum) — the web
#: wizard's; the Alta passes its own (`meegle.prefill.ALTA_CATALOG_MAX_TOKENS`).
SELECT_MAX_TOKENS = 16000
#: Appended to the tool results before the LAST turn when `last_turn_hint` is on (the
#: Alta's 3-turn run, m-24854322): a thinking model gets `tool_choice: auto`, so it is
#: told — not forced — to choose now.
LAST_TURN_HINT = (
    "Este es tu último turno: no busques más y entrega ahora tu selección con {tool}, "
    "con lo que ya viste."
)
#: Rows a catalog tool returns per call — enough to see the variants of a word.
TOOL_RESULTS = 25

CLASSIFIABLE_KINDS = ("topic", "place", "generic", "noise")
NO_NICHE = "none"
FIT_LEVELS = ("alta", "media")

SEARCH_TOOL = "buscar_hashtags"
NICHE_TOOL = "hashtags_del_nicho"
CHOOSE_TOOL = "elegir_hashtags"
CLASSIFY_TOOL = "clasificar_hashtags"


#: The error every hashtag run raises — the shared one, under the name callers know.
HashtagAIError = ClaudeToolError


@dataclass(frozen=True)
class TagClassification:
    tag: str
    kind: str
    niche: str | None
    country_code: str | None


@dataclass(frozen=True)
class BrandProfile:
    """What the selection reads about the brand. Every field but the handle is optional:
    the run works on whatever the wizard knows."""

    handle: str
    bio: str = ""
    category: str = ""
    #: The operator's own words for the rubro (`DiscoverySeed.terms`).
    rubro: Sequence[str] = ()
    #: Taxonomy labels of the seed's niches ("Comida y bebida").
    niches: Sequence[str] = ()
    city: str = ""
    country: str = ""
    #: Hashtags the brand itself uses (`DiscoverySeed.hashtags`).
    own_hashtags: Sequence[str] = ()
    positioning: str = ""
    audience: str = ""


@dataclass(frozen=True)
class Candidate:
    """A catalog hashtag as a tool shows it."""

    tag: str
    seen_count: int = 0
    niche: str | None = None


@dataclass(frozen=True)
class HashtagPick:
    tag: str
    fit: str
    reason: str


class CatalogSearch(Protocol):
    """The catalog side of the selection tools. Implementations filter what must never
    be offered (places, generic tags, the brand's own) — the model only sees what these
    return."""

    def search(self, query: str) -> Sequence[Candidate]:
        """Tags close to `query` (typos and accents tolerated), most used first."""
        ...

    def niche(self, key: str) -> Sequence[Candidate]:
        """Tags classified under the taxonomy niche `key`, most used first."""
        ...


# --------------------------------------------------------------------------------------
# prompts and tools
# --------------------------------------------------------------------------------------

CLASSIFY_SYSTEM = """\
Clasificas hashtags de TikTok e Instagram para el catálogo de una plataforma que busca \
referentes (cuentas influyentes de un rubro) en el mercado hispanohablante, sobre todo \
Colombia y Venezuela. Los hashtags vienen sin '#', en minúsculas y a veces sin tildes; \
pueden estar en español, inglés o portugués. Entregas el resultado con la herramienta \
clasificar_hashtags, un resultado por hashtag, escrito exactamente como llegó.

kind
- topic: nombra un tema, producto, servicio, oficio, disciplina o formato de contenido \
concreto (hamburguesas, crossfit, programacion, recetas, maquillaje, bienesraices). \
Las marcas o productos de consumo masivo que la gente usa como tema (apple, android, \
iphone, minecraft) también son topic.
- place: nombra una ciudad, país, región, estado o barrio, aunque vaya pegado a un tema \
(cucutafood, comidacolombia y caracasburger son place: la búsqueda por lugar se hace aparte).
- generic: sirve para alcance o es relleno sin tema (fyp, viral, parati, paratiiii, \
trending, tendencia, capcut, happy, comparte, enero, bruh).
- noise: el nombre de una persona, cuenta, negocio o producto pequeño concreto \
(jesusdaviduseche87, carterpcs), una cadena sin sentido, letras sueltas o algo que no \
se entiende. Ante la duda entre noise y topic, piensa si el tag sirve para encontrar \
cuentas de un rubro: si no sirve, es noise.

niche — solo para topic: el nicho de la lista que mejor encaje, o "none" si ninguno \
encaja de verdad (por ejemplo mascotas, autos o finanzas no están en la lista: none). \
No fuerces un nicho. Para kind distinto de topic, siempre "none".

country_code — solo para place, y solo si el lugar es inequívoco: el código ISO 3166-1 \
alfa-2 en mayúsculas (CO, VE, MX…). En cualquier otro caso, "".
"""


SELECT_SYSTEM = """\
Eres el analista de hashtags de una plataforma que busca referentes —cuentas influyentes \
del mismo rubro— en TikTok e Instagram para una marca. Recibes el perfil de UNA marca y \
algunos hashtags de nuestro catálogo para empezar. Con las herramientas buscas en el \
catálogo los hashtags con los que conviene buscar cuentas de ese rubro, para complementar \
los que la marca ya usa, y terminas SIEMPRE llamando a elegir_hashtags (con una lista \
vacía si nada sirve).

Cómo buscar: prueba las palabras con las que la gente nombra ese producto o servicio \
(sinónimos, singular y plural, la forma en inglés, el nombre del oficio). Pocas búsquedas \
bien pensadas valen más que muchas.

Un hashtag sirve solo si las cuentas que publican con él son pares reales de esta marca:
1. Mismo producto o servicio.
2. Mismo modelo de negocio y formato. Un tema general puede agrupar negocios distintos \
que no comparten audiencia ni compiten entre sí: formal frente a callejero, un servicio \
para personas frente al mismo servicio para mascotas, venta frente a alquiler, hacer \
frente a enseñar frente a vender. Si el hashtag describe una variante distinta de la de \
la marca, descártalo aunque comparta el tema.
3. Mismo público y posicionamiento cuando el perfil lo deja claro (premium o económico, \
vegano o tradicional, infantil o adulto…).

Descarta siempre: nombres de lugares, hashtags genéricos o de alcance, nombres propios de \
otras cuentas, marcas o personas, y cadenas sin sentido. No repitas los hashtags que la \
marca ya usa. Si dos hashtags son la misma palabra (singular y plural, con o sin tilde, \
español e inglés), elige solo el que más cuentas usan.

Es mejor devolver pocos, o ninguno, que uno dudoso: cada hashtag elegido cuesta créditos \
de búsqueda. Solo puedes elegir hashtags que te haya mostrado el catálogo, escritos \
exactamente igual; nunca inventes uno.

fit: "alta" si es claramente del mismo rubro y formato que la marca; "media" si es del \
mismo rubro pero más amplio. reason: una frase corta en español que explique por qué \
encaja con esta marca en concreto. Ordena de mejor a peor."""


def _select_tools(niches: Sequence[str]) -> list[dict[str, Any]]:
    return [
        strict_tool(
            SEARCH_TOOL,
            "Busca en el catálogo hashtags parecidos a una palabra o frase (tolera errores "
            "de tipeo y tildes). Devuelve hasta 25, con cuántas cuentas los usan y su nicho. "
            "Los lugares, los genéricos y los que la marca ya usa nunca aparecen.",
            {"consulta": {"type": "string", "description": "Una palabra o frase corta."}},
        ),
        strict_tool(
            NICHE_TOOL,
            "Los hashtags más usados de un nicho de la taxonomía.",
            {"nicho": {"type": "string", "enum": list(niches)}},
        ),
        strict_tool(
            CHOOSE_TOOL,
            "Entrega la selección final para esta marca. Llámala una sola vez, al terminar; "
            "una lista vacía es una respuesta válida.",
            {
                "picks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tag": {"type": "string"},
                            "fit": {"type": "string", "enum": list(FIT_LEVELS)},
                            "reason": {"type": "string"},
                        },
                        "required": ["tag", "fit", "reason"],
                        "additionalProperties": False,
                    },
                }
            },
        ),
    ]


def _classify_tool(niches: Sequence[str]) -> dict[str, Any]:
    return strict_tool(
        CLASSIFY_TOOL,
        "Registra la clasificación de cada hashtag recibido.",
        {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string"},
                        "kind": {"type": "string", "enum": list(CLASSIFIABLE_KINDS)},
                        "niche": {"type": "string", "enum": [*niches, NO_NICHE]},
                        "country_code": {"type": "string"},
                    },
                    "required": ["tag", "kind", "niche", "country_code"],
                    "additionalProperties": False,
                },
            }
        },
    )


def _classify_message(tags: Sequence[str], niches: Mapping[str, str]) -> str:
    niche_lines = "\n".join(f"- {key}: {label}" for key, label in niches.items())
    tag_lines = "\n".join(tags)
    return f"Nichos:\n{niche_lines}\n\nHashtags ({len(tags)}):\n{tag_lines}"


def _candidate_lines(candidates: Sequence[Candidate]) -> str:
    return "\n".join(
        f"{c.tag} ({c.seen_count} cuentas" + (f", nicho {c.niche})" if c.niche else ")")
        for c in candidates
    )


def _brand_message(
    brand: BrandProfile,
    starting: Sequence[Candidate],
    niches: Mapping[str, str],
    max_picks: int,
) -> str:
    fields = [
        ("Cuenta", f"@{brand.handle}"),
        ("Bio", brand.bio),
        ("Categoría de Instagram", brand.category),
        ("Rubro (escrito por el operador)", ", ".join(brand.rubro)),
        ("Nicho", ", ".join(brand.niches)),
        ("Ubicación", ", ".join(p for p in (brand.city, brand.country) if p)),
        ("Hashtags que ya usa", " ".join(f"#{t}" for t in brand.own_hashtags)),
        ("Posicionamiento", brand.positioning),
        ("Audiencia", brand.audience),
    ]
    profile = "\n".join(f"{name}: {value}" for name, value in fields if value.strip())
    niche_lines = ", ".join(f"{key} ({label})" for key, label in niches.items())
    start = _candidate_lines(starting) if starting else "(ninguno: usa las herramientas)"
    return (
        f"Marca:\n{profile}\n\nNichos de la taxonomía: {niche_lines}\n\n"
        f"Para empezar, del catálogo:\n{start}\n\n"
        f"Elige como máximo {max_picks} y entrégalos con {CHOOSE_TOOL}."
    )


# --------------------------------------------------------------------------------------
# the runs
# --------------------------------------------------------------------------------------


@observability.traced("clasificar hashtags", tags=("brand_kit",))
def classify_hashtags(
    tags: Sequence[str],
    niches: Mapping[str, str],
    *,
    api_key: str,
    config: ModelConfig = ModelConfig(CLASSIFY_MODEL),
    client_factory: ClientFactory | None = None,
) -> tuple[list[TagClassification], CallStats]:
    """Classify up to `CLASSIFY_BATCH` tags; the answer is the `clasificar_hashtags`
    tool call. `niches` maps taxonomy key → label. Answers for tags that were not asked
    about are dropped; a tag the model skipped is simply absent."""
    if len(tags) > CLASSIFY_BATCH:
        raise ValueError(f"at most {CLASSIFY_BATCH} tags per call, got {len(tags)}")
    asked = list(dict.fromkeys(normalize_tag(t) for t in tags))
    client = (client_factory or default_client)(api_key)
    meter = Meter(config)
    tool = _classify_tool(list(niches))
    response = create_turn(
        client,
        config,
        meter,
        system=CLASSIFY_SYSTEM,
        messages=[{"role": "user", "content": _classify_message(asked, niches)}],
        tools=[tool],
        tool_choice=forced_or_auto(config, CLASSIFY_TOOL),
        # 16000 is the ceiling the SDK allows without streaming; with thinking on, it
        # covers the reasoning plus ~80 output tokens per tag at `CLASSIFY_BATCH`.
        max_tokens=16000 if config.thinks else max(4096, 80 * len(asked)),
    )
    calls = [b for b in tool_uses(response) if b.name == CLASSIFY_TOOL]
    if not calls:
        raise HashtagAIError(f"{config.model_id} did not call {CLASSIFY_TOOL}")
    meter.tool_calls = 1
    wanted = set(asked)
    out: list[TagClassification] = []
    seen: set[str] = set()
    for item in (calls[0].input or {}).get("results") or []:
        try:
            tag = normalize_tag(str(item.get("tag", "")))
        except ValueError:
            continue
        kind = item.get("kind")
        if tag not in wanted or tag in seen or kind not in CLASSIFIABLE_KINDS:
            continue
        seen.add(tag)
        niche = item.get("niche")
        code = str(item.get("country_code") or "").strip().upper()
        out.append(
            TagClassification(
                tag=tag,
                kind=kind,
                niche=niche if kind == "topic" and niche in niches else None,
                country_code=code
                if kind == "place" and len(code) == 2 and code.isalpha()
                else None,
            )
        )
    return out, meter.stats()


def _unplural(slug: str) -> str:
    """A crude plural-blind key: every `s` dropped, then a trailing `e` (so `-es` plurals
    meet their singular: `programadores` / `programador`). Hashtags glue words together,
    so the plural can sit mid-tag (`perroscalientes` / `perrocaliente`) where a suffix
    check never sees it."""
    return slug.replace("s", "").rstrip("e")


def _same_word(slug: str, others: set[str]) -> bool:
    """`slug` is already in `others` up to a plural: `hamburguesa`/`hamburguesas`,
    `programador`/`programadores`, `perrocaliente`/`perroscalientes`. Enforced here
    because the prompt's "only one spelling" rule is followed most of the time, not
    always (measured 2026-09-25: Sonnet 5 picked `hamburguesas` AND `hamburguesa`, and
    `perrocaliente` for a brand that uses `perroscalientes`) — and a second spelling of
    the same word spends a search on the same accounts."""
    key = _unplural(slug)
    return any(slug == other or key == _unplural(other) for other in others)


@observability.traced("elegir hashtags", tags=("brand_kit",))
def select_hashtags(
    brand: BrandProfile,
    catalog: CatalogSearch,
    niches: Mapping[str, str],
    *,
    api_key: str,
    starting: Sequence[Candidate] = (),
    max_picks: int = 3,
    config: ModelConfig = ModelConfig(SELECT_MODEL, SELECT_EFFORT),
    client_factory: ClientFactory | None = None,
    max_turns: int = MAX_TURNS,
    max_tokens: int | None = None,
    budget: DollarMeter | None = None,
    last_turn_hint: bool = False,
) -> tuple[list[HashtagPick], CallStats]:
    """Let Claude explore the catalog with its tools and choose, for this brand, at most
    `max_picks` hashtags, best first. Only tags a tool (or `starting`) showed it can come
    back — never one the brand already uses, never two spellings of one word. Raises
    `HashtagAIError` (with the run's `stats`) when the run ends without
    `elegir_hashtags`, is cut by `max_tokens`, or meets a turn its `budget` cannot pay.

    `max_tokens` / `budget` / `last_turn_hint` are the Alta's limits (m-24854322): the
    defaults — `SELECT_MAX_TOKENS` on a thinking model, no meter, no hint — are the web
    wizard's, unchanged."""
    client = (client_factory or default_client)(api_key)
    meter = Meter(config)
    tools = _select_tools(list(niches))
    shown: dict[str, str] = {fold(c.tag): c.tag for c in starting}
    own = {fold(t) for t in brand.own_hashtags}
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _brand_message(brand, starting, niches, max_picks)}
    ]
    nudged = False

    def run_tool(name: str, arguments: Mapping[str, Any]) -> tuple[str, bool]:
        if name == SEARCH_TOOL:
            query = str(arguments.get("consulta") or "").strip()
            found = list(catalog.search(query))[:TOOL_RESULTS] if query else []
            empty = f"Sin resultados para '{query}'."
        elif name == NICHE_TOOL:
            key = str(arguments.get("nicho") or "")
            if key not in niches:
                return f"Nicho desconocido: '{key}'.", True
            found = list(catalog.niche(key))[:TOOL_RESULTS]
            empty = f"El nicho '{key}' no tiene hashtags todavía."
        else:
            return f"Herramienta desconocida: '{name}'.", True
        for c in found:
            shown.setdefault(fold(c.tag), c.tag)
        return (_candidate_lines(found) if found else empty), False

    turn_tokens = max_tokens or (SELECT_MAX_TOKENS if config.thinks else 4096)
    for turn in range(max_turns):
        if last_turn_hint and turn == max_turns - 1 and turn > 0:
            _hint_last_turn(messages)
        response = create_turn(
            client,
            config,
            meter,
            system=SELECT_SYSTEM,
            messages=messages,
            tools=tools,
            tool_choice={"type": "auto"},
            max_tokens=turn_tokens,
            budget=budget,
        )
        uses = tool_uses(response)
        meter.tool_calls += len(uses)
        final = next((u for u in uses if u.name == CHOOSE_TOOL), None)
        if final is not None:
            return _picks(final.input or {}, shown, own, max_picks), meter.stats()
        messages.append({"role": "assistant", "content": response.content})
        if not uses:
            if nudged:
                break
            nudged = True
            messages.append({"role": "user", "content": f"Entrega tu selección con {CHOOSE_TOOL}."})
            continue
        results = []
        for use in uses:
            content, is_error = run_tool(use.name, use.input or {})
            result: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": use.id,
                "content": content,
            }
            if is_error:
                result["is_error"] = True
            results.append(result)
        messages.append({"role": "user", "content": results})
    raise HashtagAIError(
        f"{config.model_id} ended without calling {CHOOSE_TOOL}", stats=meter.stats()
    )


def _hint_last_turn(messages: list[dict[str, Any]]) -> None:
    """`LAST_TURN_HINT` as a text block after the last user message's tool results."""
    hint = {"type": "text", "text": LAST_TURN_HINT.format(tool=CHOOSE_TOOL)}
    last = messages[-1]
    if last.get("role") != "user":
        messages.append({"role": "user", "content": [hint]})
        return
    content = last["content"]
    if isinstance(content, str):
        last["content"] = [{"type": "text", "text": content}, hint]
    else:
        last["content"] = [*content, hint]


def _picks(
    arguments: Mapping[str, Any], shown: Mapping[str, str], own: set[str], max_picks: int
) -> list[HashtagPick]:
    picks: list[HashtagPick] = []
    taken: set[str] = set()
    for item in arguments.get("picks") or []:
        slug = fold(str(item.get("tag", "")).lstrip("#"))
        if slug not in shown or _same_word(slug, own) or _same_word(slug, taken):
            continue
        fit = item.get("fit") if item.get("fit") in FIT_LEVELS else "media"
        taken.add(slug)
        picks.append(HashtagPick(shown[slug], fit, str(item.get("reason") or "").strip()))
        if len(picks) >= max_picks:
            break
    return picks
