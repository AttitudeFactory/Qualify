"""Claude reviews the referentes a search found, as a TOOL — stateless, nothing learned.

`review_accounts` sends one brand's profile and a shortlist of accounts (what each one
says about itself: bio, category, a few captions, the hashtags it uses) and gets the
answer as one `revisar_cuentas` tool call. Per account:

- `encaja` — whether the account is a real peer of THIS brand (same product or service,
  same business format, same audience), i.e. worth showing as referente / competencia.
  The discovery drops what does not fit; an account the operator added by hand is never
  dropped, the verdict only warns.
- `tipo` — what the account IS: `marca` (a business, store, product), `creador` (a person
  making content: influencer, reviewer, expert), `medio` (news, magazine, a page that
  reposts others' content) or `otro`. A property of the account, shown as a flag on the
  card.
- `razon` — one short sentence, shown to the operator: a model's decision is shown with
  its reason and stored with its provenance (`CallStats`).

A judgement about one brand's accounts, returned to the caller and never written back
anywhere as a rule: nothing accumulates per rubro, and the prompt carries principles,
not per-rubro lists. An account the model was not asked about is ignored; one it skipped
is simply absent from the answer (the caller treats it as unreviewed).

API facts pinned from the `claude-api` skill (2026-09) — see `qualify_api.claude_tools`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

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

#: Chosen by `packages/api/evals/referentes_ai` (Haiku 4.5 vs Sonnet 5) — see that
#: directory's README for the numbers behind it. Haiku let 25 of 212 traps through and
#: once answered only 25 of 55 accounts; Sonnet let none through at either effort, and
#: `low` kept 0.92 of the good referentes (vs 0.96 at `medium`, whose extra drops were
#: arguable) at ~30% less cost and latency per phase.
REVIEW_MODEL = "claude-sonnet-5"
REVIEW_EFFORT: str | None = "low"

REVIEW_TOOL = "revisar_cuentas"

#: Accounts per call: a phase's shortlist fits in one (`creator_discovery.REVIEW_PER_NETWORK`
#: × 2 networks), plus room for a few manual ones.
REVIEW_BATCH = 30

KINDS = ("marca", "creador", "medio", "otro")

#: What the model reads per account — enough to judge, bounded so a batch stays small.
MAX_CAPTIONS = 3
CAPTION_CHARS = 220
BIO_CHARS = 300
MAX_HASHTAGS = 12
NOTE_CHARS = 300

#: The error every review raises — the shared one.
ReviewAIError = ClaudeToolError


@dataclass(frozen=True)
class BrandBrief:
    """What the review reads about the brand the referentes are for. Every field but the
    handle is optional: the review works on whatever the wizard knows."""

    handle: str
    bio: str = ""
    category: str = ""
    #: The operator's own words for the rubro (`DiscoverySeed.terms`).
    rubro: Sequence[str] = ()
    #: Taxonomy labels of the seed's niches ("Comida y bebida").
    niches: Sequence[str] = ()
    #: The hashtags the search ran with (the brand's own plus the chosen ones).
    hashtags: Sequence[str] = ()
    city: str = ""
    country: str = ""
    positioning: str = ""
    audience: str = ""


@dataclass(frozen=True)
class AccountToReview:
    """One account as the model sees it. `id` is the caller's key, echoed back."""

    id: str
    network: str
    handle: str
    name: str = ""
    bio: str = ""
    category: str = ""
    followers: int | None = None
    captions: Sequence[str] = ()
    hashtags: Sequence[str] = ()
    #: Added by the operator by hand (not found by the search) — the model is told, so
    #: its reason is written as advice, and the caller never drops it.
    manual: bool = False
    #: What the operator wrote about a manual account ("pastelería de mi barrio, no
    #: tiene redes") — the only evidence for an account with no profile to read.
    note: str = ""


@dataclass(frozen=True)
class AccountReview:
    id: str
    kind: str
    fits: bool
    reason: str


# --------------------------------------------------------------------------------------
# prompt and tool
# --------------------------------------------------------------------------------------

