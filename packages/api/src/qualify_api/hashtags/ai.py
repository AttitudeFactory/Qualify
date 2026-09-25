"""Claude over the hashtag catalog — two stateless calls, nothing learned from use.

- `classify_hashtags` — what a tag IS (`topic` / `place` / `generic` / `noise`, and which
  taxonomy niche for a topic). A property of the tag alone, the same for every brand, so
  the answer is stored on the shared catalog (`classified_by='ai'`, never over a manual
  decision — `repository.apply_classifications`).
- `select_hashtags` — which catalog hashtags fit ONE brand's referentes search (a
  restaurant is not `#streetfood`). A judgement about that brand, so it is returned to
  the caller and NEVER written back as a term → tag link: nothing accumulates per rubro,
  and a rubro nobody searched before gets the same judgement as one searched a hundred
  times. The prompts carry principles, not per-rubro rules or examples.

API facts pinned from the `claude-api` skill (2026-09), not from memory:

- Model ids are the bare aliases (`claude-haiku-4-5`, `claude-sonnet-5`), never dated.
- Structured output goes through `output_config.format` (json_schema); Haiku 4.5
  supports it. Prefill is rejected on the 4.6+ family.
- `effort` lives in `output_config` and is rejected by Haiku 4.5; Sonnet 5 runs adaptive
  thinking when `thinking` is omitted. Sampling parameters are rejected by Sonnet 5, so
  none are sent to either.
- A refusal is an HTTP 200 with `stop_reason == "refusal"`: checked before `content`.
- The client is always built with an explicit `api_key` (`QUALIFY_ANTHROPIC_API_KEY`,
  same variable as the creative module): the no-arg constructor would fall back to
  ambient credentials and bill the wrong account.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .repository import fold, normalize_tag

API_KEY_ENV = "QUALIFY_ANTHROPIC_API_KEY"

#: Defaults chosen by `packages/api/evals/hashtag_ai` (Haiku 4.5 vs Sonnet 5, 2026-09-25)
#: — see that directory's README for the numbers behind each one. In short: classifying
#: a tag is easy and bulk, Haiku matches Sonnet at a quarter of the cost; choosing tags
#: for a brand is the judgement the feature exists for, and Haiku fell into the very trap
#: it must avoid (`#comidacallejera` for a smash-burger restaurant) where Sonnet did not.
CLASSIFY_MODEL = "claude-haiku-4-5"
SELECT_MODEL = "claude-sonnet-5"
SELECT_EFFORT = "medium"

#: Tags per classification call: large enough to amortise the system prompt, small
#: enough that one malformed answer only costs a batch.
CLASSIFY_BATCH = 80

#: $ per million tokens (input, output), from the `claude-api` skill's model table
#: (cached 2026-06-24). Used for reporting only — nothing is budgeted from it.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5": (5.0, 25.0),
}

CLASSIFIABLE_KINDS = ("topic", "place", "generic", "noise")
NO_NICHE = "none"
FIT_LEVELS = ("alta", "media")


class HashtagAIError(RuntimeError):
    """The call could not produce a usable answer (refusal, truncation, bad JSON)."""


class MissingAPIKey(HashtagAIError):
    """`QUALIFY_ANTHROPIC_API_KEY` is not set — callers fall back to the rule path."""


@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    #: `output_config.effort` — None for models that reject it (Haiku 4.5).
    effort: str | None = None

    @property
    def label(self) -> str:
        return f"{self.model_id}@{self.effort}" if self.effort else self.model_id


@dataclass(frozen=True)
class CallStats:
    """Provenance and cost of one call — what the caller records next to the answer."""

    model_id: str
    model_revision: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        price_in, price_out = PRICES.get(self.model_id, (0.0, 0.0))
        return (self.input_tokens * price_in + self.output_tokens * price_out) / 1_000_000


@dataclass(frozen=True)
class TagClassification:
    tag: str
    kind: str
    niche: str | None
    country_code: str | None


@dataclass(frozen=True)
class BrandProfile:
    """What the selection reads about the brand. Every field but the handle is optional:
    the call works on whatever the wizard knows."""

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
    """A catalog hashtag offered to the selection."""

    tag: str
    seen_count: int = 0
    niche: str | None = None


@dataclass(frozen=True)
class HashtagPick:
    tag: str
    fit: str
    reason: str


# --------------------------------------------------------------------------------------
# prompts
# --------------------------------------------------------------------------------------

CLASSIFY_SYSTEM = """\
Clasificas hashtags de TikTok e Instagram para el catálogo de una plataforma que busca \
referentes (cuentas influyentes de un rubro) en el mercado hispanohablante, sobre todo \
Colombia y Venezuela. Los hashtags vienen sin '#', en minúsculas y a veces sin tildes; \
pueden estar en español, inglés o portugués.

Para cada hashtag decide:

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

Devuelve un resultado por cada hashtag recibido, con el hashtag escrito exactamente \
como llegó."""


SELECT_SYSTEM = """\
Eres el analista de hashtags de una plataforma que busca referentes —cuentas influyentes \
del mismo rubro— en TikTok e Instagram para una marca. Recibes el perfil de UNA marca y \
una lista de hashtags candidatos que ya existen en nuestra base, con cuántas cuentas los \
han usado. Eliges con cuáles conviene buscar cuentas, para complementar los hashtags que \
la marca ya usa.

Un hashtag sirve solo si las cuentas que publican con él son pares reales de esta marca:
1. Mismo producto o servicio.
2. Mismo modelo de negocio y formato. Un tema general puede agrupar negocios distintos \
que no comparten audiencia ni compiten entre sí: formal frente a callejero, un servicio \
para personas frente al mismo servicio para mascotas, venta frente a alquiler, hacer \
frente a enseñar frente a vender. Si el hashtag describe una variante distinta de la de \
la marca, descártalo aunque comparta el tema.
3. Mismo público y posicionamiento cuando el perfil lo deja claro (premium o económico, \
vegano o tradicional, infantil o adulto…).

Descarta siempre: nombres de lugares (ciudad, país, región, barrio; la búsqueda por \
lugar se hace aparte), hashtags genéricos o de alcance (fyp, viral, parati…), nombres \
propios de otras cuentas, marcas o personas, y cadenas sin sentido. No repitas los \
hashtags que la marca ya usa. Si dos candidatos son la misma palabra (singular y plural, \
con o sin tilde, español e inglés), elige solo el que más cuentas usan.

Es mejor devolver pocos, o ninguno, que uno dudoso: cada hashtag elegido cuesta créditos \
de búsqueda. Solo puedes elegir hashtags de la lista, escritos exactamente igual; nunca \
inventes uno.