REVIEW_SYSTEM = """\
Eres el analista de referentes de una plataforma de marketing para marcas y creadores \
del mercado hispanohablante. Una búsqueda en TikTok e Instagram encontró cuentas para UNA \
marca; tú revisas cada cuenta con lo que ella misma dice (nombre, bio, categoría, \
publicaciones, hashtags) y entregas el resultado con la herramienta revisar_cuentas, un \
resultado por cuenta; el id es el número entre corchetes con el que llegó la cuenta \
(solo el número: "1", "2"…).

encaja — true si la cuenta sirve a esta marca como referente o competencia: un par real.
1. Mismo producto o servicio, o contenido sobre ese mismo producto o servicio (un creador \
que reseña restaurantes le sirve a un restaurante; uno que enseña programación le sirve a \
una academia de programación).
2. Mismo modelo de negocio y formato. Un tema general agrupa negocios distintos que no \
comparten audiencia ni compiten: formal frente a callejero, un servicio para personas \
frente al mismo servicio para mascotas, venta frente a alquiler, hacer frente a enseñar \
frente a vender. Si la cuenta es una variante distinta de la de la marca, no encaja \
aunque comparta el tema.
3. Mismo público cuando el perfil de la marca lo deja claro (premium o económico, \
profesional o aficionado, adultos o niños).
No encaja: la cuenta es de otro rubro y solo coincidió por una palabra, un hashtag de \
lugar o un hashtag genérico; es entretenimiento, humor o memes sin relación con el rubro; \
es un noticiero, una revista o una página de noticias; o es la propia marca.
Si la cuenta casi no trae datos (sin bio ni publicaciones) y nada indica otro rubro, \
encaja: la falta de datos no es motivo para descartar. Si los datos muestran otro rubro, \
no encaja.

tipo — qué ES la cuenta, independiente de si encaja:
- marca: un negocio, tienda, restaurante, empresa, producto o servicio que vende.
- creador: una persona que hace contenido (influencer, reseñador, experto, profesional \
que muestra su trabajo con su propio nombre).
- medio: noticias, revista, o una página que publica contenido de otros (recopilaciones, \
guías de lugares, "los mejores de…").
- otro: nada de lo anterior o no se puede saber.
Un profesional independiente que se promociona con su nombre (un chef, un barbero, un \
entrenador) es creador; su negocio con nombre comercial es marca.

razon — una frase corta en español, para el operador: qué hace la cuenta y por qué encaja \
o no con esta marca. Sin repetir el nombre de la cuenta.

Las cuentas marcadas "agregada a mano" las eligió el operador: revísalas igual, con la \
misma exigencia; si no encaja, dilo con respeto en la razón (el operador decide).
"""


def _review_tool() -> dict:
    return strict_tool(
        REVIEW_TOOL,
        "Entrega la revisión de todas las cuentas recibidas.",
        {
            "resultados": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "tipo": {"type": "string", "enum": list(KINDS)},
                        "encaja": {"type": "boolean"},
                        "razon": {"type": "string"},
                    },
                    "required": ["id", "tipo", "encaja", "razon"],
                    "additionalProperties": False,
                },
            }
        },
    )


def _clip(text: str, limit: int) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _brand_block(brand: BrandBrief) -> str:
    lines = [f"Marca: @{brand.handle.lstrip('@')}"]
    if brand.category:
        lines.append(f"Categoría: {brand.category}")
    if brand.bio:
        lines.append(f"Bio: {_clip(brand.bio, BIO_CHARS)}")
    if brand.rubro:
        lines.append(f"Rubro, en palabras del operador: {', '.join(brand.rubro)}")
    if brand.niches:
        lines.append(f"Nicho: {', '.join(brand.niches)}")
    if brand.positioning:
        lines.append(f"Posicionamiento: {_clip(brand.positioning, BIO_CHARS)}")
    if brand.audience:
        lines.append(f"Público: {_clip(brand.audience, BIO_CHARS)}")
    place = ", ".join(p for p in (brand.city, brand.country) if p)
    if place:
        lines.append(f"Ubicación: {place}")
    if brand.hashtags:
        lines.append("Hashtags de la búsqueda: " + " ".join(f"#{t}" for t in brand.hashtags))
    return "\n".join(lines)