fit: "alta" si es claramente del mismo rubro y formato que la marca; "media" si es del \
mismo rubro pero más amplio. reason: una frase corta en español que explique por qué \
encaja con esta marca en concreto. Ordena de mejor a peor."""


def _classify_schema(niches: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
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
        "required": ["results"],
        "additionalProperties": False,
    }


_SELECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
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
    "required": ["picks"],
    "additionalProperties": False,
}


def _classify_message(tags: Sequence[str], niches: Mapping[str, str]) -> str:
    niche_lines = "\n".join(f"- {key}: {label}" for key, label in niches.items())
    tag_lines = "\n".join(tags)
    return f"Nichos:\n{niche_lines}\n\nHashtags ({len(tags)}):\n{tag_lines}"


def _brand_message(brand: BrandProfile, candidates: Sequence[Candidate], max_picks: int) -> str:
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
    lines = []
    for c in candidates:
        meta = f"{c.seen_count} cuentas" + (f", nicho {c.niche}" if c.niche else "")
        lines.append(f"{c.tag} ({meta})")
    return (
        f"Marca:\n{profile}\n\nCandidatos ({len(candidates)}):\n"
        + "\n".join(lines)
        + f"\n\nElige como máximo {max_picks}."
    )


# --------------------------------------------------------------------------------------
# the call
# --------------------------------------------------------------------------------------

ClientFactory = Callable[[str], Any]


def api_key_from_env() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise MissingAPIKey(f"{API_KEY_ENV} is not set")
    return key


def _default_client(api_key: str) -> Any:
    import anthropic  # lazy: optional dependency (`qualify-creative[llm]`)

    return anthropic.Anthropic(api_key=api_key)


def _call(
    *,
    config: ModelConfig,
    system: str,
    user: str,
    schema: Mapping[str, Any],
    max_tokens: int,
    api_key: str,
    client_factory: ClientFactory | None,
) -> tuple[dict[str, Any], CallStats]:
    client = (client_factory or _default_client)(api_key)
    output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": dict(schema)}}
    if config.effort:
        output_config["effort"] = config.effort
    response = client.messages.create(
        model=config.model_id,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config=output_config,
    )
    if response.stop_reason == "refusal":
        raise HashtagAIError(f"{config.model_id} refused the request")
    if response.stop_reason == "max_tokens":
        raise HashtagAIError(f"{config.model_id} hit max_tokens={max_tokens}")
    usage = response.usage
    stats = CallStats(
        model_id=config.model_id,
        model_revision=getattr(response, "model", None),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
    )
    for block in response.content:
        if getattr(block, "type", None) == "text":
            try:
                parsed = json.loads(block.text)
            except ValueError as exc:
                raise HashtagAIError(f"{config.model_id} returned invalid JSON") from exc
            if not isinstance(parsed, dict):
                raise HashtagAIError(f"{config.model_id} returned a non-object")
            return parsed, stats
    raise HashtagAIError(f"{config.model_id} returned no text block")


def classify_hashtags(
    tags: Sequence[str],
    niches: Mapping[str, str],
    *,
    api_key: str,
    config: ModelConfig = ModelConfig(CLASSIFY_MODEL),
    client_factory: ClientFactory | None = None,
) -> tuple[list[TagClassification], CallStats]:
    """Classify up to `CLASSIFY_BATCH` tags in one call. `niches` maps taxonomy key →
    label. Answers for tags that were not asked about are dropped; a tag the model
    skipped is simply absent (the caller leaves it as it was)."""
    if len(tags) > CLASSIFY_BATCH:
        raise ValueError(f"at most {CLASSIFY_BATCH} tags per call, got {len(tags)}")
    asked = list(dict.fromkeys(normalize_tag(t) for t in tags))
    payload, stats = _call(
        config=config,
        system=CLASSIFY_SYSTEM,
        user=_classify_message(asked, niches),
        schema=_classify_schema(list(niches)),
        # 16000 is the ceiling the SDK allows without streaming; with thinking on, it
        # covers the reasoning plus ~80 output tokens per tag at `CLASSIFY_BATCH`.
        max_tokens=max(4096, 80 * len(asked)) if config.effort is None else 16000,
        api_key=api_key,
        client_factory=client_factory,
    )
    wanted = set(asked)
    out: list[TagClassification] = []
    seen: set[str] = set()
    for item in payload.get("results") or []:
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
    return out, stats


def _same_word(slug: str, others: set[str]) -> bool:
    """`slug` is already in `others` up to a plural: `hamburguesa`/`hamburguesas`,
    `programador`/`programadores`. Enforced here because the prompt's "only one spelling"
    rule is followed most of the time, not always (measured live 2026-09-25: Sonnet 5
    picked both `hamburguesas` and `hamburguesa`) — and a second spelling of the same
    word spends a search on the same accounts."""
    return any(
        slug == other or slug in (other + "s", other + "es") or other in (slug + "s", slug + "es")
        for other in others
    )


def select_hashtags(
    brand: BrandProfile,
    candidates: Sequence[Candidate],
    *,
    api_key: str,
    max_picks: int = 3,
    config: ModelConfig = ModelConfig(SELECT_MODEL, SELECT_EFFORT),
    client_factory: ClientFactory | None = None,
) -> tuple[list[HashtagPick], CallStats]:
    """The candidates worth searching with for this brand, best first, at most
    `max_picks`. Only tags from `candidates` can come back (a hallucinated tag is dropped
    here, whatever the model wrote), never one the brand already uses, and never two
    spellings of the same word."""
    if not candidates:
        return [], CallStats(config.model_id, None, 0, 0)
    offered = {fold(c.tag): c.tag for c in candidates}
    own = {fold(t) for t in brand.own_hashtags}
    payload, stats = _call(
        config=config,
        system=SELECT_SYSTEM,
        user=_brand_message(brand, candidates, max_picks),
        schema=_SELECT_SCHEMA,
        max_tokens=4096 if config.effort is None else 16000,
        api_key=api_key,
        client_factory=client_factory,
    )
    picks: list[HashtagPick] = []
    taken: set[str] = set()
    for item in payload.get("picks") or []:
        slug = fold(str(item.get("tag", "")).lstrip("#"))
        if slug not in offered or _same_word(slug, own) or _same_word(slug, taken):
            continue
        fit = item.get("fit") if item.get("fit") in FIT_LEVELS else "media"
        taken.add(slug)
        picks.append(HashtagPick(offered[slug], fit, str(item.get("reason") or "").strip()))
        if len(picks) >= max_picks:
            break
    return picks, stats