def _account_block(number: int, account: AccountToReview) -> str:
    head = f"[{number}] {account.network} @{account.handle.lstrip('@')}"
    if account.manual:
        head += " — agregada a mano"
    lines = [head]
    if account.name:
        lines.append(f"  nombre: {_clip(account.name, 80)}")
    if account.category:
        lines.append(f"  categoría: {_clip(account.category, 80)}")
    if account.followers is not None:
        lines.append(f"  seguidores: {account.followers}")
    if account.bio:
        lines.append(f"  bio: {_clip(account.bio, BIO_CHARS)}")
    for caption in list(account.captions)[:MAX_CAPTIONS]:
        if caption.strip():
            lines.append(f"  publicación: {_clip(caption, CAPTION_CHARS)}")
    if account.hashtags:
        tags = list(dict.fromkeys(account.hashtags))[:MAX_HASHTAGS]
        lines.append("  hashtags: " + " ".join(f"#{t}" for t in tags))
    if account.note:
        lines.append(f"  nota del operador: {_clip(account.note, NOTE_CHARS)}")
    if len(lines) == 1:
        lines.append("  (sin datos del perfil)")
    return "\n".join(lines)


def _review_message(brand: BrandBrief, accounts: Sequence[AccountToReview]) -> str:
    blocks = "\n\n".join(_account_block(n, a) for n, a in enumerate(accounts, 1))
    return (
        f"{_brand_block(brand)}\n\n"
        f"Cuentas a revisar ({len(accounts)}):\n\n{blocks}\n\n"
        "Revisa todas y entrega el resultado con revisar_cuentas."
    )


def review_accounts(
    brand: BrandBrief,
    accounts: Sequence[AccountToReview],
    *,
    api_key: str,
    config: ModelConfig = ModelConfig(REVIEW_MODEL, REVIEW_EFFORT),
    client_factory: ClientFactory | None = None,
) -> tuple[list[AccountReview], CallStats]:
    """Review up to `REVIEW_BATCH` accounts for one brand in one call; the answer is the
    `revisar_cuentas` tool call. Answers for ids that were not asked about, repeated ids
    and malformed items are dropped."""
    if not accounts:
        return [], CallStats(config.model_id, None, 0, 0)
    if len(accounts) > REVIEW_BATCH:
        raise ValueError(f"at most {REVIEW_BATCH} accounts per call, got {len(accounts)}")
    client = (client_factory or default_client)(api_key)
    meter = Meter(config)
    response = create_turn(
        client,
        config,
        meter,
        system=REVIEW_SYSTEM,
        messages=[{"role": "user", "content": _review_message(brand, accounts)}],
        tools=[_review_tool()],
        tool_choice=forced_or_auto(config, REVIEW_TOOL),
        # ~90 output tokens per account; with thinking on, the ceiling the SDK allows
        # without streaming covers the reasoning too.
        max_tokens=16000 if config.thinks else max(2048, 120 * len(accounts)),
    )
    calls = [b for b in tool_uses(response) if b.name == REVIEW_TOOL]
    if not calls:
        raise ReviewAIError(f"{config.model_id} did not call {REVIEW_TOOL}")
    meter.tool_calls = 1
    # The model answers with the number each account was shown under: a caller's id
    # (`otro:pasteleria-dona-rosa`) came back mangled — measured 2026-09-25, the prefix
    # dropped. The caller's own id is still accepted verbatim.
    by_number = {str(n): a.id for n, a in enumerate(accounts, 1)}
    wanted = {a.id for a in accounts}
    out: list[AccountReview] = []
    seen: set[str] = set()
    for item in (calls[0].input or {}).get("resultados") or []:
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("id", "")).strip().strip("[]").strip()
        account_id = by_number.get(raw_id, raw_id)
        kind = item.get("tipo")
        fits = item.get("encaja")
        if account_id not in wanted or account_id in seen:
            continue
        if kind not in KINDS or not isinstance(fits, bool):
            continue
        seen.add(account_id)
        out.append(
            AccountReview(
                id=account_id,
                kind=str(kind),
                fits=fits,
                reason=_clip(str(item.get("razon") or ""), 240),
            )
        )
    return out, meter.stats()
